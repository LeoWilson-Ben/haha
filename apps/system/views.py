import os
import tempfile
import uuid
from pathlib import Path

from django.utils import timezone
from django.conf import settings
from django.db.models import Q
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .models import Banner

# 上传允许的扩展名：头像/帖子图片 + 帖子视频
_UPLOAD_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp")
_UPLOAD_VIDEO_EXTS = (".mp4", ".mov", ".webm", ".avi", ".mkv", ".m4v")


def _result(code=0, message="success", data=None):
    return {"code": code, "message": message, "data": data}


@api_view(["GET"])
@permission_classes([AllowAny])
def banners(request):
    """轮播图：type=home|splash"""
    t = (request.GET.get("type") or "home").strip().lower()
    now = timezone.now()
    qs = Banner.objects.filter(type=t, status=1).filter(
        Q(start_at__isnull=True) | Q(start_at__lte=now)
    ).filter(
        Q(end_at__isnull=True) | Q(end_at__gte=now)
    ).order_by("sort_order", "id")[:10]
    items = [{"id": b.id, "imageUrl": b.image_url, "linkUrl": b.link_url or "", "sortOrder": b.sort_order} for b in qs]
    return Response(_result(data=items))


@api_view(["POST"])
@permission_classes([AllowAny])
def upload(request):
    """上传图片/文件，multipart key=file。返回 { url }，用于头像、帖子图片与帖子视频。启用 OSS 时上传到阿里云并返回签名 URL。"""
    from apps.account.session_store import get_user_id_by_token
    auth = request.META.get("HTTP_AUTHORIZATION") or ""
    if auth.startswith("Bearer "):
        token = auth[7:].strip()
        uid = get_user_id_by_token(token)
        if not uid:
            return Response(_result(401, "请先登录"), status=status.HTTP_401_UNAUTHORIZED)
    else:
        return Response(_result(401, "请先登录"), status=status.HTTP_401_UNAUTHORIZED)

    f = request.FILES.get("file")
    if not f:
        return Response(_result(400, "缺少 file 字段"), status=status.HTTP_400_BAD_REQUEST)
    ext = (os.path.splitext(f.name)[1] or ".bin").lower()
    if ext not in _UPLOAD_IMAGE_EXTS and ext not in _UPLOAD_VIDEO_EXTS:
        ext = ".jpg"
    name = f"{uuid.uuid4().hex}{ext}"
    is_video = ext in _UPLOAD_VIDEO_EXTS
    oss_folder = "video" if is_video else "image"

    # 启用 OSS 时上传到阿里云：图片进 image/，视频进 video/；视频会额外生成封面进 video_cover/
    if getattr(settings, "ALIYUN_OSS_ENABLED", False) and getattr(settings, "ALIYUN_OSS_BUCKET", ""):
        from .oss_upload import upload_file_to_oss, upload_path_to_oss
        from .video_cover import extract_first_frame

        if is_video:
            # 视频：先落盘再上传（便于截帧），并生成封面图上传
            tmp_video = None
            tmp_cover = None
            try:
                fd, tmp_path = tempfile.mkstemp(suffix=ext, prefix="upload_video_")
                tmp_video = Path(tmp_path)
                try:
                    with os.fdopen(fd, "wb") as out:
                        for chunk in f.chunks():
                            out.write(chunk)
                except Exception:
                    tmp_video.unlink(missing_ok=True)
                    raise
                object_name = f"{oss_folder}/{name}"
                url, err = upload_path_to_oss(
                    tmp_video,
                    object_name,
                    bucket=settings.ALIYUN_OSS_BUCKET,
                    endpoint=settings.ALIYUN_OSS_ENDPOINT,
                    credential_file=settings.ALIYUN_OSS_CREDENTIAL_FILE,
                    signed_url_expires=getattr(settings, "ALIYUN_OSS_SIGNED_URL_EXPIRES", 604800),
                )
                if err:
                    return Response(_result(500, err or "OSS 上传失败"), status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                cover_url = None
                cover_path = extract_first_frame(tmp_video)
                if cover_path:
                    tmp_cover = cover_path
                    cover_name = f"{Path(name).stem}_cover.jpg"
                    cover_object = f"video_cover/{cover_name}"
                    cover_url, cover_err = upload_path_to_oss(
                        cover_path,
                        cover_object,
                        bucket=settings.ALIYUN_OSS_BUCKET,
                        endpoint=settings.ALIYUN_OSS_ENDPOINT,
                        credential_file=settings.ALIYUN_OSS_CREDENTIAL_FILE,
                        signed_url_expires=getattr(settings, "ALIYUN_OSS_SIGNED_URL_EXPIRES", 604800),
                    )
                    if cover_err:
                        cover_url = None
                result_data = {"url": url}
                if cover_url:
                    result_data["coverUrl"] = cover_url
                return Response(_result(data=result_data))
            finally:
                if tmp_video and tmp_video.exists():
                    try:
                        tmp_video.unlink()
                    except Exception:
                        pass
                if tmp_cover and Path(tmp_cover).exists():
                    try:
                        Path(tmp_cover).unlink()
                    except Exception:
                        pass

        object_name = f"{oss_folder}/{name}"
        url, err = upload_file_to_oss(
            f,
            object_name,
            bucket=settings.ALIYUN_OSS_BUCKET,
            endpoint=settings.ALIYUN_OSS_ENDPOINT,
            credential_file=settings.ALIYUN_OSS_CREDENTIAL_FILE,
            signed_url_expires=getattr(settings, "ALIYUN_OSS_SIGNED_URL_EXPIRES", 604800),
        )
        if err:
            return Response(_result(500, err or "OSS 上传失败"), status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        return Response(_result(data={"url": url}))

    # 已不再使用本地 media 存储，请配置并启用 OSS（ALIYUN_OSS_ENABLED=1, ALIYUN_OSS_BUCKET）或临时关闭 OSS 时设 ALIYUN_OSS_ENABLED=0 并取消下面注释以回退到本地
    return Response(_result(503, "上传服务未配置 OSS，请联系管理员"), status=503)
    # 本地存储（仅当需要临时回退时取消注释）
    # root = getattr(settings, "MEDIA_ROOT", None)
    # url_prefix = getattr(settings, "MEDIA_URL", "media/")
    # if not root:
    #     return Response(_result(500, "未配置 MEDIA_ROOT"), status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    # root.mkdir(parents=True, exist_ok=True)
    # path = root / name
    # with open(path, "wb") as out:
    #     for chunk in f.chunks():
    #         out.write(chunk)
    # rel = f"{url_prefix.rstrip('/')}/{name}"
    # try:
    #     url = request.build_absolute_uri(rel)
    # except Exception:
    #     url = rel
    # return Response(_result(data={"url": url}))


def _get_client_ip(request):
    """从请求中获取客户端 IP"""
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("HTTP_X_REAL_IP") or request.META.get("REMOTE_ADDR", "")


def _fetch_ip_location_tool_lu(ip):
    """调用 tool.lu 接口查询 IP 属地"""
    import json
    import urllib.request
    import urllib.parse

    try:
        data = urllib.parse.urlencode({"ip": ip}).encode()
        req = urllib.request.Request(
            "https://tool.lu/ip/ajax.html",
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0 (compatible; XuanYu/1.0)",
            },
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read().decode())
        if body.get("status") and isinstance(body.get("text"), dict):
            t = body["text"]
            # 优先 ip2region（较详细），其次 taobao
            return (t.get("ip2region") or t.get("taobao") or t.get("chunzhen") or "").strip() or None
    except Exception:
        pass
    return None


def _fetch_ip_location_ipapi(ip):
    """备用：ip-api.com 免费接口"""
    import json
    import urllib.request

    try:
        req = urllib.request.Request(
            f"http://ip-api.com/json/{ip}?lang=zh-CN&fields=country,regionName,city,isp",
            headers={"User-Agent": "XuanYu/1.0"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read().decode())
        parts = [body.get("country", ""), body.get("regionName", ""), body.get("city", ""), body.get("isp", "")]
        return " ".join(p for p in parts if p).strip() or None
    except Exception:
        pass
    return None


def get_ip_location_for_request(request):
    """根据请求 IP 解析属地，供发帖等场景使用。返回属地字符串或 None"""
    ip = _get_client_ip(request)
    if not ip or ip in ("127.0.0.1", "::1", "localhost"):
        return "本地"
    if ip.startswith("192.168.") or ip.startswith("10.") or ip.startswith("172."):
        return "内网"
    loc = _fetch_ip_location_tool_lu(ip)
    if not loc:
        loc = _fetch_ip_location_ipapi(ip)
    return loc


@api_view(["GET"])
@permission_classes([AllowAny])
def ip_location(request):
    """根据请求 IP 解析属地，用于展示 IP 属地"""
    ip = _get_client_ip(request)
    if not ip or ip in ("127.0.0.1", "::1", "localhost"):
        return Response(_result(data={"ip": ip or "", "location": "本地"}))
    if ip.startswith("192.168.") or ip.startswith("10.") or ip.startswith("172."):
        return Response(_result(data={"ip": ip, "location": "内网"}))
    location = _fetch_ip_location_tool_lu(ip)
    if not location:
        location = _fetch_ip_location_ipapi(ip)
    if not location:
        location = "未知"
    return Response(_result(data={"ip": ip, "location": location}))
