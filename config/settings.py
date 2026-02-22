# 连接方式来自需求文档末尾：MySQL 密码 12345678，Redis 本地 6379
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-secret-change-in-production")
DEBUG = os.environ.get("DEBUG", "1") == "1"
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "apps.account",
    "apps.fortune",
    "apps.community",
    "apps.system",
    "apps.im",
    "apps.voice_match",
    "apps.admin_api",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
CORS_ALLOW_ALL_ORIGINS = True
APPEND_SLASH = False  # 避免 /api/auth/login 被重定向导致 POST 丢失 body

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": "lingshu",
        "USER": "root",
        "PASSWORD": "12345678",
        "HOST": "localhost",
        "PORT": "3306",
        "OPTIONS": {"charset": "utf8mb4"},
    }
}

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": "redis://127.0.0.1:6379/0",
        "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
    }
}
SESSION_ENGINE = "django.contrib.sessions.backends.cache"
SESSION_CACHE_ALIAS = "default"

SESSION_COOKIE_AGE = 7 * 24 * 60 * 60  # 7 天
LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_TZ = True
STATIC_URL = "static/"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# 自定义配置（与架构设计一致）
APP_SESSION_TTL_DAYS = 7
# 短信：True=开发模式固定 123456，False=走阿里云 Dypnsapi 发真实短信
APP_SMS_DEV_MODE = os.environ.get("APP_SMS_DEV_MODE", "0") == "1"
# 阿里云短信验证码（仅当 APP_SMS_DEV_MODE=False 时使用）
ALIYUN_SMS_CREDENTIAL_FILE = os.environ.get(
    "ALIYUN_SMS_CREDENTIAL_FILE",
    str(BASE_DIR / "VerifyCodeServer" / "1771223142676.txt"),
)
ALIYUN_SMS_SIGN_NAME = os.environ.get("ALIYUN_SMS_SIGN_NAME", "速通互联验证码")
ALIYUN_SMS_TEMPLATE_CODE = os.environ.get("ALIYUN_SMS_TEMPLATE_CODE", "100001")
ALIYUN_SMS_TEMPLATE_PARAM = os.environ.get(
    "ALIYUN_SMS_TEMPLATE_PARAM",
    '{"code":"##code##","min":"5"}',
)
# 重置密码专用模板（请求验证码时传 scene=resetPassword 时使用）
ALIYUN_SMS_TEMPLATE_CODE_RESET_PASSWORD = os.environ.get("ALIYUN_SMS_TEMPLATE_CODE_RESET_PASSWORD", "100003")
ALIYUN_SMS_TEMPLATE_PARAM_RESET_PASSWORD = os.environ.get(
    "ALIYUN_SMS_TEMPLATE_PARAM_RESET_PASSWORD",
    '{"code":"##code##","min":"5"}',
)
# 修改绑定手机专用模板（请求验证码时传 scene=changePhone 时使用）
ALIYUN_SMS_TEMPLATE_CODE_CHANGE_PHONE = os.environ.get("ALIYUN_SMS_TEMPLATE_CODE_CHANGE_PHONE", "100002")
ALIYUN_SMS_TEMPLATE_PARAM_CHANGE_PHONE = os.environ.get(
    "ALIYUN_SMS_TEMPLATE_PARAM_CHANGE_PHONE",
    '{"code":"##code##","min":"5"}',
)

# 阿里云 OSS：默认启用，图片/视频全部走 OSS，不再使用本地 media 存储
ALIYUN_OSS_ENABLED = os.environ.get("ALIYUN_OSS_ENABLED", "1") == "1"
ALIYUN_OSS_CREDENTIAL_FILE = os.environ.get(
    "ALIYUN_OSS_CREDENTIAL_FILE",
    str(BASE_DIR / "VerifyCodeServer" / "1771223142676.txt"),
)
ALIYUN_OSS_BUCKET = os.environ.get("ALIYUN_OSS_BUCKET", "xuanyuapp")
ALIYUN_OSS_ENDPOINT = os.environ.get("ALIYUN_OSS_ENDPOINT", "oss-cn-beijing.aliyuncs.com")
# 签名 URL 有效期（秒），私有读时返回带签名的临时链接，过期需重新向接口申请
ALIYUN_OSS_SIGNED_URL_EXPIRES = int(os.environ.get("ALIYUN_OSS_SIGNED_URL_EXPIRES", "604800"))  # 默认 7 天

# 管理后台 API 鉴权：请求头 X-Admin-Token 需与此一致；不设置时仅 DEBUG 下允许访问
ADMIN_API_KEY = os.environ.get("ADMIN_API_KEY", "")

# 日志：apps.fortune（今日养生等）的 INFO 写入文件，gunicorn 下可 tail -f 查看
_log_fortune_dir = BASE_DIR / "logs"
_fortune_log_file = "/tmp/fortune.log"
try:
    _log_fortune_dir.mkdir(parents=True, exist_ok=True)
    _fortune_log_file = str(_log_fortune_dir / "fortune.log")
except Exception:
    pass  # 用 /tmp/fortune.log

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "fortune": {"format": "%(asctime)s [%(levelname)s] %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
        "fortune_file": {
            "class": "logging.FileHandler",
            "filename": _fortune_log_file,
            "encoding": "utf-8",
            "formatter": "fortune",
        },
    },
    "loggers": {
        "apps.fortune.views": {
            "level": "INFO",
            "handlers": ["console", "fortune_file"],
            "propagate": False,
        },
    },
}
