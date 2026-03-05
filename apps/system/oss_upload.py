# -*- coding: utf-8 -*-
"""
阿里云 OSS 上传：读取凭据文件后上传文件。Bucket 私有读时返回签名 URL，防止泄漏。
凭据文件格式同短信：accessKeyId xxx / accessKeySecret xxx
"""
import logging
from pathlib import Path
from urllib.parse import urlparse, unquote

logger = logging.getLogger(__name__)


def _load_credential(file_path):
    access_key_id = None
    access_key_secret = None
    path = Path(file_path)
    if path.is_file():
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split(None, 1)
                if len(parts) < 2:
                    continue
                key, value = parts[0].strip(), parts[1].strip()
                if key == "accessKeyId":
                    access_key_id = value
                elif key == "accessKeySecret":
                    access_key_secret = value
    return access_key_id, access_key_secret


def upload_file_to_oss(file_obj, object_name, bucket, endpoint, credential_file, signed_url_expires=604800):
    """
    将 file_obj（Django UploadedFile）上传到 OSS 的 object_name。
    返回签名 URL（私有读，防泄漏），(url, None) 成功，(None, error_message) 失败。
    signed_url_expires: 签名有效期（秒），默认 7 天。
    """
    access_key_id, access_key_secret = _load_credential(credential_file)
    if not access_key_id or not access_key_secret:
        return None, "OSS 凭据无效"

    try:
        import oss2
    except ImportError:
        logger.exception("oss2 未安装，请 pip install oss2")
        return None, "OSS 依赖未安装"

    auth = oss2.Auth(access_key_id, access_key_secret)
    if not endpoint.startswith("http"):
        endpoint = f"https://{endpoint}"
    bucket_obj = oss2.Bucket(auth, endpoint, bucket)

    try:
        data = b"".join(file_obj.chunks())
        bucket_obj.put_object(object_name, data)
    except Exception as e:
        logger.exception("OSS 上传失败: %s", e)
        return None, str(e)

    # 私有读：返回带过期时间的签名 URL，避免公共读导致泄漏
    try:
        url = bucket_obj.sign_url("GET", object_name, signed_url_expires)
    except Exception as e:
        logger.exception("OSS 签名 URL 生成失败: %s", e)
        return None, str(e)
    return url, None


def upload_path_to_oss(file_path, object_name, bucket, endpoint, credential_file, signed_url_expires=604800):
    """
    将本地文件（如临时生成的封面图）上传到 OSS。
    返回 (url, None) 成功，(None, error_message) 失败。
    """
    path = Path(file_path)
    if not path.is_file():
        return None, "文件不存在"
    access_key_id, access_key_secret = _load_credential(credential_file)
    if not access_key_id or not access_key_secret:
        return None, "OSS 凭据无效"
    try:
        import oss2
    except ImportError:
        logger.exception("oss2 未安装，请 pip install oss2")
        return None, "OSS 依赖未安装"
    auth = oss2.Auth(access_key_id, access_key_secret)
    if not endpoint.startswith("http"):
        endpoint = f"https://{endpoint}"
    bucket_obj = oss2.Bucket(auth, endpoint, bucket)
    try:
        with open(path, "rb") as f:
            bucket_obj.put_object(object_name, f.read())
    except Exception as e:
        logger.exception("OSS 上传失败: %s", e)
        return None, str(e)
    try:
        url = bucket_obj.sign_url("GET", object_name, signed_url_expires)
    except Exception as e:
        logger.exception("OSS 签名 URL 生成失败: %s", e)
        return None, str(e)
    return url, None


def get_presigned_upload_urls(
    object_name,
    bucket,
    endpoint,
    credential_file,
    upload_expires=3600,
    read_expires=604800,
):
    """
    生成客户端直传 OSS 的预签名 URL。
    :return: (upload_url, read_url, None) 成功，(None, None, error_message) 失败。
    """
    access_key_id, access_key_secret = _load_credential(credential_file)
    if not access_key_id or not access_key_secret:
        return None, None, "OSS 凭据无效"
    try:
        import oss2
    except ImportError:
        logger.exception("oss2 未安装")
        return None, None, "OSS 依赖未安装"
    auth = oss2.Auth(access_key_id, access_key_secret)
    if not endpoint.startswith("http"):
        endpoint = f"https://{endpoint}"
    bucket_obj = oss2.Bucket(auth, endpoint, bucket)
    try:
        upload_url = bucket_obj.sign_url("PUT", object_name, upload_expires)
        read_url = bucket_obj.sign_url("GET", object_name, read_expires)
        return upload_url, read_url, None
    except Exception as e:
        logger.exception("OSS 预签名生成失败: %s", e)
        return None, None, str(e)


def refresh_signed_url(oss_url, bucket, endpoint, credential_file, signed_url_expires=604800):
    """
    根据已有 OSS 签名 URL 或同 Bucket 的 OSS 地址，用当前凭据重新生成签名 URL（解决过期 403）。
    若 URL 不是本 Bucket 的 OSS 地址或解析失败，原样返回。
    """
    if not oss_url or not isinstance(oss_url, str) or not oss_url.strip():
        return oss_url
    try:
        parsed = urlparse(oss_url.strip())
        # 例如 https://xuanyuapp.oss-cn-beijing.aliyuncs.com/image%2Fxxx.jpg?...
        netloc = (parsed.netloc or "").lower()
        if not netloc or bucket not in netloc or "aliyuncs.com" not in netloc:
            return oss_url
        path = (parsed.path or "").strip().lstrip("/")
        if not path:
            return oss_url
        object_key = unquote(path)
    except Exception:
        return oss_url
    access_key_id, access_key_secret = _load_credential(credential_file)
    if not access_key_id or not access_key_secret:
        return oss_url
    try:
        import oss2
    except ImportError:
        return oss_url
    try:
        auth = oss2.Auth(access_key_id, access_key_secret)
        ep = endpoint if endpoint.startswith("http") else f"https://{endpoint}"
        bucket_obj = oss2.Bucket(auth, ep, bucket)
        return bucket_obj.sign_url("GET", object_key, signed_url_expires)
    except Exception as e:
        logger.warning("OSS 刷新签名失败 %s: %s", object_key, e)
        return oss_url


def refresh_oss_url_if_applicable(url):
    """
    若 url 为本项目配置的 OSS 签名地址，则用当前凭据重新生成签名 URL（用于头像、封面等，解决过期 403）。
    否则原样返回。需在 Django 环境内调用（依赖 settings）。
    """
    if not url or not isinstance(url, str) or not url.strip():
        return url
    try:
        from django.conf import settings
        if not getattr(settings, "ALIYUN_OSS_ENABLED", False) or not getattr(settings, "ALIYUN_OSS_BUCKET", ""):
            return url
        bucket = settings.ALIYUN_OSS_BUCKET
        endpoint = getattr(settings, "ALIYUN_OSS_ENDPOINT", "oss-cn-beijing.aliyuncs.com")
        cred = getattr(settings, "ALIYUN_OSS_CREDENTIAL_FILE", "")
        expires = getattr(settings, "ALIYUN_OSS_SIGNED_URL_EXPIRES", 604800)
        return refresh_signed_url(url.strip(), bucket, endpoint, cred, expires)
    except Exception:
        return url


def download_oss_to_path(object_name, local_path, bucket, endpoint, credential_file):
    """将 OSS 对象下载到本地，用于服务端截视频封面等。返回 (True, None) 或 (False, error_message)。"""
    path = Path(local_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    access_key_id, access_key_secret = _load_credential(credential_file)
    if not access_key_id or not access_key_secret:
        return False, "OSS 凭据无效"
    try:
        import oss2
    except ImportError:
        return False, "OSS 依赖未安装"
    auth = oss2.Auth(access_key_id, access_key_secret)
    if not endpoint.startswith("http"):
        endpoint = f"https://{endpoint}"
    bucket_obj = oss2.Bucket(auth, endpoint, bucket)
    try:
        bucket_obj.get_object_to_file(object_name, str(path))
        return True, None
    except Exception as e:
        logger.exception("OSS 下载失败: %s", e)
        return False, str(e)

