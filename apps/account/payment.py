# -*- coding: utf-8 -*-
"""
微信支付 & 支付宝 支付逻辑
配置从 server/Pay.txt 或环境变量读取，未配置时返回 None 表示支付未启用。
"""
import json
import logging
import os
from decimal import Decimal
from pathlib import Path

logger = logging.getLogger(__name__)

# 配置缓存
_pay_config = None


def _load_pay_config():
    """从 Pay.txt 或环境变量加载支付配置"""
    global _pay_config
    if _pay_config is not None:
        return _pay_config

    base_dir = Path(__file__).resolve().parent.parent.parent
    config = {}

    # 环境变量优先
    config["SERVER_BASE_URL"] = os.environ.get("PAY_SERVER_BASE_URL", "").strip()
    config["WECHAT_MCHID"] = os.environ.get("WECHAT_MCHID", "").strip()
    config["WECHAT_APPID"] = os.environ.get("WECHAT_APPID", "").strip()
    config["WECHAT_APIV3_KEY"] = os.environ.get("WECHAT_APIV3_KEY", "").strip()
    config["WECHAT_CERT_SERIAL_NO"] = os.environ.get("WECHAT_CERT_SERIAL_NO", "").strip()
    config["WECHAT_PRIVATE_KEY_PATH"] = os.environ.get("WECHAT_PRIVATE_KEY_PATH", "").strip()
    config["ALIPAY_APP_ID"] = os.environ.get("ALIPAY_APP_ID", "").strip()
    config["ALIPAY_APP_PRIVATE_KEY"] = os.environ.get("ALIPAY_APP_PRIVATE_KEY", "").strip()
    config["ALIPAY_PUBLIC_KEY"] = os.environ.get("ALIPAY_PUBLIC_KEY", "").strip()
    config["ALIPAY_SANDBOX"] = os.environ.get("ALIPAY_SANDBOX", "0").strip() == "1"

    pay_file = base_dir / "Pay.txt"
    if pay_file.exists():
        with open(pay_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    v = v.strip().strip('"').strip("'")
                    key = k.strip()
                    if key and not config.get(key):
                        config[key] = v

    # 私钥路径若为相对路径，则相对于 server 目录
    if config.get("WECHAT_PRIVATE_KEY_PATH") and not Path(config["WECHAT_PRIVATE_KEY_PATH"]).is_absolute():
        config["WECHAT_PRIVATE_KEY_PATH"] = str(base_dir / config["WECHAT_PRIVATE_KEY_PATH"].lstrip("server/"))

    _pay_config = config
    return config


def _wechat_configured(cfg):
    """微信支付是否已配置"""
    return bool(
        cfg.get("WECHAT_MCHID")
        and cfg.get("WECHAT_APPID")
        and cfg.get("WECHAT_APIV3_KEY")
        and cfg.get("WECHAT_CERT_SERIAL_NO")
        and cfg.get("WECHAT_PRIVATE_KEY_PATH")
    )


def _alipay_configured(cfg):
    """支付宝是否已配置"""
    return bool(
        cfg.get("ALIPAY_APP_ID")
        and cfg.get("ALIPAY_APP_PRIVATE_KEY")
        and cfg.get("ALIPAY_PUBLIC_KEY")
    )


def create_wechat_app_order(order_no: str, amount_yuan: Decimal, subject: str, notify_url: str) -> dict | None:
    """
    创建微信 APP 支付订单，返回 fluwx 所需参数 {appId, partnerId, prepayId, packageValue, nonceStr, timestamp, sign}
    用于直接唤起微信 APP 支付。
    """
    cfg = _load_pay_config()
    if not _wechat_configured(cfg) or not cfg.get("SERVER_BASE_URL"):
        return None

    try:
        from wechatpayv3 import WeChatPay, WeChatPayType
        import time
        import secrets
        import base64
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        from cryptography.hazmat.backends import default_backend

        key_path = cfg["WECHAT_PRIVATE_KEY_PATH"]
        if not Path(key_path).exists():
            logger.warning("微信支付私钥文件不存在: %s", key_path)
            return None

        with open(key_path, "r", encoding="utf-8") as f:
            private_key = f.read()

        wxpay = WeChatPay(
            wechatpay_type=WeChatPayType.APP,
            mchid=cfg["WECHAT_MCHID"],
            private_key=private_key,
            cert_serial_no=cfg["WECHAT_CERT_SERIAL_NO"],
            apiv3_key=cfg["WECHAT_APIV3_KEY"],
            appid=cfg["WECHAT_APPID"],
            notify_url=notify_url,
        )

        amount_fen = int(amount_yuan * 100)
        code, message = wxpay.pay(
            description=subject[:127],
            out_trade_no=order_no,
            amount={"total": amount_fen},
            pay_type=WeChatPayType.APP,
        )

        if code != 200:
            logger.warning("微信 APP 下单失败: code=%s message=%s", code, message)
            return None

        data = json.loads(message) if isinstance(message, str) else message
        prepay_id = (data or {}).get("prepay_id")
        if not prepay_id:
            return None

        app_id = cfg["WECHAT_APPID"]
        partner_id = cfg["WECHAT_MCHID"]
        package_value = "Sign=WXPay"
        nonce_str = secrets.token_hex(16)
        timestamp = int(time.time())

        # V3 签名字符串：appId\ntimestamp\nnonceStr\nprepay_id\n\n
        sign_str = f"{app_id}\n{timestamp}\n{nonce_str}\n{prepay_id}\n\n"
        key = load_pem_private_key(private_key.encode(), password=None, backend=default_backend())
        signature = key.sign(sign_str.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())
        sign = base64.b64encode(signature).decode("utf-8")

        return {
            "appId": app_id,
            "partnerId": partner_id,
            "prepayId": prepay_id,
            "packageValue": package_value,
            "nonceStr": nonce_str,
            "timestamp": timestamp,
            "sign": sign,
            "signType": "RSA",
        }
    except Exception as e:
        logger.exception("微信 APP 支付下单异常: %s", e)
    return None


def create_wechat_h5_order(order_no: str, amount_yuan: Decimal, subject: str, notify_url: str) -> dict | None:
    """
    创建微信 H5 支付订单，返回 {"payUrl": "https://..."} 或 None
    """
    cfg = _load_pay_config()
    if not _wechat_configured(cfg) or not cfg.get("SERVER_BASE_URL"):
        return None

    try:
        from wechatpayv3 import WeChatPay, WeChatPayType

        key_path = cfg["WECHAT_PRIVATE_KEY_PATH"]
        if not Path(key_path).exists():
            logger.warning("微信支付私钥文件不存在: %s", key_path)
            return None

        with open(key_path, "r", encoding="utf-8") as f:
            private_key = f.read()

        wxpay = WeChatPay(
            wechatpay_type=WeChatPayType.H5,
            mchid=cfg["WECHAT_MCHID"],
            private_key=private_key,
            cert_serial_no=cfg["WECHAT_CERT_SERIAL_NO"],
            apiv3_key=cfg["WECHAT_APIV3_KEY"],
            appid=cfg["WECHAT_APPID"],
            notify_url=notify_url,
        )

        amount_fen = int(amount_yuan * 100)
        base_url = cfg.get("SERVER_BASE_URL", "").rstrip("/")
        scene_info = {
            "payer_client_ip": "127.0.0.1",
            "h5_info": {
                "type": "Wap",
                "wap_url": base_url or "https://example.com",
                "wap_name": "玄语",
            },
        }
        code, message = wxpay.pay(
            description=subject[:127],
            out_trade_no=order_no,
            amount={"total": amount_fen},
            pay_type=WeChatPayType.H5,
            scene_info=scene_info,
        )

        if code == 200:
            data = json.loads(message) if isinstance(message, str) else message
            h5_url = (data or {}).get("h5_url")
            if h5_url:
                return {"payUrl": h5_url}
        logger.warning("微信 H5 下单失败: code=%s message=%s", code, message)
    except Exception as e:
        logger.exception("微信支付下单异常: %s", e)
    return None


def create_alipay_app_order(order_no: str, amount_yuan: Decimal, subject: str, notify_url: str) -> dict | None:
    """
    创建支付宝 APP 支付订单，返回 {"orderString": "..."} 供 tobias 调起支付宝 APP。
    """
    cfg = _load_pay_config()
    if not _alipay_configured(cfg) or not cfg.get("SERVER_BASE_URL"):
        return None

    try:
        from alipay.aop.api.AlipayClientConfig import AlipayClientConfig
        from alipay.aop.api.DefaultAlipayClient import DefaultAlipayClient
        from alipay.aop.api.domain.AlipayTradeAppPayModel import AlipayTradeAppPayModel
        from alipay.aop.api.request.AlipayTradeAppPayRequest import AlipayTradeAppPayRequest

        app_private_key = cfg["ALIPAY_APP_PRIVATE_KEY"]
        if app_private_key.strip().startswith("-----BEGIN"):
            pass
        else:
            p = Path(app_private_key)
            if not p.is_absolute():
                base_dir = Path(__file__).resolve().parent.parent.parent
                p = base_dir / app_private_key.lstrip("server/")
            if p.exists():
                with open(p, "r", encoding="utf-8") as f:
                    app_private_key = f.read()
            else:
                return None

        gateway = "https://openapi-sandbox.dl.alipaydev.com/gateway.do" if cfg.get("ALIPAY_SANDBOX") else "https://openapi.alipay.com/gateway.do"
        alipay_config = AlipayClientConfig()
        alipay_config.server_url = gateway
        alipay_config.app_id = cfg["ALIPAY_APP_ID"]
        alipay_config.app_private_key = app_private_key
        alipay_config.alipay_public_key = cfg["ALIPAY_PUBLIC_KEY"]

        client = DefaultAlipayClient(alipay_client_config=alipay_config, logger=logger)

        model = AlipayTradeAppPayModel()
        model.out_trade_no = order_no
        model.total_amount = str(amount_yuan)
        model.subject = subject[:256]
        model.product_code = "QUICK_MSECURITY_PAY"
        model.body = subject[:128] if len(subject) > 128 else subject

        request = AlipayTradeAppPayRequest(biz_model=model)
        request.notify_url = notify_url

        order_string = client.sdk_execute(request)
        if order_string:
            return {"orderString": order_string}
    except ImportError as e:
        logger.warning("支付宝 SDK 未安装或缺少 APP 支付类: %s", e)
    except Exception as e:
        logger.exception("支付宝 APP 下单异常: %s", e)
    return None


def create_alipay_wap_order(order_no: str, amount_yuan: Decimal, subject: str, notify_url: str, return_url: str) -> dict | None:
    """
    创建支付宝手机网站支付订单，返回 {"payUrl": "https://..."} 或 None
    """
    cfg = _load_pay_config()
    if not _alipay_configured(cfg) or not cfg.get("SERVER_BASE_URL"):
        return None

    try:
        from alipay.aop.api.AlipayClientConfig import AlipayClientConfig
        from alipay.aop.api.DefaultAlipayClient import DefaultAlipayClient

        # 手机网站支付：AlipayTradeWapPayModel；若无则用 AlipayTradePagePayModel（PC 页在手机浏览器也可用）
        try:
            from alipay.aop.api.domain.AlipayTradeWapPayModel import AlipayTradeWapPayModel
            from alipay.aop.api.request.AlipayTradeWapPayRequest import AlipayTradeWapPayRequest
            model_cls, request_cls = AlipayTradeWapPayModel, AlipayTradeWapPayRequest
            product_code = "QUICK_WAP_WAY"
        except ImportError:
            from alipay.aop.api.domain.AlipayTradePagePayModel import AlipayTradePagePayModel
            from alipay.aop.api.request.AlipayTradePagePayRequest import AlipayTradePagePayRequest
            model_cls, request_cls = AlipayTradePagePayModel, AlipayTradePagePayRequest
            product_code = "FAST_INSTANT_TRADE_PAY"

        app_private_key = cfg["ALIPAY_APP_PRIVATE_KEY"]
        if app_private_key.strip().startswith("-----BEGIN"):
            # PEM 内容
            pass
        else:
            # 文件路径
            p = Path(app_private_key)
            if not p.is_absolute():
                base_dir = Path(__file__).resolve().parent.parent.parent
                p = base_dir / app_private_key.lstrip("server/")
            if p.exists():
                with open(p, "r", encoding="utf-8") as f:
                    app_private_key = f.read()

        gateway = "https://openapi-sandbox.dl.alipaydev.com/gateway.do" if cfg.get("ALIPAY_SANDBOX") else "https://openapi.alipay.com/gateway.do"

        alipay_config = AlipayClientConfig()
        alipay_config.server_url = gateway
        alipay_config.app_id = cfg["ALIPAY_APP_ID"]
        alipay_config.app_private_key = app_private_key
        alipay_config.alipay_public_key = cfg["ALIPAY_PUBLIC_KEY"]

        client = DefaultAlipayClient(alipay_client_config=alipay_config, logger=logger)

        model = model_cls()
        model.out_trade_no = order_no
        model.total_amount = str(amount_yuan)
        model.subject = subject[:256]
        model.product_code = product_code
        model.body = subject[:128] if len(subject) > 128 else subject

        request = request_cls(biz_model=model)
        request.notify_url = notify_url
        request.return_url = return_url

        # page_execute 返回 GET 请求的 URL
        pay_url = client.page_execute(request, http_method="GET")
        if pay_url:
            return {"payUrl": pay_url}
    except ImportError as e:
        logger.warning("支付宝 SDK 未安装: pip install alipay-sdk-python %s", e)
    except Exception as e:
        logger.exception("支付宝下单异常: %s", e)
    return None


def verify_wechat_callback(request) -> dict | None:
    """
    验证微信支付回调，返回解密后的 resource（交易详情）或 None
    wechatpayv3 callback 需要 headers 和 body，Django 用 request.META 作为 headers
    """
    cfg = _load_pay_config()
    if not _wechat_configured(cfg):
        return None

    try:
        from wechatpayv3 import WeChatPay, WeChatPayType

        key_path = cfg["WECHAT_PRIVATE_KEY_PATH"]
        if not Path(key_path).exists():
            return None

        with open(key_path, "r", encoding="utf-8") as f:
            private_key = f.read()

        wxpay = WeChatPay(
            wechatpay_type=WeChatPayType.H5,
            mchid=cfg["WECHAT_MCHID"],
            private_key=private_key,
            cert_serial_no=cfg["WECHAT_CERT_SERIAL_NO"],
            apiv3_key=cfg["WECHAT_APIV3_KEY"],
            appid=cfg["WECHAT_APPID"],
            notify_url="",
        )

        # Django: request.META 含 HTTP_* 头，request.body 为 bytes
        headers = {k.replace("HTTP_", "").replace("_", "-").title(): v for k, v in request.META.items() if k.startswith("HTTP_")}
        result = wxpay.callback(headers, request.body)
        if result and isinstance(result, dict):
            # callback 可能返回解密后的 resource，或含 event_type + resource 的结构
            if "resource" in result and "out_trade_no" not in result:
                return result.get("resource") or result
            return result
    except Exception as e:
        logger.exception("微信支付回调验证失败: %s", e)
    return None


def verify_alipay_callback(request) -> dict | None:
    """
    验证支付宝回调，返回验签通过后的参数字典或 None
    """
    cfg = _load_pay_config()
    if not _alipay_configured(cfg):
        return None

    try:
        # 支付宝 POST 表单，转为 dict
        params = dict(request.POST) if hasattr(request, "POST") else {}
        params = {k: (v[0] if isinstance(v, list) else v) for k, v in params.items()}
        if not params or "sign" not in params:
            return None

        sign = params.get("sign")
        if not sign:
            return None

        # 验签时排除 sign、sign_type，按 key 排序后拼接
        sign_params = {k: v for k, v in params.items() if k not in ("sign", "sign_type") and v}
        sorted_items = sorted(sign_params.items())
        sign_str = "&".join(f"{k}={v}" for k, v in sorted_items if v)

        alipay_public_key = cfg["ALIPAY_PUBLIC_KEY"].strip()
        if alipay_public_key.startswith("-----BEGIN"):
            pub_key_str = alipay_public_key
        elif len(alipay_public_key) > 100 and "/" not in alipay_public_key[:50]:
            # 支付宝控制台复制的纯 base64 公钥
            pub_key_str = f"-----BEGIN PUBLIC KEY-----\n{alipay_public_key}\n-----END PUBLIC KEY-----"
        else:
            p = Path(alipay_public_key)
            if not p.is_absolute():
                base_dir = Path(__file__).resolve().parent.parent.parent
                p = base_dir / alipay_public_key.lstrip("server/")
            if p.exists():
                with open(p, "r", encoding="utf-8") as f:
                    pub_key_str = f.read()
            else:
                return None

        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.backends import default_backend
        import base64

        public_key = serialization.load_pem_public_key(pub_key_str.encode(), backend=default_backend())
        signature = base64.b64decode(sign)
        public_key.verify(signature, sign_str.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())
        return params
    except Exception as e:
        logger.exception("支付宝回调验证失败: %s", e)
    return None
