"""HTTP scraping and Inertia.js metadata extraction client for AnimeUnity."""

import html
import json
import os
import re
import threading
from typing import Any
import cloudscraper
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage


class AnimeUnityScraper:
    """Encapsulates sitemap discovery, page parsing, episode pagination, and video streams."""

    def __init__(self, base_domain: str) -> None:
        self.base_domain = base_domain.rstrip("/")
        self.scraper = cloudscraper.create_scraper(
            browser={"browser": "firefox", "platform": "darwin", "desktop": True}
        )

    @staticmethod
    def extract_inertia_props(page_html: str) -> dict[str, Any]:
        """Decode and parse the Inertia.js `data-page` JSON payload from raw HTML."""
        match = re.search(r'data-page="([^"]+)"', page_html)
        if not match:
            raise ValueError("Could not find Inertia data-page attribute in HTML.")
        decoded_json = html.unescape(match.group(1))
        page_data = json.loads(decoded_json)
        return page_data.get("props", {})

    def fetch_all_anime_urls(self) -> list[str]:
        """Collect all unique `/anime/` URLs from XML sitemaps."""
        anime_urls: list[str] = []
        sub_sitemaps: list[str] = []

        try:
            index_res = self.scraper.get(f"{self.base_domain}/sitemap.xml", timeout=20)
            if index_res.status_code == 200:
                locs = re.findall(r"<loc>(.*?)</loc>", index_res.text)
                sub_sitemaps = [u for u in locs if "/sitemaps/anime-" in u and u.endswith(".xml")]
                anime_urls.extend(u for u in locs if "/anime/" in u)
        except Exception:
            pass

        # Fall back to sequential sitemap discovery if sitemap.xml didn't list sub-sitemaps.
        if not sub_sitemaps and not anime_urls:
            page = 1
            while True:
                sm_url = f"{self.base_domain}/sitemaps/anime-{page}.xml"
                sm_res = self.scraper.get(sm_url, timeout=20)
                if sm_res.status_code != 200:
                    break
                locs = re.findall(r"<loc>(.*?)</loc>", sm_res.text)
                anime_urls.extend(u for u in locs if "/anime/" in u)
                page += 1
        else:
            for sm_url in sub_sitemaps:
                sm_res = self.scraper.get(sm_url, timeout=20)
                if sm_res.status_code == 200:
                    locs = re.findall(r"<loc>(.*?)</loc>", sm_res.text)
                    anime_urls.extend(u for u in locs if "/anime/" in u)

        return list(dict.fromkeys(anime_urls))

    def fetch_anime_page(self, relative_page_path: str) -> dict[str, Any] | None:
        """Fetch and normalize anime metadata and initial episodes from a series page."""
        full_url = f"{self.base_domain}{relative_page_path}"
        response = self.scraper.get(full_url, timeout=15)
        response.raise_for_status()

        props = self.extract_inertia_props(response.text)
        info = props.get("anime")
        if not info:
            return None

        raw_title = info.get("title") or info.get("title_ja") or "Unknown_Anime"
        clean_title = re.sub(r"[^a-zA-Z0-9_ -]", "", raw_title).strip()

        images = info.get("images") or {}
        genres = [g.get("name") for g in info.get("genres", []) if g.get("name")]
        studios = [s.get("name") for s in info.get("studios", []) if s.get("name")]

        formatted_related = [
            {
                "id": rel.get("id"),
                "title": rel.get("title") or rel.get("title_ja"),
                "title_eng": rel.get("title"),
                "type": rel.get("type", ""),
                "date": str(rel.get("year") or "9999"),
            }
            for rel in (props.get("relatedAnimes") or [])
        ]
        formatted_related.sort(key=lambda item: str(item.get("date", "9999")))

        loaded_block = props.get("loadedEpisodes") or {}

        return {
            "remote_id": info.get("id"),
            "title": clean_title,
            "source_url": relative_page_path,
            "cover_url": images.get("poster") or images.get("cover"),
            "plot": info.get("plot"),
            "anime_type": info.get("type"),
            "status": info.get("default_status"),
            "release_year": info.get("year"),
            "studio": ", ".join(studios) if studios else None,
            "genres_json": json.dumps(genres),
            "related_json": json.dumps(formatted_related),
            "initial_episodes": loaded_block.get("episodes") or [],
            "tab_size": loaded_block.get("tab_size") or 120,
            "total_expected": loaded_block.get("total") or info.get("total_episodes") or 0,
        }

    def fetch_all_episodes(
        self,
        remote_id: int,
        initial_episodes: list[dict[str, Any]],
        tab_size: int = 120,
        total_expected: int = 0,
        anime_title: str = "",
    ) -> list[dict[str, Any]]:
        """Paginate through `/api/anime/{id}/episodes` until all episodes are collected."""
        episodes: list[dict[str, Any]] = []
        seen_ids: set[Any] = set()

        for ep in initial_episodes:
            ep_id = ep.get("id")
            if ep_id not in seen_ids:
                seen_ids.add(ep_id)
                episodes.append(ep)

        start = len(initial_episodes) + 1 if initial_episodes else 1
        while True:
            if total_expected and len(episodes) >= total_expected:
                break

            try:
                api_url = f"{self.base_domain}/api/anime/{remote_id}/episodes?start={start}"
                res = self.scraper.get(api_url, timeout=15)
                res.raise_for_status()
                payload = res.json()

                if isinstance(payload, list):
                    chunk = payload
                else:
                    chunk = payload.get("episodes") or []
                    tab_size = payload.get("tab_size") or tab_size
                    total_expected = payload.get("total") or total_expected

                if not chunk:
                    break

                added = 0
                for ep in chunk:
                    ep_id = ep.get("id")
                    if ep_id not in seen_ids:
                        seen_ids.add(ep_id)
                        episodes.append(ep)
                        added += 1

                if added == 0:
                    break

                start += tab_size
            except Exception as err:
                print(f"Stopped episode pagination at start={start} for {anime_title}: {err}")
                break

        return episodes

    @staticmethod
    def select_video_id(episode_payload: dict[str, Any], preferred_lang: str = "jpn") -> int | None:
        """Pick the video stream ID matching `preferred_lang`, falling back to the first visible stream."""
        videos = episode_payload.get("videos") or []
        if not videos:
            return None

        visible = [v for v in videos if not v.get("is_hidden")] or videos
        target_lang = preferred_lang.lower()
        chosen = next(
            (v for v in visible if str(v.get("language", "")).lower() == target_lang),
            visible[0],
        )
        return chosen.get("id")

    def download_cover(self, image_url: str | None, slug: str, covers_dir: str) -> str | None:
        """Download, resize, and atomically save an anime poster image."""
        if not image_url:
            return None

        cover_path = os.path.join(covers_dir, f"{slug}.jpg")
        tmp_path = f"{cover_path}.tmp"

        if os.path.exists(cover_path):
            return cover_path

        try:
            res = self.scraper.get(image_url, timeout=15)
            res.raise_for_status()

            image = QImage.fromData(res.content)
            if not image.isNull():
                scaled = image.scaled(
                    225,
                    330,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                scaled.save(tmp_path, "JPG", -1)
            else:
                with open(tmp_path, "wb") as f:
                    f.write(res.content)

            os.replace(tmp_path, cover_path)
            return cover_path
        except Exception as err:
            print(f"Failed to download cover for {slug}: {err}")
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            return None

    def open_video_stream(
        self,
        video_id: int | str,
        qualities: list[int],
        abort_event: threading.Event | None = None,
    ):
        """Request an MP4 stream trying `qualities` in order until a valid video response is returned."""
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,video/mp4,*/*;q=0.8",
            "Referer": f"{self.base_domain}/",
        }

        for quality in qualities:
            if abort_event and abort_event.is_set():
                raise InterruptedError("Cancelled by user")

            dl_url = f"{self.base_domain}/episode-videos/{video_id}/download?quality={quality}"
            response = self.scraper.get(
                dl_url,
                headers=headers,
                stream=True,
                timeout=20,
                allow_redirects=True,
            )

            content_type = response.headers.get("Content-Type", "").lower()
            if response.status_code == 200 and "text/html" not in content_type:
                return response
            response.close()

        raise ValueError(f"No valid MP4 download stream returned for video ID {video_id}.")
