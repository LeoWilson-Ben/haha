# -*- coding: utf-8 -*-
"""支付回调 URL（AllowAny，供微信/支付宝服务器调用）"""
from django.urls import path
from . import pay_views

urlpatterns = [
    path("wechat/notify", pay_views.wechat_notify),
    path("alipay/notify", pay_views.alipay_notify),
]
