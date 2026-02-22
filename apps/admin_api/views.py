# -*- coding: utf-8 -*-
"""管理后台 API：名师审核、内容、举报、提现、用户、核心数据看板、AI 提示词"""
import json
from datetime import timedelta
from decimal import Decimal

from django.core.cache import cache
from django.db import connection
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .auth import admin_api_required, _result
from apps.account.models import User, WithdrawApply
from apps.community.models import Post, Report, SystemNotification
from apps.system.models import Announcement


def _send_announcement_system_notification(announcement):
    """公告上架时给全量用户插入一条系统通知（分批，每批 500）"""
    try:
        user_ids = list(
            User.objects.exclude(mobile__startswith="deleted_").values_list("id", flat=True)
        )
        title = (announcement.title or "平台公告")[:255]
        content = (announcement.content or "")[:2000]
        extra = json.dumps(
            {"announcementId": announcement.id, "linkUrl": (announcement.link_url or "") or None},
            ensure_ascii=False,
        )[:1024]
        batch = 500
        for i in range(0, len(user_ids), batch):
            chunk = user_ids[i : i + batch]
            SystemNotification.objects.bulk_create([
                SystemNotification(
                    user_id=uid,
                    type="announcement",
                    title=title,
                    content=content,
                    extra_json=extra,
                )
                for uid in chunk
            ])
    except Exception:
        pass


# ---------- 核心数据看板（替代原仪表盘） ----------
@api_view(["GET"])
@admin_api_required
def core_data_board(request):
    """
    核心数据看板：实时数据 DAU/WAU/MAU、新增用户、留存率；
    业务数据：订单量/交易额、内容发布量、付费转化率；
    趋势数据：按 period=day|week|month|year 与 start_date/end_date 返回时间序列。
    """
    period = (request.GET.get("period") or "day").strip().lower()
    if period not in ("day", "week", "month", "year"):
        period = "day"
    start_date = (request.GET.get("start_date") or "").strip()
    end_date = (request.GET.get("end_date") or "").strip()
    now = timezone.now()
    today = now.date()

    try:
        with connection.cursor() as c:
            # 活跃用户：有发帖/订单/钱包流水任一行为的用户（无登录日志时用此近似）
            def distinct_users_sql(table, dt_col, since):
                return f"SELECT DISTINCT user_id FROM {table} WHERE {dt_col} >= %s"
            since_1d = now - timedelta(days=1)
            since_7d = now - timedelta(days=7)
            since_30d = now - timedelta(days=30)
            dau_set = set()
            for sql, params in [
                ("SELECT DISTINCT user_id FROM post WHERE created_at >= %s", [since_1d]),
                ("SELECT DISTINCT user_id FROM wallet_log WHERE created_at >= %s", [since_1d]),
                ("SELECT DISTINCT user_id FROM order_main WHERE created_at >= %s", [since_1d]),
            ]:
                c.execute(sql, params)
                dau_set.update(r[0] for r in c.fetchall())
            wau_set, mau_set = set(), set()
            for sql, params in [
                ("SELECT DISTINCT user_id FROM post WHERE created_at >= %s", [since_7d]),
                ("SELECT DISTINCT user_id FROM wallet_log WHERE created_at >= %s", [since_7d]),
                ("SELECT DISTINCT user_id FROM order_main WHERE created_at >= %s", [since_7d]),
            ]:
                c.execute(sql, params)
                wau_set.update(r[0] for r in c.fetchall())
            for sql, params in [
                ("SELECT DISTINCT user_id FROM post WHERE created_at >= %s", [since_30d]),
                ("SELECT DISTINCT user_id FROM wallet_log WHERE created_at >= %s", [since_30d]),
                ("SELECT DISTINCT user_id FROM order_main WHERE created_at >= %s", [since_30d]),
            ]:
                c.execute(sql, params)
                mau_set.update(r[0] for r in c.fetchall())

            # 新增用户：昨日、近7日、近30日
            c.execute(
                "SELECT COUNT(*) FROM user WHERE created_at >= %s AND created_at < %s",
                [today - timedelta(days=1), today],
            )
            new_users_1d = (c.fetchone() or (0,))[0]
            c.execute("SELECT COUNT(*) FROM user WHERE created_at >= %s", [since_7d])
            new_users_7d = (c.fetchone() or (0,))[0]
            c.execute("SELECT COUNT(*) FROM user WHERE created_at >= %s", [since_30d])
            new_users_30d = (c.fetchone() or (0,))[0]

            # 留存率：次日/7日/30日（注册于 N 天前的用户中，在之后有活动的比例）
            def retention(reg_days_ago, activity_days_ago):
                reg_start = today - timedelta(days=reg_days_ago + 1)
                reg_end = today - timedelta(days=reg_days_ago)
                act_start = today - timedelta(days=activity_days_ago)
                act_end = (today + timedelta(days=1)) if activity_days_ago == 0 else (today - timedelta(days=activity_days_ago - 1))
                c.execute(
                    "SELECT COUNT(*) FROM user WHERE created_at >= %s AND created_at < %s",
                    [reg_start, reg_end],
                )
                total = (c.fetchone() or (0,))[0]
                if total == 0:
                    return None
                c.execute(
                    "SELECT COUNT(DISTINCT u.id) FROM user u "
                    "INNER JOIN (SELECT user_id FROM post WHERE created_at >= %s AND created_at < %s "
                    "UNION SELECT user_id FROM wallet_log WHERE created_at >= %s AND created_at < %s "
                    "UNION SELECT user_id FROM order_main WHERE created_at >= %s AND created_at < %s) a ON u.id = a.user_id "
                    "WHERE u.created_at >= %s AND u.created_at < %s",
                    [act_start, act_end, act_start, act_end, act_start, act_end, reg_start, reg_end],
                )
                active = (c.fetchone() or (0,))[0]
                return round(100.0 * active / total, 1)
            retention_1d = retention(1, 0)
            retention_7d = retention(7, 6)
            retention_30d = retention(30, 29)

            # 业务数据
            c.execute(
                "SELECT COUNT(*), COALESCE(SUM(amount),0) FROM order_main WHERE status = 'paid' AND paid_at IS NOT NULL"
            )
            row = c.fetchone()
            order_count = (row[0] or 0)
            gmv = float(row[1] or 0)
            post_count = Post.objects.filter(status=1).count()
            total_users = User.objects.count()
            c.execute("SELECT COUNT(DISTINCT user_id) FROM order_main WHERE status = 'paid' AND paid_at IS NOT NULL")
            paid_users = (c.fetchone() or (0,))[0]
            conversion = round(100.0 * paid_users / total_users, 1) if total_users else 0

            # 待办数量
            c.execute("SELECT COUNT(*) FROM teacher_apply WHERE status = 'pending'")
            teacher_pending = (c.fetchone() or (0,))[0]
            withdraw_pending = WithdrawApply.objects.filter(status="pending").count()
            report_pending = Report.objects.filter(status="pending").count()

        # 趋势：按 period 聚合
        trend = []
        if start_date and end_date:
            try:
                from datetime import datetime as dt
                start = dt.strptime(start_date, "%Y-%m-%d").date()
                end = dt.strptime(end_date, "%Y-%m-%d").date()
            except Exception:
                start, end = today - timedelta(days=30), today
        else:
            start = today - timedelta(days=30)
            end = today
        with connection.cursor() as c:
            if period == "day":
                c.execute(
                    "SELECT DATE(created_at) AS d, COUNT(*) AS cnt FROM user WHERE created_at >= %s AND created_at <= %s GROUP BY DATE(created_at) ORDER BY d",
                    [start, end],
                )
                new_by_day = {str(r[0]): r[1] for r in c.fetchall()}
                c.execute(
                    "SELECT DATE(created_at) AS d, COUNT(*) FROM post WHERE created_at >= %s AND created_at <= %s GROUP BY DATE(created_at) ORDER BY d",
                    [start, end],
                )
                post_by_day = {str(r[0]): r[1] for r in c.fetchall()}
                c.execute(
                    "SELECT DATE(paid_at) AS d, COUNT(*), COALESCE(SUM(amount),0) FROM order_main WHERE status='paid' AND paid_at IS NOT NULL AND paid_at >= %s AND paid_at <= %s GROUP BY DATE(paid_at) ORDER BY d",
                    [start, end],
                )
                order_by_day = {}
                gmv_by_day = {}
                for r in c.fetchall():
                    order_by_day[str(r[0])] = r[1]
                    gmv_by_day[str(r[0])] = float(r[2])
                d = start
                while d <= end:
                    ds = str(d)
                    trend.append({
                        "date": ds,
                        "newUsers": new_by_day.get(ds, 0),
                        "postCount": post_by_day.get(ds, 0),
                        "orderCount": order_by_day.get(ds, 0),
                        "gmv": gmv_by_day.get(ds, 0),
                    })
                    d += timedelta(days=1)
            else:
                c.execute(
                    "SELECT DATE(created_at) AS d, COUNT(*) FROM user WHERE created_at >= %s AND created_at <= %s GROUP BY DATE(created_at) ORDER BY d",
                    [start, end],
                )
                rows = c.fetchall()
                for r in rows:
                    trend.append({"date": str(r[0]), "newUsers": r[1], "postCount": 0, "orderCount": 0, "gmv": 0})
                if not trend and start <= end:
                    trend = [{"date": str(start), "newUsers": 0, "postCount": 0, "orderCount": 0, "gmv": 0}]

        return Response(_result(data={
            "realtime": {
                "dau": len(dau_set),
                "wau": len(wau_set),
                "mau": len(mau_set),
                "newUsers1d": new_users_1d,
                "newUsers7d": new_users_7d,
                "newUsers30d": new_users_30d,
                "retention1d": retention_1d,
                "retention7d": retention_7d,
                "retention30d": retention_30d,
            },
            "business": {
                "orderCount": order_count,
                "gmv": gmv,
                "postCount": post_count,
                "paidConversionRate": conversion,
            },
            "pending": {
                "teacherPendingCount": teacher_pending,
                "withdrawPendingCount": withdraw_pending,
                "reportPendingCount": report_pending,
            },
            "trend": trend,
            "period": period,
            "startDate": str(start),
            "endDate": str(end),
        }))
    except Exception as e:
        return Response(_result(500, str(e)), status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["GET"])
@admin_api_required
def dashboard_stats(request):
    """兼容旧接口：返回核心看板中的 pending + 总用户/帖子数"""
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
        if status_filter == "approved" and items:
            user_ids = [x["userId"] for x in items]
            price_map = {}
            try:
                with connection.cursor() as c2:
                    c2.execute(
                        "SELECT user_id, consult_price FROM user_profile WHERE user_id IN (%s) AND is_master = 1"
                        % ",".join(["%s"] * len(user_ids)),
                        user_ids,
                    )
                    price_map = {r[0]: float(r[1]) if r[1] is not None else 10.0 for r in c2.fetchall()}
            except Exception:
                pass
            for x in items:
                x["consultPrice"] = price_map.get(x["userId"], 10.0)
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
            try:
                c.execute(
                    "UPDATE user_profile SET consult_price = 10 WHERE user_id = %s AND (consult_price IS NULL OR consult_price = 0)",
                    [user_id],
                )
            except Exception:
                pass
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


@api_view(["POST"])
@admin_api_required
def teacher_set_consult_price(request, user_id):
    """设置名师咨询单价（元）。body: { "consultPrice": 10 }"""
    try:
        price = request.data.get("consultPrice") if request.data is not None else None
        if price is None:
            return Response(_result(400, "缺少 consultPrice"), status=status.HTTP_400_BAD_REQUEST)
        try:
            price_val = round(float(price), 2)
        except (TypeError, ValueError):
            return Response(_result(400, "consultPrice 无效"), status=status.HTTP_400_BAD_REQUEST)
        if price_val < 0 or price_val > 99999.99:
            return Response(_result(400, "单价需在 0～99999.99 之间"), status=status.HTTP_400_BAD_REQUEST)
        with connection.cursor() as c:
            c.execute("SELECT 1 FROM user_profile WHERE user_id = %s AND is_master = 1", [user_id])
            if c.fetchone() is None:
                return Response(_result(404, "该用户不是名师"), status=status.HTTP_404_NOT_FOUND)
            c.execute(
                "UPDATE user_profile SET consult_price = %s, updated_at = NOW() WHERE user_id = %s",
                [price_val, user_id],
            )
        return Response(_result(data={"message": "已更新", "consultPrice": price_val}))
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
        media_urls = []
        if p.media_urls_json:
            try:
                media_urls = json.loads(p.media_urls_json) if isinstance(p.media_urls_json, str) else p.media_urls_json
            except (TypeError, ValueError):
                pass
        if not isinstance(media_urls, list):
            media_urls = []
        media_cover_urls = []
        if getattr(p, "media_cover_urls_json", None):
            try:
                media_cover_urls = json.loads(p.media_cover_urls_json) if isinstance(p.media_cover_urls_json, str) else p.media_cover_urls_json
            except (TypeError, ValueError):
                pass
        if not isinstance(media_cover_urls, list):
            media_cover_urls = []
        items.append({
            "id": p.id,
            "userId": p.user_id,
            "nickname": getattr(u, "nickname", None) or f"用户{p.user_id}",
            "content": (p.content or "")[:200],
            "contentFull": p.content or "",
            "mediaType": p.media_type or "image_text",
            "mediaUrls": media_urls,
            "mediaCoverUrls": media_cover_urls,
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
    """举报列表，支持 status=pending|handled；返回举报人、被举报人（帖子作者或用户）"""
    status_filter = (request.GET.get("status") or "pending").strip().lower()
    if status_filter not in ("pending", "handled"):
        status_filter = "pending"
    page = max(1, int(request.GET.get("page") or 1))
    page_size = min(50, max(1, int(request.GET.get("page_size") or 20)))
    start = (page - 1) * page_size
    qs = Report.objects.filter(status=status_filter).order_by("-id")[start : start + page_size]
    reporter_ids = list({r.reporter_id for r in qs})
    users = {u.id: u for u in User.objects.filter(id__in=reporter_ids)} if reporter_ids else {}

    # 被举报人：帖子举报为帖子作者，用户举报为被举报用户
    target_user_ids = set()
    post_id_to_user = {}
    post_ids = [r.target_id for r in qs if (r.target_type or "").strip().lower() == "post"]
    if post_ids:
        for row in Post.objects.filter(id__in=post_ids).values_list("id", "user_id"):
            post_id_to_user[row[0]] = row[1]
            target_user_ids.add(row[1])
    for r in qs:
        if (r.target_type or "").strip().lower() == "user":
            target_user_ids.add(r.target_id)
    target_users = {u.id: u for u in User.objects.filter(id__in=target_user_ids)} if target_user_ids else {}

    items = []
    for r in qs:
        u = users.get(r.reporter_id)
        target_uid = None
        if (r.target_type or "").strip().lower() == "user":
            target_uid = r.target_id
        elif (r.target_type or "").strip().lower() == "post":
            target_uid = post_id_to_user.get(r.target_id)
        target_user = target_users.get(target_uid) if target_uid else None
        target_nickname = (getattr(target_user, "nickname", None) or (f"用户{target_uid}" if target_uid else "")) if target_user or target_uid else "-"
        items.append({
            "id": r.id,
            "reporterId": r.reporter_id,
            "reporterNickname": getattr(u, "nickname", None) or f"用户{r.reporter_id}",
            "targetType": r.target_type,
            "targetId": r.target_id,
            "targetUserId": target_uid,
            "targetNickname": target_nickname,
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
    """处理举报：status=handled；可选 punish_post=1 下架被举报帖子，punish_user=1 禁用被举报用户"""
    try:
        r = Report.objects.filter(id=report_id).first()
        if not r:
            return Response(_result(404, "举报不存在"), status=status.HTTP_404_NOT_FOUND)
        if r.status != "pending":
            return Response(_result(400, "已处理过"), status=status.HTTP_400_BAD_REQUEST)
        data = request.data or {}
        handle_result = (data.get("handleResult") or data.get("handle_result") or "").strip()[:255]
        punish_post = data.get("punishPost") or data.get("punish_post")
        punish_user = data.get("punishUser") or data.get("punish_user")
        Report.objects.filter(id=report_id).update(
            status="handled",
            handle_result=handle_result or None,
            handled_at=timezone.now(),
        )
        if punish_post and r.target_type == "post":
            p = Post.objects.filter(id=r.target_id).first()
            if p:
                Post.objects.filter(id=r.target_id).update(status=0)
                extra = json.dumps({"postId": p.id}, ensure_ascii=False)
                SystemNotification.objects.create(
                    user_id=p.user_id,
                    type="post_removed",
                    title="您的帖子已被下架",
                    content=handle_result or "因违反社区规范，您的帖子已被下架。如有疑问请联系客服。",
                    extra_json=extra,
                )
        if punish_user:
            uid = r.target_id if r.target_type == "user" else None
            if uid is None and r.target_type == "post":
                p = Post.objects.filter(id=r.target_id).first()
                if p:
                    uid = p.user_id
            if uid is not None:
                User.objects.filter(id=uid).update(status=0)
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
    """用户列表，keyword 搜手机号/昵称。已注销用户（mobile 以 deleted_ 开头）不展示"""
    keyword = (request.GET.get("keyword") or "").strip()[:50]
    page = max(1, int(request.GET.get("page") or 1))
    page_size = min(50, max(1, int(request.GET.get("page_size") or 20)))
    start = (page - 1) * page_size
    qs = User.objects.all().exclude(mobile__startswith="deleted_").order_by("-id")
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


def _clear_user_related_records(user_id):
    """删除用户时清空该用户在所有关联表中的记录（在事务外按表执行，单表失败不阻断）"""
    uid = [user_id]
    with connection.cursor() as c:
        # IM：消息、会话成员、群申请、聊天申请
        try:
            c.execute("DELETE FROM message WHERE sender_id = %s", uid)
            c.execute("DELETE FROM conversation_member WHERE user_id = %s", uid)
            c.execute("DELETE FROM chat_apply WHERE from_user_id = %s OR to_user_id = %s", [user_id, user_id])
        except Exception:
            pass
        try:
            c.execute("DELETE FROM group_join_apply WHERE user_id = %s", uid)
        except Exception:
            pass
        # 互动通知、关注、点赞、收藏
        try:
            c.execute("DELETE FROM notification WHERE user_id = %s OR from_user_id = %s", [user_id, user_id])
            c.execute("DELETE FROM user_follow WHERE user_id = %s OR target_user_id = %s", [user_id, user_id])
            c.execute("DELETE FROM post_like WHERE user_id = %s", uid)
            c.execute("DELETE FROM post_favorite WHERE user_id = %s", uid)
        except Exception:
            pass
        # 评论：该用户发的评论 + 该用户帖子下的评论
        try:
            c.execute("DELETE FROM comment WHERE user_id = %s", uid)
            c.execute("SELECT id FROM post WHERE user_id = %s", uid)
            post_ids = [r[0] for r in c.fetchall()]
            if post_ids:
                placeholders = ",".join(["%s"] * len(post_ids))
                c.execute(f"DELETE FROM comment WHERE post_id IN ({placeholders})", post_ids)
                c.execute(f"DELETE FROM post_like WHERE post_id IN ({placeholders})", post_ids)
                c.execute(f"DELETE FROM post_favorite WHERE post_id IN ({placeholders})", post_ids)
            c.execute("DELETE FROM post WHERE user_id = %s", uid)
        except Exception:
            pass
        # 举报、处罚、匹配配置、语音房间
        try:
            c.execute("DELETE FROM report WHERE reporter_id = %s", uid)
            c.execute("DELETE FROM user_punish WHERE user_id = %s", uid)
            c.execute("DELETE FROM match_config WHERE user_id = %s", uid)
        except Exception:
            pass
        try:
            c.execute("DELETE FROM voice_room WHERE user_id_1 = %s OR user_id_2 = %s", [user_id, user_id])
        except Exception:
            pass
        # AI 名师会话及消息
        try:
            c.execute("SELECT id FROM ai_master_chat_session WHERE user_id = %s", uid)
            session_ids = [r[0] for r in c.fetchall()]
            if session_ids:
                placeholders = ",".join(["%s"] * len(session_ids))
                c.execute(f"DELETE FROM ai_master_chat_message WHERE session_id IN ({placeholders})", session_ids)
            c.execute("DELETE FROM ai_master_chat_session WHERE user_id = %s", uid)
        except Exception:
            pass
        # 用户扩展与命理
        try:
            c.execute("DELETE FROM user_profile WHERE user_id = %s", uid)
            c.execute("DELETE FROM login_device WHERE user_id = %s", uid)
            c.execute("DELETE FROM user_bazi WHERE user_id = %s", uid)
            c.execute("DELETE FROM bazi_report WHERE user_id = %s", uid)
            c.execute("DELETE FROM fengshui_record WHERE user_id = %s", uid)
            c.execute("DELETE FROM hepan_record WHERE user_id = %s OR target_user_id = %s", [user_id, user_id])
            c.execute("DELETE FROM teacher_apply WHERE user_id = %s", uid)
        except Exception:
            pass
    # 今日养生缓存（按 user_id 的 key 无法批量删，只删常见 key 模式）
    try:
        from apps.fortune.views import HEALTH_CACHE_PREFIX
        from datetime import date
        today = date.today().strftime("%Y-%m-%d")
        cache.delete(f"{HEALTH_CACHE_PREFIX}{user_id}:{today}")
    except Exception:
        pass


@api_view(["POST"])
@admin_api_required
def user_delete(request, user_id):
    """删除用户：软删 user 并清空该用户在所有关联表中的记录"""
    try:
        u = User.objects.filter(id=user_id).first()
        if not u:
            return Response(_result(404, "用户不存在"), status=status.HTTP_404_NOT_FOUND)
        _clear_user_related_records(user_id)
        User.objects.filter(id=user_id).update(
            status=0,
            mobile=f"deleted_{user_id}",  # 保持 uk_mobile 唯一，不能置空
            password_hash="",
            nickname=f"已删除_{user_id}",
            avatar_url="",
            updated_at=timezone.now(),
        )
        return Response(_result(data={"message": "已删除"}))
    except Exception as e:
        return Response(_result(500, str(e)), status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ---------- AI 提示词配置 ----------
# 不在后台展示/编辑的 key（仅由代码使用默认提示词）
AI_PROMPT_HIDDEN_KEYS = {"xiyongshen"}


@api_view(["GET"])
@admin_api_required
def ai_prompt_list(request):
    """所有 AI 提示词列表（不含喜用神等隐藏项）"""
    try:
        with connection.cursor() as c:
            c.execute("SELECT `key`, name, content, updated_at FROM ai_prompt ORDER BY `key`")
            rows = c.fetchall()
            col = [d[0] for d in c.description]
        items = [dict(zip(col, row)) for row in rows]
        items = [x for x in items if x.get("key") not in AI_PROMPT_HIDDEN_KEYS]
        for x in items:
            u = x.pop("updated_at", None)
            x["updatedAt"] = u.isoformat() if u else None
            x["key"] = x.get("key")
        return Response(_result(data={"list": items}))
    except Exception as e:
        return Response(_result(500, str(e)), status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["GET"])
@admin_api_required
def ai_prompt_get(request, key):
    """单个 AI 提示词"""
    if key in AI_PROMPT_HIDDEN_KEYS:
        return Response(_result(404, "不存在"), status=status.HTTP_404_NOT_FOUND)
    try:
        with connection.cursor() as c:
            c.execute("SELECT `key`, name, content, updated_at FROM ai_prompt WHERE `key` = %s", [key])
            row = c.fetchone()
        if not row:
            return Response(_result(404, "不存在"), status=status.HTTP_404_NOT_FOUND)
        col = ["key", "name", "content", "updated_at"]
        item = dict(zip(col, row))
        item["updatedAt"] = item["updated_at"].isoformat() if item.get("updated_at") else None
        del item["updated_at"]
        return Response(_result(data=item))
    except Exception as e:
        return Response(_result(500, str(e)), status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ---------- 平台公告 ----------
@api_view(["GET"])
@admin_api_required
def announcement_list(request):
    """平台公告列表，支持 status=1|0，keyword 搜标题，分页"""
    status_val = request.GET.get("status")
    try:
        status_int = int(status_val) if status_val not in (None, "") else None
    except ValueError:
        status_int = None
    keyword = (request.GET.get("keyword") or "").strip()[:50]
    page = max(1, int(request.GET.get("page") or 1))
    page_size = min(50, max(1, int(request.GET.get("page_size") or 20)))
    start = (page - 1) * page_size
    qs = Announcement.objects.all().order_by("-sort_order", "-created_at")
    if status_int is not None:
        qs = qs.filter(status=status_int)
    if keyword:
        qs = qs.filter(title__icontains=keyword)
    total = qs.count()
    items = list(qs[start : start + page_size])
    out = []
    for a in items:
        out.append({
            "id": a.id,
            "title": a.title or "",
            "content": (a.content or "")[:500],
            "linkUrl": a.link_url or "",
            "status": a.status,
            "sortOrder": a.sort_order,
            "startAt": timezone.localtime(a.start_at).isoformat() if a.start_at else None,
            "endAt": timezone.localtime(a.end_at).isoformat() if a.end_at else None,
            "createdAt": timezone.localtime(a.created_at).isoformat() if a.created_at else None,
        })
    return Response(_result(data={"list": out, "total": total, "hasMore": len(items) == page_size}))


@api_view(["POST"])
@admin_api_required
def announcement_create(request):
    """新增平台公告。body: title, content?, linkUrl?, status?, sortOrder?, startAt?, endAt?"""
    try:
        data = request.data or {}
        title = (data.get("title") or "").strip()[:128]
        if not title:
            return Response(_result(400, "标题不能为空"), status=status.HTTP_400_BAD_REQUEST)
        content = (data.get("content") or "").strip() or None
        link_url = (data.get("linkUrl") or data.get("link_url") or "").strip()[:512] or None
        try:
            status_int = int(data.get("status", 1))
        except (TypeError, ValueError):
            status_int = 1
        status_int = 1 if status_int != 0 else 0
        try:
            sort_order = int(data.get("sortOrder") or data.get("sort_order") or 0)
        except (TypeError, ValueError):
            sort_order = 0
        from django.utils.dateparse import parse_datetime
        start_at = None
        end_at = None
        for key in ("startAt", "start_at"):
            raw = data.get(key)
            if raw:
                try:
                    dt = parse_datetime(str(raw))
                    if dt:
                        start_at = dt
                        break
                except Exception:
                    pass
        for key in ("endAt", "end_at"):
            raw = data.get(key)
            if raw:
                try:
                    dt = parse_datetime(str(raw))
                    if dt:
                        end_at = dt
                        break
                except Exception:
                    pass
        a = Announcement.objects.create(
            title=title,
            content=content,
            link_url=link_url,
            status=status_int,
            sort_order=sort_order,
            start_at=start_at,
            end_at=end_at,
        )
        if status_int == 1:
            _send_announcement_system_notification(a)
        return Response(_result(data={"id": a.id, "message": "已创建"}))
    except Exception as e:
        return Response(_result(500, str(e)), status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def _parse_optional_datetime(data, key):
    raw = data.get(key) or data.get(key.replace("At", "_at"))
    if not raw:
        return None
    from django.utils.dateparse import parse_datetime
    try:
        return parse_datetime(str(raw))
    except Exception:
        return None


@api_view(["GET"])
@admin_api_required
def announcement_get(request, announcement_id):
    """单条平台公告详情（编辑用）"""
    a = Announcement.objects.filter(id=announcement_id).first()
    if not a:
        return Response(_result(404, "公告不存在"), status=status.HTTP_404_NOT_FOUND)
    return Response(_result(data={
        "id": a.id,
        "title": a.title or "",
        "content": a.content or "",
        "linkUrl": a.link_url or "",
        "status": a.status,
        "sortOrder": a.sort_order,
        "startAt": timezone.localtime(a.start_at).isoformat() if a.start_at else None,
        "endAt": timezone.localtime(a.end_at).isoformat() if a.end_at else None,
        "createdAt": timezone.localtime(a.created_at).isoformat() if a.created_at else None,
    }))


@api_view(["PUT", "POST"])
@admin_api_required
def announcement_update(request, announcement_id):
    """更新平台公告。body: title?, content?, linkUrl?, status?, sortOrder?, startAt?, endAt?"""
    a = Announcement.objects.filter(id=announcement_id).first()
    if not a:
        return Response(_result(404, "公告不存在"), status=status.HTTP_404_NOT_FOUND)
    try:
        data = request.data or {}
        title = (data.get("title") or "").strip()[:128]
        if title:
            a.title = title
        content = data.get("content")
        if content is not None:
            a.content = (content or "").strip() or None
        link_url = data.get("linkUrl") or data.get("link_url")
        if link_url is not None:
            val = (str(link_url).strip() or None)
            a.link_url = (val[:512] if val else None)
        if "status" in data:
            try:
                a.status = 0 if int(data.get("status")) == 0 else 1
            except (TypeError, ValueError):
                pass
        if "sortOrder" in data or "sort_order" in data:
            try:
                a.sort_order = int(data.get("sortOrder") or data.get("sort_order") or 0)
            except (TypeError, ValueError):
                pass
        start_at = _parse_optional_datetime(data, "startAt")
        if start_at is not None:
            a.start_at = start_at
        end_at = _parse_optional_datetime(data, "endAt")
        if end_at is not None:
            a.end_at = end_at
        a.save()
        return Response(_result(data={"message": "已保存"}))
    except Exception as e:
        return Response(_result(500, str(e)), status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["POST"])
@admin_api_required
def announcement_set_status(request, announcement_id):
    """上/下架公告：status=1 展示 0 下架"""
    try:
        status_val = request.data.get("status")
        if status_val is None:
            return Response(_result(400, "缺少 status"), status=status.HTTP_400_BAD_REQUEST)
        s = 0 if int(status_val) == 0 else 1
        a = Announcement.objects.filter(id=announcement_id).first()
        if not a:
            return Response(_result(404, "公告不存在"), status=status.HTTP_404_NOT_FOUND)
        Announcement.objects.filter(id=announcement_id).update(status=s)
        if s == 1:
            _send_announcement_system_notification(a)
        return Response(_result(data={"message": "已下架" if s == 0 else "已上架"}))
    except Exception as e:
        return Response(_result(500, str(e)), status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["POST"])
@admin_api_required
def announcement_delete(request, announcement_id):
    """删除公告（物理删除）"""
    a = Announcement.objects.filter(id=announcement_id).first()
    if not a:
        return Response(_result(404, "公告不存在"), status=status.HTTP_404_NOT_FOUND)
    a.delete()
    return Response(_result(data={"message": "已删除"}))


# ---------- AI 提示词配置 ----------
# 不在后台展示/编辑的 key（仅由代码使用默认提示词）
AI_PROMPT_HIDDEN_KEYS = {"xiyongshen"}


@api_view(["PUT", "POST"])
@admin_api_required
def ai_prompt_update(request, key):
    """更新 AI 提示词。body: { name?, content }"""
    if key in AI_PROMPT_HIDDEN_KEYS:
        return Response(_result(404, "不允许修改"), status=status.HTTP_404_NOT_FOUND)
    try:
        data = request.data or {}
        name = (data.get("name") or "").strip()[:128]
        content = (data.get("content") or "").strip()
        if not content:
            return Response(_result(400, "content 不能为空"), status=status.HTTP_400_BAD_REQUEST)
        with connection.cursor() as c:
            c.execute(
                "INSERT INTO ai_prompt (`key`, name, content, updated_at) VALUES (%s, %s, %s, NOW()) "
                "ON DUPLICATE KEY UPDATE name = VALUES(name), content = VALUES(content), updated_at = NOW()",
                [key, name or key, content],
            )
        return Response(_result(data={"message": "已保存", "key": key}))
    except Exception as e:
        return Response(_result(500, str(e)), status=status.HTTP_500_INTERNAL_SERVER_ERROR)
