import os
import json
from functools import lru_cache
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
                             QListWidget, QListWidgetItem, QStackedWidget, QGroupBox, 
                             QTextEdit, QSlider, QStyle, QMessageBox, QLineEdit,
                             QApplication, QCheckBox, QDialog, QFormLayout, QDialogButtonBox,
                             QStyledItemDelegate)
from PyQt6.QtGui import QIcon, QPixmap, QKeyEvent, QMouseEvent, QPainter
from PyQt6.QtCore import QSize, Qt, pyqtSlot, pyqtSignal, QUrl, QThreadPool
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget
from core.downloader import LibrarySyncWorker

@lru_cache(maxsize=150)
def get_cached_icon(path):
    pixmap = QPixmap(path)

    scaled = pixmap.scaled(150, 220, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    return QIcon(scaled)

class LazyCoverDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)
        
        fallback_pixmap = QPixmap(150, 220)
        fallback_pixmap.fill(Qt.GlobalColor.transparent)
        self.fallback_icon = QIcon(fallback_pixmap)

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        cover_path = index.data(Qt.ItemDataRole.UserRole + 1)
        
        if cover_path and os.path.exists(cover_path):
            option.icon = get_cached_icon(cover_path)
        else:
            option.icon = self.fallback_icon


class ClickableVideoWidget(QVideoWidget):
    action_skip_back = pyqtSignal()
    action_skip_fwd = pyqtSignal()
    action_toggle_play = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        self.setFullScreen(not self.isFullScreen())
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Escape and self.isFullScreen():
            self.setFullScreen(False)
        elif event.key() == Qt.Key.Key_F:
            self.setFullScreen(not self.isFullScreen())
        elif event.key() == Qt.Key.Key_Space:
            self.action_toggle_play.emit()
            event.accept()
        elif event.key() == Qt.Key.Key_Left:
            self.action_skip_back.emit()
        elif event.key() == Qt.Key.Key_Right:
            self.action_skip_fwd.emit()
        else:
            super().keyPressEvent(event)

class DownloadRangeDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Download Range")
        
        layout = QFormLayout()
        
        self.start_input = QLineEdit()
        self.start_input.setPlaceholderText("empty for first")
        
        self.end_input = QLineEdit()
        self.end_input.setPlaceholderText("empty for last")
        
        layout.addRow("Start Episode:", self.start_input)
        layout.addRow("End Episode:", self.end_input)
        
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
        
        self.setLayout(layout)

    def get_range(self):
        return self.start_input.text().strip(), self.end_input.text().strip()

class LibraryTab(QWidget):

    episode_download_requested = pyqtSignal(dict, str)

    def __init__(self, db_manager, config_manager):
        super().__init__()
        self.db_manager = db_manager
        self.config_manager = config_manager
        
        self.thread_pool = QThreadPool()
        
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.assets_dir = os.path.join(self.base_dir, "..", "assets", "covers")
        os.makedirs(self.assets_dir, exist_ok=True)
        
        self.episode_ui_elements = {} 
        
        self.setup_ui()

    def setup_ui(self):
        self.main_layout = QVBoxLayout()
        self.stacked_widget = QStackedWidget()
        
        self.grid_page = QWidget()
        self.setup_grid_page()
        self.stacked_widget.addWidget(self.grid_page)
        
        self.details_page = QWidget()
        self.setup_details_page()
        self.stacked_widget.addWidget(self.details_page)
        
        self.player_page = QWidget()
        self.setup_player_page()
        self.stacked_widget.addWidget(self.player_page)
        
        self.main_layout.addWidget(self.stacked_widget)
        self.setLayout(self.main_layout)
        self.load_library()

    def setup_grid_page(self):
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
    
    def filter_library(self):
        """Unified filter that applies both text search and checkbox state instantly."""
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

    def setup_details_page(self):
        layout = QVBoxLayout()
        
        top_bar = QHBoxLayout()
        back_btn = QPushButton("← Back to Library")
        back_btn.setFixedWidth(150)
        back_btn.clicked.connect(lambda: self.stacked_widget.setCurrentIndex(0))
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

    def on_anime_clicked(self, item):
        anime_id = item.data(Qt.ItemDataRole.UserRole)
        self.load_details(anime_id)
        self.stacked_widget.setCurrentIndex(1)

    def on_related_clicked(self, item):
        related_db_id = item.data(Qt.ItemDataRole.UserRole)
        if related_db_id:
            self.load_details(related_db_id)

    def load_details(self, anime_id):
        anime = self.db_manager.get_anime_by_id(anime_id)
        if not anime: return
        
        self.current_anime = anime
        self.det_title.setText(anime['title'])
        
        genres = ", ".join(json.loads(anime['genres'])) if anime['genres'] else "N/A"
        meta_text = (
            f"<b>Status:</b> {anime['status'] or 'Unknown'}<br><br>"
            f"<b>Year:</b> {anime['release_year'] or 'Unknown'}<br><br>"
            f"<b>Type:</b> {anime['type'] or 'Unknown'}<br><br>"
            f"<b>Studio:</b> {anime['studio'] or 'Unknown'}<br><br>"
            f"<b>Genres:</b> {genres}"
        )
        self.det_meta.setText(meta_text)
        self.det_plot.setText(anime['plot'] or "No description available.")
        
        self.episodes_list.clear()
        episodes = self.db_manager.get_episodes_by_anime(anime_id)
        for ep in episodes:
            self.add_episode_row(ep)

        self.related_list.clear()
        if anime['related_json']:
            related_items = json.loads(anime['related_json'])
            for rel in related_items:
                rel_title = rel.get('title_eng') or rel.get('title')
                rel_remote_id = rel.get('id')
                
                rel_db_record = self.db_manager.get_anime_by_remote_id(rel_remote_id)
                
                display_text = f"{rel_title} ({rel.get('type', '')} - {rel.get('date', '')})"
                item = QListWidgetItem(display_text)
                
                if rel_remote_id == anime['remote_id']:
                    item.setFont(self.get_bold_font())
                    item.setBackground(Qt.GlobalColor.darkGray)
                    
                if rel_db_record:
                    item.setData(Qt.ItemDataRole.UserRole, rel_db_record['id'])
                    cover_path = rel_db_record['cover_path']
                    if cover_path and os.path.exists(cover_path):
                        item.setIcon(QIcon(cover_path))
                else:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                
                self.related_list.addItem(item)

    def get_bold_font(self):
        font = self.font()
        font.setBold(True)
        return font

    def add_episode_row(self, ep):
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
            'label': lbl, 
            'action_layout': action_layout
        }
        
        if ep['status'] != 'downloaded':
            lbl.setStyleSheet("color: gray;")
            btn = QPushButton("Download")
            btn.setFixedWidth(120)
            
            ep_data = {
                'num': ep['episode_number'],
                'id': ep['remote_id'], 
                'anime_id': ep['anime_id'],
                'download_dir': os.path.join(self.config_manager.get("download_directory"), self.current_anime['title']),
                'source_url': self.current_anime['source_url']
            }
            display_name = f"{self.current_anime['title']} - Ep {ep['episode_number']}"
            btn.clicked.connect(lambda _, ed=ep_data, dn=display_name, k=btn_key: self.queue_episode(ed, dn, k))
            
            action_layout.addWidget(btn)
            
            self.episode_ui_elements[btn_key]['dl_btn'] = btn
        else:
            lbl.setStyleSheet("") 
            
            play_btn = QPushButton("Play")
            play_btn.setFixedWidth(80)
            play_btn.clicked.connect(lambda _, aid=ep['anime_id'], num=ep['episode_number'], path=ep['file_path']: self.launch_player(aid, num, path))
            
            del_btn = QPushButton("Delete")
            del_btn.setFixedWidth(80)
            del_btn.setStyleSheet("color: #d9534f;")
            del_btn.clicked.connect(lambda _, aid=ep['anime_id'], num=ep['episode_number'], path=ep['file_path']: self.delete_local_episode(aid, num, path))
            
            action_layout.addWidget(play_btn)
            action_layout.addWidget(del_btn)
            
        row_layout.addWidget(action_container)
        row_widget.setLayout(row_layout)
        
        item = QListWidgetItem(self.episodes_list)
        item.setSizeHint(row_widget.sizeHint())
        item.setData(Qt.ItemDataRole.UserRole, btn_key)

        self.episodes_list.setItemWidget(item, row_widget)
    
    def delete_local_episode(self, anime_id, ep_num, file_path):
        reply = QMessageBox.question(self, 'Confirm Delete', f'Delete Episode {ep_num} from your drive?',
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception as e:
                    QMessageBox.warning(self, "Error", f"Could not delete file: {e}")
                    return
            
            self.db_manager.update_episode_status(anime_id, ep_num, 'not_downloaded')
            self.load_details(anime_id)
    
    def delete_all_episodes(self):
        if not hasattr(self, 'current_anime'): return
        
        reply = QMessageBox.question(self, 'Confirm Delete All', 
                                     f"Delete all downloaded episodes for {self.current_anime['title']}?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        
        if reply == QMessageBox.StandardButton.Yes:
            anime_id = self.current_anime['id']
            episodes = self.db_manager.get_episodes_by_anime(anime_id)
            
            for ep in episodes:
                if ep['status'] == 'downloaded' and ep['file_path']:
                    if os.path.exists(ep['file_path']):
                        try:
                            os.remove(ep['file_path'])
                        except Exception as e:
                            print(f"Failed to delete {ep['file_path']}: {e}")
                    self.db_manager.update_episode_status(anime_id, ep['episode_number'], 'not_downloaded')
            
            self.load_details(anime_id)

    def download_all_episodes(self):
        """Iterates through the current series and queues all un-downloaded episodes."""
        if not hasattr(self, 'current_anime'): return
        
        self.dl_all_btn.setEnabled(False)
        
        anime_id = self.current_anime['id']
        episodes = self.db_manager.get_episodes_by_anime(anime_id)
        
        for ep in episodes:
            if ep['status'] != 'downloaded':
                btn_key = f"{anime_id}_{ep['episode_number']}"
                ui = self.episode_ui_elements.get(btn_key)
                
                if ui and 'dl_btn' in ui and ui['dl_btn'].isEnabled():
                    ui['dl_btn'].click()
                    
        self.dl_all_btn.setEnabled(True)

    def download_range_episodes(self):
        if not hasattr(self, 'current_anime'): return
        
        dialog = DownloadRangeDialog(self)

        if dialog.exec() == 1:
            start_str, end_str = dialog.get_range()
            
            anime_id = self.current_anime['id']
            episodes = sorted(self.db_manager.get_episodes_by_anime(anime_id), key=lambda x: float(x['episode_number']))
            max_items = len(episodes)
            
            if max_items == 0:
                return
            
            try:

                start_idx = int(start_str) if start_str else 1
                end_idx = int(end_str) if end_str else max_items
            except ValueError:
                QMessageBox.warning(self, "Invalid Input", "Please enter valid row numbers.")
                return
            
            start_idx = max(1, start_idx)
            end_idx = min(max_items, end_idx)
            
            if start_idx > end_idx:
                return
            
            for i in range(start_idx - 1, end_idx):
                ep = episodes[i]
                
                btn_key = f"{anime_id}_{ep['episode_number']}"
                
                ui = self.episode_ui_elements.get(btn_key)
                
                if ui and 'dl_btn' in ui and ui['dl_btn'].isEnabled():
                    ui['dl_btn'].click()

    def start_xml_sync(self):
        self.refresh_btn.setEnabled(False)
        self.grid_widget.clear()
        
        worker = LibrarySyncWorker(self.db_manager, self.config_manager)
        worker.signals.status.connect(self.update_sync_status)
        worker.signals.error.connect(self.show_sync_error)
        worker.signals.finished.connect(self.on_sync_finished)
        
        self.thread_pool.start(worker)

    @pyqtSlot(str)
    def update_sync_status(self, status):
        self.sync_status_label.setText(status)

    @pyqtSlot(str)
    def show_sync_error(self, error_msg):
        QMessageBox.warning(self, "Sync Error", error_msg)

    @pyqtSlot()
    def on_sync_finished(self):
        self.sync_status_label.setText("Sync Complete")
        self.refresh_btn.setEnabled(True)
        self.load_library()
        
    def load_library(self):
        self.grid_widget.clear()
        self.grid_widget.setUpdatesEnabled(False)
        anime_list = self.db_manager.get_all_anime()
        
        if not hasattr(self, 'shared_placeholder'):
            transparent_pixmap = QPixmap(150, 220)
            transparent_pixmap.fill(Qt.GlobalColor.transparent)
            self.shared_placeholder = QIcon(transparent_pixmap)
        
        for anime in anime_list:
            title = anime['title']
            type = anime['type']
            year = anime['release_year']
            cover_path = anime['cover_path']
            
            display_text = f"{title}\n({type} - {year})"
            item = QListWidgetItem(display_text)
            
            item.setToolTip(display_text)
            item.setIcon(self.shared_placeholder)
            item.setData(Qt.ItemDataRole.UserRole, anime['id'])
            item.setData(Qt.ItemDataRole.UserRole + 1, cover_path)
            
            self.grid_widget.addItem(item)
        
        self.grid_widget.setUpdatesEnabled(True)
        self.filter_library()
    
    def queue_episode(self, ep_data, display_name, btn_key):
        ui = self.episode_ui_elements.get(btn_key)
        if ui and 'dl_btn' in ui:
            ui['dl_btn'].setText("Queued...")
            ui['dl_btn'].setEnabled(False)
        self.episode_download_requested.emit(ep_data, display_name)
    
    @pyqtSlot(int, str)
    def on_episode_downloaded(self, anime_id, ep_num):
        """Called when DownloadTab finishes an episode. Swaps Download out for Play/Delete."""
        btn_key = f"{anime_id}_{ep_num}"
        ui = self.episode_ui_elements.get(btn_key)
        
        if ui and hasattr(self, 'current_anime') and self.current_anime['id'] == anime_id:
            ui['label'].setStyleSheet("")
            
            layout = ui['action_layout']
            while layout.count():
                child = layout.takeAt(0)
                if child.widget():
                    child.widget().deleteLater()
            
            ep_db = next((e for e in self.db_manager.get_episodes_by_anime(anime_id) if str(e['episode_number']) == str(ep_num)), None)
            
            if ep_db:
                play_btn = QPushButton("Play")
                play_btn.setFixedWidth(80)
                play_btn.clicked.connect(lambda _, aid=anime_id, num=ep_num, path=ep_db['file_path']: self.launch_player(aid, num, path))
                
                del_btn = QPushButton("Delete")
                del_btn.setFixedWidth(80)
                del_btn.setStyleSheet("color: #d9534f;")
                del_btn.clicked.connect(lambda _, aid=anime_id, num=ep_num, path=ep_db['file_path']: self.delete_local_episode(aid, num, path))
                
                layout.addWidget(play_btn)
                layout.addWidget(del_btn)
    
    @pyqtSlot(int, str)
    def on_episode_download_cancelled(self, anime_id, ep_num):
        """Called when a download is aborted or fails to revert the UI button."""
        btn_key = f"{anime_id}_{ep_num}"
        ui = self.episode_ui_elements.get(btn_key)
        
        if ui and 'dl_btn' in ui:
            ui['dl_btn'].setText("Download")
            ui['dl_btn'].setEnabled(True)
    
    def setup_player_page(self):
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
        self.player.durationChanged.connect(lambda d: self.slider.setRange(0, d))
        
        self.fullscreen_btn = QPushButton("⛶")
        self.fullscreen_btn.setFixedWidth(40)
        self.fullscreen_btn.clicked.connect(lambda: self.video_widget.setFullScreen(not self.video_widget.isFullScreen()))
        
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
        
        self.player_page.setLayout(layout)
    
    def skip_media(self, offset_ms):
        """Skips the media player position by the given millisecond offset safely."""
        if self.player.mediaStatus() != QMediaPlayer.MediaStatus.NoMedia:
            new_pos = self.player.position() + offset_ms
            max_dur = self.player.duration()
            
            if new_pos < 0:
                new_pos = 0
            elif new_pos > max_dur:
                new_pos = max_dur
                
            self.player.setPosition(new_pos)
    
    def launch_player(self, anime_id, ep_num, file_path):
        if not file_path or not os.path.exists(file_path):
            QMessageBox.warning(self, "Error", "Video file not found locally.")
            self.db_manager.update_episode_status(anime_id, ep_num, 'not_downloaded')
            self.load_details(anime_id)
            return
            
        self.current_play_context = {'anime_id': anime_id, 'ep_num': ep_num, 'file_path': file_path}
        self.player_title.setText(f"{self.current_anime['title']} - Episode {ep_num}")
        self.player.setSource(QUrl.fromLocalFile(file_path))
        self.stacked_widget.setCurrentIndex(2)
        
        self.video_widget.setFocus() 
        
        self.player.play()
        self.play_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause))
        
        if self.config_manager.get("auto_download_next"):
            self.auto_queue_next(anime_id, ep_num)

    
    def toggle_playback(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
            self.play_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        else:
            self.player.play()
            self.play_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause))

    def play_adjacent_episode(self, offset):
        if not hasattr(self, 'current_play_context'): return
        current_num = float(self.current_play_context['ep_num'])
        episodes = sorted(self.db_manager.get_episodes_by_anime(self.current_play_context['anime_id']), key=lambda x: float(x['episode_number']))
        
        curr_index = next((i for i, ep in enumerate(episodes) if float(ep['episode_number']) == current_num), -1)
        target_index = curr_index + offset
        
        if 0 <= target_index < len(episodes):
            target_ep = episodes[target_index]
            if target_ep['status'] == 'downloaded':
                
                should_delete = (offset == 1) and self.config_manager.get("auto_delete_seen", False)
                ctx = self.current_play_context 
                
                self.exit_player_cleanup()
                
                QApplication.processEvents()
                
                if should_delete:
                    try:
                        if os.path.exists(ctx['file_path']):
                            os.remove(ctx['file_path'])
                        self.db_manager.update_episode_status(ctx['anime_id'], ctx['ep_num'], 'not_downloaded')
                        print(f"Auto-deleted {ctx['file_path']}")
                        
                        self.load_details(ctx['anime_id'])
                        
                    except Exception as e:
                        print(f"Failed to auto-delete video: {e}")
                
                self.launch_player(target_ep['anime_id'], target_ep['episode_number'], target_ep['file_path'])
            else:
                QMessageBox.information(self, "Unavailable", "That episode is not downloaded yet.")

    def auto_queue_next(self, anime_id, current_ep_num):
        episodes = sorted(self.db_manager.get_episodes_by_anime(anime_id), key=lambda x: float(x['episode_number']))
        curr_index = next((i for i, ep in enumerate(episodes) if str(ep['episode_number']) == str(current_ep_num)), -1)
        
        if curr_index != -1 and curr_index + 1 < len(episodes):
            next_ep = episodes[curr_index + 1]
            if next_ep['status'] != 'downloaded':
                btn_key = f"{anime_id}_{next_ep['episode_number']}"
                ui = self.episode_ui_elements.get(btn_key)
                
                if ui and 'dl_btn' in ui and ui['dl_btn'].isEnabled():
                    ui['dl_btn'].click()

    def exit_player(self):
        self.exit_player_cleanup()
        self.stacked_widget.setCurrentIndex(1)
        self.load_details(self.current_play_context['anime_id'])

    def exit_player_cleanup(self):
        self.player.stop()

        self.player.setSource(QUrl())
        
        if self.video_widget.isFullScreen():
            self.video_widget.setFullScreen(False)
