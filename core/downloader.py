import os
import re
import traceback
import json
import cloudscraper
from urllib.parse import urlparse
from PyQt6.QtCore import QRunnable, QObject, pyqtSignal, pyqtSlot, Qt
from PyQt6.QtGui import QImage

class WorkerSignals(QObject):
    progress = pyqtSignal(int, int)
    status = pyqtSignal(int, str)
    finished = pyqtSignal(int, str, str, str)
    error = pyqtSignal(int, str, object)

class DownloadWorker(QRunnable):
    def __init__(self, worker_id, ep_data, config_manager, abort_flag):
        super().__init__()
        self.worker_id = worker_id
        self.ep_data = ep_data
        self.chunk_size = config_manager.get("chunk_size_kb", 1024) * 1024
        self.config_manager = config_manager
        self.abort_flag = abort_flag
        self.signals = WorkerSignals()

    @pyqtSlot()
    def run(self):
        try:
            self.scraper = cloudscraper.create_scraper(
                browser={"browser": "firefox", "platform": "darwin", "desktop": True}
            )

            base_domain = self.config_manager.get("base_domain", "").rstrip('/')
            
            ep_num = self.ep_data['num']
            ep_id = self.ep_data['id']
            download_dir = self.ep_data['download_dir']
            anime_id = self.ep_data.get('anime_id')
            
            os.makedirs(download_dir, exist_ok=True)
            
            filename = f"Episode {ep_num}.mp4"
            filepath = os.path.join(download_dir, filename)

            self.signals.status.emit(self.worker_id, filename)

            embed_url_request = f"{base_domain}/embed-url/{ep_id}"
            embed_url = self.scraper.get(embed_url_request, timeout=15).text.strip()
            video_page_html = self.scraper.get(embed_url, timeout=15).text
            
            dl_match = re.search(r"window\.downloadUrl\s*=\s*'(https?://[^']+)'", video_page_html)
            if not dl_match:
                raise ValueError("No direct MP4 link found.")
                
            mp4_url = dl_match.group(1)
            
            headers = {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Referer": mp4_url
            }
            
            head_res = self.scraper.head(mp4_url, headers=headers, timeout=15)
            total_size = int(head_res.headers.get('content-length', 0))

            bytes_processed = 0
            with self.scraper.get(mp4_url, headers=headers, stream=True, timeout=15) as r:
                r.raise_for_status()
                with open(filepath, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=self.chunk_size):
                        
                        if self.abort_flag[0]:
                            raise InterruptedError("Cancelled by user")
                            
                        if chunk:
                            f.write(chunk)
                            bytes_processed += len(chunk)
                            if total_size > 0:
                                percent = int((bytes_processed / total_size) * 100)
                                self.signals.progress.emit(self.worker_id, percent)

            self.signals.finished.emit(self.worker_id, str(anime_id), str(ep_num), filepath)
            self.signals.status.emit(self.worker_id, "Idle")
            self.signals.progress.emit(self.worker_id, 0)
            
        except Exception as e:
            print(f"[DownloadWorker ERROR - Worker {self.worker_id}]")
            traceback.print_exc()
            
            try:
                if 'filepath' in locals() and os.path.exists(filepath):
                    os.remove(filepath)
            except OSError:
                pass
                
            self.signals.error.emit(self.worker_id, str(e), self.ep_data)
            
            if isinstance(e, InterruptedError):
                self.signals.status.emit(self.worker_id, "Idle")
                self.signals.progress.emit(self.worker_id, 0)
            else:
                self.signals.status.emit(self.worker_id, "Error - Retrying...")

class LibrarySyncSignals(QObject):
    status = pyqtSignal(str)
    finished = pyqtSignal()
    error = pyqtSignal(str)

class LibrarySyncWorker(QRunnable):
    def __init__(self, db_manager, config_manager):
        super().__init__()
        self.db_manager = db_manager
        self.config_manager = config_manager
        self.signals = LibrarySyncSignals()
        self.scraper = cloudscraper.create_scraper(
            browser={"browser": "firefox", "platform": "darwin", "desktop": True}
        )

        self.covers_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "assets", "covers"))
        os.makedirs(self.covers_dir, exist_ok=True)

    def download_cover(self, image_url, slug):
        if not image_url:
            return None
        
        cover_path = os.path.join(self.covers_dir, f"{slug}.jpg")
        tmp_path = cover_path + ".tmp"
        
        if os.path.exists(cover_path):
            return cover_path
            
        try:
            res = self.scraper.get(image_url, timeout=15)
            res.raise_for_status()
            
            image = QImage.fromData(res.content)
            if not image.isNull():
                scaled_image = image.scaled(225, 330, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                scaled_image.save(tmp_path, "JPG", -1) 
            else:
                with open(tmp_path, 'wb') as f:
                    f.write(res.content)
                    
            os.replace(tmp_path, cover_path) 
            return cover_path
        
        except Exception as e:
            print(f"Failed to download cover for {slug}: {e}")
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            return None

    @pyqtSlot()
    def run(self):
        base_domain = self.config_manager.get("base_domain", "").rstrip('/')
        if not base_domain:
            self.signals.error.emit("No Base Domain configured in Settings.")
            self.signals.finished.emit()
            return

        sitemap_url = f"{base_domain}/sitemap.xml"
        self.signals.status.emit("Fetching XML sitemap...")
        
        try:
            res = self.scraper.get(sitemap_url, timeout=30)
            res.raise_for_status()
            
            urls = re.findall(r'<loc>(.*?)</loc>', res.text)
            anime_urls = [u for u in urls if '/anime/' in u]
            total_urls = len(anime_urls)
            
            existing_anime = {a['source_url']: a for a in self.db_manager.get_all_anime() if a['source_url']}

            for index, url in enumerate(anime_urls, 1):
                try:
                    parsed_url = urlparse(url)
                    anime_id_match = re.search(r'/anime/(\d+-[^/]+)', parsed_url.path)
                    if not anime_id_match:
                        continue
                    
                    anime_slug = anime_id_match.group(1)
                    relative_api_path = f"/info_api/{anime_slug}"
                    
                    existing_record = existing_anime.get(relative_api_path)
                    if existing_record and str(existing_record.get('status', '')).strip().lower() in ["terminato", "finished", "completed"]:
                        
                        saved_ep_count = self.db_manager.get_saved_episode_count(existing_record['id'])
                        expected_ep_count = existing_record.get('total_episodes', 0)
                        
                        if saved_ep_count > 0 and saved_ep_count >= expected_ep_count:
                            continue
                        else:
                            self.signals.status.emit(f"Healing incomplete series: {existing_record['title']}...")

                    full_api_url = f"{base_domain}{relative_api_path}"
                    info = self.scraper.get(full_api_url, timeout=15).json()
                    
                    remote_id = info.get('id')
                    anime_name = info.get('title_eng') or info.get('title', 'Unknown_Anime')
                    anime_name = re.sub(r'[^a-zA-Z0-9_ -]', '', anime_name).strip()

                    self.signals.status.emit(f"Syncing ({index}/{total_urls}): {anime_name}")

                    image_url = info.get('imageurl')
                    local_cover_path = self.download_cover(image_url, anime_slug)

                    genres_json = json.dumps(info.get('genres', []))
                    related_list = info.get('related', [])
                    related_list.sort(key=lambda x: str(x.get('date', '9999')))
                    related_json = json.dumps(related_list)

                    db_anime_id = self.db_manager.add_or_update_anime(
                        remote_id=remote_id,
                        title=anime_name, 
                        source_url=relative_api_path,
                        cover_path=local_cover_path,
                        plot=info.get('plot'),
                        anime_type=info.get('type'),
                        status=info.get('status'),
                        release_year=info.get('date'),
                        studio=info.get('studio'),
                        genres=genres_json,
                        related_json=related_json
                    )

                    episodes = []
                    seen_ep_ids = set()
                    start_range = 0
                    step = 100

                    while True:
                        end_range = start_range + step
                        chunk_url = f"{full_api_url}/0?start_range={start_range}&end_range={end_range}"
                        chunk_res = self.scraper.get(chunk_url, timeout=15).json()
                        chunk = chunk_res.get('episodes', [])
                        if not chunk: break
                        
                        for ep in chunk:
                            if ep['id'] not in seen_ep_ids:
                                seen_ep_ids.add(ep['id'])
                                episodes.append(ep)
                        start_range += step

                    self.db_manager.update_anime_episode_count(db_anime_id, len(episodes))

                    for ep in episodes:
                        ep_num = str(ep['number'])
                        ep_id = ep['id']
                        self.db_manager.add_episode(
                            anime_id=db_anime_id, 
                            episode_number=ep_num, 
                            remote_id=ep_id, 
                            status='not_downloaded'
                        )

                except Exception as e:
                    print(f"Skipping metadata for {url}: {e}")
                    continue
                    
        except Exception as e:
            self.signals.error.emit(f"Failed to fetch or parse XML: {str(e)}")

        self.signals.finished.emit()
