"""Agora RTC Token 生成，用于语音房间加入频道。证书从环境变量或 server/Agora.txt 读取（生产环境请用环境变量）。"""
import os
import time
from pathlib import Path

# 默认从项目根下 server/Agora.txt 读取（开发）；生产用 AGORA_APP_ID / AGORA_APP_CERTIFICATE
_AGORA_DIR = Path(__file__).resolve().parent.parent.parent
_AGORA_TXT = _AGORA_DIR / "Agora.txt"

def _load_agora_config():
    app_id = os.environ.get("AGORA_APP_ID", "").strip()
    cert = os.environ.get("AGORA_APP_CERTIFICATE", "").strip()
    if not app_id or not cert:
        if _AGORA_TXT.exists():
            for line in _AGORA_TXT.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("APPID") and not app_id:
                    app_id = line.replace("APPID", "").strip()
                if line.startswith("证书") and not cert:
                    cert = line.replace("证书", "").strip()
    return app_id, cert


def build_rtc_token(channel_name: str, uid: int, expire_seconds: int = 3600) -> str:
    """生成 RTC Token，用于加入语音频道。uid 为 32 位无符号整数（1 到 2^32-1）。"""
    app_id, app_certificate = _load_agora_config()
    if not app_id or not app_certificate:
        return ""
    try:
        from agora_token_builder import RtcTokenBuilder
        role = 1  # Role_Publisher，可发语音
        privilege_expired_ts = int(time.time()) + expire_seconds
        return RtcTokenBuilder.buildTokenWithUid(
            app_id, app_certificate, channel_name, uid,
            role, privilege_expired_ts
        )
    except Exception:
        return ""
