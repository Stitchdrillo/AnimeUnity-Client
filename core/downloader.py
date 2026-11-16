import os
import re
import html
import json
import traceback
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
        filepath = None
        try:
            self.scraper = cloudscraper.create_scraper(
                browser={"browser": "firefox", "platform": "darwin", "desktop": True}
            )

            base_domain = self.config_manager.get("base_domain", "https://animeunity.cx").rstrip('/')
            
            ep_num = self.ep_data['num']
            video_id = self.ep_data['id']
            download_dir = self.ep_data['download_dir']
            anime_id = self.ep_data.get('anime_id')
            
            os.makedirs(download_dir, exist_ok=True)
            
            filename = f"Episode {ep_num}.mp4"
            filepath = os.path.join(download_dir, filename)

            self.signals.status.emit(self.worker_id, filename)

            headers = {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,video/mp4,*/*;q=0.8",
                "Referer": f"{base_domain}/"
            }

            qualities = self.config_manager.get("preferred_qualities", [1080, 720, 480])
            response = None

            for q in qualities:
                if self.abort_flag[0]:
                    raise InterruptedError("Cancelled by user")

                dl_url = f"{base_domain}/episode-videos/{video_id}/download?quality={q}"
                r = self.scraper.get(dl_url, headers=headers, stream=True, timeout=20, allow_redirects=True)
                
                content_type = r.headers.get("Content-Type", "").lower()
                if r.status_code == 200 and "text/html" not in content_type:
                    response = r
                    break
                else:
                    r.close()

            if response is None:
                raise ValueError(f"No valid MP4 download stream returned for video ID {video_id}.")

            with response as r:
                total_size = int(r.headers.get('content-length', 0))
                bytes_processed = 0

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
                if filepath and os.path.exists(filepath):
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

    def extract_inertia_props(self, page_html):
        """Extracts and parses the Inertia.js data-page JSON attribute from raw HTML."""
        match = re.search(r'data-page="([^"]+)"', page_html)
        if not match:
            raise ValueError("Could not find Inertia data-page attribute in HTML.")
        decoded_json = html.unescape(match.group(1))
        page_data = json.loads(decoded_json)
        return page_data.get("props", {})

    def fetch_all_anime_urls(self, base_domain):
        """Discovers all anime-*.xml sitemaps from sitemap.xml (or sequentially) and collects /anime/ URLs."""
        anime_urls = []
        sub_sitemaps = []

        try:
            index_res = self.scraper.get(f"{base_domain}/sitemap.xml", timeout=20)
            if index_res.status_code == 200:
                locs = re.findall(r'<loc>(.*?)</loc>', index_res.text)
                sub_sitemaps = [u for u in locs if '/sitemaps/anime-' in u and u.endswith('.xml')]
                direct_urls = [u for u in locs if '/anime/' in u]
                if direct_urls:
                    anime_urls.extend(direct_urls)
        except Exception:
            pass

        if not sub_sitemaps and not anime_urls:
            page = 1
            while True:
                sm_url = f"{base_domain}/sitemaps/anime-{page}.xml"
                sm_res = self.scraper.get(sm_url, timeout=20)
                if sm_res.status_code != 200:
                    break
                locs = re.findall(r'<loc>(.*?)</loc>', sm_res.text)
                anime_urls.extend([u for u in locs if '/anime/' in u])
                page += 1
        else:
            for sm_url in sub_sitemaps:
                sm_res = self.scraper.get(sm_url, timeout=20)
                if sm_res.status_code == 200:
                    locs = re.findall(r'<loc>(.*?)</loc>', sm_res.text)
                    anime_urls.extend([u for u in locs if '/anime/' in u])

        return list(dict.fromkeys(anime_urls))

    @pyqtSlot()
    def run(self):
        base_domain = self.config_manager.get("base_domain", "https://animeunity.cx").rstrip('/')
        if not base_domain:
            self.signals.error.emit("No Base Domain configured in Settings.")
            self.signals.finished.emit()
            return

        preferred_lang = self.config_manager.get("preferred_language", "jpn").lower()
        self.signals.status.emit("Fetching anime sitemaps...")

        try:
            anime_urls = self.fetch_all_anime_urls(base_domain)
            if not anime_urls:
                raise ValueError("No anime URLs found in sitemaps.")

            total_urls = len(anime_urls)
            existing_anime = {a['source_url']: a for a in self.db_manager.get_all_anime() if a['source_url']}

            for index, url in enumerate(anime_urls, 1):
                try:
                    parsed_url = urlparse(url)
                    anime_id_match = re.search(r'/anime/(\d+-[^/]+)', parsed_url.path)
                    if not anime_id_match:
                        continue

                    anime_slug = anime_id_match.group(1)
                    relative_page_path = f"/anime/{anime_slug}"

                    existing_record = existing_anime.get(relative_page_path)
                    if existing_record and str(existing_record.get('status', '')).strip().lower() in ["terminato", "finished", "completed"]:
                        saved_ep_count = self.db_manager.get_saved_episode_count(existing_record['id'])
                        expected_ep_count = existing_record.get('total_episodes', 0)

                        if saved_ep_count > 0 and saved_ep_count >= expected_ep_count:
                            continue
                        else:
                            self.signals.status.emit(f"Healing incomplete series: {existing_record['title']}...")

                    full_page_url = f"{base_domain}{relative_page_path}"
                    page_res = self.scraper.get(full_page_url, timeout=15)
                    page_res.raise_for_status()

                    props = self.extract_inertia_props(page_res.text)
                    info = props.get("anime")
                    if not info:
                        continue

                    remote_id = info.get("id")
                    anime_name = info.get("title") or info.get("title_ja") or "Unknown_Anime"
                    anime_name = re.sub(r'[^a-zA-Z0-9_ -]', '', anime_name).strip()

                    self.signals.status.emit(f"Syncing ({index}/{total_urls}): {anime_name}")

                    images = info.get("images") or {}
                    image_url = images.get("poster") or images.get("cover")
                    local_cover_path = self.download_cover(image_url, anime_slug)

                    genres_list = [g.get("name") for g in info.get("genres", []) if g.get("name")]
                    genres_json = json.dumps(genres_list)

                    studios_list = [s.get("name") for s in info.get("studios", []) if s.get("name")]
                    studio_str = ", ".join(studios_list) if studios_list else None

                    raw_related = props.get("relatedAnimes") or []
                    formatted_related = []
                    for rel in raw_related:
                        formatted_related.append({
                            "id": rel.get("id"),
                            "title": rel.get("title") or rel.get("title_ja"),
                            "title_eng": rel.get("title"),
                            "type": rel.get("type", ""),
                            "date": str(rel.get("year") or "9999")
                        })
                    formatted_related.sort(key=lambda x: str(x.get("date", "9999")))
                    related_json = json.dumps(formatted_related)

                    db_anime_id = self.db_manager.add_or_update_anime(
                        remote_id=remote_id,
                        title=anime_name,
                        source_url=relative_page_path,
                        cover_path=local_cover_path,
                        plot=info.get("plot"),
                        anime_type=info.get("type"),
                        status=info.get("default_status"),
                        release_year=info.get("year"),
                        studio=studio_str,
                        genres=genres_json,
                        related_json=related_json
                    )

                    episodes = []
                    seen_ep_ids = set()

                    loaded_ep_block = props.get("loadedEpisodes") or {}
                    initial_eps = loaded_ep_block.get("episodes") or []
                    tab_size = loaded_ep_block.get("tab_size") or 120
                    total_expected = loaded_ep_block.get("total") or info.get("total_episodes") or 0

                    for ep in initial_eps:
                        ep_id = ep.get("id")
                        if ep_id not in seen_ep_ids:
                            seen_ep_ids.add(ep_id)
                            episodes.append(ep)

                    start = len(initial_eps) + 1 if initial_eps else 1
                    while True:
                        if total_expected and len(episodes) >= total_expected:
                            break

                        try:
                            ep_api_url = f"{base_domain}/api/anime/{remote_id}/episodes?start={start}"
                            ep_res = self.scraper.get(ep_api_url, timeout=15)
                            ep_res.raise_for_status()
                            ep_payload = ep_res.json()

                            if isinstance(ep_payload, list):
                                chunk = ep_payload
                            else:
                                chunk = ep_payload.get("episodes") or []
                                tab_size = ep_payload.get("tab_size") or tab_size
                                total_expected = ep_payload.get("total") or total_expected

                            if not chunk:
                                break

                            added_in_chunk = 0
                            for ep in chunk:
                                ep_id = ep.get("id")
                                if ep_id not in seen_ep_ids:
                                    seen_ep_ids.add(ep_id)
                                    episodes.append(ep)
                                    added_in_chunk += 1

                            if added_in_chunk == 0:
                                break

                            start += tab_size

                        except Exception as ep_err:
                            print(f"Stopped episode pagination at start={start} for {anime_name}: {ep_err}")
                            break

                    self.db_manager.update_anime_episode_count(db_anime_id, len(episodes))

                    for ep in episodes:
                        ep_num = str(ep.get("number"))
                        videos = ep.get("videos") or []
                        if not videos:
                            continue

                        visible_videos = [v for v in videos if not v.get("is_hidden")] or videos
                        chosen_video = next(
                            (v for v in visible_videos if str(v.get("language", "")).lower() == preferred_lang),
                            visible_videos[0]
                        )
                        video_id = chosen_video.get("id")

                        if video_id:
                            self.db_manager.add_episode(
                                anime_id=db_anime_id,
                                episode_number=ep_num,
                                remote_id=video_id,
                                status='not_downloaded'
                            )

                except Exception as e:
                    print(f"Skipping metadata for {url}: {e}")
                    continue

        except Exception as e:
            self.signals.error.emit(f"Failed to fetch or parse XML: {str(e)}")

        self.signals.finished.emit()
