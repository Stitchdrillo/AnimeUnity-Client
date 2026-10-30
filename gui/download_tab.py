from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar,
    QGroupBox, QListWidget, QPushButton, QListWidgetItem
)
from PyQt6.QtCore import QThreadPool, pyqtSlot, pyqtSignal, Qt
from core.downloader import DownloadWorker

class DownloadTab(QWidget):
    episode_downloaded_signal = pyqtSignal(int, str)
    episode_download_cancelled_signal = pyqtSignal(int, str)
    
    def __init__(self, config_manager, db_manager):
        super().__init__()
        self.config_manager = config_manager
        self.db_manager = db_manager
        
        self.thread_pool = QThreadPool()
        self.max_workers = self.config_manager.get("max_concurrent_downloads", 4)
        self.thread_pool.setMaxThreadCount(self.max_workers)
        
        self.pending_downloads = []
        self.failed_queue = []
        
        self.progress_labels = {}
        self.progress_bars = {}
        self.active_tasks = {}
        
        self.abort_flags = {i: [False] for i in range(self.max_workers)}
        
        self.setup_ui()

    def setup_ui(self):
        main_layout = QVBoxLayout()

        queue_group = QGroupBox("Pending Queue")
        queue_layout = QVBoxLayout()
        
        queue_header = QHBoxLayout()
        self.clear_queue_btn = QPushButton("Clear Queue")
        self.clear_queue_btn.clicked.connect(self.clear_queue)
        queue_header.addStretch()
        queue_header.addWidget(self.clear_queue_btn)
        queue_layout.addLayout(queue_header)
        
        self.queue_list = QListWidget()
        self.queue_list.setMinimumHeight(150)
        
        queue_layout.addWidget(self.queue_list)
        queue_group.setLayout(queue_layout)
        main_layout.addWidget(queue_group)

        prog_group = QGroupBox("Active Downloads")
        prog_layout = QVBoxLayout()
        
        for i in range(self.max_workers):
            row_layout = QHBoxLayout()
            lbl = QLabel("Idle")
            lbl.setMinimumWidth(250)
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(0)
            
            cancel_btn = QPushButton("✕")
            cancel_btn.setFixedWidth(30)
            cancel_btn.setStyleSheet("color: red; font-weight: bold;")
            cancel_btn.clicked.connect(lambda _, w=i: self.cancel_active_worker(w))
            
            row_layout.addWidget(lbl)
            row_layout.addWidget(bar)
            row_layout.addWidget(cancel_btn)
            prog_layout.addLayout(row_layout)
            
            self.progress_labels[i] = lbl
            self.progress_bars[i] = bar

        prog_group.setLayout(prog_layout)
        main_layout.addWidget(prog_group)
        main_layout.addStretch()
        
        self.setLayout(main_layout)

    def add_to_queue(self, ep_data, display_name):
        self.pending_downloads.append(ep_data)
        
        item = QListWidgetItem(self.queue_list)
        row_widget = QWidget()
        row_layout = QHBoxLayout()
        row_layout.setContentsMargins(5, 2, 5, 2)
        
        lbl = QLabel(display_name)
        cancel_btn = QPushButton("✕")
        cancel_btn.setFixedWidth(30)
        cancel_btn.clicked.connect(lambda _, it=item, ep=ep_data: self.remove_from_queue(it, ep))
        
        row_layout.addWidget(lbl)
        row_layout.addStretch()
        row_layout.addWidget(cancel_btn)
        row_widget.setLayout(row_layout)
        
        item.setSizeHint(row_widget.sizeHint())
        self.queue_list.setItemWidget(item, row_widget)
        
        worker_id = self.get_available_worker_id()
        if worker_id != -1:
            self.dispatch_next(worker_id)
    
    def remove_from_queue(self, item, ep_data):
        row = self.queue_list.row(item)
        self.queue_list.takeItem(row)
        if ep_data in self.pending_downloads:
            self.pending_downloads.remove(ep_data)
            self.episode_download_cancelled_signal.emit(int(ep_data['anime_id']), str(ep_data['num']))

    def clear_queue(self):
        for ep_data in self.pending_downloads:
            self.episode_download_cancelled_signal.emit(int(ep_data['anime_id']), str(ep_data['num']))
            
        self.queue_list.clear()
        self.pending_downloads.clear()

    def cancel_active_worker(self, worker_id):
        if worker_id in self.active_tasks:
            self.abort_flags[worker_id][0] = True
            self.progress_labels[worker_id].setText("Cancelling...")

    def get_available_worker_id(self):
        """Helper to find an idle UI row for a new worker."""
        for worker_id, lbl in self.progress_labels.items():
            if lbl.text() == "Idle":
                return worker_id
        return -1

    def dispatch_next(self, worker_id):
        if worker_id == -1 or not self.pending_downloads:
            return
        
        self.progress_labels[worker_id].setText("Starting...")
        self.abort_flags[worker_id][0] = False
        
        ep_data = self.pending_downloads.pop(0)

        if self.queue_list.count() > 0:
            self.queue_list.takeItem(0)
        
        self.active_tasks[worker_id] = (ep_data['anime_id'], ep_data['num'])

        worker = DownloadWorker(worker_id, ep_data, self.config_manager, self.abort_flags[worker_id])
        worker.signals.progress.connect(self.update_progress)
        worker.signals.status.connect(self.update_status)
        worker.signals.finished.connect(self.on_download_finished)
        worker.signals.error.connect(self.on_download_error)
        self.thread_pool.start(worker)

    @pyqtSlot(int, int)
    def update_progress(self, worker_id, percent):
        if worker_id in self.progress_bars:
            self.progress_bars[worker_id].setValue(percent)

    @pyqtSlot(int, str)
    def update_status(self, worker_id, status_text):
        if worker_id in self.progress_labels:
            self.progress_labels[worker_id].setText(status_text)

    @pyqtSlot(int, str, str, str)
    def on_download_finished(self, worker_id, anime_id, ep_num, file_path):
        if anime_id and ep_num:
            self.db_manager.update_episode_status(anime_id, ep_num, 'downloaded', file_path=file_path)
            self.episode_downloaded_signal.emit(int(anime_id), str(ep_num))

        if worker_id in self.active_tasks:
            del self.active_tasks[worker_id]
        self.dispatch_next(worker_id)

    @pyqtSlot(int, str, object)
    def on_download_error(self, worker_id, error_msg, ep_data):
        if worker_id in self.active_tasks:
            del self.active_tasks[worker_id]
            
        self.episode_download_cancelled_signal.emit(int(ep_data['anime_id']), str(ep_data['num']))
            
        if error_msg != "Cancelled by user":
            self.failed_queue.append(ep_data)
            
        self.dispatch_next(worker_id)
