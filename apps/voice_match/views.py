"""
语音匹配：按性别分池，男配女一对一。加入/取消/状态/房间 join/leave。
"""
import uuid
from django.db import connection
from django.core.cache import cache
from django_redis import get_redis_connection
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.account.models import User
from apps.account.session_store import get_user_id_by_token
from .agora_token import build_rtc_token
from .models import VoiceRoom


POOL_MALE = "voice_match:pool:male"
POOL_FEMALE = "voice_match:pool:female"
USER_IN_POOL = "voice_match:user:{}"
MATCHED_ROOM = "voice_match:matched:{}"
USER_IN_POOL_TTL = 300
MATCHED_TTL = 120


def _result(code=0, message="success", data=None):
    return {"code": code, "message": message, "data": data}


def _user_id_from_request(request):
    auth = request.META.get("HTTP_AUTHORIZATION") or ""
    if auth.startswith("Bearer "):
        token = auth[7:].strip()
        return get_user_id_by_token(token)
    return None


def _try_pair(redis_conn):
    """从男池女池各取一人配对，创建房间并写入 Redis matched。返回 (room_id, user_id_1, user_id_2) 或 None。"""
    male_raw = redis_conn.lpop(POOL_MALE)
    female_raw = redis_conn.lpop(POOL_FEMALE)
    if not male_raw or not female_raw:
        if male_raw:
            redis_conn.rpush(POOL_MALE, male_raw)
        if female_raw:
            redis_conn.rpush(POOL_FEMALE, female_raw)
        return None
    try:
        user_id_1 = int(male_raw)
        user_id_2 = int(female_raw)
    except (TypeError, ValueError):
        redis_conn.rpush(POOL_MALE, male_raw)
        redis_conn.rpush(POOL_FEMALE, female_raw)
        return None
    room_id = str(uuid.uuid4()).replace("-", "")[:16]
    rtc_channel = f"voice_{room_id}"
    with connection.cursor() as cur:
        cur.execute(
            """INSERT INTO voice_room (room_id, user_id_1, user_id_2, rtc_channel, status, started_at)
               VALUES (%s, %s, %s, %s, 'ongoing', NOW())""",
            [room_id, user_id_1, user_id_2, rtc_channel],
        )
    redis_conn.setex(MATCHED_ROOM.format(user_id_1), MATCHED_TTL, room_id)
    redis_conn.setex(MATCHED_ROOM.format(user_id_2), MATCHED_TTL, room_id)
    redis_conn.delete(USER_IN_POOL.format(user_id_1))
    redis_conn.delete(USER_IN_POOL.format(user_id_2))
    return room_id, user_id_1, user_id_2


@api_view(["POST"])
@permission_classes([AllowAny])
def join_pool(request):
    """加入匹配池。校验性别与未成年人模式后入池，若可立即配对则返回 matched + room_id。"""
    user_id = _user_id_from_request(request)
    if not user_id:
        return Response(_result(401, "请先登录"), status=status.HTTP_401_UNAUTHORIZED)

    try:
        user = User.objects.get(id=user_id, status=1)
    except User.DoesNotExist:
        return Response(_result(404, "用户不存在"), status=status.HTTP_404_NOT_FOUND)

    if getattr(user, "minor_mode", 0) == 1:
        return Response(_result(data={"status": "minor_mode"}), status=status.HTTP_200_OK)

    gender = getattr(user, "gender", None)
    if gender is None or gender not in (1, 2):
        return Response(_result(data={"status": "no_gender"}), status=status.HTTP_200_OK)

    redis_conn = get_redis_connection("default")
    key_user = USER_IN_POOL.format(user_id)
    if redis_conn.get(key_user):
        return Response(_result(400, "您已在匹配中"), status=status.HTTP_400_BAD_REQUEST)

    pool = POOL_MALE if gender == 1 else POOL_FEMALE
    redis_conn.rpush(pool, str(user_id))
    redis_conn.setex(key_user, USER_IN_POOL_TTL, "1")

    # 尝试配对：若对方池有人则配对
    pair = _try_pair(redis_conn)
    if pair:
        room_id, uid1, uid2 = pair
        if user_id in (uid1, uid2):
            return Response(_result(data={"status": "matched", "roomId": room_id}))

    return Response(_result(data={"status": "waiting"}))


@api_view(["POST"])
@permission_classes([AllowAny])
def cancel_match(request):
    """取消匹配，从池中移除。"""
    user_id = _user_id_from_request(request)
    if not user_id:
        return Response(_result(401, "请先登录"), status=status.HTTP_401_UNAUTHORIZED)

    redis_conn = get_redis_connection("default")
    key_user = USER_IN_POOL.format(user_id)
    redis_conn.delete(key_user)
    for key in (POOL_MALE, POOL_FEMALE):
        redis_conn.lrem(key, 0, str(user_id))
    return Response(_result())


@api_view(["GET"])
@permission_classes([AllowAny])
def match_status(request):
    """轮询匹配结果。返回 matched + roomId 或 waiting。"""
    user_id = _user_id_from_request(request)
    if not user_id:
        return Response(_result(401, "请先登录"), status=status.HTTP_401_UNAUTHORIZED)

    redis_conn = get_redis_connection("default")
    key_matched = MATCHED_ROOM.format(user_id)
    room_id = redis_conn.get(key_matched)
    if room_id:
        room_id = room_id.decode("utf-8") if isinstance(room_id, bytes) else room_id
        redis_conn.delete(key_matched)
        return Response(_result(data={"status": "matched", "roomId": room_id}))
    return Response(_result(data={"status": "waiting"}))


def _uid_for_agora(user_id):
    """Agora uid 为 32 位无符号，用 user_id 取模避免溢出。"""
    return (int(user_id) % (2 ** 32 - 1)) or 1


@api_view(["GET"])
@permission_classes([AllowAny])
def room_join(request):
    """加入语音房间：返回 rtc_token、channel、uid、对方信息。"""
    user_id = _user_id_from_request(request)
    if not user_id:
        return Response(_result(401, "请先登录"), status=status.HTTP_401_UNAUTHORIZED)

    try:
        user = User.objects.get(id=user_id, status=1)
    except User.DoesNotExist:
        return Response(_result(404, "用户不存在"), status=status.HTTP_404_NOT_FOUND)

    if getattr(user, "minor_mode", 0) == 1:
        return Response(_result(403, "未成年人模式无法使用"), status=status.HTTP_403_FORBIDDEN)

    room_id = request.GET.get("room_id")
    if not room_id:
        return Response(_result(400, "缺少 room_id"), status=status.HTTP_400_BAD_REQUEST)

    try:
        room = VoiceRoom.objects.get(room_id=room_id, status="ongoing")
    except VoiceRoom.DoesNotExist:
        return Response(_result(404, "房间不存在或已结束"), status=status.HTTP_404_NOT_FOUND)

    if user_id not in (room.user_id_1, room.user_id_2):
        return Response(_result(403, "无权加入该房间"), status=status.HTTP_403_FORBIDDEN)

    peer_id = room.user_id_2 if user_id == room.user_id_1 else room.user_id_1
    try:
        peer = User.objects.get(id=peer_id, status=1)
    except User.DoesNotExist:
        peer = None
    peer_info = {
        "user_id": peer_id,
        "userId": peer_id,
        "nickname": getattr(peer, "nickname", None) or f"用户{peer_id}",
        "nickName": getattr(peer, "nickname", None) or f"用户{peer_id}",
        "avatar_url": getattr(peer, "avatar_url", None) or "",
        "avatarUrl": getattr(peer, "avatar_url", None) or "",
    }

    uid = _uid_for_agora(user_id)
    token = build_rtc_token(room.rtc_channel, uid)
    if not token:
        return Response(_result(500, "生成通话凭证失败"), status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    return Response(_result(data={
        "room_id": room_id,
        "roomId": room_id,
        "rtc_token": token,
        "rtcToken": token,
        "channel": room.rtc_channel,
        "channelId": room.rtc_channel,
        "uid": uid,
        "peer": peer_info,
    }))


@api_view(["POST"])
@permission_classes([AllowAny])
def room_leave(request):
    """挂断：结束房间。"""
    user_id = _user_id_from_request(request)
    if not user_id:
        return Response(_result(401, "请先登录"), status=status.HTTP_401_UNAUTHORIZED)

    room_id = request.data.get("room_id") or request.POST.get("room_id")
    if not room_id:
        return Response(_result(400, "缺少 room_id"), status=status.HTTP_400_BAD_REQUEST)

    from django.utils import timezone
    VoiceRoom.objects.filter(room_id=room_id, status="ongoing").update(
        status="ended", ended_at=timezone.now()
    )
    return Response(_result())
