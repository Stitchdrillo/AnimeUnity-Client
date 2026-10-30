import json
import os

class ConfigManager:
    def __init__(self, config_file="config.json"):
        self.config_file = config_file
        self.default_config = {
            "download_directory": os.path.join(os.path.expanduser("~"), "Videos", "Anime"),
            "max_concurrent_downloads": 4,
            "chunk_size_kb": 1024,
            "base_domain": "https://www.animeunity.co",
            "auto_download_next": False,
            "auto_delete_seen": False
        }
        self.config = self.load_config()

    def load_config(self):
        if not os.path.exists(self.config_file):
            self.save_config(self.default_config)
            return self.default_config
        with open(self.config_file, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                print("Warning: config.json error. Using defaults.")
                return self.default_config

    def save_config(self, config_data=None):
        data_to_save = config_data if config_data is not None else self.config
        with open(self.config_file, "w", encoding="utf-8") as f:
            json.dump(data_to_save, f, indent=4)

    def get(self, key, default=None):
        return self.config.get(key, default)

    def set(self, key, value):
        self.config[key] = value
        self.save_config()
