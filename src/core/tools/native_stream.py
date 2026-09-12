"""
原生库输出与原生异常的处理工具

onnxruntime / TensorRT / ncnn 这类 C++ 库做两件绕过 python 的事:
1. 日志直接写 fd 2, 一次日志分多次 write; 在 Windows 上按 utf-16-le 写出.
   多个写者并发写同一条管道时, 各自的 write 会互相插入, 字节顺序当场被破坏,
   事后任何解码都无法还原。
2. 报错时把本地化消息(DirectML 用系统 ANSI 代码页生成)按 utf-8 强解失败,
   抛出 UnicodeDecodeError, 真实错误整个丢掉, 但原始字节留在异常对象里。

本模块只依赖标准库, GUI 与各 worker 子进程共用同一份实现。
"""

import io
import os
import re
import sys
import threading
import traceback



_READ_CHUNK_BYTES = 65536

# 原生库的日志带 ANSI 颜色码, 转发前剥掉, 免得只剩颜色码的行变成一个空的前缀行
_ANSI_ESCAPE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def strip_ansi(text: str) -> str:
    """剥离 ANSI 转义序列, 全项目唯一一份实现"""
    return _ANSI_ESCAPE.sub("", text)




class OutputStreamDecoder:
    """
    把一条输出流的裸字节增量解码成文本.

    同一条流上可能混排两种编码: 
      - python 侧按 utf-8 写,
      - 部分库按 gbk 写,
      - onnxruntime 这类原生库绕过 sys.stderr 直接写 fd, 在 Windows 上是 utf-16-le.
    
    管道又会按任意字节边界切分, 所以这里按「段」处理: 
      utf-8/GBK 文本里不可能出现 0x00 字节, 
      于是 0x00 就是 utf-16-le 段的线索.
      每次只消费到完整换行符, 段起点便始终落在字符边界上,
      不会出现整段奇偶错位.
    """

    # 判定 utf-16-le 段时一次向前看的字节数
    _UTF16_PROBE_BYTES = 64

    def __init__(self) -> None:
        self._buffer = bytearray()

    @classmethod
    def _utf16le_span(cls, data: bytes, offset: int = 0) -> int:
        """从 offset 起判定连续的 utf-16-le 段长度(偶数); 不像 utf-16-le 则返回 0."""
        if data[offset:offset + 2] == b"\xff\xfe":
            cursor = offset + 2
        elif data[offset + 1:offset + 2] == b"\x00":
            # utf-16-le 的 ASCII 文本是 `字符 0x00`
            # 第二个字节非 0 说明 offset 不在字符边界上
            # 只看窗口占比不够: 短的 utf-8 前缀后面接长原生日志时会误判
            cursor = offset
        else:
            return 0

        # 段内会出现高字节非 0 的字符 (带本地化错误文本的原生日志里有中日韩)
        # 所以不能要求 NUL 占比.
        # utf-8/GBK 永远不含 0x00, 于是只推进到窗口内最后一个 NUL 之后,
        # 正好停在 utf-16 与 utf-8 的交界, 不会越界把 utf-8 字节当 utf-16 解.
        while cursor + 2 <= len(data):
            window = data[cursor:cursor + cls._UTF16_PROBE_BYTES]
            window = window[:len(window) - len(window) % 2]
            last_nul = window.rfind(b"\x00")
            if last_nul < 0:
                break
            step = last_nul + 1
            cursor += step + step % 2
        return cursor - offset

    @staticmethod
    def _last_utf8_delimiter_end(data: bytes, limit: int) -> int:
        """[0, limit) 内最后一个换行的下一个位置; 换行是 ASCII, 不会被多字节字符误判."""
        return max(data.rfind(b"\n", 0, limit), data.rfind(b"\r", 0, limit)) + 1

    @staticmethod
    def _last_utf16le_delimiter_end(data: bytes, span: int) -> int:
        """utf-16-le 段 [0, span) 内最后一个换行的下一个位置; 换行须 2 字节对齐."""
        end = 0
        for delimiter in (b"\n\x00", b"\r\x00"):
            index = data.rfind(delimiter, 0, span)
            while index > 0 and index % 2:
                index = data.rfind(delimiter, 0, index)
            if index >= 0:
                end = max(end, index + 2)
        return end

    @classmethod
    def _next_utf16le_start(cls, data: bytes) -> int:
        """返回 utf-8 段之后 utf-16-le 段的起点; 没有则返回 len(data)."""
        search_from = 0
        while True:
            index = data.find(b"\x00", search_from)
            if index < 0:
                return len(data)
            # utf-16-le 的 ASCII 文本形如 `字符 0x00`, 所以 NUL 前一字节是段起点
            start = index - 1
            if start >= 1 and cls._utf16le_span(data, start):
                return start
            search_from = index + 1

    @staticmethod
    def _decode_bytes(data: bytes, utf16le: bool = False) -> str:
        if not data:
            return ""
        if utf16le:
            try:
                if data.startswith(b"\xff\xfe"):
                    data = data[2:]  # remove BOM
                return data.decode("utf-16-le", errors="strict")
            except UnicodeDecodeError:
                pass
        try:
            return data.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            try:
                return data.decode("gbk", errors="strict")
            except UnicodeDecodeError:
                return data.decode("utf-8", errors="replace")

    def feed(self, data: bytes | bytearray, final: bool = False) -> str:
        if data:
            self._buffer.extend(data)
        decoded_parts: list[str] = []

        while self._buffer:
            raw = bytes(self._buffer)
            span = self._utf16le_span(raw)
            if span:
                # utf-16-le 段: 只在段内按 2 字节对齐找换行, 段外字节留给下一轮
                utf16le = True
                prefix_end = span - span % 2 if final else self._last_utf16le_delimiter_end(raw, span)
            else:
                # utf-8 段: 只到下一个 utf-16-le 段起点为止
                utf16le = False
                limit = self._next_utf16le_start(raw)
                prefix_end = limit if final else self._last_utf8_delimiter_end(raw, limit)
            if prefix_end <= 0:
                break

            prefix = raw[:prefix_end]
            del self._buffer[:prefix_end]
            decoded_parts.append(self._decode_bytes(prefix, utf16le=utf16le))

        # 收尾: 剩下认不出编码的零头按 utf-8 尽力解出, 不丢字节
        if final and self._buffer:
            raw = bytes(self._buffer)
            self._buffer.clear()
            decoded_parts.append(self._decode_bytes(raw))

        return "".join(decoded_parts)




def decode_native_message(exc: BaseException) -> str | None:
    """
    取回 onnxruntime 按 utf-8 强解失败而丢弃的本地化消息

    DirectML 按系统 ANSI 代码页生成消息(如 GBK 的 "参数错误。"), pybind11 按
    utf-8 解失败后把原始字节留在 UnicodeDecodeError.object 里, 异常本身不携带
    任何有效信息。这里还原出真正的错误文本; 取不到时返回 None。
    """
    if not isinstance(exc, UnicodeDecodeError):
        return None
    payload = exc.object
    if not isinstance(payload, (bytes, bytearray)):
        return None
    codec = "mbcs" if sys.platform == "win32" else "utf-8"
    return bytes(payload).decode(codec, errors="replace").strip() or None


def iter_exception_chain(exc: BaseException):
    """沿 __cause__ / __context__ 遍历异常链, 不重复访问同一异常."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def find_native_message(exc: BaseException) -> str | None:
    """
    在整条异常链里找第一个可还原的原生消息

    上层往往用 `raise XxxError("...") from e` 包一层, 原始字节因此落在内层异常上。
    """
    for item in iter_exception_chain(exc):
        detail = decode_native_message(item)
        if detail:
            return detail
    return None


def describe_exception(exc: BaseException) -> str:
    """
    把异常格式化为 traceback 文本

    能还原出被丢弃的原生消息时, 保留调用栈但把末行换成该消息,
    避免 error_raw 里只留下一个没有信息量的 UnicodeDecodeError。
    """
    detail = find_native_message(exc)
    if detail is None:
        return "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        ).rstrip()

    frames = traceback.format_list(traceback.extract_tb(exc.__traceback__))
    if not frames:
        return f"RuntimeError: {detail}"
    return f"Traceback (most recent call last):\n{''.join(frames)}RuntimeError: {detail}"


def rewrite_native_error_line(text: str, exc: BaseException | None) -> str:
    """
    把已格式化 traceback 里那行无信息量的解码错误换成还原出的原生错误

    只在链上找到 onnxruntime 的原文时才改写: 其它库抛出真 UnicodeDecodeError
    (文件编码坏了之类) 时保持原样, 那才是应该看到的错误。
    用精确的末行做替换, 不动其余调用栈与 cause 链; 找不到该行时原样返回。
    """
    if exc is None:
        return text
    for item in iter_exception_chain(exc):
        detail = decode_native_message(item)
        if not detail or "[ONNXRuntimeError]" not in detail:
            continue
        useless = "".join(
            traceback.format_exception_only(type(item), item)
        ).strip()
        if useless and useless in text:
            return text.replace(useless, f"RuntimeError: {detail}")
    return text




class NativeStderrRedirect:
    """
    把原生库直写 fd 2 的输出转成 python 的 stdout 输出

    独立进程各自持有一条私有管道, 因此 detect/obb 这类并发写者不会再互相插入字节。
    但若两个兄弟进程继承的是同一条管道(例如父进程已重定向过), 交织会原样复现,
    所以并发写 fd 2 的进程必须各自调用一次。
    """

    def __init__(self, tag: str) -> None:
        self.tag = tag
        self._saved_fd: int | None = None
        self._write_fd: int | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> "NativeStderrRedirect":
        sys.stderr.flush()
        read_fd, self._write_fd = os.pipe()
        self._saved_fd = os.dup(2)
        os.dup2(self._write_fd, 2)

        # python 侧的 stderr 走原来的 fd, 输出行为与重定向前一致
        sys.stderr = io.TextIOWrapper(
            os.fdopen(self._saved_fd, "wb", buffering=0),
            encoding="utf-8",
            errors="replace",
            write_through=True,
        )

        self._thread = threading.Thread(
            target=self._pump,
            args=(read_fd, self.tag),
            name=f"native-stderr-{self.tag}",
            daemon=True,
        )
        self._thread.start()
        return self

    @staticmethod
    def _emit(text: str, prefix: str) -> None:
        # 先剥颜色码, 免得只剩颜色码的行变成一个空的前缀行
        new_lines = []
        for raw_line in text.splitlines():
            new_line = strip_ansi(raw_line).strip()
            if new_line:
                new_lines.append(f"{prefix}{new_line}")
        if not new_lines:
            return
        # 整批一次写出, 避免中途被其它线程/进程的 stderr 写入造成行交错
        print("\n".join(new_lines), file=sys.stdout, flush=True)

    @staticmethod
    def _pump(read_fd: int, tag: str) -> None:
        decoder = OutputStreamDecoder()
        prefix = f"[{tag}] "
        try:
            while True:
                # 读线程绝不能死: 一旦退出, 管道写满会让原生库永久阻塞在 write 上
                try:
                    chunk = os.read(read_fd, _READ_CHUNK_BYTES)
                except BaseException:
                    continue
                if not chunk:
                    break
                try:
                    text = decoder.feed(chunk)
                except BaseException:
                    continue
                NativeStderrRedirect._emit(text, prefix)
            NativeStderrRedirect._emit(decoder.feed(b"", final=True), prefix)
        except BaseException:
            # 转发失败不应影响业务, 更不应把线程异常打到 stderr 造成递归
            pass
        finally:
            try:
                os.close(read_fd)
            except OSError:
                pass

    def close(self) -> None:
        try:
            sys.stderr.flush()
        except Exception:
            pass

        # 先把 fd 2 换回原目标, 之后原生库的输出回到它本该去的地方
        # (self._saved_fd 由 sys.stderr 这个 wrapper 持有, 此处仍然有效)
        if self._saved_fd is not None:
            try:
                os.dup2(self._saved_fd, 2)
            except OSError:
                pass

        if self._write_fd is not None:
            try:
                # 关掉保留的写端, 读端才会收到 EOF
                os.close(self._write_fd)
            except OSError:
                pass
            self._write_fd = None

        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    def __enter__(self) -> "NativeStderrRedirect":
        return self

    def __exit__(self, *exc_info) -> bool:
        self.close()
        return False


def redirect_native_stderr(tag: str) -> NativeStderrRedirect:
    """把本进程 fd 2 的原生输出转成 stdout 输出(带 tag 前缀)"""
    return NativeStderrRedirect(tag).start()
