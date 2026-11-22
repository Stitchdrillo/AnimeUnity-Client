"""Persistent JSON configuration management with default fallbacks."""

import json
import os
from typing import Any


class ConfigManager:
    """Loads, stores, and provides typed access to user settings."""

    KNOWN_QUALITIES = (1080, 720, 480, 420)

    def __init__(self, config_file: str | None = None) -> None:
        if config_file is None:
            project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
            config_file = os.path.join(project_root, "config.json")

        self.config_file = config_file
        self.default_config: dict[str, Any] = {
            "download_directory": os.path.join(os.path.expanduser("~"), "Videos", "Anime"),
            "max_concurrent_downloads": 4,
            "chunk_size_kb": 1024,
            "base_domain": "https://animeunity.cx",
            "preferred_language": "jpn",
            "preferred_quality": 1080,
            "auto_download_next": False,
            "auto_delete_seen": False,
        }
        self.config = self.load_config()

    def load_config(self) -> dict[str, Any]:
        """Read config from disk, merging over defaults to backfill any new keys."""
        if not os.path.exists(self.config_file):
            self.save_config(self.default_config)
            return dict(self.default_config)

        try:
            with open(self.config_file, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if not isinstance(loaded, dict):
                raise ValueError("Configuration root must be a JSON object.")
            return {**self.default_config, **loaded}
        except (json.JSONDecodeError, OSError, ValueError):
            print("Warning: Could not parse config.json. Falling back to defaults.")
            return dict(self.default_config)

    def save_config(self, config_data: dict[str, Any] | None = None) -> None:
        """Persist the current configuration dictionary to disk."""
        data_to_save = config_data if config_data is not None else self.config
        with open(self.config_file, "w", encoding="utf-8") as f:
            json.dump(data_to_save, f, indent=4)

    def get(self, key: str, default: Any = None) -> Any:
        """Retrieve a setting value, falling back to `default` if unset."""
        return self.config.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Update a setting in memory and immediately write it to disk."""
        self.config[key] = value
        self.save_config()

    def get_quality_fallback_chain(self) -> list[int]:
        """Return an ordered list of resolutions starting with the user's preference.

        Tries the preferred resolution first, falls back through lower resolutions,
        and finally tries higher resolutions so streams still succeed if lower ones
        are absent on the server.
        """
        preferred = self.get("preferred_quality")
        if preferred is None:
            legacy_list = self.get("preferred_qualities")
            preferred = legacy_list[0] if legacy_list else 1080

        try:
            preferred = int(preferred)
        except (TypeError, ValueError):
            preferred = 1080

        lower = [q for q in self.KNOWN_QUALITIES if q < preferred]
        higher = [q for q in self.KNOWN_QUALITIES if q > preferred]
        return [preferred, *lower, *higher]
