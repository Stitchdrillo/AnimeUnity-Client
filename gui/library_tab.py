"""Main library view handling the anime grid, series details, and episode actions."""

import json
import os
from typing import Any
from PyQt6.QtCore import QSize, Qt, QThreadPool, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QFont, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from core.downloader import LibrarySyncWorker
from gui.player_page import VideoPlayerPage
from gui.widgets import DownloadRangeDialog, LazyCoverDelegate


class LibraryTab(QWidget):
    """Coordinates browsing the anime catalog, inspecting episodes, and launching playback."""

    episode_download_requested = pyqtSignal(dict, str)

    def __init__(self, db_manager, config_manager) -> None:
        super().__init__()
        self.db_manager = db_manager
        self.config_manager = config_manager
        self.thread_pool = QThreadPool()

        self.current_anime: dict[str, Any] | None = None
        self.episode_ui_elements: dict[str, dict[str, Any]] = {}
        self.queued_episodes: set[str] = set()

        transparent_pixmap = QPixmap(150, 220)
        transparent_pixmap.fill(Qt.GlobalColor.transparent)
        self.shared_placeholder = QIcon(transparent_pixmap)

        self.setup_ui()

    def setup_ui(self) -> None:
        self.main_layout = QVBoxLayout()
        self.stacked_widget = QStackedWidget()

        self.grid_page = QWidget()
        self.setup_grid_page()
        self.stacked_widget.addWidget(self.grid_page)

        self.details_page = QWidget()
        self.setup_details_page()
        self.stacked_widget.addWidget(self.details_page)

        self.player_page = VideoPlayerPage(self.db_manager, self.config_manager)
        self.player_page.back_requested.connect(self.on_player_closed)
        self.player_page.auto_download_next_requested.connect(self.auto_queue_next)
        self.stacked_widget.addWidget(self.player_page)

        self.main_layout.addWidget(self.stacked_widget)
        self.setLayout(self.main_layout)
        self.load_library()

    # ------------------------------------------------------------------
    # Grid Page
    # ------------------------------------------------------------------

    def setup_grid_page(self) -> None:
        layout = QVBoxLayout()
        header_layout = QHBoxLayout()

        title_label = QLabel("<b>My Anime Library</b>")
        title_label.setStyleSheet("font-size: 18px;")

        self.sync_status_label = QLabel("Ready")
        self.sync_status_label.setStyleSheet("color: gray; font-style: italic;")

        self.refresh_btn = QPushButton("Sync from XML")
        self.refresh_btn.clicked.connect(self.start_xml_sync)

        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Search library...")
        self.search_bar.setFixedWidth(250)
        self.search_bar.textChanged.connect(lambda _: self.filter_library())

        self.downloaded_only_check = QCheckBox("Downloaded Only")
        self.downloaded_only_check.stateChanged.connect(lambda _: self.filter_library())

        header_layout.addWidget(title_label)
        header_layout.addWidget(self.search_bar)
        header_layout.addWidget(self.downloaded_only_check)
        header_layout.addStretch()
        header_layout.addWidget(self.sync_status_label)
        header_layout.addWidget(self.refresh_btn)
        layout.addLayout(header_layout)

        self.grid_widget = QListWidget()
        self.grid_widget.setViewMode(QListWidget.ViewMode.IconMode)
        self.grid_widget.setItemDelegate(LazyCoverDelegate(self.grid_widget))
        self.grid_widget.setIconSize(QSize(150, 220))
        self.grid_widget.setGridSize(QSize(170, 310))
        self.grid_widget.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.grid_widget.setSpacing(15)
        self.grid_widget.setWordWrap(True)
        self.grid_widget.setUniformItemSizes(True)
        self.grid_widget.itemDoubleClicked.connect(self.on_anime_clicked)

        layout.addWidget(self.grid_widget)
        self.grid_page.setLayout(layout)

    def load_library(self) -> None:
        """Populate the library grid from SQLite and apply active filters."""
        self.grid_widget.clear()
        self.grid_widget.setUpdatesEnabled(False)

        for anime in self.db_manager.get_all_anime():
            display_text = f"{anime['title']}\n({anime['type']} - {anime['release_year']})"
            item = QListWidgetItem(display_text)
            item.setToolTip(display_text)
            item.setIcon(self.shared_placeholder)
            item.setData(Qt.ItemDataRole.UserRole, anime["id"])
            item.setData(Qt.ItemDataRole.UserRole + 1, anime["cover_path"])
            self.grid_widget.addItem(item)

        self.grid_widget.setUpdatesEnabled(True)
        self.filter_library()

    def filter_library(self) -> None:
        """Filter visible grid cards by search query and 'Downloaded Only' toggle."""
        search_term = self.search_bar.text().lower()
        show_downloaded_only = self.downloaded_only_check.isChecked()

        for i in range(self.grid_widget.count()):
            item = self.grid_widget.item(i)
            anime_id = item.data(Qt.ItemDataRole.UserRole)
            matches_text = search_term in item.text().lower()

            if show_downloaded_only:
                has_downloads = self.db_manager.has_downloaded_episodes(anime_id)
                item.setHidden(not (matches_text and has_downloads))
            else:
                item.setHidden(not matches_text)

    # ------------------------------------------------------------------
    # Details Page
    # ------------------------------------------------------------------

    def setup_details_page(self) -> None:
        layout = QVBoxLayout()

        top_bar = QHBoxLayout()
        back_btn = QPushButton("← Back to Library")
        back_btn.setFixedWidth(150)
        back_btn.clicked.connect(self.return_to_grid)
        top_bar.addWidget(back_btn)
        top_bar.addStretch()
        layout.addLayout(top_bar)

        self.det_title = QLabel("Title")
        self.det_title.setStyleSheet("font-size: 24px; font-weight: bold;")
        self.det_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.det_title)

        middle_layout = QHBoxLayout()
        bottom_layout = QHBoxLayout()

        meta_group = QGroupBox("Information")
        meta_layout = QVBoxLayout()
        self.det_meta = QLabel()
        self.det_meta.setWordWrap(True)
        self.det_meta.setAlignment(Qt.AlignmentFlag.AlignTop)
        meta_layout.addWidget(self.det_meta)
        meta_group.setLayout(meta_layout)
        middle_layout.addWidget(meta_group, 1)

        plot_group = QGroupBox("Description")
        plot_layout = QVBoxLayout()
        self.det_plot = QTextEdit()
        self.det_plot.setReadOnly(True)
        plot_layout.addWidget(self.det_plot)
        plot_group.setLayout(plot_layout)
        middle_layout.addWidget(plot_group, 2)

        related_group = QGroupBox("Related Series")
        related_layout = QVBoxLayout()
        self.related_list = QListWidget()
        self.related_list.itemClicked.connect(self.on_related_clicked)
        related_layout.addWidget(self.related_list)
        related_group.setLayout(related_layout)
        bottom_layout.addWidget(related_group, 1)

        episodes_group = QGroupBox("Episodes")
        episodes_layout = QVBoxLayout()

        ep_header = QHBoxLayout()
        self.dl_all_btn = QPushButton("Download All Missing")
        self.dl_all_btn.clicked.connect(self.download_all_episodes)

        self.dl_range_btn = QPushButton("Download Range")
        self.dl_range_btn.clicked.connect(self.download_range_episodes)

        self.del_all_btn = QPushButton("Delete All")
        self.del_all_btn.clicked.connect(self.delete_all_episodes)

        ep_header.addStretch()
        ep_header.addWidget(self.dl_all_btn)
        ep_header.addWidget(self.dl_range_btn)
        ep_header.addWidget(self.del_all_btn)
        episodes_layout.addLayout(ep_header)

        self.episodes_list = QListWidget()
        episodes_layout.addWidget(self.episodes_list)
        episodes_group.setLayout(episodes_layout)
        bottom_layout.addWidget(episodes_group, 2)

        layout.addLayout(middle_layout, 1)
        layout.addLayout(bottom_layout, 2)
        self.details_page.setLayout(layout)

    def return_to_grid(self) -> None:
        """Switch back to the library grid and refresh active filters."""
        self.stacked_widget.setCurrentIndex(0)
        self.filter_library()

    def on_anime_clicked(self, item: QListWidgetItem) -> None:
        anime_id = item.data(Qt.ItemDataRole.UserRole)
        self.load_details(anime_id)
        self.stacked_widget.setCurrentIndex(1)

    def on_related_clicked(self, item: QListWidgetItem) -> None:
        related_db_id = item.data(Qt.ItemDataRole.UserRole)
        if related_db_id:
            self.load_details(related_db_id)

    def load_details(self, anime_id: int) -> None:
        """Populate metadata, related entries, and episode rows for `anime_id`."""
        anime = self.db_manager.get_anime_by_id(anime_id)
        if not anime:
            return

        self.current_anime = anime
        self.det_title.setText(anime["title"])

        genres = ", ".join(json.loads(anime["genres"])) if anime["genres"] else "N/A"
        self.det_meta.setText(
            f"<b>Status:</b> {anime['status'] or 'Unknown'}<br><br>"
            f"<b>Year:</b> {anime['release_year'] or 'Unknown'}<br><br>"
            f"<b>Type:</b> {anime['type'] or 'Unknown'}<br><br>"
            f"<b>Studio:</b> {anime['studio'] or 'Unknown'}<br><br>"
            f"<b>Genres:</b> {genres}"
        )
        self.det_plot.setText(anime["plot"] or "No description available.")

        self.episodes_list.clear()
        self.episode_ui_elements.clear()
        for ep in self.db_manager.get_episodes_by_anime(anime_id):
            self.add_episode_row(ep)

        self._populate_related_series(anime)

    def _populate_related_series(self, anime: dict[str, Any]) -> None:
        """Render linked prequels/sequels/spin-offs in the related list."""
        self.related_list.clear()
        if not anime["related_json"]:
            return

        bold_font = QFont(self.font())
        bold_font.setBold(True)

        for rel in json.loads(anime["related_json"]):
            rel_title = rel.get("title_eng") or rel.get("title")
            rel_remote_id = rel.get("id")
            rel_db_record = self.db_manager.get_anime_by_remote_id(rel_remote_id)

            display_text = f"{rel_title} ({rel.get('type', '')} - {rel.get('date', '')})"
            item = QListWidgetItem(display_text)

            if rel_remote_id == anime["remote_id"]:
                item.setFont(bold_font)
                item.setBackground(Qt.GlobalColor.darkGray)

            if rel_db_record:
                item.setData(Qt.ItemDataRole.UserRole, rel_db_record["id"])
                cover_path = rel_db_record["cover_path"]
                if cover_path and os.path.exists(cover_path):
                    item.setIcon(QIcon(cover_path))
            else:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)

            self.related_list.addItem(item)

    def add_episode_row(self, ep: dict[str, Any]) -> None:
        """Build and insert a single episode row with Download or Play/Delete buttons."""
        if not self.current_anime:
            return

        row_widget = QWidget()
        row_layout = QHBoxLayout()
        row_layout.setContentsMargins(5, 2, 5, 2)

        lbl = QLabel(f"Episode {ep['episode_number']}")
        row_layout.addWidget(lbl)
        row_layout.addStretch()

        action_container = QWidget()
        action_layout = QHBoxLayout()
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_container.setLayout(action_layout)

        btn_key = f"{ep['anime_id']}_{ep['episode_number']}"
        self.episode_ui_elements[btn_key] = {
            "label": lbl,
            "action_layout": action_layout,
        }

        if ep["status"] != "downloaded":
            lbl.setStyleSheet("color: gray;")
            btn = QPushButton("Download")
            btn.setFixedWidth(120)

            ep_data = {
                "num": ep["episode_number"],
                "id": ep["remote_id"],
                "anime_id": ep["anime_id"],
                "download_dir": os.path.join(
                    self.config_manager.get("download_directory"),
                    self.current_anime["title"],
                ),
                "source_url": self.current_anime["source_url"],
            }
            display_name = f"{self.current_anime['title']} - Ep {ep['episode_number']}"
            btn.clicked.connect(
                lambda _, ed=ep_data, dn=display_name, k=btn_key: self.queue_episode(ed, dn, k)
            )

            if btn_key in self.queued_episodes:
                btn.setText("Queued...")
                btn.setEnabled(False)

            action_layout.addWidget(btn)
            self.episode_ui_elements[btn_key]["dl_btn"] = btn
        else:
            lbl.setStyleSheet("")
            self._attach_downloaded_buttons(
                action_layout,
                ep["anime_id"],
                ep["episode_number"],
                ep["file_path"],
            )

        row_layout.addWidget(action_container)
        row_widget.setLayout(row_layout)

        item = QListWidgetItem(self.episodes_list)
        item.setSizeHint(row_widget.sizeHint())
        item.setData(Qt.ItemDataRole.UserRole, btn_key)
        self.episodes_list.setItemWidget(item, row_widget)

    def _attach_downloaded_buttons(
        self,
        layout: QHBoxLayout,
        anime_id: int,
        ep_num: str,
        file_path: str,
    ) -> None:
        """Add Play and Delete buttons to an episode row's action layout."""
        play_btn = QPushButton("Play")
        play_btn.setFixedWidth(80)
        play_btn.clicked.connect(
            lambda _, aid=anime_id, num=ep_num, path=file_path: self.launch_player(aid, num, path)
        )

        del_btn = QPushButton("Delete")
        del_btn.setFixedWidth(80)
        del_btn.setStyleSheet("color: #d9534f;")
        del_btn.clicked.connect(
            lambda _, aid=anime_id, num=ep_num, path=file_path: self.delete_local_episode(
                aid, num, path
            )
        )

        layout.addWidget(play_btn)
        layout.addWidget(del_btn)

    # ------------------------------------------------------------------
    # Episode Actions & Queue Synchronization
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_episode_number(value: str | int | float) -> float | None:
        """Safely parse an episode number string into a float for numeric comparison."""
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def delete_local_episode(self, anime_id: int, ep_num: str, file_path: str) -> None:
        """Prompt to delete a downloaded video file and reset its database state."""
        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            f"Delete Episode {ep_num} from your drive?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError as err:
                QMessageBox.warning(self, "Error", f"Could not delete file: {err}")
                return

        self.db_manager.update_episode_status(anime_id, ep_num, "not_downloaded")
        self.load_details(anime_id)

    def delete_all_episodes(self) -> None:
        """Delete all locally downloaded video files for the active series."""
        if not self.current_anime:
            return

        reply = QMessageBox.question(
            self,
            "Confirm Delete All",
            f"Delete all downloaded episodes for {self.current_anime['title']}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        anime_id = self.current_anime["id"]
        for ep in self.db_manager.get_episodes_by_anime(anime_id):
            if ep["status"] == "downloaded" and ep["file_path"]:
                if os.path.exists(ep["file_path"]):
                    try:
                        os.remove(ep["file_path"])
                    except OSError as err:
                        print(f"Failed to delete {ep['file_path']}: {err}")
                self.db_manager.update_episode_status(anime_id, ep["episode_number"], "not_downloaded")

        self.load_details(anime_id)

    def download_all_episodes(self) -> None:
        """Queue every non-downloaded episode in the current series."""
        if not self.current_anime:
            return

        self.dl_all_btn.setEnabled(False)
        anime_id = self.current_anime["id"]

        for ep in self.db_manager.get_episodes_by_anime(anime_id):
            if ep["status"] != "downloaded":
                btn_key = f"{anime_id}_{ep['episode_number']}"
                ui = self.episode_ui_elements.get(btn_key)
                if ui and "dl_btn" in ui and ui["dl_btn"].isEnabled():
                    ui["dl_btn"].click()

        self.dl_all_btn.setEnabled(True)

    def download_range_episodes(self) -> None:
        """Queue episodes whose numeric episode numbers fall within the user-chosen range."""
        if not self.current_anime:
            return

        dialog = DownloadRangeDialog(self)
        if dialog.exec() != 1:
            return

        start_str, end_str = dialog.get_range()
        anime_id = self.current_anime["id"]
        episodes = self.db_manager.get_episodes_by_anime(anime_id)

        numeric_values = [
            val
            for ep in episodes
            if (val := self._parse_episode_number(ep["episode_number"])) is not None
        ]
        if not numeric_values:
            return

        try:
            start_num = float(start_str) if start_str else min(numeric_values)
            end_num = float(end_str) if end_str else max(numeric_values)
        except ValueError:
            QMessageBox.warning(
                self,
                "Invalid Input",
                "Please enter valid episode numbers (e.g. 1 to 12).",
            )
            return

        if start_num > end_num:
            QMessageBox.warning(
                self,
                "Invalid Range",
                "Start episode cannot be greater than end episode.",
            )
            return

        for ep in episodes:
            ep_val = self._parse_episode_number(ep["episode_number"])
            if ep_val is None or not (start_num <= ep_val <= end_num):
                continue

            btn_key = f"{anime_id}_{ep['episode_number']}"
            ui = self.episode_ui_elements.get(btn_key)
            if ui and "dl_btn" in ui and ui["dl_btn"].isEnabled():
                ui["dl_btn"].click()

    def queue_episode(self, ep_data: dict[str, Any], display_name: str, btn_key: str) -> None:
        """Mark an episode as queued in the UI and forward it to `DownloadTab`."""
        self.queued_episodes.add(btn_key)
        ui = self.episode_ui_elements.get(btn_key)
        if ui and "dl_btn" in ui:
            ui["dl_btn"].setText("Queued...")
            ui["dl_btn"].setEnabled(False)
        self.episode_download_requested.emit(ep_data, display_name)

    @pyqtSlot(int, str)
    def on_episode_downloaded(self, anime_id: int, ep_num: str) -> None:
        """Swap the Download button out for Play/Delete once a download completes."""
        btn_key = f"{anime_id}_{ep_num}"
        self.queued_episodes.discard(btn_key)
        ui = self.episode_ui_elements.get(btn_key)

        if ui and self.current_anime and int(self.current_anime["id"]) == int(anime_id):
            try:
                ui["label"].setStyleSheet("")
                layout: QHBoxLayout = ui["action_layout"]
                while layout.count():
                    child = layout.takeAt(0)
                    if child.widget():
                        child.widget().deleteLater()

                ep_db = next(
                    (
                        e
                        for e in self.db_manager.get_episodes_by_anime(anime_id)
                        if str(e["episode_number"]) == str(ep_num)
                    ),
                    None,
                )
                if ep_db:
                    self._attach_downloaded_buttons(
                        layout,
                        anime_id,
                        ep_num,
                        ep_db["file_path"],
                    )
            except RuntimeError:
                pass

        if self.downloaded_only_check.isChecked():
            self.filter_library()

    @pyqtSlot(int, str)
    def on_episode_download_cancelled(self, anime_id: int, ep_num: str) -> None:
        """Reset an episode's button back to 'Download' when cancelled or failed."""
        btn_key = f"{anime_id}_{ep_num}"
        self.queued_episodes.discard(btn_key)
        ui = self.episode_ui_elements.get(btn_key)

        if (
            ui
            and "dl_btn" in ui
            and self.current_anime
            and int(self.current_anime["id"]) == int(anime_id)
        ):
            try:
                ui["dl_btn"].setText("Download")
                ui["dl_btn"].setEnabled(True)
            except RuntimeError:
                pass

    @pyqtSlot(int, str)
    def on_episode_download_requeued(self, anime_id: int, ep_num: str) -> None:
        """Mark an episode back as 'Queued...' when retried from the Downloads tab."""
        btn_key = f"{anime_id}_{ep_num}"
        self.queued_episodes.add(btn_key)
        ui = self.episode_ui_elements.get(btn_key)

        if (
            ui
            and "dl_btn" in ui
            and self.current_anime
            and int(self.current_anime["id"]) == int(anime_id)
        ):
            try:
                ui["dl_btn"].setText("Queued...")
                ui["dl_btn"].setEnabled(False)
            except RuntimeError:
                pass

    # ------------------------------------------------------------------
    # Sync & Player Transitions
    # ------------------------------------------------------------------

    def start_xml_sync(self) -> None:
        """Launch a background `LibrarySyncWorker` to refresh catalog metadata."""
        self.refresh_btn.setEnabled(False)
        self.grid_widget.clear()

        worker = LibrarySyncWorker(self.db_manager, self.config_manager)
        worker.signals.status.connect(self.update_sync_status)
        worker.signals.error.connect(self.show_sync_error)
        worker.signals.finished.connect(self.on_sync_finished)
        self.thread_pool.start(worker)

    @pyqtSlot(str)
    def update_sync_status(self, status: str) -> None:
        self.sync_status_label.setText(status)

    @pyqtSlot(str)
    def show_sync_error(self, error_msg: str) -> None:
        QMessageBox.warning(self, "Sync Error", error_msg)

    @pyqtSlot()
    def on_sync_finished(self) -> None:
        self.sync_status_label.setText("Sync Complete")
        self.refresh_btn.setEnabled(True)
        self.load_library()

    def launch_player(self, anime_id: int, ep_num: str, file_path: str) -> None:
        """Open `VideoPlayerPage` for the chosen episode, or refresh details if missing."""
        title = self.current_anime["title"] if self.current_anime else "Anime"
        if self.player_page.play_episode(title, anime_id, ep_num, file_path):
            self.stacked_widget.setCurrentIndex(2)
        else:
            self.load_details(anime_id)

    @pyqtSlot(int, str)
    def auto_queue_next(self, anime_id: int, current_ep_num: str) -> None:
        """Automatically queue the following episode if it is not downloaded yet."""
        episodes = sorted(
            self.db_manager.get_episodes_by_anime(anime_id),
            key=lambda ep: float(ep["episode_number"]),
        )
        curr_index = next(
            (i for i, ep in enumerate(episodes) if str(ep["episode_number"]) == str(current_ep_num)),
            -1,
        )
        if curr_index != -1 and curr_index + 1 < len(episodes):
            next_ep = episodes[curr_index + 1]
            if next_ep["status"] != "downloaded":
                btn_key = f"{anime_id}_{next_ep['episode_number']}"
                ui = self.episode_ui_elements.get(btn_key)
                if ui and "dl_btn" in ui and ui["dl_btn"].isEnabled():
                    ui["dl_btn"].click()

    @pyqtSlot(int)
    def on_player_closed(self, anime_id: int) -> None:
        """Return from the player to the series details page and refresh episode states."""
        self.stacked_widget.setCurrentIndex(1)
        self.load_details(anime_id)
