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


def _require_upload_auth(request):
    """校验上传相关接口的登录态，返回 (user_id, None) 或 (None, Response)。"""
    from apps.account.session_store import get_user_id_by_token
    auth = request.META.get("HTTP_AUTHORIZATION") or ""
    if not auth.startswith("Bearer "):
        return None, Response(_result(401, "请先登录"), status=status.HTTP_401_UNAUTHORIZED)
    token = auth[7:].strip()
    uid = get_user_id_by_token(token)
    if not uid:
        return None, Response(_result(401, "请先登录"), status=status.HTTP_401_UNAUTHORIZED)
    return uid, None


@api_view(["POST"])
@permission_classes([AllowAny])
def presign_upload(request):
    """
    获取直传 OSS 的预签名 URL，避免文件经后端转发。
    body: { "type": "image" | "video" }，可选 "ext": ".mp4" 等。
    返回: { uploadUrl, url, objectKey }。客户端用 PUT uploadUrl 上传文件，url 为展示用签名读链接。
    """
    uid, err_resp = _require_upload_auth(request)
    if err_resp is not None:
        return err_resp
    if not getattr(settings, "ALIYUN_OSS_ENABLED", False) or not getattr(settings, "ALIYUN_OSS_BUCKET", ""):
        return Response(_result(503, "上传服务未配置 OSS"), status=503)
    upload_type = (request.data.get("type") or request.GET.get("type") or "image").strip().lower()
    if upload_type not in ("image", "video"):
        upload_type = "image"
    ext = (request.data.get("ext") or request.GET.get("ext") or (".mp4" if upload_type == "video" else ".jpg")).strip().lower()
    if upload_type == "video" and ext not in _UPLOAD_VIDEO_EXTS:
        ext = ".mp4"
    if upload_type == "image" and ext not in _UPLOAD_IMAGE_EXTS:
        ext = ".jpg"
    oss_folder = "video" if upload_type == "video" else "image"
    name = f"{uuid.uuid4().hex}{ext}"
    object_key = f"{oss_folder}/{name}"
    from .oss_upload import get_presigned_upload_urls
    read_expires = getattr(settings, "ALIYUN_OSS_SIGNED_URL_EXPIRES", 604800)
    upload_url, read_url, err = get_presigned_upload_urls(
        object_key,
        bucket=settings.ALIYUN_OSS_BUCKET,
        endpoint=settings.ALIYUN_OSS_ENDPOINT,
        credential_file=settings.ALIYUN_OSS_CREDENTIAL_FILE,
        upload_expires=3600,
        read_expires=read_expires,
    )
    if err:
        return Response(_result(500, err or "生成上传链接失败"), status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    return Response(_result(data={"uploadUrl": upload_url, "url": read_url, "objectKey": object_key}))


@api_view(["POST"])
@permission_classes([AllowAny])
def confirm_upload(request):
    """
    视频直传 OSS 后，由后端拉取视频、截封面并上传封面，返回展示用 url 与 coverUrl。
    body: { "objectKey": "video/xxx.mp4" }。
    """
    uid, err_resp = _require_upload_auth(request)
    if err_resp is not None:
        return err_resp
    object_key = (request.data.get("objectKey") or request.GET.get("objectKey") or "").strip()
    if not object_key or not object_key.startswith("video/"):
        return Response(_result(400, "缺少或无效的 objectKey"), status=status.HTTP_400_BAD_REQUEST)
    if not getattr(settings, "ALIYUN_OSS_ENABLED", False) or not getattr(settings, "ALIYUN_OSS_BUCKET", ""):
        return Response(_result(503, "上传服务未配置 OSS"), status=503)
    from .oss_upload import download_oss_to_path, upload_path_to_oss, get_presigned_upload_urls
    from .video_cover import extract_first_frame
    tmp_video = None
    tmp_cover = None
    try:
        fd, tmp_path = tempfile.mkstemp(suffix=Path(object_key).suffix or ".mp4", prefix="confirm_video_")
        tmp_video = Path(tmp_path)
        os.close(fd)
        ok, err = download_oss_to_path(
            object_key,
            str(tmp_video),
            bucket=settings.ALIYUN_OSS_BUCKET,
            endpoint=settings.ALIYUN_OSS_ENDPOINT,
            credential_file=settings.ALIYUN_OSS_CREDENTIAL_FILE,
        )
        if not ok:
            return Response(_result(500, err or "拉取视频失败"), status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        read_expires = getattr(settings, "ALIYUN_OSS_SIGNED_URL_EXPIRES", 604800)
        upload_url, read_url, _ = get_presigned_upload_urls(
            object_key,
            bucket=settings.ALIYUN_OSS_BUCKET,
            endpoint=settings.ALIYUN_OSS_ENDPOINT,
            credential_file=settings.ALIYUN_OSS_CREDENTIAL_FILE,
            upload_expires=60,
            read_expires=read_expires,
        )
        if not read_url:
            return Response(_result(500, "生成视频链接失败"), status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        cover_url = None
        cover_path = extract_first_frame(tmp_video)
        if cover_path:
            tmp_cover = cover_path
            cover_name = f"{Path(object_key).stem}_cover.jpg"
            cover_object = f"video_cover/{cover_name}"
            cover_url, cover_err = upload_path_to_oss(
                cover_path,
                cover_object,
                bucket=settings.ALIYUN_OSS_BUCKET,
                endpoint=settings.ALIYUN_OSS_ENDPOINT,
                credential_file=settings.ALIYUN_OSS_CREDENTIAL_FILE,
                signed_url_expires=read_expires,
            )
            if cover_err:
                cover_url = None
        result_data = {"url": read_url}
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


def _fetch_ip_location_antping(ip):
    """调用 antping.com 接口查询 IP 属地，返回如 湖北省 武汉市 洪山区 中国移动（/ 已替换为空格）"""
    import json
    import urllib.parse
    import urllib.request

    try:
        url = f"https://antping.com/geek/network-tools-service/ping/getIpAddress?target={urllib.parse.quote(ip)}"
        req = urllib.request.Request(
            url,
            method="GET",
            headers={
                "Accept": "application/json, text/plain, */*",
                "User-Agent": "Mozilla/5.0 (compatible; XuanYu/1.0)",
                "Referer": "https://antping.com/ip",
            },
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read().decode())
        if body.get("code") == 200 and isinstance(body.get("data"), dict):
            addr = (body["data"].get("address") or "").strip()
            if addr:
                return addr.replace("/", " ")
    except Exception:
        pass
    return None


def _fetch_ip_location_tool_lu(ip):
    """备用：tool.lu 接口"""
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
    loc = _fetch_ip_location_antping(ip)
    if not loc:
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
    location = _fetch_ip_location_antping(ip)
    if not location:
        location = _fetch_ip_location_tool_lu(ip)
    if not location:
        location = _fetch_ip_location_ipapi(ip)
    if not location:
        location = "未知"
    return Response(_result(data={"ip": ip, "location": location}))
