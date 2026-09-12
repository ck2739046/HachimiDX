import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import QTextEdit, QVBoxLayout, QWidget

from ..ui_style import UI_Style



class _OutputStreamDecoder:
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







@dataclass
class _RunnerFileLog:
    """记录某个 runner 对应的落盘日志文件状态.

    path / path_key: 规范化后的路径及其比较用 key（Windows 下大小写不敏感）.
    file: 已打开的文本文件句柄（utf-8、覆盖写、统一 \\n 换行）.
    is_last_line_replaceable / last_line_start: 为在文件里复刻 GUI 的
        “\\r 进度行原地替换”而记录的状态：last_line_start 是上一行在文件中的
        字节偏移，is_last_line_replaceable 表示上一行是否允许被覆盖.
    """
    path: Path
    path_key: str
    file: TextIO
    is_last_line_replaceable: bool = False
    last_line_start: int | None = None





class OutputLogWidget(QWidget):
    """通用日志输出组件。

    Supports two usage patterns:
    1) Manual: call append_text(text) / clear output with clear()
    2) Runner streaming: bind to a runner_id via bind_current_runner_id(),
       then connect to ProcessManager signals (handle_process_output, handle_process_ended).

    Notes:
    - Handles carriage-return (\r) progress updates by replacing the last line.
    - Strips ANSI escape sequences.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_runner_id: set = set()

        # 全局日志过滤
        # 外层每项是一个关键词列表
        # 行中包含内层列表中所有 str 才忽略该行
        self._ignore_contains_filters: list[list[str]] = [

            # NCNN 在创建 Vulkan GPU 实例时默认写入
            ["[", "queueC=", "queueT=", "rebar=", "r-score="],
            ["[", "fp16-p/s/u/a=", "int8-p/s/u/a="],
            ["[", "subgroup=", "ops="],
            ["[", "fp16-cm=", "int8-cm="],

            # TensorRT 推理 detect/obb
            ["[TRT] [I] Loaded engine size: "],
            ["[TRT] [I] [MemUsageChange] TensorRT-managed allocation in IExecutionContext creation: "],
            ["[TRT] [W] WARNING The logger passed into createInferRuntime differs from one already registered for an existing builder, runtime, or refitter. "],

            # TensorRT 推理 classify
            ["[TRT] [I] [MS] Running engine with multi stream info"],
            ["[TRT] [I] [MS] Number of aux streams is"],
            ["[TRT] [I] [MS] Number of total worker streams is"],
            ["[TRT] [I] [MS] The main stream provided by execute/enqueue calls is the first worker stream"],

            # TensorRT 转换模型
            ["[TRT] [W] Requested amount of GPU memory "],
            ["[TRT] [W] UNSUPPORTED_STATE: Skipping tactic"],
            ["[TRT] [E] [virtualMemoryBuffer.cpp::nvinfer1::StdVirtualMemoryBufferImpl::resizePhysical::154] Error Code"],

            # Librosa 加载音频 (detect click start)
            ["error: No comment text / valid description?"],

            # onnxruntime-gpu 找不到 cuda ep 设备 (误报)
            ["No registered plugin EP device found for 'CUDAExecutionProvider' with device_id="],
        ]

        # 保存的最大行数
        self.max_output_lines = 4000
        # 标记最后一行是否可被替换 (用于处理 \r)
        self._is_last_line_replaceable = False
        # ANSI 转义序列的正则表达式
        self._ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
        self._stream_decoders: dict[tuple[str, str], _OutputStreamDecoder] = {}
        self._text_buffers: dict[tuple[str, str], str] = {}
        # runner_id -> _RunnerFileLog：当前带文件日志的 runner 及其文件句柄
        self._runner_file_logs: dict[str, _RunnerFileLog] = {}
        # path_key -> runner_id：每个日志路径当前被哪个 runner 占用，
        # 用于避免多个 runner 同写一个文件时互相覆盖
        self._log_path_owners: dict[str, str] = {}

        self._setup_ui()



    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)  # 只读模式
        self.text_edit.setFixedHeight(UI_Style.output_log_widget_height)
        self.text_edit.setStyleSheet(
            f"""
            QTextEdit {{
                background-color: {UI_Style.COLORS['grey']};
                color: {UI_Style.COLORS['text_primary']};
                border: none;
                padding: 10px;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 12px;
            }}
            QScrollBar:vertical {{
                background-color: {UI_Style.COLORS['bg']};
                width: 12px;
                border: none;
            }}
            QScrollBar::handle:vertical {{
                background-color: {UI_Style.COLORS['text_secondary']};
                border-radius: 6px;
                min-height: 20px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: {UI_Style.COLORS['accent']};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: none;
            }}
            """
        )

        layout.addWidget(self.text_edit)



    def _limit_output_lines(self) -> None:
        document = self.text_edit.document()
        if document.blockCount() <= self.max_output_lines:
            return
        # 删除旧的行，保证总行数不超过 max_output_lines
        cursor = QTextCursor(document)
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        # 计算需要删除的行数
        lines_to_remove = document.blockCount() - self.max_output_lines
        for _ in range(lines_to_remove):
            cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
            cursor.removeSelectedText()
            cursor.deleteChar()  # 删除换行符



    def _append_output(
        self,
        text: str,
        replace_last: bool = False,
        runner_id: str | None = None,
    ) -> None:
        """
        添加输出文本
        
        :param text: 要添加的文本
        :param replace_last: 是否替换最后一行（用于进度条更新，处理 \\r）
        :param runner_id: 该输出归属的 runner；用于把同一行镜像写到对应日志文件
        """
        
        if self._should_ignore_line(text):
            return

        # 保存当前滚动条位置
        scrollbar = self.text_edit.verticalScrollBar()
        old_scroll_value = scrollbar.value()

        # 在添加内容前检查是否在底部
        if scrollbar.value() >= scrollbar.maximum() - 5:
            was_at_bottom = True
        else:
            was_at_bottom = False
        
        if replace_last:
            # 只在上一行是进度行时才替换
            if self._is_last_line_replaceable:
                # 替换最后一行：移动到文档末尾，选择当前行，删除并插入新文本
                cursor = self.text_edit.textCursor()
                cursor.movePosition(QTextCursor.MoveOperation.End)
                cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock, QTextCursor.MoveMode.KeepAnchor)
                cursor.removeSelectedText()
                cursor.insertText(text)
                # 不要设置光标，避免触发自动滚动
            else:
                # 如果上一行不是进度行，则追加新行
                self.text_edit.append(text)
            # 标记这一行是进度行
            self._is_last_line_replaceable = True
        else:
            # 追加新行
            self.text_edit.append(text)
            # 标记这一行不是进度行
            self._is_last_line_replaceable = False

        self._write_file_log(runner_id, text, replace_last)
        
        # 限制最大行数
        self._limit_output_lines()
        
        # 智能滚动：仅当用户之前在底部时才自动滚动
        if was_at_bottom:
            self.text_edit.moveCursor(QTextCursor.MoveOperation.End)
        else:
            # 如果用户不在底部，恢复原来的滚动位置
            scrollbar.setValue(old_scroll_value)



    def append_text(self, text, runner_id: str | None = None):
        """
        手动添加文本（用于非进程输出的日志）
        安全假设：手动添加的文本不包含 \r
        
        :param text: 要添加的文本
        """
        self._append_output(text, replace_last=False, runner_id=runner_id)


    @staticmethod
    def _normalize_log_path(path: str | Path) -> tuple[Path, str]:
        """规范化日志路径，返回 (Path, 比较用 key).
        以便后续判断两个路径是否指向同一文件.
        """
        normalized_path = Path(path).expanduser().resolve(strict=False)
        return normalized_path, os.path.normcase(str(normalized_path))


    def _close_runner_file_log(self, runner_id: str) -> None:
        """关闭并移除某 runner 的日志文件，同时释放对应路径的所有权."""
        state = self._runner_file_logs.pop(runner_id, None)
        if state is None:
            return

        # 仅当该路径的所有者正是本 runner 时才释放所有权
        if self._log_path_owners.get(state.path_key) == runner_id:
            self._log_path_owners.pop(state.path_key, None)
        try:
            state.file.close()
        except (OSError, ValueError):
            pass


    def _configure_runner_file_log(
        self,
        runner_id: str,
        enabled: bool,
        logtxt_path: str | Path | None,
    ) -> None:
        """为某 runner 开启/关闭文件日志（关闭并重开，以“w”覆盖写入）.

        若 enabled 为 False 则只关闭旧句柄；若开启则要求提供 logtxt_path，
        规范化路径、处理同路径所有权冲突后打开文件并注册.
        """
        self._close_runner_file_log(runner_id)
        if not enabled:
            return
        if logtxt_path is None or not str(logtxt_path).strip():
            raise ValueError("logtxt_path is required when file logging is enabled")

        try:
            path, path_key = self._normalize_log_path(logtxt_path)
        except (OSError, RuntimeError, ValueError) as exc:
            print(f'Failed to prepare output log "{logtxt_path}": {exc}')
            return
        # 同一路径已被别的 runner 占用（旧任务未结束又新开了同位置日志）时，
        # 先关掉旧 runner，保证同一时刻只有一个写者
        old_runner_id = self._log_path_owners.get(path_key)
        if old_runner_id is not None and old_runner_id != runner_id:
            self._close_runner_file_log(old_runner_id)

        try:
            # 确保父目录存在；"w" 模式会清空旧文件，代表这份日志从本任务重新开始
            path.parent.mkdir(parents=True, exist_ok=True)
            log_file = path.open("w", encoding="utf-8", newline="\n")
        except OSError as exc:
            print(f'Failed to open output log "{path}": {exc}')
            return
        self._runner_file_logs[runner_id] = _RunnerFileLog(
            path=path,
            path_key=path_key,
            file=log_file,
        )
        self._log_path_owners[path_key] = runner_id


    def _get_runner_file_log(self, runner_id: str | None) -> _RunnerFileLog | None:
        """返回某 runner 的文件日志状态；runner_id 为 None 时返回 None."""
        if runner_id is None:
            return None
        return self._runner_file_logs.get(runner_id)


    def _resolve_append_runner_id(self, runner_id: str | None) -> str | None:
        """把一次输出归到具体的、带有文件日志的 runner_id.

        显式传入 runner_id 且它带日志时直接用它；
        否则在当前绑定集合里找“唯一”带日志的 runner——只有恰好一个才返回，
        多个或零个都返回 None（避免歧义 / 无日志可写）.
        """
        if runner_id is not None:
            return runner_id if self._get_runner_file_log(runner_id) is not None else None

        candidates = [
            current_runner_id
            for current_runner_id in self._current_runner_id
            if self._get_runner_file_log(current_runner_id) is not None
        ]
        return candidates[0] if len(candidates) == 1 else None


    def _write_file_log(
        self,
        runner_id: str | None,
        text: str,
        replace_last: bool,
    ) -> None:
        """把一行文本写入对应 runner 的日志文件（与屏显逻辑保持一致）.

        普通行：追加到文件末尾，并记录其起始偏移；进度行（replace_last=True）
        且上一行可替换时：seek 回上一行起始处覆盖写再 truncate，从而在文件里
        也做到“\\r 原地更新同一行”，不会产生堆积的重复进度行.
        """
        resolved_runner_id = self._resolve_append_runner_id(runner_id)
        state = self._get_runner_file_log(resolved_runner_id)
        if state is None:
            return

        try:
            if replace_last and state.is_last_line_replaceable and state.last_line_start is not None:
                # 覆盖上一进度行：回到其起始偏移，重写并截断其后内容
                state.file.seek(state.last_line_start)
                state.file.write(text)
                state.file.write("\n")
                state.file.truncate()
            else:
                # 普通追加：定位到文件末尾，记录新行起始偏移后写入
                state.file.seek(0, 2)
                state.last_line_start = state.file.tell()
                state.file.write(text)
                state.file.write("\n")
            state.file.flush()
            state.is_last_line_replaceable = replace_last
        except (OSError, UnicodeError, ValueError) as exc:
            # 磁盘/编码异常不应拖垮 GUI：打印后关闭该文件，后续输出不再尝试写
            print(f'Failed to write output log "{state.path}": {exc}')
            if resolved_runner_id is not None:
                self._close_runner_file_log(resolved_runner_id)


    def _clear_output_state(self) -> None:
        """只清空 GUI 显示与解码/文本缓冲，不改动已落盘的文件日志."""
        self.text_edit.clear()
        self._stream_decoders.clear()
        self._text_buffers.clear()
        self._is_last_line_replaceable = False


    def clear(self) -> None:
        """清空输出区域（仅屏幕显示）.

        刻意不同步清空 runner 的文件日志：HachimiDX_log.txt 是一次抄谱的
        落盘产物，用户点击“清空”只是清掉屏幕历史，不应删除/截断已生成的日志，
        后续若仍有输出（进程仍在跑）也会照常续写.
        """
        self._clear_output_state()


    # ===== Process runner_output handling (runner_id + bytes) =====

    def bind_current_runner_id(
        self,
        runner_id: str | None,
        clear: bool = False,
        *,
        log_enabled: bool = False,
        logtxt_path: str | Path | None = None,
    ) -> None:
        """
        Bind this output widget to a specific runner_id.
        When runner_id is set, handle_process_output will only accept output for the same runner_id.

        Note: output widget holds a list of runner_ids.

        Args:
            runner_id (str | None): The runner ID to bind to. If None, unbinds from any runner.
            clear (bool): Whether to clear existing output when setting a new runner ID.
            log_enabled (bool): Whether to enable file logging for this runner.
            logtxt_path (str | Path | None): Path to the log file when logging is enabled.
        """
        
        if runner_id:
            # 绑定新 runner：按其配置（重新）打开日志文件并接管该路径
            self._configure_runner_file_log(runner_id, log_enabled, logtxt_path)
            self._current_runner_id.add(runner_id)
        else:
            # 解除绑定：关闭所有仍持有的 runner 日志文件
            for current_runner_id in tuple(self._current_runner_id):
                self._close_runner_file_log(current_runner_id)
            self._current_runner_id = set()
            
        if clear:
            # clear 只清屏幕显示，不影响已落盘的日志文件
            self._clear_output_state()

    
    def handle_process_ended(self, runner_id: str, _: any) -> None:
        """
        Slot: consume ProcessManager.signals.runner_ended(runner_id, RunnerEnded).
        Unbinds the given runner_id from this output widget.
        """

        self._flush_runner(runner_id)
        # 任务结束：刷新缓冲后关闭其日志文件句柄，此后该 txt 不再被本组件修改
        self._close_runner_file_log(runner_id)
        self._current_runner_id.discard(runner_id)



    def handle_process_output(self, runner_id: str, stream: str, payload: object) -> None:
        """
        Slot: consume ProcessManager.signals.runner_output(runner_id, stream, bytes).
        Handles output only if runner_id matches the bound runner_id(s).
        """

        if not self._current_runner_id or runner_id not in self._current_runner_id:
            return

        if not isinstance(payload, (bytes, bytearray)):
            return
        if stream not in {"stdout", "stderr"}:
            return

        key = (runner_id, stream)
        decoder = self._stream_decoders.setdefault(key, _OutputStreamDecoder())
        text = decoder.feed(payload)
        if text:
            self._process_text_buffer(key, text)




    def flush_buffer(self) -> None:
        """刷新缓冲区，输出剩余内容"""
        runner_ids = {runner_id for runner_id, _ in self._stream_decoders}
        runner_ids.update(runner_id for runner_id, _ in self._text_buffers)
        for runner_id in runner_ids:
            self._flush_runner(runner_id)


    def _flush_runner(self, runner_id: str) -> None:
        keys = {
            key for key in self._stream_decoders
            if key[0] == runner_id
        }
        keys.update(
            key for key in self._text_buffers
            if key[0] == runner_id
        )
        for key in keys:
            decoder = self._stream_decoders.pop(key, None)
            if decoder is not None:
                text = decoder.feed(b"", final=True)
                if text:
                    self._process_text_buffer(key, text)
            buffered_text = self._text_buffers.pop(key, "")
            if buffered_text.strip():
                self._append_output(
                    self._strip_ansi(buffered_text),
                    replace_last=False,
                    runner_id=runner_id,
                )



    def _strip_ansi(self, text: str) -> str:
        """移除 ANSI 转义序列"""
        return self._ansi_escape.sub('', text)



    def _should_ignore_line(self, text: str) -> bool:
        """根据包含词过滤列表判断该行是否应忽略"""
        if not text:
            return False
        for keywords in self._ignore_contains_filters:
            if all(keyword and keyword in text for keyword in keywords):
                return True
        return False



    def _process_text_buffer(self, key: tuple[str, str], text: str) -> None:
        """处理文本缓冲区中的 \\r 和 \\n"""
        # 将新文本添加到缓冲区
        text_buffer = self._text_buffers.get(key, "") + text
        
        # 处理缓冲区中的文本
        while True:
            # 检查是否有换行符
            if '\n' in text_buffer:
                # 有换行符，处理到换行符为止的内容
                line, text_buffer = text_buffer.split('\n', 1)
                
                # 处理 \\r（回车符）
                if '\r' in line:
                    # 有多个 \\r 分隔的部分，只保留最后一段
                    parts = line.split('\r')
                    final_text = parts[-1]
                    
                    # 如果有多个部分，说明之前有进度更新
                    if len(parts) > 1:
                        # 先用倒数第二个部分更新进度行（如果存在）
                        if len(parts) >= 2 and parts[-2].strip():
                            clean_line = self._strip_ansi(parts[-2])
                            self._append_output(
                                clean_line,
                                replace_last=True,
                                runner_id=key[0],
                            )
                    
                    # 然后追加最终文本作为新行（如果非空）
                    if final_text.strip():
                        clean_line = self._strip_ansi(final_text)
                        self._append_output(
                            clean_line,
                            replace_last=False,
                            runner_id=key[0],
                        )
                    else:
                        # 只有当进度内容未被过滤时，才发送空行以固定进度行
                        if len(parts) >= 2:
                            progress_clean = self._strip_ansi(parts[-2])
                            if not self._should_ignore_line(progress_clean):
                                self._append_output(
                                    "",
                                    replace_last=False,
                                    runner_id=key[0],
                                )
                        else:
                            self._append_output(
                                "",
                                replace_last=False,
                                runner_id=key[0],
                            )
                else:
                    # 没有 \\r，直接追加
                    if line.strip():
                        clean_line = self._strip_ansi(line)
                        self._append_output(
                            clean_line,
                            replace_last=False,
                            runner_id=key[0],
                        )
                        
            elif '\r' in text_buffer:
                # 有回车符但没有换行符，说明是进度更新
                parts = text_buffer.split('\r')
                # 只发送倒数第二个部分（如果有的话）
                # 因为最后一个部分可能不完整，需要保留在缓冲区
                if len(parts) >= 2:
                    # 取倒数第二个部分（这是最新的完整进度）
                    progress_text = parts[-2]
                    if progress_text.strip():
                        clean_line = self._strip_ansi(progress_text)
                        self._append_output(
                            clean_line,
                            replace_last=True,
                            runner_id=key[0],
                        )
                # 保留最后一部分在缓冲区
                text_buffer = parts[-1]
                break
            else:
                # 没有换行符也没有回车符，等待更多数据
                break

        self._text_buffers[key] = text_buffer


    def get_recent_lines(self, num_lines):
        """
        获取最近几行文本 (过滤空行)
        
        :param num_lines: 要获取的行数
        :return: 最近几行文本的字符串
        """
        full_text = self.text_edit.toPlainText()
        lines = full_text.split('\n')
        # 获取最后 num_lines 行，过滤空行
        recent_lines = [line for line in lines[-num_lines:] if line.strip()]
        return '\n'.join(recent_lines)
