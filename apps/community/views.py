"""
社区：信息流（关注/同城/推荐）、帖子 CRUD、话题、点赞评论收藏
"""
import json
import re
from django.db import connection
from django.db.models import Q, F, Sum
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.account.models import User
from apps.account.session_store import get_user_id_by_token
from apps.system.views import get_ip_location_for_request
from .models import Topic, Post, Comment, PostLike, PostFavorite, UserFollow, Report, Notification


def _result(code=0, message="success", data=None):
    return {"code": code, "message": message, "data": data}


def _create_notification(user_id, ntype, from_user_id, post_id, comment_id=None, content_snippet=None):
    """给帖子作者发互动通知，不给自己发"""
    if user_id == from_user_id:
        return
    snippet = (content_snippet or "")[:255]
    Notification.objects.create(
        user_id=user_id,
        type=ntype,
        from_user_id=from_user_id,
        post_id=post_id,
        comment_id=comment_id,
        content_snippet=snippet or None,
        read=0,
    )


def _user_id_from_request(request):
    auth = request.META.get("HTTP_AUTHORIZATION") or ""
    if auth.startswith("Bearer "):
        token = auth[7:].strip()
        return get_user_id_by_token(token)
    return None


def _topics_for_ids(ids):
    if not ids:
        return []
    qs = Topic.objects.filter(id__in=ids, status=1)
    return [{"id": t.id, "name": t.name} for t in qs]


def _post_item(p, u, topic_list, liked=False, favorited=False):
    media_urls = []
    if p.media_urls_json:
        try:
            media_urls = json.loads(p.media_urls_json) if isinstance(p.media_urls_json, str) else p.media_urls_json
        except Exception:
            pass
    media_cover_urls = []
    if getattr(p, "media_cover_urls_json", None):
        try:
            media_cover_urls = json.loads(p.media_cover_urls_json) if isinstance(p.media_cover_urls_json, str) else p.media_cover_urls_json
        except Exception:
            pass
    tags = []
    if getattr(p, "tags_json", None):
        try:
            tags = json.loads(p.tags_json) if isinstance(p.tags_json, str) else p.tags_json
        except Exception:
            pass
    allow_comment = getattr(p, "allow_comment", 1)
    return {
        "id": p.id,
        "userId": p.user_id,
        "nickname": getattr(u, "nickname", None) or f"用户{p.user_id}",
        "avatarUrl": getattr(u, "avatar_url", None),
        "content": p.content or "",
        "mediaType": p.media_type,
        "mediaUrls": media_urls,
        "mediaCoverUrls": media_cover_urls if isinstance(media_cover_urls, list) else [],
        "allowComment": bool(allow_comment),
        "locationCode": getattr(p, "location_code", None) or None,
        "topicIds": topic_list and [t["id"] for t in topic_list] or [],
        "topics": topic_list or [],
        "tags": tags if isinstance(tags, list) else [],
        "likeCount": p.like_count,
        "commentCount": p.comment_count,
        "shareCount": p.share_count,
        "liked": liked,
        "favorited": favorited,
        "createdAt": p.created_at.isoformat() if p.created_at else None,
    }


@api_view(["GET"])
@permission_classes([AllowAny])
def topic_list(request):
    """话题列表，按热度/排序"""
    qs = Topic.objects.filter(status=1).order_by("-heat_score", "sort_order")[:50]
    data = [
        {"id": t.id, "name": t.name, "coverUrl": t.cover_url, "heatScore": t.heat_score}
        for t in qs
    ]
    return Response(_result(data=data))


@api_view(["GET"])
@permission_classes([AllowAny])
def feed(request):
    """信息流：tab=follow|local|recommend，page, page_size"""
    tab = (request.GET.get("tab") or "recommend").strip().lower()
    page = max(1, int(request.GET.get("page") or 1))
    page_size = min(30, max(1, int(request.GET.get("page_size") or 20)))
    user_id = _user_id_from_request(request)

    qs = Post.objects.filter(status=1).order_by("-created_at")
    if tab in ("follow", "following") and user_id:
        # 关注：只显示当前账号关注的用户发的帖
        try:
            ids = list(
                UserFollow.objects.filter(user_id=user_id).values_list("target_user_id", flat=True)
            )
            if ids:
                qs = qs.filter(user_id__in=ids)
            else:
                qs = qs.none()
        except Exception:
            qs = qs.none()
    elif tab == "local":
        # 同城：显示与当前请求 IP 定位相同的用户发的帖（post.location_code 含 IP 属地中的地区名）
        loc = get_ip_location_for_request(request)
        if not loc or loc in ("本地", "内网", "未知"):
            qs = qs.none()
        else:
            parts = [p.strip() for p in loc.replace("|", " ").split() if len(p.strip()) > 1]
            if parts:
                match_q = Q(location_code__icontains=parts[0])
                for p in parts[1:4]:
                    match_q = match_q | Q(location_code__icontains=p)
                qs = qs.filter(
                    Q(location_code__isnull=False)
                    & ~Q(location_code="")
                    & match_q
                )
            else:
                qs = qs.none()
    start = (page - 1) * page_size
    posts = list(qs[start : start + page_size])
    user_ids = list({p.user_id for p in posts})
    users = {u.id: u for u in User.objects.filter(id__in=user_ids)} if user_ids else {}
    liked_set = set()
    favorited_set = set()
    if user_id and posts:
        post_ids = [p.id for p in posts]
        liked_set = set(PostLike.objects.filter(user_id=user_id, post_id__in=post_ids).values_list("post_id", flat=True))
        favorited_set = set(PostFavorite.objects.filter(user_id=user_id, post_id__in=post_ids).values_list("post_id", flat=True))
    all_topic_ids = set()
    for p in posts:
        if p.topic_ids_json:
            try:
                ids = json.loads(p.topic_ids_json) if isinstance(p.topic_ids_json, str) else p.topic_ids_json
                all_topic_ids.update(ids)
            except Exception:
                pass
    topics_map = {t.id: {"id": t.id, "name": t.name} for t in Topic.objects.filter(id__in=all_topic_ids)} if all_topic_ids else {}
    items = []
    for p in posts:
        u = users.get(p.user_id)
        topic_ids = []
        if p.topic_ids_json:
            try:
                topic_ids = json.loads(p.topic_ids_json) if isinstance(p.topic_ids_json, str) else p.topic_ids_json
            except Exception:
                pass
        topic_list = [topics_map[i] for i in topic_ids if i in topics_map]
        items.append(_post_item(p, u, topic_list, liked=(p.id in liked_set), favorited=(p.id in favorited_set)))
    return Response(_result(data={"list": items, "hasMore": len(posts) == page_size}))


@api_view(["POST"])
@permission_classes([AllowAny])
def create_post(request):
    """发帖"""
    user_id = _user_id_from_request(request)
    if not user_id:
        return Response(_result(400, "请先登录"), status=status.HTTP_400_BAD_REQUEST)
    content = (request.data.get("content") or "").strip()
    content = re.sub(r"[\r\n\u2028\u2029\s]+$", "", content)  # 去除文末换行及空白
    if not content:
        return Response(_result(400, "请输入内容"), status=status.HTTP_400_BAD_REQUEST)
    topic_ids = request.data.get("topicIds") or []
    if isinstance(topic_ids, str):
        try:
            topic_ids = json.loads(topic_ids)
        except Exception:
            topic_ids = []
    tags = request.data.get("tags") or []
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except Exception:
            tags = []
    if not isinstance(tags, list):
        tags = []
    tags = [str(t).strip()[:20] for t in tags if t][:10]
    media_urls = request.data.get("mediaUrls") or []
    if isinstance(media_urls, str):
        try:
            media_urls = json.loads(media_urls)
        except Exception:
            media_urls = []
    media_cover_urls = request.data.get("mediaCoverUrls") or []
    if isinstance(media_cover_urls, str):
        try:
            media_cover_urls = json.loads(media_cover_urls)
        except Exception:
            media_cover_urls = []
    if not isinstance(media_cover_urls, list):
        media_cover_urls = []
    media_type = "video" if request.data.get("mediaType") == "video" else "image_text"
    vis = request.data.get("visibility")
    visibility = 2 if vis == 2 else 1
    allow_comment = 0 if request.data.get("allowComment") is False else 1
    location_code = (
        request.data.get("locationCode") or request.data.get("location") or request.data.get("locationName") or ""
    ).strip() or None
    location_code = location_code[:32] if location_code else None
    if not location_code:
        loc = get_ip_location_for_request(request)
        location_code = loc[:32] if loc else None
    post = Post(
        user_id=user_id,
        content=content,
        media_type=media_type,
        media_urls_json=json.dumps(media_urls) if media_urls else None,
        media_cover_urls_json=json.dumps(media_cover_urls) if media_cover_urls else None,
        topic_ids_json=json.dumps(topic_ids) if topic_ids else None,
        tags_json=json.dumps(tags) if tags else None,
        location_code=location_code,
        status=1,
        visibility=visibility,
        allow_comment=allow_comment,
    )
    post.save()
    return Response(_result(data={"id": post.id, "createdAt": post.created_at.isoformat()}))


@api_view(["GET"])
@permission_classes([AllowAny])
def post_detail(request, post_id):
    """帖子详情"""
    try:
        p = Post.objects.get(id=post_id, status=1)
    except Post.DoesNotExist:
        return Response(_result(404, "帖子不存在"), status=status.HTTP_404_NOT_FOUND)
    try:
        u = User.objects.get(id=p.user_id)
    except User.DoesNotExist:
        u = None
    topic_ids = []
    if p.topic_ids_json:
        try:
            topic_ids = json.loads(p.topic_ids_json)
        except Exception:
            pass
    topic_list = _topics_for_ids(topic_ids)
    user_id = _user_id_from_request(request)
    liked = bool(user_id and PostLike.objects.filter(user_id=user_id, post_id=post_id).exists())
    favorited = bool(user_id and PostFavorite.objects.filter(user_id=user_id, post_id=post_id).exists())
    data = _post_item(p, u, topic_list, liked=liked, favorited=favorited)
    data["isOwner"] = bool(user_id and p.user_id == user_id)
    return Response(_result(data=data))


@api_view(["GET"])
@permission_classes([AllowAny])
def comment_list(request, post_id):
    """评论列表，支持楼中楼"""
    page = max(1, int(request.GET.get("page") or 1))
    page_size = min(50, max(1, int(request.GET.get("page_size") or 20)))
    start = (page - 1) * page_size
    qs = Comment.objects.filter(post_id=post_id, status=1).order_by("created_at")[start : start + page_size]
    user_ids = list({c.user_id for c in qs})
    users = {u.id: u for u in User.objects.filter(id__in=user_ids)} if user_ids else {}
    items = [
        {
            "id": c.id,
            "userId": c.user_id,
            "nickname": (getattr(users.get(c.user_id), "nickname", None) if users.get(c.user_id) else None) or f"用户{c.user_id}",
            "avatarUrl": getattr(users.get(c.user_id), "avatar_url", None) if users.get(c.user_id) else None,
            "parentId": c.parent_id,
            "content": c.content,
            "likeCount": c.like_count,
            "createdAt": c.created_at.isoformat() if c.created_at else None,
        }
        for c in qs
    ]
    return Response(_result(data={"list": items, "hasMore": len(items) == page_size}))


@api_view(["POST"])
@permission_classes([AllowAny])
def add_comment(request, post_id):
    """发表评论"""
    user_id = _user_id_from_request(request)
    if not user_id:
        return Response(_result(400, "请先登录"), status=status.HTTP_400_BAD_REQUEST)
    content = (request.data.get("content") or "").strip()
    if not content:
        return Response(_result(400, "请输入评论内容"), status=status.HTTP_400_BAD_REQUEST)
    parent_id = request.data.get("parentId")
    p = Post.objects.filter(id=post_id, status=1).first()
    if not p:
        return Response(_result(404, "帖子不存在"), status=status.HTTP_404_NOT_FOUND)
    if getattr(p, "allow_comment", 1) == 0:
        return Response(_result(403, "作者已关闭评论"), status=status.HTTP_403_FORBIDDEN)
    c = Comment(post_id=post_id, user_id=user_id, parent_id=parent_id, content=content, status=1)
    c.save()
    Post.objects.filter(id=post_id).update(comment_count=F("comment_count") + 1)
    if p and p.user_id != user_id:
        _create_notification(p.user_id, "comment", user_id, post_id, comment_id=c.id, content_snippet=content[:100])
    return Response(_result(data={"id": c.id, "createdAt": c.created_at.isoformat()}))


@api_view(["POST"])
@permission_classes([AllowAny])
def post_like(request, post_id):
    """点赞/取消点赞（post_like 为联合主键表无 id，用 raw SQL 做存在判断与增删）"""
    user_id = _user_id_from_request(request)
    if not user_id:
        return Response(_result(400, "请先登录"), status=status.HTTP_400_BAD_REQUEST)
    if not Post.objects.filter(id=post_id, status=1).exists():
        return Response(_result(404, "帖子不存在"), status=status.HTTP_404_NOT_FOUND)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM post_like WHERE user_id = %s AND post_id = %s LIMIT 1",
            [user_id, post_id],
        )
        exists = cursor.fetchone() is not None
    if exists:
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM post_like WHERE user_id = %s AND post_id = %s",
                [user_id, post_id],
            )
        Post.objects.filter(id=post_id).update(like_count=F("like_count") - 1)
        return Response(_result(data={"liked": False, "likeCount": max(0, Post.objects.get(id=post_id).like_count)}))
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO post_like (user_id, post_id) VALUES (%s, %s)",
            [user_id, post_id],
        )
    Post.objects.filter(id=post_id).update(like_count=F("like_count") + 1)
    p = Post.objects.filter(id=post_id).first()
    if p and p.user_id != user_id:
        _create_notification(p.user_id, "like", user_id, post_id)
    return Response(_result(data={"liked": True, "likeCount": Post.objects.get(id=post_id).like_count}))


@api_view(["POST"])
@permission_classes([AllowAny])
def post_favorite(request, post_id):
    """收藏/取消收藏（post_favorite 为联合主键表无 id，用 raw SQL）"""
    user_id = _user_id_from_request(request)
    if not user_id:
        return Response(_result(400, "请先登录"), status=status.HTTP_400_BAD_REQUEST)
    if not Post.objects.filter(id=post_id, status=1).exists():
        return Response(_result(404, "帖子不存在"), status=status.HTTP_404_NOT_FOUND)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM post_favorite WHERE user_id = %s AND post_id = %s LIMIT 1",
            [user_id, post_id],
        )
        exists = cursor.fetchone() is not None
    if exists:
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM post_favorite WHERE user_id = %s AND post_id = %s",
                [user_id, post_id],
            )
        return Response(_result(data={"favorited": False}))
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO post_favorite (user_id, post_id) VALUES (%s, %s)",
            [user_id, post_id],
        )
    p = Post.objects.filter(id=post_id).first()
    if p and p.user_id != user_id:
        _create_notification(p.user_id, "favorite", user_id, post_id)
    return Response(_result(data={"favorited": True}))


@api_view(["GET"])
@permission_classes([AllowAny])
def topic_feed(request, topic_id):
    """话题下的帖子列表"""
    if not Topic.objects.filter(id=topic_id, status=1).exists():
        return Response(_result(404, "话题不存在"), status=status.HTTP_404_NOT_FOUND)
    page = max(1, int(request.GET.get("page") or 1))
    page_size = min(30, max(1, int(request.GET.get("page_size") or 20)))
    user_id = _user_id_from_request(request)
    # 帖子 topic_ids_json 为 JSON 数组如 [1,2]，精确匹配 topic_id
    sid = str(topic_id)
    qs = Post.objects.filter(status=1).filter(
        Q(topic_ids_json__contains=f"[{sid},") |
        Q(topic_ids_json__contains=f",{sid}]") |
        Q(topic_ids_json__contains=f",{sid},") |
        Q(topic_ids_json__contains=f"[{sid}]")
    ).order_by("-created_at")
    start = (page - 1) * page_size
    posts = list(qs[start : start + page_size])
    user_ids = list({p.user_id for p in posts})
    users = {u.id: u for u in User.objects.filter(id__in=user_ids)} if user_ids else {}
    liked_set = set(PostLike.objects.filter(user_id=user_id, post_id__in=[p.id for p in posts]).values_list("post_id", flat=True)) if user_id and posts else set()
    favorited_set = set(PostFavorite.objects.filter(user_id=user_id, post_id__in=[p.id for p in posts]).values_list("post_id", flat=True)) if user_id and posts else set()
    topic_list = _topics_for_ids([topic_id])
    items = []
    for p in posts:
        u = users.get(p.user_id)
        t_ids = []
        if p.topic_ids_json:
            try:
                t_ids = json.loads(p.topic_ids_json) if isinstance(p.topic_ids_json, str) else p.topic_ids_json
            except Exception:
                pass
        tl = _topics_for_ids(t_ids)
        items.append(_post_item(p, u, tl, liked=(p.id in liked_set), favorited=(p.id in favorited_set)))
    return Response(_result(data={"list": items, "hasMore": len(posts) == page_size}))


def _get_user_code(user_id):
    """获取用户的 8 位 user_code"""
    try:
        with connection.cursor() as c:
            c.execute("SELECT user_code FROM user WHERE id = %s", [user_id])
            row = c.fetchone()
            return (row[0] or "").strip() if row and row[0] else str(user_id).zfill(8)
    except Exception:
        return str(user_id).zfill(8)


@api_view(["GET"])
@permission_classes([AllowAny])
def user_search(request):
    """用户搜索：user_code 精确唯一；nickname 模糊可多结果"""
    keyword = (request.GET.get("keyword") or "").strip()[:32]
    if not keyword:
        return Response(_result(data={"list": []}))
    page = max(1, int(request.GET.get("page") or 1))
    page_size = min(30, max(1, int(request.GET.get("page_size") or 20)))
    items = []
    if keyword.isdigit() and len(keyword) == 8:
        u = User.objects.filter(status=1, user_code=keyword).first()
        if u:
            items = [{"userId": u.id, "userCode": getattr(u, "user_code", None) or _get_user_code(u.id), "nickname": u.nickname or f"用户{u.id}", "avatarUrl": u.avatar_url}]
    else:
        qs = User.objects.filter(status=1).filter(Q(nickname__icontains=keyword)).order_by("-id")[(page - 1) * page_size : page * page_size]
        items = [{"userId": u.id, "userCode": getattr(u, "user_code", None) or _get_user_code(u.id), "nickname": u.nickname or f"用户{u.id}", "avatarUrl": u.avatar_url} for u in qs]
    return Response(_result(data={"list": items, "hasMore": len(items) == page_size}))


def _get_user_profile_ext(user_id):
    """从 user_profile 表读取 intro、birth_date、birth_time"""
    try:
        with connection.cursor() as c:
            c.execute(
                "SELECT intro, birth_date, birth_time FROM user_profile WHERE user_id = %s",
                [user_id],
            )
            row = c.fetchone()
    except Exception:
        with connection.cursor() as c:
            c.execute("SELECT intro, birth_date FROM user_profile WHERE user_id = %s", [user_id])
            row = c.fetchone()
    if row:
        birth_time = str(row[2]).strip() if len(row) > 2 and row[2] else None
        return {
            "intro": row[0] or "",
            "birthDate": row[1].strftime("%Y-%m-%d") if row[1] else None,
            "birthTime": birth_time,
        }
    return {"intro": "", "birthDate": None, "birthTime": None}


@api_view(["GET"])
@permission_classes([AllowAny])
def user_by_code(request, user_code):
    """根据 8 位 user_code 获取用户 id，用于跳转主页"""
    u = User.objects.filter(status=1, user_code=user_code).first()
    if not u:
        return Response(_result(404, "用户不存在"), status=status.HTTP_404_NOT_FOUND)
    return Response(_result(data={"userId": u.id, "userCode": getattr(u, "user_code", None) or _get_user_code(u.id)}))


@api_view(["GET"])
@permission_classes([AllowAny])
def user_profile(request, user_id):
    """用户公开资料（查看他人主页）"""
    try:
        u = User.objects.get(id=user_id, status=1)
    except User.DoesNotExist:
        return Response(_result(404, "用户不存在"), status=status.HTTP_404_NOT_FOUND)
    current_id = _user_id_from_request(request)
    following = bool(current_id and UserFollow.objects.filter(user_id=current_id, target_user_id=user_id).exists())
    prof = _get_user_profile_ext(user_id)
    follow_count = UserFollow.objects.filter(user_id=user_id).count()
    follower_count = UserFollow.objects.filter(target_user_id=user_id).count()
    post_count = Post.objects.filter(user_id=user_id, status=1).count()
    like_count = Post.objects.filter(user_id=user_id, status=1).aggregate(s=Sum("like_count"))["s"] or 0
    return Response(_result(data={
        "userId": u.id,
        "userCode": getattr(u, "user_code", None) or _get_user_code(u.id),
        "nickname": u.nickname or f"用户{u.id}",
        "avatarUrl": u.avatar_url,
        "gender": getattr(u, "gender", None),
        "following": following,
        "intro": prof["intro"],
        "birthDate": prof["birthDate"],
        "birthTime": prof.get("birthTime"),
        "followCount": follow_count,
        "followerCount": follower_count,
        "postCount": post_count,
        "likeCount": like_count,
    }))


@api_view(["GET"])
@permission_classes([AllowAny])
def user_posts(request, user_id):
    """某用户发布的帖子列表（公开主页时间流）"""
    if not User.objects.filter(id=user_id, status=1).exists():
        return Response(_result(404, "用户不存在"), status=status.HTTP_404_NOT_FOUND)
    page = max(1, int(request.GET.get("page") or 1))
    page_size = min(30, max(1, int(request.GET.get("page_size") or 20)))
    current_id = _user_id_from_request(request)
    qs = Post.objects.filter(user_id=user_id, status=1).order_by("-created_at")
    start = (page - 1) * page_size
    posts = list(qs[start : start + page_size])
    users = {user_id: User.objects.get(id=user_id)} if posts else {}
    liked_set = set(PostLike.objects.filter(user_id=current_id, post_id__in=[p.id for p in posts]).values_list("post_id", flat=True)) if current_id and posts else set()
    favorited_set = set(PostFavorite.objects.filter(user_id=current_id, post_id__in=[p.id for p in posts]).values_list("post_id", flat=True)) if current_id and posts else set()
    all_topic_ids = set()
    for p in posts:
        if p.topic_ids_json:
            try:
                ids = json.loads(p.topic_ids_json) if isinstance(p.topic_ids_json, str) else p.topic_ids_json
                all_topic_ids.update(ids)
            except Exception:
                pass
    topics_map = {t.id: {"id": t.id, "name": t.name} for t in Topic.objects.filter(id__in=all_topic_ids)} if all_topic_ids else {}
    items = []
    for p in posts:
        u = users.get(p.user_id)
        t_ids = []
        if p.topic_ids_json:
            try:
                t_ids = json.loads(p.topic_ids_json) if isinstance(p.topic_ids_json, str) else p.topic_ids_json
            except Exception:
                pass
        tl = [topics_map[i] for i in t_ids if i in topics_map]
        items.append(_post_item(p, u, tl, liked=(p.id in liked_set), favorited=(p.id in favorited_set)))
    return Response(_result(data={"list": items, "hasMore": len(posts) == page_size}))


@api_view(["POST"])
@permission_classes([AllowAny])
def follow_toggle(request, target_user_id):
    """关注/取关（user_follow 为联合主键表无 id，用 raw SQL）"""
    user_id = _user_id_from_request(request)
    if not user_id:
        return Response(_result(400, "请先登录"), status=status.HTTP_400_BAD_REQUEST)
    if target_user_id == user_id:
        return Response(_result(400, "不能关注自己"), status=status.HTTP_400_BAD_REQUEST)
    if not User.objects.filter(id=target_user_id, status=1).exists():
        return Response(_result(404, "用户不存在"), status=status.HTTP_404_NOT_FOUND)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM user_follow WHERE user_id = %s AND target_user_id = %s LIMIT 1",
            [user_id, target_user_id],
        )
        exists = cursor.fetchone() is not None
    if exists:
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM user_follow WHERE user_id = %s AND target_user_id = %s",
                [user_id, target_user_id],
            )
        return Response(_result(data={"following": False}))
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO user_follow (user_id, target_user_id) VALUES (%s, %s)",
            [user_id, target_user_id],
        )
    return Response(_result(data={"following": True}))


@api_view(["GET"])
@permission_classes([AllowAny])
def is_following(request, user_id):
    """当前用户是否已关注某用户"""
    current_id = _user_id_from_request(request)
    if not current_id:
        return Response(_result(data={"following": False}))
    following = UserFollow.objects.filter(user_id=current_id, target_user_id=user_id).exists()
    return Response(_result(data={"following": following}))


@api_view(["GET"])
@permission_classes([AllowAny])
def my_following_list(request):
    """我关注的人列表，用于建群选人等"""
    user_id = _user_id_from_request(request)
    if not user_id:
        return Response(_result(401, "请先登录"), status=status.HTTP_401_UNAUTHORIZED)
    with connection.cursor() as cursor:
        cursor.execute("SELECT target_user_id FROM user_follow WHERE user_id = %s", [user_id])
        target_ids = [r[0] for r in cursor.fetchall()]
    if not target_ids:
        return Response(_result(data={"list": []}))
    users = list(User.objects.filter(id__in=target_ids, status=1))
    items = []
    for u in users:
        prof = _get_user_profile_ext(u.id)
        items.append({
            "userId": u.id,
            "userCode": getattr(u, "user_code", None) or _get_user_code(u.id),
            "nickname": u.nickname or f"用户{u.id}",
            "avatarUrl": u.avatar_url,
            "intro": prof.get("intro") or "暂无介绍",
        })
    return Response(_result(data={"list": items}))


@api_view(["GET"])
@permission_classes([AllowAny])
def my_followers_list(request):
    """我的粉丝列表（关注我的人）"""
    user_id = _user_id_from_request(request)
    if not user_id:
        return Response(_result(401, "请先登录"), status=status.HTTP_401_UNAUTHORIZED)
    with connection.cursor() as cursor:
        cursor.execute("SELECT user_id FROM user_follow WHERE target_user_id = %s", [user_id])
        follower_ids = [r[0] for r in cursor.fetchall()]
    if not follower_ids:
        return Response(_result(data={"list": []}))
    users = list(User.objects.filter(id__in=follower_ids, status=1))
    items = []
    for u in users:
        prof = _get_user_profile_ext(u.id)
        items.append({
            "userId": u.id,
            "userCode": getattr(u, "user_code", None) or _get_user_code(u.id),
            "nickname": u.nickname or f"用户{u.id}",
            "avatarUrl": u.avatar_url,
            "intro": prof.get("intro") or "暂无介绍",
        })
    return Response(_result(data={"list": items}))


@api_view(["GET"])
@permission_classes([AllowAny])
def masters_list(request):
    """认证通过的名师列表（is_master=1）"""
    try:
        with connection.cursor() as c:
            c.execute(
                """
                SELECT u.id, u.nickname, u.avatar_url, up.intro
                FROM user u
                INNER JOIN user_profile up ON up.user_id = u.id
                WHERE u.status = 1 AND up.is_master = 1
                ORDER BY u.id DESC
                LIMIT 50
                """
            )
            rows = c.fetchall()
    except Exception:
        try:
            with connection.cursor() as c:
                c.execute(
                    "SELECT u.id, u.nickname, u.avatar_url FROM user u "
                    "INNER JOIN user_profile up ON up.user_id = u.id "
                    "WHERE u.status = 1 AND up.is_master = 1 ORDER BY u.id DESC LIMIT 50"
                )
                rows = c.fetchall()
        except Exception:
            rows = []
    items = []
    for r in rows:
        uid = r[0]
        items.append({
            "userId": uid,
            "userCode": _get_user_code(uid),
            "nickname": r[1] or f"名师{uid}",
            "avatarUrl": r[2] if len(r) > 2 else None,
            "intro": r[3] if len(r) > 3 else "认证名师",
        })
    return Response(_result(data={"list": items}))


@api_view(["POST"])
@permission_classes([AllowAny])
def report_create(request):
    """举报（占位：落库待后台处理）"""
    user_id = _user_id_from_request(request)
    if not user_id:
        return Response(_result(400, "请先登录"), status=status.HTTP_400_BAD_REQUEST)
    target_type = (request.data.get("targetType") or "post").strip()[:20]
    target_id = request.data.get("targetId")
    if target_id is None:
        return Response(_result(400, "缺少举报对象"), status=status.HTTP_400_BAD_REQUEST)
    try:
        target_id = int(target_id)
    except (TypeError, ValueError):
        return Response(_result(400, "举报对象无效"), status=status.HTTP_400_BAD_REQUEST)
    reason = (request.data.get("reason") or "")[:255]
    Report.objects.create(reporter_id=user_id, target_type=target_type, target_id=target_id, reason=reason or None, status="pending")
    return Response(_result(data={"message": "举报已提交，我们会尽快处理"}))


@api_view(["GET"])
@permission_classes([AllowAny])
def my_favorites(request):
    """我的收藏帖子列表"""
    user_id = _user_id_from_request(request)
    if not user_id:
        return Response(_result(401, "请先登录"), status=status.HTTP_401_UNAUTHORIZED)
    page = max(1, int(request.GET.get("page") or 1))
    page_size = min(30, max(1, int(request.GET.get("page_size") or 20)))
    fav_post_ids = list(
        PostFavorite.objects.filter(user_id=user_id).order_by("-created_at").values_list("post_id", flat=True)[(page - 1) * page_size : page * page_size]
    )
    if not fav_post_ids:
        return Response(_result(data={"list": [], "hasMore": False}))
    posts = list(Post.objects.filter(id__in=fav_post_ids, status=1).order_by("-created_at"))
    # 保持收藏顺序：按 fav 时间更复杂，这里简化为按帖子时间
    user_ids = list({p.user_id for p in posts})
    users = {u.id: u for u in User.objects.filter(id__in=user_ids)} if user_ids else {}
    liked_set = set(PostLike.objects.filter(user_id=user_id, post_id__in=[p.id for p in posts]).values_list("post_id", flat=True))
    favorited_set = set(fav_post_ids)
    all_topic_ids = set()
    for p in posts:
        if p.topic_ids_json:
            try:
                ids = json.loads(p.topic_ids_json) if isinstance(p.topic_ids_json, str) else p.topic_ids_json
                all_topic_ids.update(ids)
            except Exception:
                pass
    topics_map = {t.id: {"id": t.id, "name": t.name} for t in Topic.objects.filter(id__in=all_topic_ids)} if all_topic_ids else {}
    items = []
    for p in posts:
        u = users.get(p.user_id)
        t_ids = []
        if p.topic_ids_json:
            try:
                t_ids = json.loads(p.topic_ids_json) if isinstance(p.topic_ids_json, str) else p.topic_ids_json
            except Exception:
                pass
        tl = [topics_map[i] for i in t_ids if i in topics_map]
        items.append(_post_item(p, u, tl, liked=(p.id in liked_set), favorited=True))
    return Response(_result(data={"list": items, "hasMore": len(posts) == page_size}))


@api_view(["POST"])
@permission_classes([AllowAny])
def post_share(request, post_id):
    """转发：增加分享计数；登录时给帖子作者发通知"""
    if not Post.objects.filter(id=post_id, status=1).exists():
        return Response(_result(404, "帖子不存在"), status=status.HTTP_404_NOT_FOUND)
    Post.objects.filter(id=post_id).update(share_count=F("share_count") + 1)
    p = Post.objects.get(id=post_id)
    user_id = _user_id_from_request(request)
    if user_id and p.user_id != user_id:
        _create_notification(p.user_id, "share", user_id, post_id)
    return Response(_result(data={"shareCount": p.share_count}))


@api_view(["POST"])
@permission_classes([AllowAny])
def post_delete(request, post_id):
    """删除帖子（仅作者可删）"""
    user_id = _user_id_from_request(request)
    if not user_id:
        return Response(_result(401, "请先登录"), status=status.HTTP_401_UNAUTHORIZED)
    try:
        p = Post.objects.get(id=post_id)
    except Post.DoesNotExist:
        return Response(_result(404, "帖子不存在"), status=status.HTTP_404_NOT_FOUND)
    if p.user_id != user_id:
        return Response(_result(403, "无权删除"), status=status.HTTP_403_FORBIDDEN)
    Post.objects.filter(id=post_id).update(status=0)
    return Response(_result(data={"message": "已删除"}))


@api_view(["GET"])
@permission_classes([AllowAny])
def notification_list(request):
    """互动通知列表（被评论/点赞/收藏/分享），分页"""
    user_id = _user_id_from_request(request)
    if not user_id:
        return Response(_result(401, "请先登录"), status=status.HTTP_401_UNAUTHORIZED)
    page = max(1, int(request.GET.get("page") or 1))
    page_size = min(50, max(1, int(request.GET.get("page_size") or 20)))
    qs = Notification.objects.filter(user_id=user_id).order_by("-created_at")
    unread_count = Notification.objects.filter(user_id=user_id, read=0).count()
    start = (page - 1) * page_size
    rows = list(qs[start : start + page_size])
    from_ids = list({n.from_user_id for n in rows})
    users = {u.id: u for u in User.objects.filter(id__in=from_ids)} if from_ids else {}
    type_text = {"comment": "评论", "like": "点赞", "favorite": "收藏", "share": "分享"}
    items = []
    for n in rows:
        u = users.get(n.from_user_id)
        items.append({
            "id": n.id,
            "type": n.type,
            "typeText": type_text.get(n.type, n.type),
            "fromUserId": n.from_user_id,
            "fromNickname": getattr(u, "nickname", None) or f"用户{n.from_user_id}",
            "fromAvatarUrl": getattr(u, "avatar_url", None),
            "postId": n.post_id,
            "commentId": n.comment_id,
            "contentSnippet": n.content_snippet or "",
            "read": bool(n.read),
            "createdAt": n.created_at.isoformat() if n.created_at else None,
        })
    return Response(_result(data={
        "list": items,
        "hasMore": len(rows) == page_size,
        "unreadCount": unread_count,
    }))


@api_view(["GET"])
@permission_classes([AllowAny])
def notification_unread_count(request):
    """互动通知未读数量，用于信息页角标"""
    user_id = _user_id_from_request(request)
    if not user_id:
        return Response(_result(data={"unreadCount": 0}))
    count = Notification.objects.filter(user_id=user_id, read=0).count()
    return Response(_result(data={"unreadCount": count}))


@api_view(["POST"])
@permission_classes([AllowAny])
def notification_mark_read(request):
    """标记通知已读。body: { "ids": [1,2] } 若为空则全部标已读"""
    user_id = _user_id_from_request(request)
    if not user_id:
        return Response(_result(401, "请先登录"), status=status.HTTP_401_UNAUTHORIZED)
    ids = request.data.get("ids") or []
    if isinstance(ids, str):
        try:
            ids = json.loads(ids)
        except Exception:
            ids = []
    ids = [int(x) for x in ids if x is not None]
    if ids:
        Notification.objects.filter(user_id=user_id, id__in=ids).update(read=1)
    else:
        Notification.objects.filter(user_id=user_id).update(read=1)
    return Response(_result())


