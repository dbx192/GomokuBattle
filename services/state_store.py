import json
import time
from typing import Optional

from redis import Redis

from config import (
    REDIS_ENABLED,
    REDIS_URL,
    LOGIN_RATE_LIMIT_MAX_ATTEMPTS,
    LOGIN_RATE_LIMIT_WINDOW_SECONDS,
)
from services.game_service import GomokuGame


class RedisStateStore:
    AI_TTL_SECONDS = 60 * 60 * 12
    ROOM_TTL_SECONDS = 60 * 60 * 24
    UNDO_TTL_SECONDS = 30

    def __init__(self):
        self.enabled = REDIS_ENABLED
        self.client: Optional[Redis] = None
        self._local_store: dict[str, tuple[float, str]] = {}
        self._local_counters: dict[str, tuple[int, float]] = {}
        if self.enabled:
            self.client = Redis.from_url(REDIS_URL, decode_responses=True)

    def ping(self):
        if not self.enabled or self.client is None:
            return False
        return self.client.ping()

    def _local_set(self, key: str, payload: str, ttl_seconds: int, nx: bool = False) -> bool:
        self._local_prune_key(key)
        if nx and key in self._local_store:
            return False
        self._local_store[key] = (time.time() + ttl_seconds, payload)
        return True

    def _local_get(self, key: str) -> Optional[str]:
        self._local_prune_key(key)
        item = self._local_store.get(key)
        if not item:
            return None
        return item[1]

    def _local_delete(self, key: str):
        self._local_store.pop(key, None)

    def _local_prune_key(self, key: str):
        item = self._local_store.get(key)
        if item and item[0] <= time.time():
            self._local_store.pop(key, None)

    def _game_key(self, namespace: str, entity_id: int) -> str:
        return f"gomoku:{namespace}:game:{entity_id}"

    def _undo_key(self, room_id: int) -> str:
        return f"gomoku:room:undo:{room_id}"

    def _login_limit_key(self, identifier: str) -> str:
        return f"gomoku:auth:login_limit:{identifier}"

    def save_game(self, namespace: str, entity_id: int, game: GomokuGame, ttl_seconds: int):
        payload = json.dumps(game.to_dict(), ensure_ascii=False)
        if not self.enabled or self.client is None:
            self._local_set(self._game_key(namespace, entity_id), payload, ttl_seconds)
            return
        self.client.setex(self._game_key(namespace, entity_id), ttl_seconds, payload)

    def load_game(self, namespace: str, entity_id: int) -> Optional[GomokuGame]:
        if not self.enabled or self.client is None:
            payload = self._local_get(self._game_key(namespace, entity_id))
            if not payload:
                return None
            return GomokuGame.from_dict(json.loads(payload))
        payload = self.client.get(self._game_key(namespace, entity_id))
        if not payload:
            return None
        return GomokuGame.from_dict(json.loads(payload))

    def delete_game(self, namespace: str, entity_id: int):
        if not self.enabled or self.client is None:
            self._local_delete(self._game_key(namespace, entity_id))
            return
        self.client.delete(self._game_key(namespace, entity_id))

    def create_pending_undo(self, room_id: int, requester_id: int) -> bool:
        payload = json.dumps({"requester_id": requester_id}, ensure_ascii=False)
        if not self.enabled or self.client is None:
            return self._local_set(
                self._undo_key(room_id),
                payload,
                self.UNDO_TTL_SECONDS,
                nx=True,
            )
        return bool(self.client.set(self._undo_key(room_id), payload, ex=self.UNDO_TTL_SECONDS, nx=True))

    def get_pending_undo(self, room_id: int) -> Optional[dict]:
        if not self.enabled or self.client is None:
            payload = self._local_get(self._undo_key(room_id))
            if not payload:
                return None
            return json.loads(payload)
        payload = self.client.get(self._undo_key(room_id))
        if not payload:
            return None
        return json.loads(payload)

    def clear_pending_undo(self, room_id: int):
        if not self.enabled or self.client is None:
            self._local_delete(self._undo_key(room_id))
            return
        self.client.delete(self._undo_key(room_id))

    def check_login_rate_limit(self, identifier: str) -> tuple[bool, int, int]:
        if not self.enabled or self.client is None:
            key = self._login_limit_key(identifier)
            now = time.time()
            current, expires_at = self._local_counters.get(key, (0, now + LOGIN_RATE_LIMIT_WINDOW_SECONDS))
            if expires_at <= now:
                current = 0
                expires_at = now + LOGIN_RATE_LIMIT_WINDOW_SECONDS
            current += 1
            self._local_counters[key] = (current, expires_at)
            ttl = max(int(expires_at - now), 0)
            remaining = max(LOGIN_RATE_LIMIT_MAX_ATTEMPTS - current, 0)
            allowed = current <= LOGIN_RATE_LIMIT_MAX_ATTEMPTS
            return allowed, remaining, ttl
        key = self._login_limit_key(identifier)
        current = self.client.incr(key)
        if current == 1:
            self.client.expire(key, LOGIN_RATE_LIMIT_WINDOW_SECONDS)
        ttl = self.client.ttl(key)
        remaining = max(LOGIN_RATE_LIMIT_MAX_ATTEMPTS - current, 0)
        allowed = current <= LOGIN_RATE_LIMIT_MAX_ATTEMPTS
        return allowed, remaining, max(ttl, 0)

    def reset_login_rate_limit(self, identifier: str):
        if not self.enabled or self.client is None:
            self._local_counters.pop(self._login_limit_key(identifier), None)
            return
        self.client.delete(self._login_limit_key(identifier))


state_store = RedisStateStore()
