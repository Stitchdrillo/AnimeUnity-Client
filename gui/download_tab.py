"""Download queue UI with concurrent worker slots and failed-download retry controls."""

import threading
from typing import Any
from PyQt6.QtCore import QThreadPool, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from core.downloader import DownloadWorker


class DownloadTab(QWidget):
    """Manages pending episodes, active download workers, and retrying failed tasks."""

    episode_downloaded_signal = pyqtSignal(int, str)
    episode_download_cancelled_signal = pyqtSignal(int, str)
    episode_download_requeued_signal = pyqtSignal(int, str)

    def __init__(self, config_manager, db_manager) -> None:
        super().__init__()
        self.config_manager = config_manager
        self.db_manager = db_manager

        self.thread_pool = QThreadPool()
        self.max_workers: int = self.config_manager.get("max_concurrent_downloads", 4)
        self.thread_pool.setMaxThreadCount(self.max_workers)

        self.pending_downloads: list[dict[str, Any]] = []
        self.failed_downloads: list[dict[str, Any]] = []

        self.progress_labels: dict[int, QLabel] = {}
        self.progress_bars: dict[int, QProgressBar] = {}
        self.active_tasks: dict[int, dict[str, Any]] = {}
        self.abort_events: dict[int, threading.Event] = {
            i: threading.Event() for i in range(self.max_workers)
        }

        self.setup_ui()

    def setup_ui(self) -> None:
        main_layout = QVBoxLayout()

        # Pending Queue section
        queue_group = QGroupBox("Pending Queue")
        queue_layout = QVBoxLayout()

        queue_header = QHBoxLayout()
        self.failed_status_label = QLabel("")
        self.failed_status_label.setStyleSheet("color: #d9534f; font-weight: bold;")
        self.failed_status_label.hide()

        self.retry_failed_btn = QPushButton("Retry Failed")
        self.retry_failed_btn.clicked.connect(self.retry_failed_downloads)
        self.retry_failed_btn.hide()

        self.clear_failed_btn = QPushButton("Dismiss Failed")
        self.clear_failed_btn.clicked.connect(self.clear_failed_downloads)
        self.clear_failed_btn.hide()

        self.clear_queue_btn = QPushButton("Clear Queue")
        self.clear_queue_btn.clicked.connect(self.clear_queue)

        queue_header.addWidget(self.failed_status_label)
        queue_header.addWidget(self.retry_failed_btn)
        queue_header.addWidget(self.clear_failed_btn)
        queue_header.addStretch()
        queue_header.addWidget(self.clear_queue_btn)
        queue_layout.addLayout(queue_header)

        self.queue_list = QListWidget()
        self.queue_list.setMinimumHeight(150)
        queue_layout.addWidget(self.queue_list)

        queue_group.setLayout(queue_layout)
        main_layout.addWidget(queue_group)

        # Active Workers section
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

    # ------------------------------------------------------------------
    # Queue & Failed List Management
    # ------------------------------------------------------------------

    @staticmethod
    def _episode_key(ep_data: dict[str, Any]) -> tuple[int, str]:
        return (int(ep_data["anime_id"]), str(ep_data["num"]))

    def _refresh_failed_controls(self) -> None:
        """Show or hide failed-download retry controls based on current failure count."""
        count = len(self.failed_downloads)
        if count > 0:
            self.failed_status_label.setText(f"{count} failed")
            self.retry_failed_btn.setText(f"Retry Failed ({count})")
            self.failed_status_label.show()
            self.retry_failed_btn.show()
            self.clear_failed_btn.show()
        else:
            self.failed_status_label.hide()
            self.retry_failed_btn.hide()
            self.clear_failed_btn.hide()

    def _remove_from_failed(self, ep_data: dict[str, Any]) -> None:
        target_key = self._episode_key(ep_data)
        self.failed_downloads = [
            entry
            for entry in self.failed_downloads
            if self._episode_key(entry["ep_data"]) != target_key
        ]
        self._refresh_failed_controls()

    def add_to_queue(self, ep_data: dict[str, Any], display_name: str) -> None:
        """Append an episode to the pending list and dispatch immediately if a slot is free."""
        self._remove_from_failed(ep_data)
        entry = {"ep_data": ep_data, "display_name": display_name}
        self.pending_downloads.append(entry)

        item = QListWidgetItem(self.queue_list)
        row_widget = QWidget()
        row_layout = QHBoxLayout()
        row_layout.setContentsMargins(5, 2, 5, 2)

        lbl = QLabel(display_name)
        cancel_btn = QPushButton("✕")
        cancel_btn.setFixedWidth(30)
        cancel_btn.clicked.connect(
            lambda _, it=item, ent=entry: self.remove_from_queue(it, ent)
        )

        row_layout.addWidget(lbl)
        row_layout.addStretch()
        row_layout.addWidget(cancel_btn)
        row_widget.setLayout(row_layout)

        item.setSizeHint(row_widget.sizeHint())
        self.queue_list.setItemWidget(item, row_widget)

        worker_id = self.get_available_worker_id()
        if worker_id != -1:
            self.dispatch_next(worker_id)

    def remove_from_queue(self, item: QListWidgetItem, entry: dict[str, Any]) -> None:
        """Remove a single unstarted episode from the pending queue."""
        row = self.queue_list.row(item)
        self.queue_list.takeItem(row)
        if entry in self.pending_downloads:
            self.pending_downloads.remove(entry)
            ep_data = entry["ep_data"]
            self.episode_download_cancelled_signal.emit(
                int(ep_data["anime_id"]),
                str(ep_data["num"]),
            )

    def clear_queue(self) -> None:
        """Cancel all pending episodes and notify the Library tab to reset their buttons."""
        for entry in self.pending_downloads:
            ep_data = entry["ep_data"]
            self.episode_download_cancelled_signal.emit(
                int(ep_data["anime_id"]),
                str(ep_data["num"]),
            )

        self.queue_list.clear()
        self.pending_downloads.clear()

    def retry_failed_downloads(self) -> None:
        """Re-queue all failed episodes and update their Library buttons to 'Queued...'."""
        to_retry = list(self.failed_downloads)
        self.failed_downloads.clear()
        self._refresh_failed_controls()

        for entry in to_retry:
            ep_data = entry["ep_data"]
            self.episode_download_requeued_signal.emit(
                int(ep_data["anime_id"]),
                str(ep_data["num"]),
            )
            self.add_to_queue(ep_data, entry["display_name"])

    def clear_failed_downloads(self) -> None:
        """Dismiss recorded failures without re-queuing them."""
        self.failed_downloads.clear()
        self._refresh_failed_controls()

    # ------------------------------------------------------------------
    # Worker Dispatch & Signal Handlers
    # ------------------------------------------------------------------

    def cancel_active_worker(self, worker_id: int) -> None:
        """Signal an active worker thread to abort its current download."""
        if worker_id in self.active_tasks:
            self.abort_events[worker_id].set()
            self.progress_labels[worker_id].setText("Cancelling...")

    def get_available_worker_id(self) -> int:
        """Return the index of an idle worker row, or -1 if all slots are busy."""
        for worker_id, lbl in self.progress_labels.items():
            if lbl.text() == "Idle":
                return worker_id
        return -1

    def dispatch_next(self, worker_id: int) -> None:
        """Pop the next queued episode and start a `DownloadWorker` on `worker_id`."""
        if worker_id == -1 or not self.pending_downloads:
            return

        self.progress_labels[worker_id].setText("Starting...")
        self.abort_events[worker_id].clear()

        entry = self.pending_downloads.pop(0)
        ep_data = entry["ep_data"]

        if self.queue_list.count() > 0:
            self.queue_list.takeItem(0)

        self.active_tasks[worker_id] = entry

        worker = DownloadWorker(
            worker_id,
            ep_data,
            self.config_manager,
            self.abort_events[worker_id],
        )
        worker.signals.progress.connect(self.update_progress)
        worker.signals.status.connect(self.update_status)
        worker.signals.finished.connect(self.on_download_finished)
        worker.signals.error.connect(self.on_download_error)
        self.thread_pool.start(worker)

    @pyqtSlot(int, int)
    def update_progress(self, worker_id: int, percent: int) -> None:
        if worker_id in self.progress_bars:
            self.progress_bars[worker_id].setValue(percent)

    @pyqtSlot(int, str)
    def update_status(self, worker_id: int, status_text: str) -> None:
        if worker_id in self.progress_labels:
            self.progress_labels[worker_id].setText(status_text)

    @pyqtSlot(int, str, str, str)
    def on_download_finished(
        self,
        worker_id: int,
        anime_id: str,
        ep_num: str,
        file_path: str,
    ) -> None:
        """Persist completion to SQLite, notify the Library tab, and advance the queue."""
        if anime_id and ep_num:
            self.db_manager.update_episode_status(
                int(anime_id),
                ep_num,
                "downloaded",
                file_path=file_path,
            )
            self.episode_downloaded_signal.emit(int(anime_id), str(ep_num))

        self.active_tasks.pop(worker_id, None)
        self.dispatch_next(worker_id)

    @pyqtSlot(int, str, object)
    def on_download_error(self, worker_id: int, error_msg: str, ep_data: dict[str, Any]) -> None:
        """Record non-cancelled failures for retry, reset UI state, and advance the queue."""
        task_entry = self.active_tasks.pop(worker_id, None)
        self.episode_download_cancelled_signal.emit(
            int(ep_data["anime_id"]),
            str(ep_data["num"]),
        )

        if error_msg != "Cancelled by user":
            display_name = (
                task_entry["display_name"]
                if task_entry
                else f"Anime {ep_data['anime_id']} - Ep {ep_data['num']}"
            )
            target_key = self._episode_key(ep_data)
            already_recorded = any(
                self._episode_key(item["ep_data"]) == target_key
                for item in self.failed_downloads
            )
            if not already_recorded:
                self.failed_downloads.append(
                    {
                        "ep_data": ep_data,
                        "display_name": display_name,
                        "error": error_msg,
                    }
                )
                self._refresh_failed_controls()

        self.dispatch_next(worker_id)
