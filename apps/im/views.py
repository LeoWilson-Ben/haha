"""
自研 IM：会话列表、单聊、群聊、消息收发、聊天申请、可加入群聊
"""
from django.db import connection
from django.db.models import Max, Q
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.account.models import User
from apps.account.session_store import get_user_id_by_token
from .models import Conversation, ConversationMember, Message, ChatApply, ImGroup


def _result(code=0, message="success", data=None):
    return {"code": code, "message": message, "data": data}


def _user_id_from_request(request):
    auth = request.META.get("HTTP_AUTHORIZATION") or ""
    if auth.startswith("Bearer "):
        token = auth[7:].strip()
        return get_user_id_by_token(token)
    return None


@api_view(["GET"])
@permission_classes([AllowAny])
def conversation_list(request):
    """我的会话列表（私聊+群聊混合），按最后消息时间倒序"""
    user_id = _user_id_from_request(request)
    if not user_id:
        return Response(_result(401, "请先登录"), status=status.HTTP_401_UNAUTHORIZED)

    my_conv_ids = list(
        ConversationMember.objects.filter(user_id=user_id).values_list("conversation_id", flat=True)
    )
    if not my_conv_ids:
        return Response(_result(data={"list": []}))

    convs = list(Conversation.objects.filter(id__in=my_conv_ids).order_by("-updated_at"))
    last_msg_map = {}
    for m in Message.objects.filter(conversation_id__in=my_conv_ids).values("conversation_id").annotate(
        mid=Max("id")
    ):
        last_msg_map[m["conversation_id"]] = m["mid"]
    last_msgs = {}
    if last_msg_map:
        for msg in Message.objects.filter(id__in=last_msg_map.values()):
            last_msgs[msg.id] = msg

    members_by_conv = {}
    last_read_by_conv = {}
    for cm in ConversationMember.objects.filter(conversation_id__in=my_conv_ids):
        if cm.user_id == user_id:
            last_read_by_conv[cm.conversation_id] = cm.last_read_msg_id or 0
        members_by_conv.setdefault(cm.conversation_id, []).append(cm.user_id)

    user_ids = set()
    for uids in members_by_conv.values():
        user_ids.update(uids)
    user_ids.discard(user_id)
    users = {u.id: u for u in User.objects.filter(id__in=user_ids)} if user_ids else {}

    items = []
    for c in convs:
        last_id = last_msg_map.get(c.id)
        last_msg = last_msgs.get(last_id) if last_id else None
        peer_name = c.name or "群聊"
        if c.type == "single":
            uids = members_by_conv.get(c.id, [])
            other = [x for x in uids if x != user_id]
            if other:
                u = users.get(other[0])
                peer_name = getattr(u, "nickname", None) or f"用户{other[0]}"
        last_read = last_read_by_conv.get(c.id, 0)
        unread = Message.objects.filter(
            conversation_id=c.id, id__gt=last_read
        ).exclude(sender_id=user_id).count()
        item = {
            "conversationId": c.id,
            "type": c.type,
            "title": peer_name,
            "lastMessage": "[图片]" if last_msg and last_msg.type == "image" else (last_msg.content_encrypted[:50] if last_msg and last_msg.content_encrypted else ""),
            "lastMessageType": last_msg.type if last_msg else None,
            "lastMessageAt": last_msg.created_at.isoformat() if last_msg and last_msg.created_at else None,
            "unreadCount": unread,
        }
        if c.type == "single":
            uids = members_by_conv.get(c.id, [])
            other = [x for x in uids if x != user_id]
            if other:
                peer_id = other[0]
                item["peerUserId"] = peer_id
                u = users.get(peer_id)
                if u:
                    item["avatarUrl"] = getattr(u, "avatar_url", None) or None
        items.append(item)
    return Response(_result(data={"list": items}))


@api_view(["POST"])
@permission_classes([AllowAny])
def get_or_create_single(request):
    """获取或创建与某用户的单聊会话。body: { "targetUserId": 123 }"""
    user_id = _user_id_from_request(request)
    if not user_id:
        return Response(_result(401, "请先登录"), status=status.HTTP_401_UNAUTHORIZED)
    target_id = request.data.get("targetUserId")
    if not target_id:
        return Response(_result(400, "缺少对方用户ID"), status=status.HTTP_400_BAD_REQUEST)
    try:
        target_id = int(target_id)
    except (TypeError, ValueError):
        return Response(_result(400, "用户ID无效"), status=status.HTTP_400_BAD_REQUEST)
    if target_id == user_id:
        return Response(_result(400, "不能与自己聊天"), status=status.HTTP_400_BAD_REQUEST)
    if not User.objects.filter(id=target_id, status=1).exists():
        return Response(_result(404, "用户不存在"), status=status.HTTP_404_NOT_FOUND)

    my_convs = set(
        ConversationMember.objects.filter(user_id=user_id).values_list("conversation_id", flat=True)
    )
    target_convs = set(
        ConversationMember.objects.filter(user_id=target_id).values_list("conversation_id", flat=True)
    )
    common = my_convs & target_convs
    for cid in common:
        c = Conversation.objects.filter(id=cid, type="single").first()
        if c:
            return Response(_result(data={"conversationId": c.id, "type": "single", "title": None}))

    c = Conversation.objects.create(type="single", name=None)
    ConversationMember(conversation_id=c.id, user_id=user_id).save()
    ConversationMember(conversation_id=c.id, user_id=target_id).save()
    u = User.objects.filter(id=target_id).first()
    title = getattr(u, "nickname", None) or f"用户{target_id}"
    return Response(_result(data={"conversationId": c.id, "type": "single", "title": title}))


@api_view(["POST"])
@permission_classes([AllowAny])
def create_group(request):
    """创建群聊。body: { "name": "群名", "memberIds": [2, 3] }，创建者自动为群主并加入"""
    user_id = _user_id_from_request(request)
    if not user_id:
        return Response(_result(401, "请先登录"), status=status.HTTP_401_UNAUTHORIZED)
    name = (request.data.get("name") or "").strip() or "群聊"
    name = name[:64]
    member_ids = request.data.get("memberIds") or []
    if isinstance(member_ids, str):
        try:
            import json
            member_ids = json.loads(member_ids)
        except Exception:
            member_ids = []
    member_ids = [int(x) for x in member_ids if x is not None]
    member_ids = list(dict.fromkeys(member_ids))
    if user_id in member_ids:
        member_ids = [x for x in member_ids if x != user_id]
    all_user_ids = [user_id] + member_ids
    if len(all_user_ids) > 500:
        return Response(_result(400, "群成员不能超过500人"), status=status.HTTP_400_BAD_REQUEST)
    exist = User.objects.filter(id__in=all_user_ids).count()
    if exist != len(all_user_ids):
        return Response(_result(400, "部分用户不存在"), status=status.HTTP_400_BAD_REQUEST)
    c = Conversation.objects.create(type="group", name=name)
    for uid in all_user_ids:
        ConversationMember.objects.create(conversation_id=c.id, user_id=uid, role="owner" if uid == user_id else "member")
    try:
        is_public = 1 if request.data.get("isPublic") is True else 0
        with connection.cursor() as cur:
            cur.execute("INSERT INTO im_group (conversation_id, owner_id, max_members, is_public) VALUES (%s, %s, 500, %s)", [c.id, user_id, is_public])
    except Exception:
        ImGroup.objects.create(conversation_id=c.id, owner_id=user_id)
    return Response(_result(data={"conversationId": c.id, "type": "group", "title": name}))


def _get_or_create_single_bulk(user_id, target_id):
    """内部：获取或创建单聊，返回 (conversation, created)"""
    my_convs = set(
        ConversationMember.objects.filter(user_id=user_id).values_list("conversation_id", flat=True)
    )
    target_convs = set(
        ConversationMember.objects.filter(user_id=target_id).values_list("conversation_id", flat=True)
    )
    common = my_convs & target_convs
    for cid in common:
        c = Conversation.objects.filter(id=cid, type="single").first()
        if c:
            return c, False
    c = Conversation.objects.create(type="single", name=None)
    ConversationMember.objects.create(conversation_id=c.id, user_id=user_id)
    ConversationMember.objects.create(conversation_id=c.id, user_id=target_id)
    return c, True


@api_view(["GET"])
@permission_classes([AllowAny])
def message_list(request, conversation_id):
    """会话消息列表，分页，按时间正序"""
    user_id = _user_id_from_request(request)
    if not user_id:
        return Response(_result(401, "请先登录"), status=status.HTTP_401_UNAUTHORIZED)
    if not ConversationMember.objects.filter(conversation_id=conversation_id, user_id=user_id).exists():
        return Response(_result(404, "会话不存在"), status=status.HTTP_404_NOT_FOUND)

    page = max(1, int(request.GET.get("page") or 1))
    page_size = min(50, max(1, int(request.GET.get("page_size") or 20)))
    start = (page - 1) * page_size
    qs = Message.objects.filter(conversation_id=conversation_id, status=1).order_by("-id")[start : start + page_size]
    msgs = list(reversed(list(qs)))
    sender_ids = list({m.sender_id for m in msgs})
    users = {u.id: u for u in User.objects.filter(id__in=sender_ids)} if sender_ids else {}
    items = []
    for m in msgs:
        u = users.get(m.sender_id)
        items.append({
            "id": m.id,
            "senderId": m.sender_id,
            "nickname": getattr(u, "nickname", None) or f"用户{m.sender_id}",
            "avatarUrl": getattr(u, "avatar_url", None),
            "type": m.type,
            "content": m.content_encrypted or "",
            "createdAt": m.created_at.isoformat() if m.created_at else None,
        })
    return Response(_result(data={"list": items, "hasMore": len(msgs) == page_size}))


@api_view(["POST"])
@permission_classes([AllowAny])
def send_message(request, conversation_id):
    """发送消息。body: { "type": "text", "content": "..." }"""
    user_id = _user_id_from_request(request)
    if not user_id:
        return Response(_result(401, "请先登录"), status=status.HTTP_401_UNAUTHORIZED)
    if not ConversationMember.objects.filter(conversation_id=conversation_id, user_id=user_id).exists():
        return Response(_result(404, "会话不存在"), status=status.HTTP_404_NOT_FOUND)

    msg_type = (request.data.get("type") or "text").strip()[:20]
    content = (request.data.get("content") or "").strip()
    if msg_type == "text" and not content:
        return Response(_result(400, "消息内容不能为空"), status=status.HTTP_400_BAD_REQUEST)
    if msg_type == "image" and not content:
        return Response(_result(400, "图片地址不能为空"), status=status.HTTP_400_BAD_REQUEST)
    if msg_type == "post" and not content:
        return Response(_result(400, "帖子信息不能为空"), status=status.HTTP_400_BAD_REQUEST)

    msg = Message.objects.create(
        conversation_id=conversation_id,
        sender_id=user_id,
        type=msg_type,
        content_encrypted=content[:2000],
        status=1,
    )
    Conversation.objects.filter(id=conversation_id).update(updated_at=msg.created_at)
    u = User.objects.filter(id=user_id).first()
    return Response(_result(data={
        "id": msg.id,
        "senderId": msg.sender_id,
        "nickname": getattr(u, "nickname", None) or f"用户{user_id}",
        "avatarUrl": getattr(u, "avatar_url", None),
        "type": msg.type,
        "content": msg.content_encrypted,
        "createdAt": msg.created_at.isoformat(),
    }))


@api_view(["GET"])
@permission_classes([AllowAny])
def chat_apply_list(request):
    """我收到的聊天申请（待处理）"""
    user_id = _user_id_from_request(request)
    if not user_id:
        return Response(_result(401, "请先登录"), status=status.HTTP_401_UNAUTHORIZED)
    qs = ChatApply.objects.filter(to_user_id=user_id, status="pending").order_by("-created_at")[:50]
    from_ids = list({a.from_user_id for a in qs})
    users = {u.id: u for u in User.objects.filter(id__in=from_ids)} if from_ids else {}
    items = []
    for a in qs:
        u = users.get(a.from_user_id)
        items.append({
            "id": a.id,
            "fromUserId": a.from_user_id,
            "fromNickname": getattr(u, "nickname", None) or f"用户{a.from_user_id}",
            "fromAvatarUrl": getattr(u, "avatar_url", None),
            "createdAt": a.created_at.isoformat() if a.created_at else None,
        })
    return Response(_result(data={"list": items}))


@api_view(["GET"])
@permission_classes([AllowAny])
def group_members(request, conversation_id):
    """群成员列表，仅群聊可用。返回 isOwner 表示当前用户是否为群主"""
    user_id = _user_id_from_request(request)
    if not user_id:
        return Response(_result(401, "请先登录"), status=status.HTTP_401_UNAUTHORIZED)
    conv = Conversation.objects.filter(id=conversation_id, type="group").first()
    if not conv:
        return Response(_result(404, "群聊不存在"), status=status.HTTP_404_NOT_FOUND)
    if not ConversationMember.objects.filter(conversation_id=conversation_id, user_id=user_id).exists():
        return Response(_result(404, "您不在此群"), status=status.HTTP_404_NOT_FOUND)
    grp = ImGroup.objects.filter(conversation_id=conversation_id).first()
    is_owner = grp and grp.owner_id == user_id
    members = list(ConversationMember.objects.filter(conversation_id=conversation_id))
    user_ids = [m.user_id for m in members]
    users = {u.id: u for u in User.objects.filter(id__in=user_ids)}
    items = []
    for m in members:
        u = users.get(m.user_id)
        items.append({
            "userId": m.user_id,
            "nickname": getattr(u, "nickname", None) or f"用户{m.user_id}",
            "avatarUrl": getattr(u, "avatar_url", None),
            "role": m.role or "member",
        })
    return Response(_result(data={"list": items, "isOwner": is_owner}))


@api_view(["GET"])
@permission_classes([AllowAny])
def group_info(request, conversation_id):
    """群聊详情：name, memberCount, isOwner, mute"""
    user_id = _user_id_from_request(request)
    if not user_id:
        return Response(_result(401, "请先登录"), status=status.HTTP_401_UNAUTHORIZED)
    conv = Conversation.objects.filter(id=conversation_id, type="group").first()
    if not conv:
        return Response(_result(404, "群聊不存在"), status=status.HTTP_404_NOT_FOUND)
    cm = ConversationMember.objects.filter(conversation_id=conversation_id, user_id=user_id).first()
    if not cm:
        return Response(_result(404, "您不在此群"), status=status.HTTP_404_NOT_FOUND)
    grp = ImGroup.objects.filter(conversation_id=conversation_id).first()
    member_count = ConversationMember.objects.filter(conversation_id=conversation_id).count()
    is_public = False
    if grp:
        try:
            with connection.cursor() as cur:
                cur.execute("SELECT is_public FROM im_group WHERE conversation_id = %s", [conversation_id])
                row = cur.fetchone()
                if row is not None:
                    is_public = bool(row[0])
        except Exception:
            pass
    return Response(_result(data={
        "name": conv.name or "群聊",
        "memberCount": member_count,
        "isOwner": bool(grp and grp.owner_id == user_id),
        "mute": bool(cm.mute),
        "isPublic": is_public,
    }))


@api_view(["PATCH"])
@permission_classes([AllowAny])
def update_group(request, conversation_id):
    """更新群信息。body: { "name"?: "新群名", "mute"?: true/false }"""
    user_id = _user_id_from_request(request)
    if not user_id:
        return Response(_result(401, "请先登录"), status=status.HTTP_401_UNAUTHORIZED)
    conv = Conversation.objects.filter(id=conversation_id, type="group").first()
    if not conv:
        return Response(_result(404, "群聊不存在"), status=status.HTTP_404_NOT_FOUND)
    cm = ConversationMember.objects.filter(conversation_id=conversation_id, user_id=user_id).first()
    if not cm:
        return Response(_result(404, "您不在此群"), status=status.HTTP_404_NOT_FOUND)
    grp = ImGroup.objects.filter(conversation_id=conversation_id).first()
    is_owner = grp and grp.owner_id == user_id

    name = request.data.get("name")
    if name is not None:
        if not is_owner:
            return Response(_result(403, "仅群主可修改群名"), status=status.HTTP_403_FORBIDDEN)
        name = (str(name) or "").strip()[:64] or "群聊"
        conv.name = name
        conv.save(update_fields=["name", "updated_at"])

    mute = request.data.get("mute")
    if mute is not None:
        cm.mute = 1 if mute else 0
        cm.save(update_fields=["mute"])

    is_public = request.data.get("isPublic")
    if is_public is not None and grp and is_owner:
        try:
            with connection.cursor() as cur:
                cur.execute(
                    "UPDATE im_group SET is_public = %s WHERE conversation_id = %s",
                    [1 if is_public else 0, conversation_id],
                )
        except Exception as e:
            err = str(e)
            if "Unknown column" in err or "is_public" in err.lower():
                return Response(
                    _result(500, "请先执行 migrate_group_public.sql 添加 is_public 字段"),
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )
            raise

    return Response(_result(data={"message": "已更新"}))


@api_view(["POST"])
@permission_classes([AllowAny])
def add_members(request, conversation_id):
    """邀请入群，仅群主。body: { "memberIds": [1, 2, 3] }"""
    user_id = _user_id_from_request(request)
    if not user_id:
        return Response(_result(401, "请先登录"), status=status.HTTP_401_UNAUTHORIZED)
    grp = ImGroup.objects.filter(conversation_id=conversation_id).first()
    if not grp or grp.owner_id != user_id:
        return Response(_result(403, "仅群主可邀请"), status=status.HTTP_403_FORBIDDEN)
    member_ids = request.data.get("memberIds") or []
    if isinstance(member_ids, str):
        try:
            import json
            member_ids = json.loads(member_ids)
        except Exception:
            member_ids = []
    member_ids = [int(x) for x in member_ids if x is not None]
    member_ids = list(dict.fromkeys(member_ids))
    member_ids = [x for x in member_ids if x != user_id]
    existing = set(
        ConversationMember.objects.filter(conversation_id=conversation_id)
        .values_list("user_id", flat=True)
    )
    member_ids = [x for x in member_ids if x not in existing]
    current_count = ConversationMember.objects.filter(conversation_id=conversation_id).count()
    if current_count + len(member_ids) > grp.max_members:
        return Response(_result(400, f"群成员不能超过{grp.max_members}人"), status=status.HTTP_400_BAD_REQUEST)
    for uid in member_ids:
        ConversationMember.objects.get_or_create(
            conversation_id=conversation_id, user_id=uid,
            defaults={"role": "member"},
        )
    return Response(_result(data={"message": f"已邀请{len(member_ids)}人", "added": len(member_ids)}))


@api_view(["POST"])
@permission_classes([AllowAny])
def kick_member(request, conversation_id):
    """踢出群成员，仅群主可操作。body: { "userId": 123 }"""
    user_id = _user_id_from_request(request)
    if not user_id:
        return Response(_result(401, "请先登录"), status=status.HTTP_401_UNAUTHORIZED)
    grp = ImGroup.objects.filter(conversation_id=conversation_id).first()
    if not grp or grp.owner_id != user_id:
        return Response(_result(403, "仅群主可踢人"), status=status.HTTP_403_FORBIDDEN)
    target_id = request.data.get("userId")
    if not target_id:
        return Response(_result(400, "缺少 userId"), status=status.HTTP_400_BAD_REQUEST)
    try:
        target_id = int(target_id)
    except (TypeError, ValueError):
        return Response(_result(400, "userId 无效"), status=status.HTTP_400_BAD_REQUEST)
    if target_id == grp.owner_id:
        return Response(_result(400, "不能踢出群主"), status=status.HTTP_400_BAD_REQUEST)
    deleted = ConversationMember.objects.filter(
        conversation_id=conversation_id,
        user_id=target_id,
    ).delete()
    if not deleted[0]:
        return Response(_result(404, "该用户不在群内"), status=status.HTTP_404_NOT_FOUND)
    return Response(_result(data={"message": "已踢出"}))


@api_view(["POST"])
@permission_classes([AllowAny])
def mark_read(request, conversation_id):
    """进入会话时标记已读，将 last_read_msg_id 更新为当前最新消息 id"""
    user_id = _user_id_from_request(request)
    if not user_id:
        return Response(_result(401, "请先登录"), status=status.HTTP_401_UNAUTHORIZED)
    last_msg = Message.objects.filter(conversation_id=conversation_id, status=1).order_by("-id").first()
    if last_msg:
        ConversationMember.objects.filter(
            conversation_id=conversation_id,
            user_id=user_id,
        ).update(last_read_msg_id=last_msg.id)
    return Response(_result())


@api_view(["POST"])
@permission_classes([AllowAny])
def send_chat_apply(request):
    """发送聊天申请。body: { "toUserId": 123 }"""
    user_id = _user_id_from_request(request)
    if not user_id:
        return Response(_result(401, "请先登录"), status=status.HTTP_401_UNAUTHORIZED)
    to_id = request.data.get("toUserId")
    if not to_id:
        return Response(_result(400, "缺少对方用户ID"), status=status.HTTP_400_BAD_REQUEST)
    try:
        to_id = int(to_id)
    except (TypeError, ValueError):
        return Response(_result(400, "用户ID无效"), status=status.HTTP_400_BAD_REQUEST)
    if to_id == user_id:
        return Response(_result(400, "不能给自己发申请"), status=status.HTTP_400_BAD_REQUEST)
    if not User.objects.filter(id=to_id, status=1).exists():
        return Response(_result(404, "用户不存在"), status=status.HTTP_404_NOT_FOUND)
    if ChatApply.objects.filter(from_user_id=user_id, to_user_id=to_id, status="pending").exists():
        return Response(_result(400, "已发送过申请，请等待对方处理"), status=status.HTTP_400_BAD_REQUEST)
    ChatApply.objects.create(from_user_id=user_id, to_user_id=to_id, status="pending")
    return Response(_result(data={"message": "已发送"}))


@api_view(["POST"])
@permission_classes([AllowAny])
def approve_chat_apply(request, apply_id):
    """同意聊天申请：创建单聊会话并返回"""
    user_id = _user_id_from_request(request)
    if not user_id:
        return Response(_result(401, "请先登录"), status=status.HTTP_401_UNAUTHORIZED)
    try:
        apply = ChatApply.objects.get(id=apply_id, to_user_id=user_id, status="pending")
    except ChatApply.DoesNotExist:
        return Response(_result(404, "申请不存在或已处理"), status=status.HTTP_404_NOT_FOUND)
    apply.status = "approved"
    apply.save(update_fields=["status", "updated_at"])
    c, _ = _get_or_create_single_bulk(apply.from_user_id, apply.to_user_id)
    u = User.objects.filter(id=apply.from_user_id).first()
    title = getattr(u, "nickname", None) or f"用户{apply.from_user_id}"
    return Response(_result(data={"conversationId": c.id, "type": "single", "title": title}))


@api_view(["POST"])
@permission_classes([AllowAny])
def reject_chat_apply(request, apply_id):
    """拒绝聊天申请"""
    user_id = _user_id_from_request(request)
    if not user_id:
        return Response(_result(401, "请先登录"), status=status.HTTP_401_UNAUTHORIZED)
    try:
        apply = ChatApply.objects.get(id=apply_id, to_user_id=user_id, status="pending")
    except ChatApply.DoesNotExist:
        return Response(_result(404, "申请不存在或已处理"), status=status.HTTP_404_NOT_FOUND)
    apply.status = "rejected"
    apply.save(update_fields=["status", "updated_at"])
    return Response(_result(data={"message": "已拒绝"}))


@api_view(["GET"])
@permission_classes([AllowAny])
def joinable_groups(request):
    """可加入的群聊列表（is_public=1 且用户未加入）。需执行 migrate_group_public.sql"""
    user_id = _user_id_from_request(request)
    if not user_id:
        return Response(_result(401, "请先登录"), status=status.HTTP_401_UNAUTHORIZED)
    try:
        with connection.cursor() as c:
            c.execute("""
                SELECT g.conversation_id, c.name, cm.cnt as member_count, g.max_members
                FROM im_group g
                JOIN conversation c ON c.id = g.conversation_id AND c.type = 'group'
                JOIN (SELECT conversation_id, COUNT(*) as cnt FROM conversation_member GROUP BY conversation_id) cm ON cm.conversation_id = g.conversation_id
                WHERE g.is_public = 1 AND cm.cnt < g.max_members
                AND g.conversation_id NOT IN (SELECT conversation_id FROM conversation_member WHERE user_id = %s)
                ORDER BY cm.cnt DESC
            """, [user_id])
            rows = c.fetchall()
    except Exception:
        return Response(_result(data={"list": []}))
    items = [{"conversationId": r[0], "name": r[1] or "群聊", "memberCount": r[2], "maxMembers": r[3]} for r in rows]
    return Response(_result(data={"list": items}))


@api_view(["POST"])
@permission_classes([AllowAny])
def apply_join_group(request, conversation_id):
    """申请加入群聊。需执行 migrate_group_public.sql 创建 group_join_apply 表"""
    user_id = _user_id_from_request(request)
    if not user_id:
        return Response(_result(401, "请先登录"), status=status.HTTP_401_UNAUTHORIZED)
    grp = ImGroup.objects.filter(conversation_id=conversation_id).first()
    if not grp:
        return Response(_result(404, "群聊不存在"), status=status.HTTP_404_NOT_FOUND)
    if ConversationMember.objects.filter(conversation_id=conversation_id, user_id=user_id).exists():
        return Response(_result(400, "您已是群成员"))
    try:
        with connection.cursor() as c:
            c.execute("SELECT is_public FROM im_group WHERE conversation_id = %s", [conversation_id])
            row = c.fetchone()
            if not row or row[0] != 1:
                return Response(_result(400, "该群暂不开放加入"))
            c.execute("SELECT 1 FROM group_join_apply WHERE user_id = %s AND conversation_id = %s AND status = 'pending'", [user_id, conversation_id])
            if c.fetchone():
                return Response(_result(400, "已提交过申请，请等待群主处理"))
            c.execute("INSERT INTO group_join_apply (user_id, conversation_id, status) VALUES (%s, %s, 'pending')", [user_id, conversation_id])
    except Exception as e:
        return Response(_result(500, f"操作失败: {e}"), status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    return Response(_result(data={"message": "已提交申请"}))


@api_view(["GET"])
@permission_classes([AllowAny])
def group_join_apply_list(request):
    """群主收到的入群申请（我拥有的群，待处理）。需执行 migrate_group_public.sql"""
    user_id = _user_id_from_request(request)
    if not user_id:
        return Response(_result(401, "请先登录"), status=status.HTTP_401_UNAUTHORIZED)
    try:
        with connection.cursor() as c:
            c.execute("""
                SELECT gja.id, gja.user_id, gja.conversation_id, gja.created_at,
                       c.name as group_name
                FROM group_join_apply gja
                JOIN im_group g ON g.conversation_id = gja.conversation_id AND g.owner_id = %s
                JOIN conversation c ON c.id = gja.conversation_id
                WHERE gja.status = 'pending'
                ORDER BY gja.created_at DESC
                LIMIT 50
            """, [user_id])
            rows = c.fetchall()
    except Exception:
        return Response(_result(data={"list": []}))
    if not rows:
        return Response(_result(data={"list": []}))
    from_ids = list({r[1] for r in rows})
    users = {u.id: u for u in User.objects.filter(id__in=from_ids)}
    items = []
    for r in rows:
        apply_id, from_user_id, conv_id, created_at, group_name = r[0], r[1], r[2], r[3], r[4]
        u = users.get(from_user_id)
        items.append({
            "id": apply_id,
            "type": "group",
            "fromUserId": from_user_id,
            "fromNickname": getattr(u, "nickname", None) or f"用户{from_user_id}",
            "fromAvatarUrl": getattr(u, "avatar_url", None),
            "conversationId": conv_id,
            "groupName": group_name or "群聊",
            "createdAt": created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at),
        })
    return Response(_result(data={"list": items}))


@api_view(["POST"])
@permission_classes([AllowAny])
def approve_group_join_apply(request, apply_id):
    """群主同意入群申请，将申请人加入群"""
    user_id = _user_id_from_request(request)
    if not user_id:
        return Response(_result(401, "请先登录"), status=status.HTTP_401_UNAUTHORIZED)
    try:
        with connection.cursor() as c:
            c.execute("""
                SELECT gja.user_id, gja.conversation_id
                FROM group_join_apply gja
                JOIN im_group g ON g.conversation_id = gja.conversation_id AND g.owner_id = %s
                WHERE gja.id = %s AND gja.status = 'pending'
            """, [user_id, apply_id])
            row = c.fetchone()
    except Exception:
        return Response(_result(404, "申请不存在或已处理"), status=status.HTTP_404_NOT_FOUND)
    if not row:
        return Response(_result(404, "申请不存在或已处理"), status=status.HTTP_404_NOT_FOUND)
    target_user_id, conversation_id = row[0], row[1]
    # 加入群
    ConversationMember.objects.get_or_create(
        conversation_id=conversation_id, user_id=target_user_id,
        defaults={"role": "member"},
    )
    # 更新申请状态
    with connection.cursor() as c:
        c.execute("UPDATE group_join_apply SET status = 'approved' WHERE id = %s", [apply_id])
    conv = Conversation.objects.filter(id=conversation_id).first()
    group_name = (conv.name or "群聊") if conv else "群聊"
    return Response(_result(data={"conversationId": conversation_id, "type": "group", "title": group_name}))


@api_view(["POST"])
@permission_classes([AllowAny])
def reject_group_join_apply(request, apply_id):
    """群主拒绝入群申请"""
    user_id = _user_id_from_request(request)
    if not user_id:
        return Response(_result(401, "请先登录"), status=status.HTTP_401_UNAUTHORIZED)
    try:
        with connection.cursor() as c:
            c.execute("""
                UPDATE group_join_apply gja
                JOIN im_group g ON g.conversation_id = gja.conversation_id AND g.owner_id = %s
                SET gja.status = 'rejected'
                WHERE gja.id = %s AND gja.status = 'pending'
            """, [user_id, apply_id])
            updated = c.rowcount
    except Exception:
        return Response(_result(404, "申请不存在或已处理"), status=status.HTTP_404_NOT_FOUND)
    if updated == 0:
        return Response(_result(404, "申请不存在或已处理"), status=status.HTTP_404_NOT_FOUND)
    return Response(_result(data={"message": "已拒绝"}))


@api_view(["GET"])
@permission_classes([AllowAny])
def master_consult_list(request):
    """名师咨询会话列表：与 名师(is_master=1) 的单聊。需执行 migrate_teacher.sql"""
    user_id = _user_id_from_request(request)
    if not user_id:
        return Response(_result(401, "请先登录"), status=status.HTTP_401_UNAUTHORIZED)
    try:
        with connection.cursor() as c:
            c.execute("""
                SELECT c.id, c.updated_at, cm_other.user_id as peer_user_id
                FROM conversation c
                JOIN conversation_member cm_me ON cm_me.conversation_id = c.id AND cm_me.user_id = %s
                JOIN conversation_member cm_other ON cm_other.conversation_id = c.id AND cm_other.user_id != %s
                JOIN user_profile up ON up.user_id = cm_other.user_id AND up.is_master = 1
                WHERE c.type = 'single'
                ORDER BY c.updated_at DESC
            """, [user_id, user_id])
            rows = c.fetchall()
    except Exception:
        return Response(_result(data={"list": []}))
    if not rows:
        return Response(_result(data={"list": []}))
    conv_ids = [r[0] for r in rows]
    last_msg_map = {}
    for m in Message.objects.filter(conversation_id__in=conv_ids).values("conversation_id").annotate(mid=Max("id")):
        last_msg_map[m["conversation_id"]] = m["mid"]
    last_msgs = {}
    if last_msg_map:
        for msg in Message.objects.filter(id__in=last_msg_map.values()):
            last_msgs[msg.id] = msg
    last_read_map = {cm.conversation_id: cm.last_read_msg_id or 0 for cm in ConversationMember.objects.filter(conversation_id__in=conv_ids, user_id=user_id)}
    peer_ids = list({r[2] for r in rows})
    users = {u.id: u for u in User.objects.filter(id__in=peer_ids)}
    items = []
    for r in rows:
        conv_id, updated_at, peer_id = r[0], r[1], r[2]
        u = users.get(peer_id)
        peer_name = getattr(u, "nickname", None) or f"名师{peer_id}"
        last_id = last_msg_map.get(conv_id)
        last_msg = last_msgs.get(last_id) if last_id else None
        last_read = last_read_map.get(conv_id, 0)
        unread = Message.objects.filter(conversation_id=conv_id, id__gt=last_read).exclude(sender_id=user_id).count()
        items.append({
            "conversationId": conv_id,
            "type": "single",
            "title": peer_name,
            "peerUserId": peer_id,
            "lastMessage": "[图片]" if last_msg and last_msg.type == "image" else (last_msg.content_encrypted[:50] if last_msg and last_msg.content_encrypted else ""),
            "lastMessageAt": last_msg.created_at.isoformat() if last_msg and last_msg.created_at else None,
            "unreadCount": unread,
        })
    return Response(_result(data={"list": items}))
