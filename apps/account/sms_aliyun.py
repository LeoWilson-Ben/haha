# -*- coding: utf-8 -*-
"""
阿里云短信验证码发送（Dypnsapi SendSmsVerifyCode）。
凭据从 settings.ALIYUN_SMS_CREDENTIAL_FILE 指向的文本文件读取，格式：
  accessKeyId xxx
  accessKeySecret xxx
"""
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _load_credential_from_file(file_path):
    """从 1771223142676.txt 格式的文件读取 accessKeyId 和 accessKeySecret。"""
    path = Path(file_path)
    if not path.is_file():
        return None, None
    access_key_id = None
    access_key_secret = None
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


def send_sms_verify_code(mobile, code, sign_name, template_code, template_param_template):
    """
    调用阿里云 SendSmsVerifyCode 发送短信验证码。
    template_param_template 中 ##code## 会被替换为实际 code，如 '{"code":"##code##","min":"5"}'
    返回 (True, None) 成功，失败返回 (False, error_message)。
    """
    from django.conf import settings

    cred_path = getattr(settings, "ALIYUN_SMS_CREDENTIAL_FILE", None)
    if not cred_path:
        return False, "未配置 ALIYUN_SMS_CREDENTIAL_FILE"

    access_key_id, access_key_secret = _load_credential_from_file(cred_path)
    if not access_key_id or not access_key_secret:
        return False, "凭据文件无效或缺少 accessKeyId/accessKeySecret"

    template_param = (template_param_template or "").replace("##code##", code)

    try:
        from alibabacloud_tea_openapi import models as open_api_models
        from alibabacloud_dypnsapi20170525.client import Client as DypnsapiClient
        from alibabacloud_dypnsapi20170525 import models as dypnsapi_models
        from alibabacloud_tea_util import models as util_models
    except ImportError as e:
        logger.exception("阿里云短信 SDK 未安装: %s", e)
        return False, "短信服务依赖未安装"

    config = open_api_models.Config(
        access_key_id=access_key_id,
        access_key_secret=access_key_secret,
        endpoint="dypnsapi.aliyuncs.com",
    )
    client = DypnsapiClient(config)
    req = dypnsapi_models.SendSmsVerifyCodeRequest(
        phone_number=mobile,
        sign_name=sign_name,
        template_code=template_code,
        template_param=template_param,
    )
    runtime = util_models.RuntimeOptions()

    try:
        resp = client.send_sms_verify_code_with_options(req, runtime)
        body = getattr(resp, "body", None)
        if body and (getattr(body, "code", None) == "OK" or getattr(body, "success", False)):
            return True, None
        msg = getattr(body, "message", None) or "发送失败"
        return False, msg
    except Exception as e:
        err_msg = str(e)
        if hasattr(e, "data") and isinstance(getattr(e, "data", None), dict):
            err_msg = e.data.get("Message", err_msg)
        logger.exception("阿里云发送验证码失败: %s", e)
        return False, err_msg
