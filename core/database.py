import sqlite3
import os
import threading

class DatabaseManager:
    def __init__(self, db_name="library.db"):
        self.db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", db_name)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock() 
        self.init_db()

    def init_db(self):
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute('''
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
            ''')
            cursor.execute('''
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
            ''')
            self.conn.commit()

    def close(self):
        self.conn.close()

    def add_or_update_anime(self, remote_id, title, source_url=None, cover_path=None, plot=None, 
                            anime_type=None, status=None, release_year=None, 
                            studio=None, genres=None, related_json=None):
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute('SELECT id FROM anime WHERE remote_id = ?', (remote_id,))
            result = cursor.fetchone()
            
            if result:
                anime_id = result[0]
                cursor.execute('''
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
                ''', (title, source_url, cover_path, plot, anime_type, status, release_year, studio, genres, related_json, anime_id))
                self.conn.commit()
                return anime_id
                
            cursor.execute('''
                INSERT INTO anime (remote_id, title, source_url, cover_path, plot, type, status, release_year, studio, genres, related_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (remote_id, title, source_url, cover_path, plot, anime_type, status, release_year, studio, genres, related_json))
            self.conn.commit()
            return cursor.lastrowid

    def get_all_anime(self):
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute('SELECT * FROM anime ORDER BY title')
            return [dict(row) for row in cursor.fetchall()]
    
    def get_anime_by_id(self, anime_id):
        with self.lock:
            self.conn.row_factory = sqlite3.Row
            cursor = self.conn.cursor()
            cursor.execute('SELECT * FROM anime WHERE id = ?', (anime_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_anime_by_remote_id(self, remote_id):
        with self.lock:
            self.conn.row_factory = sqlite3.Row
            cursor = self.conn.cursor()
            cursor.execute('SELECT * FROM anime WHERE remote_id = ?', (remote_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_anime_by_title(self, title):
        with self.lock:
            self.conn.row_factory = sqlite3.Row
            cursor = self.conn.cursor()
            cursor.execute('SELECT id, cover_path FROM anime WHERE title = ?', (title,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def update_anime_episode_count(self, anime_id, total):
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute('UPDATE anime SET total_episodes = ? WHERE id = ?', (total, anime_id))
            self.conn.commit()

    def add_episode(self, anime_id, episode_number, remote_id=None, status='pending', file_path=None):
        with self.lock:
            cursor = self.conn.cursor()
            try:
                cursor.execute('''
                    INSERT INTO episodes (anime_id, episode_number, remote_id, status, file_path)
                    VALUES (?, ?, ?, ?, ?)
                ''', (anime_id, str(episode_number), remote_id, status, file_path))
                self.conn.commit()
            except sqlite3.IntegrityError:
                self.update_episode_status(anime_id, episode_number, status, file_path, remote_id)

    def update_episode_status(self, anime_id, episode_number, status, file_path=None, remote_id=None):
        with self.lock:
            cursor = self.conn.cursor()
            if file_path:
                cursor.execute('''
                    UPDATE episodes 
                    SET status = ?, file_path = ?, remote_id = COALESCE(?, remote_id)
                    WHERE anime_id = ? AND episode_number = ?
                ''', (status, file_path, remote_id, anime_id, str(episode_number)))
            else:
                cursor.execute('''
                    UPDATE episodes 
                    SET status = ?, remote_id = COALESCE(?, remote_id)
                    WHERE anime_id = ? AND episode_number = ?
                ''', (status, remote_id, anime_id, str(episode_number)))
            self.conn.commit()

    def get_episodes_by_anime(self, anime_id):
        with self.lock:
            self.conn.row_factory = sqlite3.Row
            cursor = self.conn.cursor()
            cursor.execute('SELECT * FROM episodes WHERE anime_id = ? ORDER BY CAST(episode_number AS REAL)', (anime_id,))
            return [dict(row) for row in cursor.fetchall()]
    
    def get_saved_episode_count(self, anime_id):
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute('SELECT COUNT(id) FROM episodes WHERE anime_id = ?', (anime_id,))
            row = cursor.fetchone()
            return row[0] if row else 0
    
    def has_downloaded_episodes(self, anime_id):
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT 1 FROM episodes 
                WHERE anime_id = ? AND status = 'downloaded' 
                LIMIT 1
            ''', (anime_id,))
            return cursor.fetchone() is not None
