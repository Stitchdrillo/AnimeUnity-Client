"""Thread-safe SQLite persistence layer for anime metadata and episode states."""

import os
import sqlite3
import threading
from typing import Any


class DatabaseManager:
    """Manages local SQLite storage for synced series and downloaded episodes."""

    def __init__(self, db_name: str = "library.db") -> None:
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        self.db_path = os.path.join(project_root, db_name)

        # Shared across UI and QThreadPool workers; guarded by an RLock.
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.init_db()

    def init_db(self) -> None:
        """Create database tables and constraints if they do not exist."""
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("PRAGMA foreign_keys = ON;")
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS anime (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    remote_id INTEGER UNIQUE,
                    title TEXT NOT NULL,
                    source_url TEXT,
                    cover_path TEXT,
                    total_episodes INTEGER DEFAULT 0,
                    plot TEXT,
                    type TEXT,
                    status TEXT,
                    release_year TEXT,
                    studio TEXT,
                    genres TEXT,
                    related_json TEXT,
                    date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS episodes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    anime_id INTEGER,
                    remote_id INTEGER,
                    episode_number TEXT NOT NULL,
                    file_path TEXT,
                    status TEXT DEFAULT 'pending',
                    FOREIGN KEY (anime_id) REFERENCES anime (id),
                    UNIQUE(anime_id, episode_number)
                )
                """
            )
            self.conn.commit()

    def close(self) -> None:
        """Close the underlying SQLite connection safely."""
        with self.lock:
            self.conn.close()

    def add_or_update_anime(
        self,
        remote_id: int,
        title: str,
        source_url: str | None = None,
        cover_path: str | None = None,
        plot: str | None = None,
        anime_type: str | None = None,
        status: str | None = None,
        release_year: str | int | None = None,
        studio: str | None = None,
        genres: str | None = None,
        related_json: str | None = None,
    ) -> int:
        """Insert a new anime record or update an existing one by `remote_id`."""
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("SELECT id FROM anime WHERE remote_id = ?", (remote_id,))
            existing = cursor.fetchone()

            if existing:
                anime_id = existing["id"]
                cursor.execute(
                    """
                    UPDATE anime SET
                        title = ?,
                        source_url = COALESCE(?, source_url),
                        cover_path = COALESCE(?, cover_path),
                        plot = COALESCE(?, plot),
                        type = COALESCE(?, type),
                        status = COALESCE(?, status),
                        release_year = COALESCE(?, release_year),
                        studio = COALESCE(?, studio),
                        genres = COALESCE(?, genres),
                        related_json = COALESCE(?, related_json)
                    WHERE id = ?
                    """,
                    (
                        title,
                        source_url,
                        cover_path,
                        plot,
                        anime_type,
                        status,
                        release_year,
                        studio,
                        genres,
                        related_json,
                        anime_id,
                    ),
                )
                self.conn.commit()
                return anime_id

            cursor.execute(
                """
                INSERT INTO anime (
                    remote_id, title, source_url, cover_path, plot,
                    type, status, release_year, studio, genres, related_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    remote_id,
                    title,
                    source_url,
                    cover_path,
                    plot,
                    anime_type,
                    status,
                    release_year,
                    studio,
                    genres,
                    related_json,
                ),
            )
            self.conn.commit()
            return cursor.lastrowid

    def get_all_anime(self) -> list[dict[str, Any]]:
        """Return all anime records sorted alphabetically by title."""
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM anime ORDER BY title")
            return [dict(row) for row in cursor.fetchall()]

    def get_anime_by_id(self, anime_id: int) -> dict[str, Any] | None:
        """Fetch a single anime record by its local primary key."""
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM anime WHERE id = ?", (anime_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_anime_by_remote_id(self, remote_id: int) -> dict[str, Any] | None:
        """Fetch a single anime record by its remote site ID."""
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM anime WHERE remote_id = ?", (remote_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_anime_by_title(self, title: str) -> dict[str, Any] | None:
        """Fetch basic anime info matching an exact title."""
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("SELECT id, cover_path FROM anime WHERE title = ?", (title,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def update_anime_episode_count(self, anime_id: int, total: int) -> None:
        """Update the expected total episode count for an anime."""
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("UPDATE anime SET total_episodes = ? WHERE id = ?", (total, anime_id))
            self.conn.commit()

    def add_episode(
        self,
        anime_id: int,
        episode_number: str | int | float,
        remote_id: int | None = None,
        status: str = "pending",
        file_path: str | None = None,
    ) -> None:
        """Insert an episode row, or update its status/remote_id if it already exists."""
        with self.lock:
            cursor = self.conn.cursor()
            try:
                cursor.execute(
                    """
                    INSERT INTO episodes (anime_id, episode_number, remote_id, status, file_path)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (anime_id, str(episode_number), remote_id, status, file_path),
                )
                self.conn.commit()
            except sqlite3.IntegrityError:
                self.update_episode_status(anime_id, episode_number, status, file_path, remote_id)

    def update_episode_status(
        self,
        anime_id: int,
        episode_number: str | int | float,
        status: str,
        file_path: str | None = None,
        remote_id: int | None = None,
    ) -> None:
        """Update download status (and optionally local file path or video ID) for an episode."""
        with self.lock:
            cursor = self.conn.cursor()
            if file_path is not None:
                cursor.execute(
                    """
                    UPDATE episodes
                    SET status = ?, file_path = ?, remote_id = COALESCE(?, remote_id)
                    WHERE anime_id = ? AND episode_number = ?
                    """,
                    (status, file_path, remote_id, anime_id, str(episode_number)),
                )
            else:
                cursor.execute(
                    """
                    UPDATE episodes
                    SET status = ?, remote_id = COALESCE(?, remote_id)
                    WHERE anime_id = ? AND episode_number = ?
                    """,
                    (status, remote_id, anime_id, str(episode_number)),
                )
            self.conn.commit()

    def get_episodes_by_anime(self, anime_id: int) -> list[dict[str, Any]]:
        """Return all episodes for a series ordered numerically by episode number."""
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT * FROM episodes WHERE anime_id = ? ORDER BY CAST(episode_number AS REAL)",
                (anime_id,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_saved_episode_count(self, anime_id: int) -> int:
        """Return the number of episode rows stored for a given anime."""
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("SELECT COUNT(id) FROM episodes WHERE anime_id = ?", (anime_id,))
            row = cursor.fetchone()
            return row[0] if row else 0

    def has_downloaded_episodes(self, anime_id: int) -> bool:
        """Return True if at least one episode of the series is marked as downloaded."""
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                SELECT 1 FROM episodes
                WHERE anime_id = ? AND status = 'downloaded'
                LIMIT 1
                """,
                (anime_id,),
            )
            return cursor.fetchone() is not None
