from PyQt6.QtWidgets import QWidget, QVBoxLayout, QPlainTextEdit, QPushButton, QHBoxLayout
from PyQt6.QtCore import pyqtSignal, QObject, pyqtSlot
from PyQt6.QtGui import QFont

class StreamRedirector(QObject):
    text_written = pyqtSignal(str)

    def write(self, text):
        self.text_written.emit(str(text))

    def flush(self):
        pass

class ConsoleTab(QWidget):
    def __init__(self):
        super().__init__()
        self.setup_ui()

    def setup_ui(self):
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
    def append_text(self, text):
        scrollbar = self.text_area.verticalScrollBar()
        is_at_bottom = scrollbar.value() >= scrollbar.maximum() - 2
        
        self.text_area.moveCursor(self.text_area.textCursor().MoveOperation.End)
        self.text_area.insertPlainText(text)
        
        if is_at_bottom:
            scrollbar.setValue(scrollbar.maximum())

    def clear_console(self):
        self.text_area.clear()
