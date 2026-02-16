# -*- coding: utf-8 -*-
"""管理后台 API：名师审核、内容、举报、提现、用户"""
import json
from django.conf import settings
from django.db import connection
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .auth import admin_api_required, _result
from apps.account.models import User, WithdrawApply
from apps.community.models import Post, Comment, Report


# ---------- 仪表盘 ----------
@api_view(["GET"])
@admin_api_required
def dashboard_stats(request):
    """统计：用户数、帖子数、待审核名师、待审核提现、待处理举报"""
    try:
        with connection.cursor() as c:
            user_count = User.objects.count()
            post_count = Post.objects.filter(status=1).count()
            c.execute("SELECT COUNT(*) FROM teacher_apply WHERE status = 'pending'")
            teacher_pending = (c.fetchone() or (0,))[0]
            withdraw_pending = WithdrawApply.objects.filter(status="pending").count()
            report_pending = Report.objects.filter(status="pending").count()
        return Response(_result(data={
            "userCount": user_count,
            "postCount": post_count,
            "teacherPendingCount": teacher_pending,
            "withdrawPendingCount": withdraw_pending,
            "reportPendingCount": report_pending,
        }))
    except Exception as e:
        return Response(_result(500, str(e)), status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ---------- 名师入驻审核 ----------
@api_view(["GET"])
@admin_api_required
def teacher_apply_list(request):
    """名师入驻申请列表，支持 status=pending|approved|rejected"""
    status_filter = (request.GET.get("status") or "pending").strip().lower()
    if status_filter not in ("pending", "approved", "rejected"):
        status_filter = "pending"
    page = max(1, int(request.GET.get("page") or 1))
    page_size = min(50, max(1, int(request.GET.get("page_size") or 20)))
    offset = (page - 1) * page_size
    try:
        with connection.cursor() as c:
            c.execute(
                """SELECT ta.id, ta.user_id, ta.real_name, ta.status, ta.remark, ta.created_at, ta.updated_at,
                          u.nickname, u.mobile
                   FROM teacher_apply ta
                   LEFT JOIN user u ON u.id = ta.user_id
                   WHERE ta.status = %s
                   ORDER BY ta.id DESC
                   LIMIT %s OFFSET %s""",
                [status_filter, page_size, offset],
            )
            rows = c.fetchall()
            col = [d[0] for d in c.description]
        items = []
        for row in rows:
            r = dict(zip(col, row))
            items.append({
                "id": r["id"],
                "userId": r["user_id"],
                "realName": r["real_name"],
                "nickname": r["nickname"] or f"用户{r['user_id']}",
                "mobile": (r["mobile"] or "")[:3] + "****" + (r["mobile"] or "")[-4:] if r.get("mobile") and len(str(r["mobile"])) >= 7 else "",
                "status": r["status"],
                "remark": r["remark"] or "",
                "createdAt": r["created_at"].isoformat() if r.get("created_at") else None,
                "updatedAt": r["updated_at"].isoformat() if r.get("updated_at") else None,
            })
        return Response(_result(data={"list": items, "hasMore": len(items) == page_size}))
    except Exception as e:
        return Response(_result(500, str(e)), status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["POST"])
@admin_api_required
def teacher_apply_approve(request, apply_id):
    """通过名师入驻申请：更新 teacher_apply 为 approved，并设置 user_profile.is_master=1"""
    try:
        with connection.cursor() as c:
            c.execute("SELECT id, user_id, status FROM teacher_apply WHERE id = %s", [apply_id])
            row = c.fetchone()
        if not row:
            return Response(_result(404, "申请不存在"), status=status.HTTP_404_NOT_FOUND)
        _id, user_id, st = row
        if st != "pending":
            return Response(_result(400, "该申请已处理"), status=status.HTTP_400_BAD_REQUEST)
        with connection.cursor() as c:
            c.execute("UPDATE teacher_apply SET status = 'approved', updated_at = NOW() WHERE id = %s", [apply_id])
            c.execute(
                "UPDATE user_profile SET is_master = 1, updated_at = NOW() WHERE user_id = %s",
                [user_id],
            )
            if c.rowcount == 0:
                c.execute(
                    "INSERT INTO user_profile (user_id, is_master, created_at, updated_at) VALUES (%s, 1, NOW(), NOW())",
                    [user_id],
                )
        return Response(_result(data={"message": "已通过"}))
    except Exception as e:
        return Response(_result(500, str(e)), status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["POST"])
@admin_api_required
def teacher_apply_reject(request, apply_id):
    """驳回名师入驻申请"""
    remark = (request.data.get("remark") or "").strip()[:255]
    try:
        with connection.cursor() as c:
            c.execute("SELECT id, status FROM teacher_apply WHERE id = %s", [apply_id])
            row = c.fetchone()
        if not row:
            return Response(_result(404, "申请不存在"), status=status.HTTP_404_NOT_FOUND)
        if row[1] != "pending":
            return Response(_result(400, "该申请已处理"), status=status.HTTP_400_BAD_REQUEST)
        with connection.cursor() as c:
            c.execute(
                "UPDATE teacher_apply SET status = 'rejected', remark = %s, updated_at = NOW() WHERE id = %s",
                [remark or None, apply_id],
            )
        return Response(_result(data={"message": "已驳回"}))
    except Exception as e:
        return Response(_result(500, str(e)), status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ---------- 内容审核（帖子） ----------
@api_view(["GET"])
@admin_api_required
def post_list(request):
    """帖子列表，支持 status=1|0，keyword 搜内容"""
    status_val = request.GET.get("status")
    try:
        status_int = int(status_val) if status_val not in (None, "") else 1
    except ValueError:
        status_int = 1
    keyword = (request.GET.get("keyword") or "").strip()[:50]
    page = max(1, int(request.GET.get("page") or 1))
    page_size = min(50, max(1, int(request.GET.get("page_size") or 20)))
    start = (page - 1) * page_size
    qs = Post.objects.filter(status=status_int).order_by("-id")
    if keyword:
        qs = qs.filter(content__icontains=keyword)
    total = qs.count()
    posts = list(qs[start : start + page_size])
    user_ids = list({p.user_id for p in posts})
    users = {u.id: u for u in User.objects.filter(id__in=user_ids)} if user_ids else {}
    items = []
    for p in posts:
        u = users.get(p.user_id)
        items.append({
            "id": p.id,
            "userId": p.user_id,
            "nickname": getattr(u, "nickname", None) or f"用户{p.user_id}",
            "content": (p.content or "")[:200],
            "mediaType": p.media_type or "image_text",
            "status": p.status,
            "likeCount": p.like_count,
            "commentCount": p.comment_count,
            "createdAt": p.created_at.isoformat() if p.created_at else None,
        })
    return Response(_result(data={"list": items, "total": total, "hasMore": len(posts) == page_size}))


@api_view(["POST"])
@admin_api_required
def post_set_status(request, post_id):
    """设置帖子状态：1 正常 0 下架/隐藏"""
    try:
        status_val = request.data.get("status")
        if status_val is None:
            return Response(_result(400, "缺少 status"), status=status.HTTP_400_BAD_REQUEST)
        s = int(status_val)
        if s not in (0, 1):
            return Response(_result(400, "status 须为 0 或 1"), status=status.HTTP_400_BAD_REQUEST)
        p = Post.objects.filter(id=post_id).first()
        if not p:
            return Response(_result(404, "帖子不存在"), status=status.HTTP_404_NOT_FOUND)
        Post.objects.filter(id=post_id).update(status=s)
        return Response(_result(data={"message": "已下架" if s == 0 else "已恢复"}))
    except Exception as e:
        return Response(_result(500, str(e)), status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ---------- 举报 ----------
@api_view(["GET"])
@admin_api_required
def report_list(request):
    """举报列表，支持 status=pending|handled"""
    status_filter = (request.GET.get("status") or "pending").strip().lower()
    if status_filter not in ("pending", "handled"):
        status_filter = "pending"
    page = max(1, int(request.GET.get("page") or 1))
    page_size = min(50, max(1, int(request.GET.get("page_size") or 20)))
    start = (page - 1) * page_size
    qs = Report.objects.filter(status=status_filter).order_by("-id")[start : start + page_size]
    reporter_ids = list({r.reporter_id for r in qs})
    users = {u.id: u for u in User.objects.filter(id__in=reporter_ids)} if reporter_ids else {}
    items = []
    for r in qs:
        u = users.get(r.reporter_id)
        items.append({
            "id": r.id,
            "reporterId": r.reporter_id,
            "reporterNickname": getattr(u, "nickname", None) or f"用户{r.reporter_id}",
            "targetType": r.target_type,
            "targetId": r.target_id,
            "reason": r.reason or "",
            "status": r.status,
            "handleResult": r.handle_result or "",
            "handledAt": r.handled_at.isoformat() if r.handled_at else None,
            "createdAt": r.created_at.isoformat() if r.created_at else None,
        })
    return Response(_result(data={"list": items, "hasMore": len(qs) == page_size}))


@api_view(["POST"])
@admin_api_required
def report_handle(request, report_id):
    """处理举报：status=handled, handle_result 可选"""
    try:
        r = Report.objects.filter(id=report_id).first()
        if not r:
            return Response(_result(404, "举报不存在"), status=status.HTTP_404_NOT_FOUND)
        if r.status != "pending":
            return Response(_result(400, "已处理过"), status=status.HTTP_400_BAD_REQUEST)
        handle_result = (request.data.get("handleResult") or request.data.get("handle_result") or "").strip()[:255]
        Report.objects.filter(id=report_id).update(
            status="handled",
            handle_result=handle_result or None,
            handled_at=timezone.now(),
        )
        return Response(_result(data={"message": "已处理"}))
    except Exception as e:
        return Response(_result(500, str(e)), status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ---------- 提现审核 ----------
@api_view(["GET"])
@admin_api_required
def withdraw_list(request):
    """提现申请列表，支持 status=pending|approved|rejected"""
    status_filter = (request.GET.get("status") or "pending").strip().lower()
    if status_filter not in ("pending", "approved", "rejected"):
        status_filter = "pending"
    page = max(1, int(request.GET.get("page") or 1))
    page_size = min(50, max(1, int(request.GET.get("page_size") or 20)))
    start = (page - 1) * page_size
    qs = WithdrawApply.objects.filter(status=status_filter).order_by("-id")[start : start + page_size]
    user_ids = list({w.user_id for w in qs})
    users = {u.id: u for u in User.objects.filter(id__in=user_ids)} if user_ids else {}
    items = []
    for w in qs:
        u = users.get(w.user_id)
        items.append({
            "id": w.id,
            "userId": w.user_id,
            "nickname": getattr(u, "nickname", None) or f"用户{w.user_id}",
            "mobile": getattr(u, "mobile", None) or "",
            "amount": float(w.amount),
            "bankCardSnapshot": w.bank_card_snapshot or "",
            "status": w.status,
            "remark": w.remark or "",
            "createdAt": w.created_at.isoformat() if w.created_at else None,
            "auditAt": w.audit_at.isoformat() if w.audit_at else None,
        })
    return Response(_result(data={"list": items, "hasMore": len(qs) == page_size}))


@api_view(["POST"])
@admin_api_required
def withdraw_approve(request, withdraw_id):
    """通过提现申请"""
    try:
        w = WithdrawApply.objects.filter(id=withdraw_id).first()
        if not w:
            return Response(_result(404, "申请不存在"), status=status.HTTP_404_NOT_FOUND)
        if w.status != "pending":
            return Response(_result(400, "已处理过"), status=status.HTTP_400_BAD_REQUEST)
        WithdrawApply.objects.filter(id=withdraw_id).update(
            status="approved",
            audit_at=timezone.now(),
        )
        return Response(_result(data={"message": "已通过"}))
    except Exception as e:
        return Response(_result(500, str(e)), status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["POST"])
@admin_api_required
def withdraw_reject(request, withdraw_id):
    """驳回提现申请"""
    remark = (request.data.get("remark") or "").strip()[:255]
    try:
        w = WithdrawApply.objects.filter(id=withdraw_id).first()
        if not w:
            return Response(_result(404, "申请不存在"), status=status.HTTP_404_NOT_FOUND)
        if w.status != "pending":
            return Response(_result(400, "已处理过"), status=status.HTTP_400_BAD_REQUEST)
        WithdrawApply.objects.filter(id=withdraw_id).update(
            status="rejected",
            remark=remark or None,
            audit_at=timezone.now(),
        )
        return Response(_result(data={"message": "已驳回"}))
    except Exception as e:
        return Response(_result(500, str(e)), status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ---------- 用户管理 ----------
@api_view(["GET"])
@admin_api_required
def user_list(request):
    """用户列表，keyword 搜手机号/昵称"""
    keyword = (request.GET.get("keyword") or "").strip()[:50]
    page = max(1, int(request.GET.get("page") or 1))
    page_size = min(50, max(1, int(request.GET.get("page_size") or 20)))
    start = (page - 1) * page_size
    qs = User.objects.all().order_by("-id")
    if keyword:
        from django.db.models import Q
        qs = qs.filter(Q(mobile__icontains=keyword) | Q(nickname__icontains=keyword))
    total = qs.count()
    users = list(qs[start : start + page_size])
    items = []
    for u in users:
        items.append({
            "id": u.id,
            "mobile": u.mobile or "",
            "nickname": u.nickname or f"用户{u.id}",
            "avatarUrl": getattr(u, "avatar_url", None) or "",
            "status": u.status,
            "createdAt": u.created_at.isoformat() if u.created_at else None,
        })
    return Response(_result(data={"list": items, "total": total, "hasMore": len(users) == page_size}))


@api_view(["POST"])
@admin_api_required
def user_set_status(request, user_id):
    """设置用户状态：0 禁用 1 正常"""
    try:
        status_val = request.data.get("status")
        if status_val is None:
            return Response(_result(400, "缺少 status"), status=status.HTTP_400_BAD_REQUEST)
        s = int(status_val)
        if s not in (0, 1):
            return Response(_result(400, "status 须为 0 或 1"), status=status.HTTP_400_BAD_REQUEST)
        u = User.objects.filter(id=user_id).first()
        if not u:
            return Response(_result(404, "用户不存在"), status=status.HTTP_404_NOT_FOUND)
        User.objects.filter(id=user_id).update(status=s)
        return Response(_result(data={"message": "已禁用" if s == 0 else "已启用"}))
    except Exception as e:
        return Response(_result(500, str(e)), status=status.HTTP_500_INTERNAL_SERVER_ERROR)
