import re
import random
from django.conf import settings
from django.core.cache import cache
from django.db.utils import OperationalError, ProgrammingError
from django.contrib.auth.hashers import make_password, check_password
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .models import User, UserWallet, WalletLog, OrderMain, WithdrawApply
from .session_store import create_session, get_user_id_by_token

SMS_CODE_PREFIX = "sms:code:"
CODE_TTL = 5 * 60  # 5 分钟
MOBILE_PATTERN = re.compile(r"^1[3-9]\d{9}$")
DEV_CODE = "123456"


def _normalize_mobile(raw):
    """只保留数字，便于与 Redis key 一致"""
    s = (raw or "").strip()
    digits = re.sub(r"\D", "", s)
    return digits


def _result(code=0, message="success", data=None):
    return {"code": code, "message": message, "data": data}


def _get_user_code(user_id):
    """获取用户的 8 位 user_code"""
    from django.db import connection
    try:
        with connection.cursor() as c:
            c.execute("SELECT user_code FROM user WHERE id = %s", [user_id])
            row = c.fetchone()
            return (row[0] or "").strip() if row and row[0] else str(user_id).zfill(8)
    except Exception:
        return str(user_id).zfill(8)


def _ensure_user_code(user):
    """为新用户生成并写入 8 位 user_code（基于注册时间），若已有则跳过"""
    from django.db import connection
    try:
        with connection.cursor() as c:
            c.execute("SELECT user_code FROM user WHERE id = %s", [user.id])
            row = c.fetchone()
            if row and row[0]:
                return
            import time
            base = int(time.time() * 1000) % 100000000
            code = str((base + user.id) % 100000000).zfill(8)
            for _ in range(10):
                try:
                    c.execute("UPDATE user SET user_code = %s WHERE id = %s", [code, user.id])
                    if c.rowcount:
                        break
                except Exception:
                    pass
                code = str((int(code) + 1) % 100000000).zfill(8)
    except Exception:
        pass


@api_view(["GET"])
@permission_classes([AllowAny])
def health(request):
    """健康检查：MySQL、Redis"""
    from django.db import connection
    from django.core.cache import cache as redis_cache

    result = {"status": "UP", "mysql": "DOWN", "redis": "DOWN"}
    try:
        connection.ensure_connection()
        result["mysql"] = "UP"
    except Exception as e:
        result["mysql"] = f"DOWN: {e}"
    try:
        redis_cache.set("health_check", 1, 5)
        redis_cache.delete("health_check")
        result["redis"] = "UP"
    except Exception as e:
        result["redis"] = f"DOWN: {e}"
    return Response(result)


@api_view(["POST"])
@permission_classes([AllowAny])
def send_code(request):
    """发送验证码：开发模式固定 123456；否则走阿里云 Dypnsapi 发真实短信。
    body 可传 scene=resetPassword 使用重置密码模板 100003；scene=changePhone 使用修改手机模板 100002。"""
    mobile = _normalize_mobile(request.data.get("mobile"))
    if not MOBILE_PATTERN.match(mobile):
        return Response(_result(400, "请输入中国大陆手机号"), status=status.HTTP_400_BAD_REQUEST)

    import logging
    logger = logging.getLogger(__name__)
    dev_mode = getattr(settings, "APP_SMS_DEV_MODE", True)
    code = DEV_CODE if dev_mode else f"{random.randint(0, 999999):06d}"
    key = SMS_CODE_PREFIX + mobile
    scene = (request.data.get("scene") or request.data.get("type") or "").strip().lower()
    is_reset_password = scene == "resetpassword"
    is_change_phone = scene == "changephone"

    if dev_mode:
        cache.set(key, code, CODE_TTL)
        scene_desc = " (重置密码)" if is_reset_password else " (修改手机)" if is_change_phone else ""
        logger.info("【开发】短信验证码 %s -> %s%s", mobile, code, scene_desc)
        return Response(_result())

    from .sms_aliyun import send_sms_verify_code
    sign_name = getattr(settings, "ALIYUN_SMS_SIGN_NAME", "速通互联验证码")
    if is_reset_password:
        template_code = getattr(settings, "ALIYUN_SMS_TEMPLATE_CODE_RESET_PASSWORD", "100003")
        template_param = getattr(settings, "ALIYUN_SMS_TEMPLATE_PARAM_RESET_PASSWORD", '{"code":"##code##","min":"5"}')
    elif is_change_phone:
        template_code = getattr(settings, "ALIYUN_SMS_TEMPLATE_CODE_CHANGE_PHONE", "100002")
        template_param = getattr(settings, "ALIYUN_SMS_TEMPLATE_PARAM_CHANGE_PHONE", '{"code":"##code##","min":"5"}')
    else:
        template_code = getattr(settings, "ALIYUN_SMS_TEMPLATE_CODE", "100001")
        template_param = getattr(settings, "ALIYUN_SMS_TEMPLATE_PARAM", '{"code":"##code##","min":"5"}')
    ok, err = send_sms_verify_code(mobile, code, sign_name, template_code, template_param)
    if not ok:
        return Response(_result(500, err or "验证码发送失败"), status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    cache.set(key, code, CODE_TTL)
    return Response(_result())


@api_view(["POST"])
@permission_classes([AllowAny])
def login(request):
    """手机号+验证码登录，7 天会话"""
    mobile = _normalize_mobile(request.data.get("mobile"))
    code_raw = request.data.get("code")
    code = str(code_raw).strip() if code_raw is not None else ""
    device_id = (request.data.get("deviceId") or "").strip()

    if not MOBILE_PATTERN.match(mobile):
        return Response(_result(400, "请输入中国大陆手机号"), status=status.HTTP_400_BAD_REQUEST)
    if not code:
        return Response(_result(400, "验证码不能为空"), status=status.HTTP_400_BAD_REQUEST)

    key = SMS_CODE_PREFIX + mobile
    stored = cache.get(key)
    dev_mode = getattr(settings, "APP_SMS_DEV_MODE", True)
    if stored is None:
        if dev_mode and code == DEV_CODE:
            pass
        else:
            return Response(_result(400, "验证码错误或已过期（请先点「获取验证码」）"), status=status.HTTP_400_BAD_REQUEST)
    else:
        stored_str = stored.decode("utf-8") if isinstance(stored, bytes) else str(stored)
        if stored_str.strip() != code:
            return Response(_result(400, "验证码错误或已过期"), status=status.HTTP_400_BAD_REQUEST)
        cache.delete(key)

    try:
        user = User.objects.filter(mobile=mobile).first()
        if not user:
            return Response(_result(400, "用户不存在，请先注册"), status=status.HTTP_400_BAD_REQUEST)
    except (OperationalError, ProgrammingError):
        return Response(
            _result(500, "请先执行 sql/schema.sql 创建 user 表"),
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    if user.status == 0:
        return Response(_result(400, "账号已被禁用"), status=status.HTTP_400_BAD_REQUEST)

    token = create_session(user.id, device_id)
    user_code = _get_user_code(user.id)
    return Response(
        _result(
            data={
                "token": token,
                "userId": user.id,
                "userCode": user_code,
                "nickname": user.nickname,
                "avatarUrl": user.avatar_url,
                "minorMode": user.minor_mode or 0,
                "isNewUser": False,
            }
        )
    )


@api_view(["POST"])
@permission_classes([AllowAny])
def register(request):
    """注册：手机号 + 验证码 + 设置密码，注册成功后返回 token（即自动登录）"""
    mobile = _normalize_mobile(request.data.get("mobile"))
    code_raw = request.data.get("code")
    code = str(code_raw).strip() if code_raw is not None else ""
    password = (request.data.get("password") or "").strip()

    if not MOBILE_PATTERN.match(mobile):
        return Response(_result(400, "请输入中国大陆手机号"), status=status.HTTP_400_BAD_REQUEST)
    if not code:
        return Response(_result(400, "请输入验证码"), status=status.HTTP_400_BAD_REQUEST)
    if not password or len(password) < 6:
        return Response(_result(400, "密码至少 6 位"), status=status.HTTP_400_BAD_REQUEST)

    key = SMS_CODE_PREFIX + mobile
    stored = cache.get(key)
    dev_mode = getattr(settings, "APP_SMS_DEV_MODE", True)
    if stored is None:
        if dev_mode and code == DEV_CODE:
            pass
        else:
            return Response(_result(400, "验证码错误或已过期（请先获取验证码）"), status=status.HTTP_400_BAD_REQUEST)
    else:
        stored_str = stored.decode("utf-8") if isinstance(stored, bytes) else str(stored)
        if stored_str.strip() != code:
            return Response(_result(400, "验证码错误或已过期"), status=status.HTTP_400_BAD_REQUEST)
        cache.delete(key)

    try:
        user = User.objects.filter(mobile=mobile).first()
        if user:
            return Response(_result(400, "该手机号已注册，请直接登录"), status=status.HTTP_400_BAD_REQUEST)
        user = User.objects.create(
            mobile=mobile,
            password_hash=make_password(password),
            status=1,
            minor_mode=0,
        )
        _ensure_user_code(user)
    except (OperationalError, ProgrammingError):
        return Response(
            _result(500, "注册失败，请稍后重试"),
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    token = create_session(user.id, "flutter_dev")
    user_code = _get_user_code(user.id)
    return Response(
        _result(
            data={
                "token": token,
                "userId": user.id,
                "userCode": user_code,
                "nickname": user.nickname,
                "avatarUrl": user.avatar_url,
                "minorMode": user.minor_mode or 0,
                "isNewUser": True,
            }
        )
    )


@api_view(["POST"])
@permission_classes([AllowAny])
def login_by_password(request):
    """密码登录：手机号 + 密码"""
    mobile = _normalize_mobile(request.data.get("mobile"))
    password = (request.data.get("password") or "").strip()
    device_id = (request.data.get("deviceId") or "").strip() or "flutter_dev"

    if not MOBILE_PATTERN.match(mobile):
        return Response(_result(400, "请输入中国大陆手机号"), status=status.HTTP_400_BAD_REQUEST)
    if not password:
        return Response(_result(400, "请输入密码"), status=status.HTTP_400_BAD_REQUEST)

    try:
        user = User.objects.get(mobile=mobile)
    except User.DoesNotExist:
        return Response(_result(400, "用户不存在，请先注册"), status=status.HTTP_400_BAD_REQUEST)

    if not user.password_hash:
        return Response(_result(400, "该账号未设置密码，请使用验证码登录"), status=status.HTTP_400_BAD_REQUEST)
    if not check_password(password, user.password_hash):
        return Response(_result(400, "手机号或密码错误"), status=status.HTTP_400_BAD_REQUEST)
    if user.status == 0:
        return Response(_result(400, "账号已被禁用"), status=status.HTTP_400_BAD_REQUEST)

    token = create_session(user.id, device_id)
    user_code = _get_user_code(user.id)
    return Response(
        _result(
            data={
                "token": token,
                "userId": user.id,
                "userCode": user_code,
                "nickname": user.nickname,
                "avatarUrl": user.avatar_url,
                "minorMode": user.minor_mode or 0,
                "isNewUser": False,
            }
        )
    )


def _verify_sms_code(mobile, code):
    """校验短信验证码，成功返回 True，失败返回 (False, error_message)。"""
    key = SMS_CODE_PREFIX + mobile
    stored = cache.get(key)
    dev_mode = getattr(settings, "APP_SMS_DEV_MODE", True)
    if stored is None:
        if dev_mode and code == DEV_CODE:
            return True, None
        return False, "验证码错误或已过期（请先获取验证码）"
    stored_str = stored.decode("utf-8") if isinstance(stored, bytes) else str(stored)
    if stored_str.strip() != code:
        return False, "验证码错误或已过期"
    cache.delete(key)
    return True, None


@api_view(["POST"])
@permission_classes([AllowAny])
def reset_password(request):
    """忘记密码：手机号 + 短信验证码 + 新密码，重置后需重新登录。"""
    mobile = _normalize_mobile(request.data.get("mobile"))
    code_raw = request.data.get("code")
    code = str(code_raw).strip() if code_raw is not None else ""
    new_password = (request.data.get("password") or request.data.get("newPassword") or "").strip()

    if not MOBILE_PATTERN.match(mobile):
        return Response(_result(400, "请输入中国大陆手机号"), status=status.HTTP_400_BAD_REQUEST)
    if not code:
        return Response(_result(400, "请输入验证码"), status=status.HTTP_400_BAD_REQUEST)
    if not new_password or len(new_password) < 6:
        return Response(_result(400, "新密码至少 6 位"), status=status.HTTP_400_BAD_REQUEST)

    ok, err = _verify_sms_code(mobile, code)
    if not ok:
        return Response(_result(400, err), status=status.HTTP_400_BAD_REQUEST)

    try:
        user = User.objects.get(mobile=mobile)
    except User.DoesNotExist:
        return Response(_result(400, "该手机号未注册"), status=status.HTTP_400_BAD_REQUEST)
    if user.status == 0:
        return Response(_result(400, "账号已被禁用"), status=status.HTTP_400_BAD_REQUEST)

    user.password_hash = make_password(new_password)
    user.save(update_fields=["password_hash", "updated_at"])
    return Response(_result(message="密码已重置，请使用新密码登录"))


@api_view(["POST"])
def change_password(request):
    """已登录用户修改密码：原密码 + 新密码"""
    user_id = _user_id_from_request(request)
    if not user_id:
        return Response(_result(401, "请先登录"), status=status.HTTP_401_UNAUTHORIZED)

    old_password = (request.data.get("oldPassword") or request.data.get("old_password") or "").strip()
    new_password = (request.data.get("newPassword") or request.data.get("password") or request.data.get("new_password") or "").strip()

    if not old_password:
        return Response(_result(400, "请输入原密码"), status=status.HTTP_400_BAD_REQUEST)
    if not new_password or len(new_password) < 6:
        return Response(_result(400, "新密码至少 6 位"), status=status.HTTP_400_BAD_REQUEST)

    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return Response(_result(404, "用户不存在"), status=status.HTTP_404_NOT_FOUND)

    if not user.password_hash:
        return Response(_result(400, "您未设置过密码，请使用忘记密码进行设置"), status=status.HTTP_400_BAD_REQUEST)
    if not check_password(old_password, user.password_hash):
        return Response(_result(400, "原密码错误"), status=status.HTTP_400_BAD_REQUEST)

    user.password_hash = make_password(new_password)
    user.save(update_fields=["password_hash", "updated_at"])
    return Response(_result(message="密码修改成功"))


@api_view(["POST"])
def change_phone(request):
    """已登录用户修改绑定手机：原手机验证码 + 新手机号 + 新手机验证码"""
    user_id = _user_id_from_request(request)
    if not user_id:
        return Response(_result(401, "请先登录"), status=status.HTTP_401_UNAUTHORIZED)

    old_code = (request.data.get("oldCode") or request.data.get("old_code") or "").strip()
    new_mobile = _normalize_mobile(request.data.get("newMobile") or request.data.get("new_mobile"))
    new_code = (request.data.get("newCode") or request.data.get("new_code") or "").strip()

    if not old_code:
        return Response(_result(400, "请输入原手机验证码"), status=status.HTTP_400_BAD_REQUEST)
    if not MOBILE_PATTERN.match(new_mobile):
        return Response(_result(400, "请输入有效的新手机号"), status=status.HTTP_400_BAD_REQUEST)
    if not new_code:
        return Response(_result(400, "请输入新手机验证码"), status=status.HTTP_400_BAD_REQUEST)

    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return Response(_result(404, "用户不存在"), status=status.HTTP_404_NOT_FOUND)

    old_mobile = (user.mobile or "").strip()
    if not old_mobile:
        return Response(_result(400, "您未绑定手机号"), status=status.HTTP_400_BAD_REQUEST)
    if old_mobile == new_mobile:
        return Response(_result(400, "新手机号不能与原手机号相同"), status=status.HTTP_400_BAD_REQUEST)

    ok, err = _verify_sms_code(old_mobile, old_code)
    if not ok:
        return Response(_result(400, "原手机验证码错误或已过期"), status=status.HTTP_400_BAD_REQUEST)

    ok, err = _verify_sms_code(new_mobile, new_code)
    if not ok:
        return Response(_result(400, "新手机验证码错误或已过期"), status=status.HTTP_400_BAD_REQUEST)

    if User.objects.filter(mobile=new_mobile).exclude(id=user_id).exists():
        return Response(_result(400, "该手机号已被其他账号绑定"), status=status.HTTP_400_BAD_REQUEST)

    user.mobile = new_mobile
    user.save(update_fields=["mobile", "updated_at"])
    return Response(_result(message="手机号修改成功"))


def _user_id_from_request(request):
    auth = request.META.get("HTTP_AUTHORIZATION") or ""
    if auth.startswith("Bearer "):
        token = auth[7:].strip()
        return get_user_id_by_token(token)
    return None


def _get_user_profile(user_id):
    """从 user_profile 表读取 intro、birth_date、birth_time、is_master"""
    from django.db import connection
    try:
        with connection.cursor() as c:
            c.execute(
                "SELECT intro, birth_date, birth_time, COALESCE(is_master, 0) FROM user_profile WHERE user_id = %s",
                [user_id],
            )
            row = c.fetchone()
    except Exception:
        try:
            with connection.cursor() as c:
                c.execute(
                    "SELECT intro, birth_date FROM user_profile WHERE user_id = %s",
                    [user_id],
                )
                row = c.fetchone()
        except Exception:
            row = None
    if row:
        birth_time_val = None
        is_master_val = False
        if len(row) >= 4:  # intro, birth_date, birth_time, is_master
            birth_time_val = str(row[2]).strip() if row[2] else None
            is_master_val = bool(row[3])
        elif len(row) >= 3:  # intro, birth_date, is_master (old schema)
            is_master_val = bool(row[2])
        return {
            "intro": row[0] or "",
            "birthDate": row[1].strftime("%Y-%m-%d") if row[1] else None,
            "birthTime": birth_time_val,
            "isMaster": is_master_val,
        }
    return {"intro": "", "birthDate": None, "birthTime": None, "isMaster": False}


@api_view(["GET"])
def me(request):
    """当前登录用户信息"""
    user_id = _user_id_from_request(request)
    if not user_id:
        return Response(_result(401, "请先登录"), status=status.HTTP_401_UNAUTHORIZED)
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return Response(_result(404, "用户不存在"), status=status.HTTP_404_NOT_FOUND)
    if user.status == 0:
        return Response(_result(400, "账号已被禁用"), status=status.HTTP_400_BAD_REQUEST)
    profile = _get_user_profile(user_id)
    follow_count = follower_count = post_count = 0
    try:
        from django.db import connection
        with connection.cursor() as c:
            c.execute("SELECT COUNT(*) FROM user_follow WHERE user_id = %s", [user_id])
            follow_count = c.fetchone()[0] or 0
            c.execute("SELECT COUNT(*) FROM user_follow WHERE target_user_id = %s", [user_id])
            follower_count = c.fetchone()[0] or 0
            c.execute("SELECT COUNT(*) FROM post WHERE user_id = %s AND status = 1", [user_id])
            post_count = c.fetchone()[0] or 0
    except Exception:
        pass
    return Response(_result(data={
        "userId": user.id,
        "userCode": _get_user_code(user.id),
        "mobile": user.mobile,
        "nickname": user.nickname or "",
        "avatarUrl": user.avatar_url or "",
        "gender": user.gender,
        "minorMode": user.minor_mode or 0,
        "intro": profile["intro"],
        "birthDate": profile["birthDate"],
        "birthTime": profile.get("birthTime"),
        "followCount": follow_count,
        "followerCount": follower_count,
        "postCount": post_count,
        "isMaster": profile.get("isMaster", False),
    }))


@api_view(["GET", "POST"])
def user_location(request):
    """GET：返回当前用户保存的定位（user_profile.region_code）。POST：保存定位到数据库。"""
    user_id = _user_id_from_request(request)
    if not user_id:
        return Response(_result(401, "请先登录"), status=status.HTTP_401_UNAUTHORIZED)
    from django.db import connection
    if request.method == "GET":
        try:
            with connection.cursor() as c:
                c.execute(
                    "SELECT region_code FROM user_profile WHERE user_id = %s",
                    [user_id],
                )
                row = c.fetchone()
            region = (row[0] or "").strip() if row and row[0] else None
        except Exception:
            region = None
        return Response(_result(data={"locationCode": region, "location": region}))
    # POST
    loc = (
        request.data.get("locationCode")
        or request.data.get("location")
        or request.data.get("locationName")
        or ""
    )
    loc = (str(loc).strip() or "")[:32]
    try:
        with connection.cursor() as c:
            c.execute(
                """
                INSERT INTO user_profile (user_id, region_code, created_at, updated_at)
                VALUES (%s, %s, NOW(), NOW())
                ON DUPLICATE KEY UPDATE region_code = %s, updated_at = NOW()
                """,
                [user_id, loc or None, loc or None],
            )
    except Exception:
        try:
            with connection.cursor() as c:
                c.execute("SELECT 1 FROM user_profile WHERE user_id = %s", [user_id])
                if c.fetchone():
                    c.execute(
                        "UPDATE user_profile SET region_code = %s, updated_at = NOW() WHERE user_id = %s",
                        [loc or None, user_id],
                    )
                else:
                    c.execute(
                        "INSERT INTO user_profile (user_id, region_code, created_at, updated_at) VALUES (%s, %s, NOW(), NOW())",
                        [user_id, loc or None],
                    )
        except Exception:
            pass
    return Response(_result(data={"locationCode": loc or None}))


def _upsert_user_profile(user_id, intro=None, birth_date=None, birth_time=None):
    """插入或更新 user_profile 的 intro、birth_date、birth_time。None 表示保留原值"""
    from django.db import connection
    prof = _get_user_profile(user_id)
    intro_val = (str(intro).strip() or None)[:500] if intro is not None else (prof["intro"] or None)
    birth_val = (str(birth_date).strip() or None) if birth_date is not None else prof["birthDate"]
    birth_time_val = (str(birth_time).strip() or None)[:10] if birth_time is not None else prof.get("birthTime")
    try:
        with connection.cursor() as c:
            c.execute(
                """
                INSERT INTO user_profile (user_id, intro, birth_date, birth_time, created_at, updated_at)
                VALUES (%s, %s, %s, %s, NOW(), NOW())
                ON DUPLICATE KEY UPDATE intro = COALESCE(%s, intro), birth_date = COALESCE(%s, birth_date),
                birth_time = COALESCE(%s, birth_time), updated_at = NOW()
                """,
                [user_id, intro_val or None, birth_val, birth_time_val, intro_val, birth_val, birth_time_val],
            )
            if birth_val is not None or birth_time_val is not None:
                try:
                    c.execute("UPDATE user_profile SET xiyongshen = NULL WHERE user_id = %s", [user_id])
                except Exception:
                    pass
    except Exception:
        with connection.cursor() as c:
            c.execute(
                """
                INSERT INTO user_profile (user_id, intro, birth_date, created_at, updated_at)
                VALUES (%s, %s, %s, NOW(), NOW())
                ON DUPLICATE KEY UPDATE intro = %s, birth_date = %s, updated_at = NOW()
                """,
                [user_id, intro_val or None, birth_val, intro_val or None, birth_val],
            )


@api_view(["PATCH", "PUT"])
def update_profile(request):
    """更新昵称、头像、简介、出生日期"""
    user_id = _user_id_from_request(request)
    if not user_id:
        return Response(_result(401, "请先登录"), status=status.HTTP_401_UNAUTHORIZED)
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return Response(_result(404, "用户不存在"), status=status.HTTP_404_NOT_FOUND)
    nickname = request.data.get("nickname")
    if nickname is not None:
        user.nickname = (str(nickname).strip() or user.nickname)[:64]
    avatar_url = request.data.get("avatarUrl")
    if avatar_url is not None:
        user.avatar_url = (str(avatar_url).strip() or user.avatar_url)[:512] if str(avatar_url).strip() else None
    user.save(update_fields=["nickname", "avatar_url", "updated_at"])
    gender = request.data.get("gender")
    if gender is not None:
        try:
            g = int(gender)
            if g in (0, 1, 2):
                user.gender = g
                user.save(update_fields=["gender", "updated_at"])
        except (TypeError, ValueError):
            pass
    intro = request.data.get("intro")
    birth_date = request.data.get("birthDate")
    birth_time = request.data.get("birthTime")
    if intro is not None or birth_date is not None or birth_time is not None:
        _upsert_user_profile(user_id, intro=intro, birth_date=birth_date, birth_time=birth_time)
    prof = _get_user_profile(user_id)
    return Response(_result(data={
        "nickname": user.nickname,
        "avatarUrl": user.avatar_url,
        "gender": user.gender,
        "intro": prof["intro"],
        "birthDate": prof["birthDate"],
        "birthTime": prof.get("birthTime"),
    }))


@api_view(["GET", "PATCH"])
def privacy_settings(request):
    """GET：获取个人信息展示隐私设置；PATCH：更新。showIntro/showLocation/showAge/showBirthDate 0否1是"""
    user_id = _user_id_from_request(request)
    if not user_id:
        return Response(_result(401, "请先登录"), status=status.HTTP_401_UNAUTHORIZED)
    from django.db import connection

    def _get_privacy(user_id):
        try:
            with connection.cursor() as c:
                c.execute(
                    """SELECT COALESCE(show_intro, 1), COALESCE(show_location, 1),
                       COALESCE(show_age, 1), COALESCE(show_birth_date, 0)
                       FROM user_profile WHERE user_id = %s""",
                    [user_id],
                )
                row = c.fetchone()
        except Exception:
            return {"showIntro": 1, "showLocation": 1, "showAge": 1, "showBirthDate": 0}
        if row:
            return {
                "showIntro": 1 if (len(row) > 0 and row[0]) else 0,
                "showLocation": 1 if (len(row) > 1 and row[1]) else 0,
                "showAge": 1 if (len(row) > 2 and row[2]) else 0,
                "showBirthDate": 1 if (len(row) > 3 and row[3]) else 0,
            }
        return {"showIntro": 1, "showLocation": 1, "showAge": 1, "showBirthDate": 0}

    if request.method == "GET":
        return Response(_result(data=_get_privacy(user_id)))

    # PATCH
    show_intro = request.data.get("showIntro")
    show_location = request.data.get("showLocation")
    show_age = request.data.get("showAge")
    show_birth_date = request.data.get("showBirthDate")

    updates = []
    params = []
    if show_intro is not None:
        updates.append("show_intro = %s")
        params.append(1 if show_intro else 0)
    if show_location is not None:
        updates.append("show_location = %s")
        params.append(1 if show_location else 0)
    if show_age is not None:
        updates.append("show_age = %s")
        params.append(1 if show_age else 0)
    if show_birth_date is not None:
        updates.append("show_birth_date = %s")
        params.append(1 if show_birth_date else 0)

    if updates:
        try:
            with connection.cursor() as c:
                c.execute(
                    "SELECT 1 FROM user_profile WHERE user_id = %s",
                    [user_id],
                )
                if c.fetchone():
                    params.append(user_id)
                    c.execute(
                        f"UPDATE user_profile SET {', '.join(updates)}, updated_at = NOW() WHERE user_id = %s",
                        params,
                    )
                else:
                    si = 1 if (show_intro is None or show_intro) else 0
                    sl = 1 if show_location is None or show_location else 0
                    sa = 1 if show_age is None or show_age else 0
                    sb = 1 if show_birth_date else 0
                    c.execute(
                        """INSERT INTO user_profile (user_id, show_intro, show_location, show_age, show_birth_date, created_at, updated_at)
                           VALUES (%s, %s, %s, %s, %s, NOW(), NOW())""",
                        [user_id, si, sl, sa, sb],
                    )
        except Exception:
            pass
    return Response(_result(data=_get_privacy(user_id)))


def _ensure_wallet(user_id):
    from django.db import connection
    with connection.cursor() as c:
        c.execute(
            "INSERT IGNORE INTO user_wallet (user_id, balance, frozen_amount, version) VALUES (%s, 0, 0, 0)",
            [user_id],
        )


@api_view(["GET"])
def wallet_balance(request):
    """余额"""
    user_id = _user_id_from_request(request)
    if not user_id:
        return Response(_result(401, "请先登录"), status=status.HTTP_401_UNAUTHORIZED)
    _ensure_wallet(user_id)
    try:
        w = UserWallet.objects.get(user_id=user_id)
    except UserWallet.DoesNotExist:
        return Response(_result(data={"balance": "0.0000", "frozenAmount": "0.0000"}))
    return Response(_result(data={
        "balance": str(w.balance),
        "frozenAmount": str(w.frozen_amount),
    }))


@api_view(["GET"])
def wallet_log_list(request):
    """资金流水"""
    user_id = _user_id_from_request(request)
    if not user_id:
        return Response(_result(401, "请先登录"), status=status.HTTP_401_UNAUTHORIZED)
    page = max(1, int(request.GET.get("page") or 1))
    page_size = min(50, max(1, int(request.GET.get("page_size") or 20)))
    start = (page - 1) * page_size
    qs = WalletLog.objects.filter(user_id=user_id).order_by("-created_at")[start : start + page_size]
    items = [
        {"id": log.id, "type": log.type, "amount": str(log.amount), "orderNo": log.order_no, "remark": log.remark, "createdAt": log.created_at.isoformat() if log.created_at else None}
        for log in qs
    ]
    return Response(_result(data={"list": items, "hasMore": len(items) == page_size}))


@api_view(["GET"])
def order_list(request):
    """订单列表"""
    user_id = _user_id_from_request(request)
    if not user_id:
        return Response(_result(401, "请先登录"), status=status.HTTP_401_UNAUTHORIZED)
    page = max(1, int(request.GET.get("page") or 1))
    page_size = min(50, max(1, int(request.GET.get("page_size") or 20)))
    start = (page - 1) * page_size
    qs = OrderMain.objects.filter(user_id=user_id).order_by("-created_at")[start : start + page_size]
    items = [
        {"id": o.id, "orderNo": o.order_no, "type": o.type, "amount": str(o.amount), "status": o.status, "subject": o.subject, "paidAt": o.paid_at.isoformat() if o.paid_at else None, "createdAt": o.created_at.isoformat() if o.created_at else None}
        for o in qs
    ]
    return Response(_result(data={"list": items, "hasMore": len(items) == page_size}))


@api_view(["POST"])
def withdraw_apply(request):
    """提交提现申请（占位：仅落库，需后台审核）"""
    user_id = _user_id_from_request(request)
    if not user_id:
        return Response(_result(401, "请先登录"), status=status.HTTP_401_UNAUTHORIZED)
    amount = request.data.get("amount")
    try:
        amount_val = float(amount)
    except (TypeError, ValueError):
        return Response(_result(400, "金额无效"), status=status.HTTP_400_BAD_REQUEST)
    if amount_val <= 0:
        return Response(_result(400, "金额必须大于0"), status=status.HTTP_400_BAD_REQUEST)
    bank_card_snapshot = (request.data.get("bankCardSnapshot") or "").strip()[:500]
    w = WithdrawApply.objects.create(user_id=user_id, amount=amount_val, bank_card_snapshot=bank_card_snapshot or None, status="pending")
    return Response(_result(data={"id": w.id, "status": w.status, "createdAt": w.created_at.isoformat()}))


def _hash_id_card(raw):
    """身份证号哈希存储"""
    import hashlib
    s = (raw or "").strip()
    if not s:
        return None
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


@api_view(["POST"])
def teacher_apply(request):
    """名师入驻：提交实名认证申请。body: { realName, idCard }"""
    user_id = _user_id_from_request(request)
    if not user_id:
        return Response(_result(401, "请先登录"), status=status.HTTP_401_UNAUTHORIZED)
    real_name = (request.data.get("realName") or request.data.get("real_name") or "").strip()
    id_card = (request.data.get("idCard") or request.data.get("id_card") or "").strip()
    if not real_name or len(real_name) < 2:
        return Response(_result(400, "请输入真实姓名"), status=status.HTTP_400_BAD_REQUEST)
    if not id_card or len(id_card) != 18:
        return Response(_result(400, "请输入18位身份证号"), status=status.HTTP_400_BAD_REQUEST)
    id_card_hash = _hash_id_card(id_card)
    from django.db import connection
    try:
        with connection.cursor() as c:
            c.execute(
                "SELECT status FROM teacher_apply WHERE user_id = %s ORDER BY id DESC LIMIT 1",
                [user_id],
            )
            row = c.fetchone()
        if row and row[0] == "pending":
            return Response(_result(400, "您已有待审核的申请"), status=status.HTTP_400_BAD_REQUEST)
        if row and row[0] == "approved":
            return Response(_result(400, "您已是认证名师"), status=status.HTTP_400_BAD_REQUEST)
        with connection.cursor() as c:
            c.execute(
                "INSERT INTO teacher_apply (user_id, real_name, id_card_hash, status) VALUES (%s, %s, %s, 'pending')",
                [user_id, real_name[:64], id_card_hash],
            )
    except Exception as e:
        return Response(_result(500, "提交失败，请确认已执行 migrate_teacher.sql"), status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    return Response(_result(data={"message": "已提交，等待审核"}))


@api_view(["GET"])
def teacher_status(request):
    """名师入驻申请状态：none/pending/approved/rejected"""
    user_id = _user_id_from_request(request)
    if not user_id:
        return Response(_result(401, "请先登录"), status=status.HTTP_401_UNAUTHORIZED)
    prof = _get_user_profile(user_id)
    if prof.get("isMaster"):
        return Response(_result(data={"status": "approved"}))
    from django.db import connection
    try:
        with connection.cursor() as c:
            c.execute(
                "SELECT status FROM teacher_apply WHERE user_id = %s ORDER BY id DESC LIMIT 1",
                [user_id],
            )
            row = c.fetchone()
        if row:
            return Response(_result(data={"status": row[0]}))
    except Exception:
        pass
    return Response(_result(data={"status": "none"}))
