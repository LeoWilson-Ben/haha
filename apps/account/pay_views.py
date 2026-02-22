# -*- coding: utf-8 -*-
"""
支付回调：微信、支付宝异步通知
收到支付成功回调后：更新订单状态、增加余额、写流水。
"""
import logging
from datetime import datetime
from decimal import Decimal

from django.db import connection
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from . import payment

logger = logging.getLogger(__name__)


def _on_payment_success(order_no: str, pay_channel: str, pay_trade_no: str, amount: Decimal):
    """支付成功：更新订单、加余额、写流水"""
    with connection.cursor() as c:
        c.execute(
            "SELECT id, user_id, amount, status FROM order_main WHERE order_no = %s FOR UPDATE",
            [order_no],
        )
        row = c.fetchone()
    if not row:
        logger.warning("支付回调订单不存在: %s", order_no)
        return False
    oid, user_id, order_amount, status = row
    if status == "paid":
        logger.info("订单已处理过: %s", order_no)
        return True

    if amount < order_amount:
        logger.warning("支付金额与订单不符: order=%s expect=%s got=%s", order_no, order_amount, amount)
        return False

    with connection.cursor() as c:
        c.execute(
            "UPDATE order_main SET status = 'paid', pay_channel = %s, pay_trade_no = %s, paid_at = NOW(), updated_at = NOW() WHERE id = %s",
            [pay_channel, pay_trade_no[:128], oid],
        )
        c.execute(
            "UPDATE user_wallet SET balance = balance + %s, version = version + 1, updated_at = NOW() WHERE user_id = %s",
            [amount, user_id],
        )
        c.execute(
            "INSERT INTO wallet_log (user_id, type, amount, order_no, remark, created_at) VALUES (%s, 'recharge', %s, %s, %s, NOW())",
            [user_id, amount, order_no, f"{pay_channel}充值"],
        )
    logger.info("支付成功: order_no=%s user_id=%s amount=%s", order_no, user_id, amount)
    return True


@csrf_exempt
@require_http_methods(["POST"])
def wechat_notify(request):
    """微信支付 V3 异步通知（callback 返回解密后的 resource 内容）"""
    result = payment.verify_wechat_callback(request)
    if not result:
        return HttpResponse(status=400)

    trade_state = result.get("trade_state")
    if trade_state != "SUCCESS":
        return HttpResponse(b'{"code":"SUCCESS","message":"ok"}', content_type="application/json")

    out_trade_no = result.get("out_trade_no")
    transaction_id = result.get("transaction_id")
    amount_obj = result.get("amount", {})
    total = amount_obj.get("total") or amount_obj.get("payer_total")  # 分
    if not out_trade_no or total is None:
        return HttpResponse(status=400)

    amount_yuan = Decimal(total) / 100
    _on_payment_success(out_trade_no, "wechat", transaction_id or "", amount_yuan)
    return HttpResponse(b'{"code":"SUCCESS","message":"ok"}', content_type="application/json")


@csrf_exempt
@require_http_methods(["POST"])
def alipay_notify(request):
    """支付宝异步通知"""
    result = payment.verify_alipay_callback(request)
    if not result:
        return HttpResponse("fail")

    trade_status = result.get("trade_status")
    if trade_status not in ("TRADE_SUCCESS", "TRADE_FINISHED"):
        return HttpResponse("success")

    out_trade_no = result.get("out_trade_no")
    trade_no = result.get("trade_no")
    total_amount = result.get("total_amount")
    if not out_trade_no or not total_amount:
        return HttpResponse("fail")

    try:
        amount_yuan = Decimal(str(total_amount))
    except Exception:
        return HttpResponse("fail")

    _on_payment_success(out_trade_no, "alipay", trade_no or "", amount_yuan)
    return HttpResponse("success")
