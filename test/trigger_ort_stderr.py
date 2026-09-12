"""让 onnxruntime 在原生层输出 utf-16-le stderr, 用于验证日志解码与落盘.

背景:
    onnxruntime 的 C++ 日志绕过 python 的 sys.stderr 直接写 fd, 在 Windows 上
    每个字符按 2 字节写出(utf-16-le), 还带 ANSI 颜色码; 而 python 自己的
    print 走的是 utf-8. 因此同一个 stderr 里会混着两种编码, 且 utf-16 数据
    会被管道切成奇数长度片段.

用法::

    ./python/python.exe test/trigger_ort_stderr.py            # 抓真实字节样本
    ./python/python.exe test/trigger_ort_stderr.py --replay   # 用样本驱动 OutputLogWidget

第 1 种只做子进程捕获, 样本落在 temp/ort_stderr_capture/. 第 2 种额外把样本
按管道分片大小灌进 OutputLogWidget(含文件日志), 直接看 log 和 output_widget
处理得对不对.
"""

from __future__ import annotations

import argparse
import binascii
import io
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MODEL = ROOT / "data" / "models" / "check_device_test.fp32.onnx"
CAPTURE_DIR = ROOT / "temp" / "ort_stderr_capture"

# 模拟管道读取: 故意混入奇数长度和高低大小片段
CHUNK_PATTERN = (1, 3, 4093, 2, 7, 4096, 5, 1021)


def _child(mode: str) -> None:
    """子进程侧: 制造 ORT 原生输出. 由父进程用管道捕获原始字节."""
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", write_through=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", write_through=True)
    print(f"[py] child start, mode={mode}, 这行是 python 写出的 utf-8 中文")
    sys.stderr.write("[py-stderr] child start 的 utf-8 行\n")

    import onnxruntime as ort

    tmpdir = Path(tempfile.mkdtemp())
    garbage = tmpdir / "garbage.onnx"
    garbage.write_bytes(b"this is not an onnx model at all" * 8)

    def attempt(name: str, fn) -> None:
        print(f"[py] >>> {name}")
        sys.stderr.write(f"[py-stderr] {name} 之前的 utf-8 行\n")
        try:
            fn()
            print(f"[py] <<< {name} 完成")
        except BaseException as exc:
            print(f"[py] <<< {name} 抛出 {type(exc).__name__}: {str(exc)[:160]}")
        sys.stderr.write(f"[py-stderr] {name} 之后的 utf-8 行\n")
        print(f"[py] {name} 之后, 中文标记行")

    if mode == "mixed":
        # ERROR 级: 无可用 CUDA 设备时 ORT 原生打 [E:onnxruntime:Default, ...]
        ort.set_default_logger_severity(3)
        attempt(
            "CUDA EP 会话",
            lambda: ort.InferenceSession(str(MODEL), providers=["CUDAExecutionProvider"]),
        )
        # INFO 级: 原生 utf-16 输出量足够多, 与 python 的 utf-8 行交错
        ort.set_default_logger_severity(1)
        attempt("损坏的模型", lambda: ort.InferenceSession(str(garbage), providers=["CPUExecutionProvider"]))
        attempt(
            "注册不存在的 EP 动态库",
            lambda: ort.capi._pybind_state.register_execution_provider_library("BadEP", str(tmpdir / "missing.dll")),
        )
        ort.set_default_logger_severity(2)
        attempt("正常 CPU 会话", lambda: ort.InferenceSession(str(MODEL), providers=["CPUExecutionProvider"]))
    elif mode == "flood":
        # VERBOSE 级: 单次会话就能刷出上百 KB 原生 utf-16 日志
        ort.set_default_logger_severity(0)

        def many() -> None:
            for _ in range(3):
                ort.InferenceSession(str(MODEL), providers=["CPUExecutionProvider"])

        attempt("VERBOSE 级别连续建会话", many)
    else:
        raise SystemExit(f"unknown mode: {mode}")

    print("[py] child exit")


def _feed_chunked(decoder, data: bytes) -> str:
    """按 CHUNK_PATTERN 分片喂给解码器, 模拟 pipe 的任意切分."""
    parts: list[str] = []
    offset = 0
    index = 0
    while offset < len(data):
        size = CHUNK_PATTERN[index % len(CHUNK_PATTERN)]
        parts.append(decoder.feed(data[offset : offset + size]))
        offset += size
        index += 1
    parts.append(decoder.feed(b"", final=True))
    return "".join(parts)


def _describe(out: list[str], label: str, data: bytes) -> None:
    out.append(f"===== {label}: {len(data)} bytes =====")
    if not data:
        out.append("  (empty)")
        return

    odd_nul = data[1::2].count(0)
    even_nul = data[0::2].count(0)
    out.append(f"  零字节分布: even={even_nul} odd={odd_nul} (odd 占优 => utf-16-le)")
    out.append(f"  first 48B hex: {binascii.hexlify(data[:48]).decode()}")

    naive = data.decode("utf-8", errors="replace")
    out.append(
        f"  直接 utf-8 解码: NUL={naive.count(chr(0))} 替换符={naive.count(chr(0xFFFD))} 行数={len(naive.splitlines())}"
    )

    from src.app.widgets.output_log import _OutputStreamDecoder

    text = _feed_chunked(_OutputStreamDecoder(), data)
    lines = text.splitlines()
    out.append(
        f"  解码器分片喂入: NUL={text.count(chr(0))} 替换符={text.count(chr(0xFFFD))} 行数={len(lines)}"
    )
    for line in lines[:12]:
        out.append(f"    | {line[:160]}")


def _capture(out: list[str]) -> dict[str, bytes]:
    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    if not MODEL.is_file():
        raise SystemExit(f"缺少测试模型: {MODEL}")

    captures: dict[str, bytes] = {}
    for mode in ("mixed", "flood"):
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--child", mode],
            capture_output=True,
            cwd=str(ROOT),
        )
        out.append(f"########## mode={mode} exit={result.returncode} ##########")
        for stream, data in (("stdout", result.stdout), ("stderr", result.stderr)):
            _describe(out, f"{mode}/{stream}", data)
            key = f"{mode}_{stream}"
            (CAPTURE_DIR / f"{key}.bin").write_bytes(data)
            captures[key] = data
        out.append("")
    return captures


def _replay(out: list[str], captures: dict[str, bytes]) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from src.app.widgets.output_log import OutputLogWidget

    app = QApplication.instance() or QApplication([])
    widget = OutputLogWidget()
    runner_id = "ort-stderr-test"
    log_path = CAPTURE_DIR / "replay_output_log.txt"
    widget.bind_current_runner_id(runner_id, clear=True, log_enabled=True, logtxt_path=log_path)

    streams = [
        (stream, captures.get(f"mixed_{stream}", b""))
        for stream in ("stdout", "stderr")
    ]
    # 把每个流切成若干片后交替投递, 尽量贴近两个管道的交错顺序
    for slice_index in range(4):
        for stream, data in streams:
            piece = data[len(data) * slice_index // 4 : len(data) * (slice_index + 1) // 4]
            offset = 0
            chunk_index = 0
            while offset < len(piece):
                size = CHUNK_PATTERN[chunk_index % len(CHUNK_PATTERN)]
                widget.handle_process_output(runner_id, stream, piece[offset : offset + size])
                offset += size
                chunk_index += 1

    widget.handle_process_ended(runner_id, None)

    widget_text = widget.text_edit.toPlainText()
    log_text = log_path.read_text(encoding="utf-8") if log_path.is_file() else ""
    widget_path = CAPTURE_DIR / "replay_widget_text.txt"
    widget_path.write_text(widget_text, encoding="utf-8")

    for name, text in (("output_widget", widget_text), ("log 文件", log_text)):
        ort_lines = [line for line in text.splitlines() if "onnxruntime" in line]
        out.append(
            f"{name}: {len(text.splitlines())} 行, NUL={text.count(chr(0))}, "
            f"替换符={text.count(chr(0xFFFD))}, 含 onnxruntime 的行={len(ort_lines)}"
        )
        for line in ort_lines[:5]:
            out.append(f"    | {line[:160]}")
        for line in text.splitlines()[:6]:
            out.append(f"    (head) | {line[:160]}")

    out.append(f"widget 全文: {widget_path}")
    out.append(f"落盘日志: {log_path}")


# 应当被 _ignore_contains_filters 命中的原生行(实测里就是它泄漏进了日志)
_FILTERED_LINE = (
    "\x1b[0;93m2026-09-11 23:04:54.4684750 [W:onnxruntime:Default, "
    "onnxruntime_pybind_state.cc:711 onnxruntime::python::CreateExecutionProviderFactoryInstance"
    "::<lambda_1>::operator ()] No registered plugin EP device found for 'CUDAExecutionProvider' "
    "with device_id=0\x1b[m\n"
)
# 过滤列表不认识的原生错误行, 必须原样可读地显示出来
_VISIBLE_LINE = (
    "\x1b[1;31m2026-09-11 23:04:52.5841017 [E:onnxruntime:, inference_session.cc:2700 "
    "onnxruntime::InferenceSession::Initialize] Conflicting session configuration: explicitly added "
    "the CPU EP to the session, but also disabled fallback to the CPU EP.\x1b[m\n"
)
# 原生行里嵌着 Windows 本地化文本(高字节非 0), 是编码判定最容易出错的地方
_CJK_LINE = (
    "2026-09-11 23:04:52.5841017 [E:onnxruntime:Default, provider_bridge_ort.cc:2367 "
    "onnxruntime::TryGetProviderInfo_TensorRT] Error loading \"onnxruntime_providers_tensorrt.dll\" "
    "which depends on \"cublas64_12.dll\" which is missing. (Error 126: 找不到指定的模块。)\n"
)
# 末尾不完整的行, 复刻管道把 utf-16 段截断在字符中间
_TRAILING_FRAGMENT = (
    "2026-09-11 23:05:04.2068629 [I:onnxruntime:, inference_session.cc:754 "
    "onnxruntime::InferenceSession::TraceSessionOptions] Session Options {  exec"
)


def _build_mixed_chunk(prefix: bytes) -> bytes:
    """复刻实测的坏 chunk: 奇数长度的 utf-8 前缀 + utf-16-le 原生日志, 末尾截断在字符中间."""
    payload = (_FILTERED_LINE + _VISIBLE_LINE + _CJK_LINE + _TRAILING_FRAGMENT).encode("utf-16-le")
    # 砍掉半个字符: 复刻管道把 utf-16 段切成奇数长度、剩余部分留到下一批的情况
    return prefix + payload[:-1]


def _chunk_mix(out: list[str]) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from src.app.widgets.output_log import OutputLogWidget

    app = QApplication.instance() or QApplication([])
    # 与 HachimiDX_log.txt 里那条真实记录一致的 57 字节 utf-8 前缀(奇数长度)
    prefix = "[ort-trigger] native 触发后, stderr 上的 utf-8 行\r\n".encode("utf-8")
    chunk = _build_mixed_chunk(prefix)

    out.append(f"合成 chunk: {len(chunk)} 字节, utf-8 前缀 {len(prefix)} 字节(奇数={len(prefix) % 2 == 1})")
    out.append(f"被过滤行是否命中过滤列表: {OutputLogWidget()._should_ignore_line(_FILTERED_LINE)}")
    out.append("")

    # 两种投递方式: 一次整块 / 在 utf-16 段中间切开
    deliveries = {
        "whole": [chunk],
        "split": [chunk[: len(prefix) + 40], chunk[len(prefix) + 40:]],
    }
    for name, pieces in deliveries.items():
        widget = OutputLogWidget()
        runner_id = "chunk-mix"
        log_path = CAPTURE_DIR / f"chunk_mix_{name}_log.txt"
        widget.bind_current_runner_id(runner_id, clear=True, log_enabled=True, logtxt_path=log_path)
        for piece in pieces:
            # 再按 37 字节(奇数)切分, 模拟管道按任意字节边界投递
            for offset in range(0, len(piece), 37):
                widget.handle_process_output(runner_id, "stderr", piece[offset:offset + 37])
        widget.handle_process_ended(runner_id, None)

        widget_text = widget.text_edit.toPlainText()
        log_text = log_path.read_text(encoding="utf-8") if log_path.is_file() else ""
        out.append(f"### {name}")
        for label, text in (("output_widget", widget_text), ("log 文件", log_text)):
            leaked = [line for line in text.splitlines() if "No registered plugin EP" in line]
            visible = [line for line in text.splitlines() if "Conflicting session configuration" in line]
            localized = [line for line in text.splitlines() if "找不到指定的模块" in line]
            out.append(
                f"  {label}: {len(text.splitlines())} 行, NUL={text.count(chr(0))}, "
                f"替换符={text.count(chr(0xFFFD))}, 泄漏的 EP 警告={len(leaked)}, "
                f"可读的原生错误={len(visible)}, 可读的本地化文本={len(localized)}"
            )
        for line in widget_text.splitlines():
            out.append(f"    | {line[:150]}")
        out.append("")


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 onnxruntime 原生 utf-16-le stderr 样本")
    parser.add_argument("--child", choices=("mixed", "flood"), help=argparse.SUPPRESS)
    parser.add_argument("--replay", action="store_true", help="把样本灌进 OutputLogWidget 和文件日志")
    parser.add_argument("--chunk-mix", action="store_true", help="复刻实测的混合编码坏 chunk 并比对")
    args = parser.parse_args()

    if args.child:
        _child(args.child)
        return

    out: list[str] = []
    if args.chunk_mix:
        out.append("########## chunk-mix ##########")
        _chunk_mix(out)
    if not args.chunk_mix or args.replay:
        captures = _capture(out)
        if args.replay:
            out.append("########## replay ##########")
            _replay(out, captures)

    report = CAPTURE_DIR / "report.txt"
    report.write_text("\n".join(out), encoding="utf-8")
    # 报告里含误码后的乱码字符, 控制台按 utf-8 输出避免二次编码失败
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", write_through=True)
    print("\n".join(out))
    print(f"\n完整报告: {report}")


if __name__ == "__main__":
    main()
