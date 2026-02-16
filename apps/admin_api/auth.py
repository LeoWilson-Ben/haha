# -*- coding: utf-8 -*-
"""管理端请求鉴权：校验 X-Admin-Token 与 settings.ADMIN_API_KEY"""
from functools import wraps
from django.conf import settings
from rest_framework import status
from rest_framework.response import Response


def _result(code=0, message="success", data=None):
    return {"code": code, "message": message, "data": data}


def admin_api_required(view_func):
    """要求请求头带 X-Admin-Token 且与 settings.ADMIN_API_KEY 一致；未配置时仅 DEBUG 允许"""
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        key = getattr(settings, "ADMIN_API_KEY", None)
        token = (request.META.get("HTTP_X_ADMIN_TOKEN") or "").strip()
        if key:
            if token != key:
                return Response(_result(401, "未授权"), status=status.HTTP_401_UNAUTHORIZED)
        elif not getattr(settings, "DEBUG", False):
            return Response(_result(401, "未配置管理端密钥"), status=status.HTTP_401_UNAUTHORIZED)
        return view_func(request, *args, **kwargs)
    return wrapped
