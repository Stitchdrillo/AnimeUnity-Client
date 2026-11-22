"""Embedded local video player page with keyboard shortcuts and episode navigation."""

import os
from typing import Any
from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSlider,
    QStyle,
    QVBoxLayout,
    QWidget,
)
from gui.widgets import ClickableVideoWidget


class VideoPlayerPage(QWidget):
    """Self-contained media player view embedded inside the Library stacked widget."""

    back_requested = pyqtSignal(int)
    auto_download_next_requested = pyqtSignal(int, str)

    def __init__(self, db_manager, config_manager) -> None:
        super().__init__()
        self.db_manager = db_manager
        self.config_manager = config_manager
        self.current_context: dict[str, Any] | None = None
        self.setup_ui()

    def setup_ui(self) -> None:
        layout = QVBoxLayout()

        top_bar = QHBoxLayout()
        back_btn = QPushButton("← Back to Series")
        back_btn.setFixedWidth(150)
        back_btn.clicked.connect(self.exit_player)

        self.player_title = QLabel("Title - Episode X")
        self.player_title.setStyleSheet("font-size: 18px; font-weight: bold;")
        self.player_title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        top_bar.addWidget(back_btn)
        top_bar.addWidget(self.player_title, 1)
        top_bar.addStretch()
        layout.addLayout(top_bar)

        self.video_widget = ClickableVideoWidget()
        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)
        self.player.setVideoOutput(self.video_widget)
        layout.addWidget(self.video_widget, 1)

        self.video_widget.action_skip_back.connect(lambda: self.skip_media(-10000))
        self.video_widget.action_skip_fwd.connect(lambda: self.skip_media(10000))
        self.video_widget.action_toggle_play.connect(self.toggle_playback)

        controls = QHBoxLayout()
        self.skip_back_btn = QPushButton("⏪ 10s")
        self.skip_back_btn.setFixedWidth(60)
        self.skip_back_btn.clicked.connect(lambda: self.skip_media(-10000))

        self.play_btn = QPushButton()
        self.play_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self.play_btn.clicked.connect(self.toggle_playback)

        self.skip_fwd_btn = QPushButton("10s ⏩")
        self.skip_fwd_btn.setFixedWidth(60)
        self.skip_fwd_btn.clicked.connect(lambda: self.skip_media(10000))

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.sliderMoved.connect(self.player.setPosition)
        self.player.positionChanged.connect(self.slider.setValue)
        self.player.durationChanged.connect(lambda duration: self.slider.setRange(0, duration))

        self.fullscreen_btn = QPushButton("⛶")
        self.fullscreen_btn.setFixedWidth(40)
        self.fullscreen_btn.clicked.connect(
            lambda: self.video_widget.setFullScreen(not self.video_widget.isFullScreen())
        )

        controls.addWidget(self.skip_back_btn)
        controls.addWidget(self.play_btn)
        controls.addWidget(self.skip_fwd_btn)
        controls.addWidget(self.slider)
        controls.addWidget(self.fullscreen_btn)
        layout.addLayout(controls)

        nav_bar = QHBoxLayout()
        self.prev_btn = QPushButton("Previous Episode")
        self.next_btn = QPushButton("Next Episode")
        self.prev_btn.clicked.connect(lambda: self.play_adjacent_episode(-1))
        self.next_btn.clicked.connect(lambda: self.play_adjacent_episode(1))

        nav_bar.addWidget(self.prev_btn)
        nav_bar.addStretch()
        nav_bar.addWidget(self.next_btn)
        layout.addLayout(nav_bar)

        self.setLayout(layout)

    def play_episode(self, anime_title: str, anime_id: int, ep_num: str, file_path: str) -> bool:
        """Load and start playing a local episode file. Returns False if the file is missing."""
        if not file_path or not os.path.exists(file_path):
            QMessageBox.warning(self, "Error", "Video file not found locally.")
            self.db_manager.update_episode_status(anime_id, ep_num, "not_downloaded")
            return False

        self.current_context = {
            "anime_title": anime_title,
            "anime_id": anime_id,
            "ep_num": ep_num,
            "file_path": file_path,
        }
        self.player_title.setText(f"{anime_title} - Episode {ep_num}")
        self.player.setSource(QUrl.fromLocalFile(file_path))

        self.video_widget.setFocus()
        self.player.play()
        self.play_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause))

        if self.config_manager.get("auto_download_next"):
            self.auto_download_next_requested.emit(anime_id, str(ep_num))

        return True

    def skip_media(self, offset_ms: int) -> None:
        """Seek forward or backward by `offset_ms` milliseconds within media bounds."""
        if self.player.mediaStatus() == QMediaPlayer.MediaStatus.NoMedia:
            return
        new_pos = max(0, min(self.player.duration(), self.player.position() + offset_ms))
        self.player.setPosition(new_pos)

    def toggle_playback(self) -> None:
        """Toggle between playing and paused states."""
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
            self.play_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        else:
            self.player.play()
            self.play_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause))

    def play_adjacent_episode(self, offset: int) -> None:
        """Switch to the previous (`offset=-1`) or next (`offset=1`) downloaded episode."""
        if not self.current_context:
            return

        current_num = float(self.current_context["ep_num"])
        anime_id = self.current_context["anime_id"]
        anime_title = self.current_context["anime_title"]

        episodes = sorted(
            self.db_manager.get_episodes_by_anime(anime_id),
            key=lambda ep: float(ep["episode_number"]),
        )
        curr_index = next(
            (i for i, ep in enumerate(episodes) if float(ep["episode_number"]) == current_num),
            -1,
        )
        target_index = curr_index + offset

        if not (0 <= target_index < len(episodes)):
            return

        target_ep = episodes[target_index]
        if target_ep["status"] != "downloaded":
            QMessageBox.information(self, "Unavailable", "That episode is not downloaded yet.")
            return

        should_delete = (offset == 1) and self.config_manager.get("auto_delete_seen", False)
        previous_ctx = self.current_context

        # Release the file handle before attempting to delete the watched video on Windows.
        self.cleanup()
        QApplication.processEvents()

        if should_delete:
            try:
                if os.path.exists(previous_ctx["file_path"]):
                    os.remove(previous_ctx["file_path"])
                self.db_manager.update_episode_status(
                    previous_ctx["anime_id"],
                    previous_ctx["ep_num"],
                    "not_downloaded",
                )
                print(f"Auto-deleted {previous_ctx['file_path']}")
            except OSError as err:
                print(f"Failed to auto-delete video: {err}")

        self.play_episode(
            anime_title,
            target_ep["anime_id"],
            target_ep["episode_number"],
            target_ep["file_path"],
        )

    def exit_player(self) -> None:
        """Stop playback and return to the parent series details page."""
        self.cleanup()
        if self.current_context:
            self.back_requested.emit(self.current_context["anime_id"])

    def cleanup(self) -> None:
        """Stop playback, release the media source, and exit fullscreen if active."""
        self.player.stop()
        self.player.setSource(QUrl())
        if self.video_widget.isFullScreen():
            self.video_widget.setFullScreen(False)
