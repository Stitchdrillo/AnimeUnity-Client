"""Background Qt workers for episode downloads and library synchronization."""

import os
import re
import threading
import traceback
from typing import Any
from urllib.parse import urlparse
from PyQt6.QtCore import QObject, QRunnable, pyqtSignal, pyqtSlot
from core.scraper import AnimeUnityScraper


class WorkerSignals(QObject):
    """Qt signals emitted by `DownloadWorker`."""

    progress = pyqtSignal(int, int)
    status = pyqtSignal(int, str)
    finished = pyqtSignal(int, str, str, str)
    error = pyqtSignal(int, str, object)


class DownloadWorker(QRunnable):
    """Downloads a single episode in a worker thread with automatic transient retries."""

    MAX_RETRIES = 2
    RETRY_DELAY_SECONDS = 2.0

    def __init__(
        self,
        worker_id: int,
        ep_data: dict[str, Any],
        config_manager,
        abort_event: threading.Event,
    ) -> None:
        super().__init__()
        self.worker_id = worker_id
        self.ep_data = ep_data
        self.config_manager = config_manager
        self.chunk_size = config_manager.get("chunk_size_kb", 1024) * 1024
        self.abort_event = abort_event
        self.signals = WorkerSignals()

    def _download_once(self, scraper: AnimeUnityScraper, filepath: str, qualities: list[int]) -> None:
        """Perform a single stream-to-disk attempt for the configured episode."""
        video_id = self.ep_data["id"]
        response = scraper.open_video_stream(video_id, qualities, abort_event=self.abort_event)

        with response as r:
            total_size = int(r.headers.get("content-length", 0))
            bytes_processed = 0

            with open(filepath, "wb") as f:
                for chunk in r.iter_content(chunk_size=self.chunk_size):
                    if self.abort_event.is_set():
                        raise InterruptedError("Cancelled by user")

                    if chunk:
                        f.write(chunk)
                        bytes_processed += len(chunk)
                        if total_size > 0:
                            percent = int((bytes_processed / total_size) * 100)
                            self.signals.progress.emit(self.worker_id, percent)

    @staticmethod
    def _cleanup_partial_file(filepath: str | None) -> None:
        """Remove an incomplete `.mp4` file if present."""
        if not filepath:
            return
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
        except OSError:
            pass

    @pyqtSlot()
    def run(self) -> None:
        """Execute the download with automatic retry handling for transient failures."""
        ep_num = self.ep_data["num"]
        anime_id = self.ep_data.get("anime_id")
        download_dir = self.ep_data["download_dir"]

        os.makedirs(download_dir, exist_ok=True)
        filename = f"Episode {ep_num}.mp4"
        filepath = os.path.join(download_dir, filename)

        base_domain = self.config_manager.get("base_domain", "https://animeunity.cx")
        qualities = self.config_manager.get_quality_fallback_chain()
        scraper = AnimeUnityScraper(base_domain)

        total_attempts = self.MAX_RETRIES + 1

        for attempt in range(1, total_attempts + 1):
            try:
                if self.abort_event.is_set():
                    raise InterruptedError("Cancelled by user")

                if attempt == 1:
                    self.signals.status.emit(self.worker_id, filename)
                else:
                    self.signals.progress.emit(self.worker_id, 0)
                    self.signals.status.emit(
                        self.worker_id,
                        f"Retrying ({attempt - 1}/{self.MAX_RETRIES}): {filename}",
                    )

                self._download_once(scraper, filepath, qualities)

                self.signals.finished.emit(self.worker_id, str(anime_id), str(ep_num), filepath)
                self.signals.status.emit(self.worker_id, "Idle")
                self.signals.progress.emit(self.worker_id, 0)
                return

            except InterruptedError as cancel_err:
                self._cleanup_partial_file(filepath)
                self.signals.error.emit(self.worker_id, str(cancel_err), self.ep_data)
                self.signals.status.emit(self.worker_id, "Idle")
                self.signals.progress.emit(self.worker_id, 0)
                return

            except Exception as err:
                print(f"[DownloadWorker ERROR - Worker {self.worker_id}, Attempt {attempt}/{total_attempts}]")
                traceback.print_exc()
                self._cleanup_partial_file(filepath)

                if attempt < total_attempts:
                    # Wait interruptibly so user cancellation during backoff responds immediately.
                    if self.abort_event.wait(timeout=self.RETRY_DELAY_SECONDS):
                        self.signals.error.emit(self.worker_id, "Cancelled by user", self.ep_data)
                        self.signals.status.emit(self.worker_id, "Idle")
                        self.signals.progress.emit(self.worker_id, 0)
                        return
                else:
                    self.signals.error.emit(self.worker_id, str(err), self.ep_data)
                    self.signals.status.emit(self.worker_id, "Idle")
                    self.signals.progress.emit(self.worker_id, 0)


class LibrarySyncSignals(QObject):
    """Qt signals emitted by `LibrarySyncWorker`."""

    status = pyqtSignal(str)
    finished = pyqtSignal()
    error = pyqtSignal(str)


class LibrarySyncWorker(QRunnable):
    """Synchronizes the local SQLite catalog and cover cache against remote sitemaps."""

    COMPLETED_STATUSES = {"terminato", "finished", "completed"}

    def __init__(self, db_manager, config_manager) -> None:
        super().__init__()
        self.db_manager = db_manager
        self.config_manager = config_manager
        self.signals = LibrarySyncSignals()

        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        self.covers_dir = os.path.join(project_root, "assets", "covers")
        os.makedirs(self.covers_dir, exist_ok=True)

    def _is_series_complete(self, record: dict[str, Any] | None) -> bool:
        """Check whether a finished series already has all its episodes stored locally."""
        if not record:
            return False
        status = str(record.get("status", "")).strip().lower()
        if status not in self.COMPLETED_STATUSES:
            return False

        saved_count = self.db_manager.get_saved_episode_count(record["id"])
        expected_count = record.get("total_episodes", 0)
        return saved_count > 0 and saved_count >= expected_count

    def _sync_single_anime(
        self,
        scraper: AnimeUnityScraper,
        relative_page_path: str,
        anime_slug: str,
        existing_record: dict[str, Any] | None,
        preferred_lang: str,
        index: int,
        total_urls: int,
    ) -> None:
        """Fetch, persist, and populate episodes for a single series URL."""
        if existing_record and self._is_series_complete(existing_record):
            return

        status = (
            str(existing_record.get("status", "")).strip().lower()
            if existing_record
            else ""
        )
        if existing_record and status in self.COMPLETED_STATUSES:
            self.signals.status.emit(
                f"Healing ({index}/{total_urls}): {existing_record['title']}..."
            )
        else:
            label = existing_record["title"] if existing_record else anime_slug
            self.signals.status.emit(f"Syncing ({index}/{total_urls}): {label}...")

        meta = scraper.fetch_anime_page(relative_page_path)
        if not meta:
            return

        anime_name = meta["title"]
        self.signals.status.emit(f"Syncing ({index}/{total_urls}): {anime_name}")

        local_cover_path = scraper.download_cover(meta["cover_url"], anime_slug, self.covers_dir)

        db_anime_id = self.db_manager.add_or_update_anime(
            remote_id=meta["remote_id"],
            title=anime_name,
            source_url=meta["source_url"],
            cover_path=local_cover_path,
            plot=meta["plot"],
            anime_type=meta["anime_type"],
            status=meta["status"],
            release_year=meta["release_year"],
            studio=meta["studio"],
            genres=meta["genres_json"],
            related_json=meta["related_json"],
        )

        episodes = scraper.fetch_all_episodes(
            remote_id=meta["remote_id"],
            initial_episodes=meta["initial_episodes"],
            tab_size=meta["tab_size"],
            total_expected=meta["total_expected"],
            anime_title=anime_name,
        )

        self.db_manager.update_anime_episode_count(db_anime_id, len(episodes))

        for ep in episodes:
            ep_num = str(ep.get("number"))
            video_id = scraper.select_video_id(ep, preferred_lang=preferred_lang)
            if video_id:
                self.db_manager.add_episode(
                    anime_id=db_anime_id,
                    episode_number=ep_num,
                    remote_id=video_id,
                    status="not_downloaded",
                )

    @pyqtSlot()
    def run(self) -> None:
        """Discover anime pages from XML sitemaps and sync missing or ongoing series."""
        base_domain = self.config_manager.get("base_domain", "https://animeunity.cx").rstrip("/")
        if not base_domain:
            self.signals.error.emit("No Base Domain configured in Settings.")
            self.signals.finished.emit()
            return

        preferred_lang = self.config_manager.get("preferred_language", "jpn").lower()
        scraper = AnimeUnityScraper(base_domain)
        self.signals.status.emit("Fetching anime sitemaps...")

        try:
            anime_urls = scraper.fetch_all_anime_urls()
            if not anime_urls:
                raise ValueError("No anime URLs found in sitemaps.")

            total_urls = len(anime_urls)
            existing_anime = {
                a["source_url"]: a for a in self.db_manager.get_all_anime() if a["source_url"]
            }

            for index, url in enumerate(anime_urls, 1):
                try:
                    parsed_url = urlparse(url)
                    slug_match = re.search(r"/anime/(\d+-[^/]+)", parsed_url.path)
                    if not slug_match:
                        continue

                    anime_slug = slug_match.group(1)
                    relative_path = f"/anime/{anime_slug}"

                    self._sync_single_anime(
                        scraper=scraper,
                        relative_page_path=relative_path,
                        anime_slug=anime_slug,
                        existing_record=existing_anime.get(relative_path),
                        preferred_lang=preferred_lang,
                        index=index,
                        total_urls=total_urls,
                    )
                except Exception as err:
                    print(f"Skipping metadata for {url}: {err}")
                    continue

        except Exception as err:
            self.signals.error.emit(f"Failed to fetch or parse XML: {err}")

        self.signals.finished.emit()
