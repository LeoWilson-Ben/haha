"""Agora RTC Token 生成，用于语音房间加入频道。证书从环境变量或 server/Agora.txt 读取（生产环境请用环境变量）。"""
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# 多个可能路径，适配不同部署方式（runserver/gunicorn 等）
def _agora_txt_candidates():
    base = Path(__file__).resolve().parent.parent.parent  # server/
    cwd = Path.cwd()
    return [
        base / "Agora.txt",
        cwd / "Agora.txt",
        cwd / "server" / "Agora.txt",
        Path("/Users/houhouhou/StudioProjects/XuanYu/server/Agora.txt"),  # 开发机 fallback
    ]


def _parse_value(line: str, prefix: str) -> str:
    """从 APPID=xxx 或 证书=xxx 等格式解析出值"""
    if not line.startswith(prefix):
        return ""
    rest = line[len(prefix):].lstrip("=: \t")
    return rest.strip()


def _load_agora_config():
    app_id = (os.environ.get("AGORA_APP_ID") or "").strip()
    cert = (os.environ.get("AGORA_APP_CERTIFICATE") or "").strip()
    if not app_id or not cert:
        for f in _agora_txt_candidates():
            if f.exists():
                try:
                    for line in f.read_text(encoding="utf-8").splitlines():
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if line.upper().startswith("APPID") and not app_id:
                            app_id = _parse_value(line, "APPID") or _parse_value(line, "appid")
                        if line.startswith("证书") and not cert:
                            cert = _parse_value(line, "证书")
                        if line.upper().startswith("CERTIFICATE") and not cert:
                            cert = _parse_value(line, "CERTIFICATE") or _parse_value(line, "certificate")
                except Exception as e:
                    logger.warning("读取 Agora.txt 失败 %s: %s", f, e)
                break
    return app_id, cert


def build_rtc_token(channel_name: str, uid: int, expire_seconds: int = 3600) -> str:
    """生成 RTC Token，用于加入语音频道。uid 为 32 位无符号整数（1 到 2^32-1）。"""
    app_id, app_certificate = _load_agora_config()
    if not app_id or not app_certificate:
        logger.warning(
            "Agora 未配置：请设置环境变量 AGORA_APP_ID、AGORA_APP_CERTIFICATE，"
            "或在 server/Agora.txt 中配置（格式见下方）。当前 app_id=%s cert=%s",
            "已配置" if app_id else "未配置",
            "已配置" if app_certificate else "未配置",
        )
        return ""
    try:
        from apps.voice_match.agora_sdk.RtcTokenBuilder2 import RtcTokenBuilder, Role_Publisher
        # 使用官方 AccessToken2（Token v2），token_expire / privilege_expire 为「从现在起的秒数」
        return RtcTokenBuilder.build_token_with_uid(
            app_id, app_certificate, channel_name, uid,
            Role_Publisher, expire_seconds, expire_seconds
        )
    except Exception as e:
        logger.exception("Agora Token 生成失败: %s", e)
        return ""
