"""7 天会话存 Redis，与架构设计一致"""
import uuid
from django.core.cache import cache
from django.conf import settings

SESSION_PREFIX = "session:"
TTL = getattr(settings, "APP_SESSION_TTL_DAYS", 7) * 24 * 60 * 60  # 秒


def create_session(user_id: int, device_id: str = None) -> str:
    token = uuid.uuid4().hex
    key = SESSION_PREFIX + token
    cache.set(key, {"user_id": user_id, "device_id": device_id or ""}, timeout=TTL)
    return token


def get_user_id_by_token(token: str):
    if not token:
        return None
    data = cache.get(SESSION_PREFIX + token)
    return data.get("user_id") if data else None


def refresh_session(token: str) -> None:
    key = SESSION_PREFIX + token
    data = cache.get(key)
    if data:
        cache.set(key, data, timeout=TTL)


def remove_session(token: str) -> None:
    cache.delete(SESSION_PREFIX + token)
