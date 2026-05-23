import re

from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import QTextEdit, QVBoxLayout, QWidget

from ..ui_style import UI_Style


class OutputLogWidget(QWidget):
    """通用日志输出组件。

    Supports two usage patterns:
    1) Manual: call append_text(text)
    2) QProcess streaming (raw): connect QProcess.readyReadStandardOutput
       to handle_raw_output (recommended with MergedChannels).

    Notes:
    - Handles carriage-return (\r) progress updates by replacing the last line.
    - Strips ANSI escape sequences.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_runner_id: set = set()

        # 全局日志过滤：行中包含以下任一关键词时忽略该行
        self._ignore_contains_filters: list[str] = [
            
            # TensorRT 推理 detect/obb
            "[TRT] [I] Loaded engine size: ",
            "[TRT] [I] [MemUsageChange] TensorRT-managed allocation in IExecutionContext creation: ",
            "[TRT] [W] WARNING The logger passed into createInferRuntime differs from one already registered for an existing builder, runtime, or refitter. ",
            
            # TensorRT 推理 classify
            "[TRT] [I] [MS] Running engine with multi stream info",
            "[TRT] [I] [MS] Number of aux streams is",
            "[TRT] [I] [MS] Number of total worker streams is",
            "[TRT] [I] [MS] The main stream provided by execute/enqueue calls is the first worker stream",
            
            # TensorRT 转换模型
            "[TRT] [W] Requested amount of GPU memory ",
            "[TRT] [W] UNSUPPORTED_STATE: Skipping tactic",
            "[TRT] [E] [virtualMemoryBuffer.cpp::nvinfer1::StdVirtualMemoryBufferImpl::resizePhysical::154] Error Code",

            # Librosa 加载音频 (detect click start)
            "error: No comment text / valid description?"
        ]

        # 保存的最大行数
        self.max_output_lines = 1000
        # 标记最后一行是否可被替换 (用于处理 \r)
        self._is_last_line_replaceable = False
        # ANSI 转义序列的正则表达式
        self._ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
        # 文本缓冲区（用于处理 \r）
        self._text_buffer = ""

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
        # 删除旧的行，仅保留最近的 400 行
        cursor = QTextCursor(document)
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        # 计算需要删除的行数
        lines_to_remove = document.blockCount() - self.max_output_lines
        for _ in range(lines_to_remove):
            cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
            cursor.removeSelectedText()
            cursor.deleteChar()  # 删除换行符



    def _append_output(self, text: str, replace_last: bool = False) -> None:
        """
        添加输出文本
        
        :param text: 要添加的文本
        :param replace_last: 是否替换最后一行（用于进度条更新，处理 \\r）
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
        
        # 限制最大行数
        self._limit_output_lines()
        
        # 智能滚动：仅当用户之前在底部时才自动滚动
        if was_at_bottom:
            self.text_edit.moveCursor(QTextCursor.MoveOperation.End)
        else:
            # 如果用户不在底部，恢复原来的滚动位置
            scrollbar.setValue(old_scroll_value)



    def append_text(self, text):
        """
        手动添加文本（用于非进程输出的日志）
        安全假设：手动添加的文本不包含 \r
        
        :param text: 要添加的文本
        """
        self._append_output(text, replace_last=False)


    # ===== Process runner_output handling (runner_id + bytes) =====

    def bind_current_runner_id(self, runner_id: str | None, clear: bool = False) -> None:
        """
        Bind this output widget to a specific runner_id.
        When runner_id is set, handle_process_output will only accept output for the same runner_id.

        Note: output widget holds a list of runner_ids.

        Args:
            runner_id (str | None): The runner ID to bind to. If None, unbinds from any runner.
            clear (bool): Whether to clear existing output when setting a new runner ID.
        """
        
        if runner_id:
            self._current_runner_id.add(runner_id)
        else:
            self._current_runner_id = set()
            
        if clear:
            self.text_edit.clear()
            self._text_buffer = ""
            self._is_last_line_replaceable = False

    
    def handle_process_ended(self, runner_id: str, _: any) -> None:
        """
        Slot: consume ProcessManager.signals.runner_ended(runner_id, RunnerEnded).
        Unbinds the given runner_id from this output widget.
        """

        self._current_runner_id.discard(runner_id)



    def handle_process_output(self, runner_id: str, payload: object) -> None:
        """
        Slot: consume ProcessManager.signals.runner_output(runner_id, bytes).
        Handles output only if runner_id matches the bound runner_id(s).
        """

        if not self._current_runner_id or runner_id not in self._current_runner_id:
            return

        if not isinstance(payload, (bytes, bytearray)):
            return

        text = self._decode_output(payload)
        self._process_text_buffer(text)




    # ===== QProcess raw output handling =====

    def handle_raw_output(self):
        """
        处理来自 QProcess 的原始输出（槽函数）
        直接连接到 QProcess.readyReadStandardOutput 信号
        """
        # 获取发送者（QProcess）
        process = self.sender()
        if not process:
            return
        
        # 读取原始字节
        output = process.readAllStandardOutput()
        
        # 解码
        text = self._decode_output(output)
        
        # 处理 \r 和 \n
        self._process_text_buffer(text)



    def flush_buffer(self) -> None:
        """刷新缓冲区，输出剩余内容"""
        if self._text_buffer.strip():
            clean_line = self._strip_ansi(self._text_buffer)
            self._append_output(clean_line, replace_last=False)
            self._text_buffer = ""



    def _strip_ansi(self, text: str) -> str:
        """移除 ANSI 转义序列"""
        return self._ansi_escape.sub('', text)



    def _should_ignore_line(self, text: str) -> bool:
        """根据包含词过滤列表判断该行是否应忽略"""
        if not text:
            return False

        for keyword in self._ignore_contains_filters:
            if keyword and keyword in text:
                return True
        return False



    def _decode_output(self, byte_array) -> str:
        """解码字节流"""
        # 先尝试 UTF-8 编码（Python 脚本默认输出）
        try:
            return bytes(byte_array).decode('utf-8', errors='strict')
        except UnicodeDecodeError:
            # 失败则尝试 GBK（Windows 控制台默认）
            try:
                return bytes(byte_array).decode('gbk', errors='strict')
            except:
                # 最后使用 UTF-8 with replace（兜底）
                return bytes(byte_array).decode('utf-8', errors='replace')



    def _process_text_buffer(self, text: str) -> None:
        """处理文本缓冲区中的 \\r 和 \\n"""
        # 将新文本添加到缓冲区
        self._text_buffer += text
        
        # 处理缓冲区中的文本
        while True:
            # 检查是否有换行符
            if '\n' in self._text_buffer:
                # 有换行符，处理到换行符为止的内容
                line, self._text_buffer = self._text_buffer.split('\n', 1)
                
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
                            self._append_output(clean_line, replace_last=True)
                    
                    # 然后追加最终文本作为新行（如果非空）
                    if final_text.strip():
                        clean_line = self._strip_ansi(final_text)
                        self._append_output(clean_line, replace_last=False)
                    else:
                        # 只有当进度内容未被过滤时，才发送空行以固定进度行
                        if len(parts) >= 2:
                            progress_clean = self._strip_ansi(parts[-2])
                            if not self._should_ignore_line(progress_clean):
                                self._append_output("", replace_last=False)
                        else:
                            self._append_output("", replace_last=False)
                else:
                    # 没有 \\r，直接追加
                    if line.strip():
                        clean_line = self._strip_ansi(line)
                        self._append_output(clean_line, replace_last=False)
                        
            elif '\r' in self._text_buffer:
                # 有回车符但没有换行符，说明是进度更新
                parts = self._text_buffer.split('\r')
                # 只发送倒数第二个部分（如果有的话）
                # 因为最后一个部分可能不完整，需要保留在缓冲区
                if len(parts) >= 2:
                    # 取倒数第二个部分（这是最新的完整进度）
                    progress_text = parts[-2]
                    if progress_text.strip():
                        clean_line = self._strip_ansi(progress_text)
                        self._append_output(clean_line, replace_last=True)
                # 保留最后一部分在缓冲区
                self._text_buffer = parts[-1]
                break
            else:
                # 没有换行符也没有回车符，等待更多数据
                break


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
