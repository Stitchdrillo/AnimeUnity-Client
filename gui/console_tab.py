"""Live stdout/stderr console viewer tab."""

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QHBoxLayout, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget


class StreamRedirector(QObject):
    """File-like stream wrapper that forwards `write()` calls over a Qt signal."""

    text_written = pyqtSignal(str)

    def write(self, text: str) -> None:
        self.text_written.emit(str(text))

    def flush(self) -> None:
        pass


class ConsoleTab(QWidget):
    """Read-only dark console widget displaying redirected application logs."""

    def __init__(self) -> None:
        super().__init__()
        self.setup_ui()

    def setup_ui(self) -> None:
        layout = QVBoxLayout()

        toolbar = QHBoxLayout()
        self.clear_btn = QPushButton("Clear Console")
        self.clear_btn.setFixedWidth(120)
        self.clear_btn.clicked.connect(self.clear_console)
        toolbar.addStretch()
        toolbar.addWidget(self.clear_btn)
        layout.addLayout(toolbar)

        self.text_area = QPlainTextEdit()
        self.text_area.setReadOnly(True)
        self.text_area.setFont(QFont("Consolas", 10))
        self.text_area.setStyleSheet("background-color: #1e1e1e; color: #d4d4d4;")
        layout.addWidget(self.text_area)

        self.setLayout(layout)

    @pyqtSlot(str)
    def append_text(self, text: str) -> None:
        """Append log output while preserving auto-scroll only if already at the bottom."""
        scrollbar = self.text_area.verticalScrollBar()
        is_at_bottom = scrollbar.value() >= scrollbar.maximum() - 2

        self.text_area.moveCursor(self.text_area.textCursor().MoveOperation.End)
        self.text_area.insertPlainText(text)

        if is_at_bottom:
            scrollbar.setValue(scrollbar.maximum())

    def clear_console(self) -> None:
        self.text_area.clear()
