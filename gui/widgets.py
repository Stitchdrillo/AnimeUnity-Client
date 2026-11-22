"""Reusable PyQt6 widgets, item delegates, and dialogs for the library UI."""

import os
from functools import lru_cache
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QIcon, QKeyEvent, QMouseEvent, QPixmap
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLineEdit, QStyledItemDelegate


@lru_cache(maxsize=150)
def get_cached_icon(path: str) -> QIcon:
    """Load and scale a cover image once, caching the resulting `QIcon` in memory."""
    pixmap = QPixmap(path)
    scaled = pixmap.scaled(
        150,
        220,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    return QIcon(scaled)


class LazyCoverDelegate(QStyledItemDelegate):
    """Loads cover thumbnails on demand only when grid items scroll into view."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        fallback_pixmap = QPixmap(150, 220)
        fallback_pixmap.fill(Qt.GlobalColor.transparent)
        self.fallback_icon = QIcon(fallback_pixmap)

    def initStyleOption(self, option, index) -> None:
        super().initStyleOption(option, index)
        cover_path = index.data(Qt.ItemDataRole.UserRole + 1)

        if cover_path and os.path.exists(cover_path):
            option.icon = get_cached_icon(cover_path)
        else:
            option.icon = self.fallback_icon


class ClickableVideoWidget(QVideoWidget):
    """Video surface supporting double-click fullscreen and keyboard media shortcuts."""

    action_skip_back = pyqtSignal()
    action_skip_fwd = pyqtSignal()
    action_toggle_play = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        self.setFullScreen(not self.isFullScreen())
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key == Qt.Key.Key_Escape and self.isFullScreen():
            self.setFullScreen(False)
        elif key == Qt.Key.Key_F:
            self.setFullScreen(not self.isFullScreen())
        elif key == Qt.Key.Key_Space:
            self.action_toggle_play.emit()
            event.accept()
        elif key == Qt.Key.Key_Left:
            self.action_skip_back.emit()
        elif key == Qt.Key.Key_Right:
            self.action_skip_fwd.emit()
        else:
            super().keyPressEvent(event)


class DownloadRangeDialog(QDialog):
    """Modal dialog prompting for start and end episode numbers to batch-queue."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Download Range")

        layout = QFormLayout()

        self.start_input = QLineEdit()
        self.start_input.setPlaceholderText("e.g. 1 (empty for first)")

        self.end_input = QLineEdit()
        self.end_input.setPlaceholderText("e.g. 12 (empty for last)")

        layout.addRow("Start Episode:", self.start_input)
        layout.addRow("End Episode:", self.end_input)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self.setLayout(layout)

    def get_range(self) -> tuple[str, str]:
        """Return trimmed start and end episode number strings."""
        return self.start_input.text().strip(), self.end_input.text().strip()
