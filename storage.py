import json
import os
import logging

logger = logging.getLogger(__name__)


class Storage:
    def __init__(self, filepath: str):
        self.filepath = filepath
        self._data: dict[str, dict] = {}
        self._load()

    def _load(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r") as f:
                    data = json.load(f)
                raw = data.get("ads", data.get("seen_ids", []))
                if isinstance(raw, list):
                    self._data = {ad_id: {} for ad_id in raw if isinstance(ad_id, str)}
                elif isinstance(raw, dict):
                    self._data = raw
                logger.info(f"Loaded {len(self._data)} seen ads from storage")
            except Exception as e:
                logger.error(f"Failed to load storage: {e}")
                self._data = {}

    def save(self):
        try:
            with open(self.filepath, "w") as f:
                json.dump({"ads": self._data}, f)
        except Exception as e:
            logger.error(f"Failed to save storage: {e}")

    def is_seen(self, ad_id: str) -> bool:
        return ad_id in self._data

    def mark_seen(self, ad_id: str, price_usd: float | None = None, price_byn: float | None = None):
        self._data[ad_id] = {"price_usd": price_usd, "price_byn": price_byn}

    def get_ad_data(self, ad_id: str) -> dict | None:
        return self._data.get(ad_id)

    def update_ad_price(self, ad_id: str, price_usd: float | None, price_byn: float | None):
        if ad_id in self._data:
            self._data[ad_id] = {"price_usd": price_usd, "price_byn": price_byn}

    def count(self) -> int:
        return len(self._data)

    def breakdown_by_source(self) -> dict[str, int]:
        sources: dict[str, int] = {}
        for ad_id in self._data:
            prefix = ad_id.split("_")[0] if "_" in ad_id else "unknown"
            sources[prefix] = sources.get(prefix, 0) + 1
        return sources


class UserManager:
    def __init__(self, filepath: str, default_max_price: int = 350):
        self.filepath = filepath
        self.admin_ids: list[int] = []
        self.users: list[dict] = []
        self.max_price_usd: int = default_max_price
        self._load()

    def _load(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r") as f:
                    data = json.load(f)
                raw_ids = data.get("admin_ids")
                if raw_ids is None:
                    old = data.get("admin_id")
                    self.admin_ids = [old] if old is not None else []
                else:
                    self.admin_ids = list(raw_ids)
                raw = data.get("users") or data.get("user_ids", [])
                self.users = [
                    u if isinstance(u, dict) else {"id": u, "username": None}
                    for u in raw
                ]
                self.max_price_usd = data.get("max_price_usd", self.max_price_usd)
                logger.info(f"Loaded {len(self.users)} users, admins={self.admin_ids}, max_price=${self.max_price_usd}")
            except Exception as e:
                logger.error(f"Failed to load users: {e}")

    def save(self):
        try:
            with open(self.filepath, "w") as f:
                json.dump({
                    "admin_ids": self.admin_ids,
                    "users": self.users,
                    "max_price_usd": self.max_price_usd,
                }, f)
        except Exception as e:
            logger.error(f"Failed to save users: {e}")

    def set_max_price(self, price: int):
        self.max_price_usd = price
        self.save()

    def get_max_price(self) -> int:
        return self.max_price_usd

    def add_admin(self, chat_id: int):
        if chat_id not in self.admin_ids:
            self.admin_ids.append(chat_id)
            self.save()

    def is_admin(self, chat_id: int) -> bool:
        return chat_id in self.admin_ids

    def get_admin_ids(self) -> list[int]:
        return list(self.admin_ids)

    def remove_admin(self, chat_id: int):
        if chat_id in self.admin_ids:
            self.admin_ids.remove(chat_id)
            self.save()

    def clear_admins(self):
        self.admin_ids = []
        self.save()

    def add_user(self, chat_id: int, username: str | None = None) -> bool:
        if any(u["id"] == chat_id for u in self.users):
            return False
        self.users.append({"id": chat_id, "username": username})
        self.save()
        return True

    def remove_user(self, chat_id: int) -> bool:
        for u in self.users:
            if u["id"] == chat_id:
                self.users.remove(u)
                self.save()
                return True
        return False

    def list_users(self) -> list[int]:
        return [u["id"] for u in self.users]

    def list_users_display(self) -> list[str]:
        result = []
        for u in self.users:
            uid = u["id"]
            name = u.get("username")
            if name:
                result.append(f"@{name} <code>{uid}</code>")
            else:
                result.append(f"<code>{uid}</code>")
        return result

    def set_username(self, chat_id: int, username: str | None):
        for u in self.users:
            if u["id"] == chat_id:
                u["username"] = username
                self.save()
                break

    def count(self) -> int:
        return len(self.users)

    def users_without_username(self) -> list[int]:
        return [u["id"] for u in self.users if not u.get("username")]
