import json
import os
import logging

logger = logging.getLogger(__name__)


class Storage:
    def __init__(self, filepath: str):
        self.filepath = filepath
        self.seen_ids: set = set()
        self._load()

    def _load(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r") as f:
                    data = json.load(f)
                    self.seen_ids = set(data.get("seen_ids", []))
                logger.info(f"Loaded {len(self.seen_ids)} seen ads from storage")
            except Exception as e:
                logger.error(f"Failed to load storage: {e}")
                self.seen_ids = set()

    def save(self):
        try:
            with open(self.filepath, "w") as f:
                json.dump({"seen_ids": list(self.seen_ids)}, f)
        except Exception as e:
            logger.error(f"Failed to save storage: {e}")

    def is_seen(self, ad_id: str) -> bool:
        return ad_id in self.seen_ids

    def mark_seen(self, ad_id: str):
        self.seen_ids.add(ad_id)

    def count(self) -> int:
        return len(self.seen_ids)
