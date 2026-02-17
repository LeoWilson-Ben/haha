"""
命理服务：排盘、喜用神、合盘、风水、今日运势（架构设计 /api/fortune）
先提供排盘占位接口，后续接入真实算法。
今日运势基于用户出生日期调用通义千问生成，每天每用户只生成一次，结果缓存在 Redis。
风水分析：用户上传房屋图片，调用 Qwen-VL 进行风水分析。
"""
import base64
import logging
import os
from datetime import date

from django.core.cache import cache

logger = logging.getLogger(__name__)

FORTUNE_CACHE_PREFIX = "fortune:daily:"
FORTUNE_CACHE_TTL = 86400 * 2  # 48 小时，覆盖跨天请求
from django.db import connection
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.account.session_store import get_user_id_by_token


def _result(code=0, message="success", data=None):
    return {"code": code, "message": message, "data": data}


def _user_id_from_request(request):
    auth = request.META.get("HTTP_AUTHORIZATION") or ""
    if auth.startswith("Bearer "):
        token = auth[7:].strip()
        return get_user_id_by_token(token)
    return None


@api_view(["POST"])
@permission_classes([AllowAny])
def bazi_paipan(request):
    """
    八字排盘。body: { "calendarType": "solar|lunar", "birthDate": "1990-01-01", "birthTime": "08:30" }
    返回四柱、十神、神煞等占位结构，后续替换为真实算法。
    """
    calendar_type = (request.data.get("calendarType") or "solar").strip().lower()
    birth_date = (request.data.get("birthDate") or "").strip()
    birth_time = (request.data.get("birthTime") or "").strip()

    if not birth_date:
        return Response(_result(400, "请选择出生日期"), status=status.HTTP_400_BAD_REQUEST)

    # 占位结果（真实算法接入前）
    data = {
        "calendarType": calendar_type,
        "birthDate": birth_date,
        "birthTime": birth_time or "子时",
        "pillar": {
            "year": ["庚午", "金马"],
            "month": ["戊寅", "土虎"],
            "day": ["甲子", "木鼠"],
            "hour": ["丙寅", "火虎"],
        },
        "shishen": {"year": "偏财", "month": "偏印", "day": "日主", "hour": "食神"},
        "shensha": ["文昌", "桃花"],
        "xiyongshen": {"喜神": "水", "用神": "木"},
        "algorithmVersion": "1.0",
    }
    return Response(_result(data=data))


@api_view(["GET"])
@permission_classes([AllowAny])
def bazi_status(request):
    """
    当前用户命理档案状态，含八字下次可修改日期（每自然季度 1 次）。
    未登录或未保存过八字时 nextEditableAt 为 null。
    """
    user_id = _user_id_from_request(request)
    if not user_id:
        return Response(_result(data={"nextEditableAt": None}))
    next_editable_at = None
    try:
        with connection.cursor() as c:
            c.execute(
                "SELECT next_editable_at FROM user_bazi WHERE user_id = %s",
                [user_id],
            )
            row = c.fetchone()
            if row and row[0]:
                next_editable_at = row[0].isoformat() if hasattr(row[0], "isoformat") else str(row[0])
    except Exception:
        pass
    return Response(_result(data={"nextEditableAt": next_editable_at}))


def _compute_xiyongshen(birth_date, birth_time):
    """调用 Qwen 根据出生日期时辰计算喜用神，返回 {"喜神":"水","用神":"木"} 或 None"""
    import json
    prompt = f"""根据出生信息计算八字喜用神。
出生日期：{birth_date}，出生时辰：{birth_time or '未知'}。
请仅返回 JSON，格式为：{{"喜神":"金|木|水|火|土","用神":"金|木|水|火|土"}}
五行只能为：金、木、水、火、土 之一。不要其他内容。"""
    try:
        from openai import OpenAI
        client = OpenAI(
            api_key=os.getenv("DASHSCOPE_API_KEY", "sk-0c014d6601794c9dbb248ea6892dcd55"),
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        completion = client.chat.completions.create(
            model="qwen-plus",
            messages=[
                {"role": "system", "content": "你是八字命理师，根据出生信息计算喜用神，五行仅限金木水火土，只输出 JSON。"},
                {"role": "user", "content": prompt},
            ],
            timeout=30.0,
        )
        raw = (completion.choices[0].message.content if completion.choices else "").strip()
        for s in (raw, raw.split("```")[0].strip() if "```" in raw else raw):
            s = s.strip().strip("`")
            try:
                d = json.loads(s)
                xi = str(d.get("喜神") or "").strip()
                yong = str(d.get("用神") or "").strip()
                for w in ("金", "木", "水", "火", "土"):
                    if w in xi:
                        xi = w
                        break
                if xi not in ("金", "木", "水", "火", "土"):
                    xi = "木"
                for w in ("金", "木", "水", "火", "土"):
                    if w in yong:
                        yong = w
                        break
                if yong not in ("金", "木", "水", "火", "土"):
                    yong = "水"
                return {"喜神": xi, "用神": yong}
            except (json.JSONDecodeError, TypeError):
                continue
    except Exception as e:
        logger.exception("喜用神计算失败: %s", e)
    return {"喜神": "木", "用神": "水"}


def _get_user_xiyongshen(user_id):
    """获取用户喜用神，若未计算且有出生信息则计算并保存"""
    birth_date, birth_time = _get_user_birth_info(user_id)
    if not birth_date:
        return None, None, None
    xiyongshen = None
    try:
        with connection.cursor() as c:
            c.execute("SELECT xiyongshen FROM user_profile WHERE user_id = %s", [user_id])
            row = c.fetchone()
            if row and row[0]:
                import json
                try:
                    xiyongshen = json.loads(str(row[0]).strip())
                except Exception:
                    pass
    except Exception:
        pass
    if not xiyongshen or not isinstance(xiyongshen, dict):
        xiyongshen = _compute_xiyongshen(birth_date, birth_time)
        import json
        try:
            with connection.cursor() as c:
                c.execute(
                    "UPDATE user_profile SET xiyongshen = %s, updated_at = NOW() WHERE user_id = %s",
                    [json.dumps(xiyongshen, ensure_ascii=False), user_id],
                )
        except Exception:
            try:
                with connection.cursor() as c:
                    c.execute(
                        "ALTER TABLE user_profile ADD COLUMN xiyongshen VARCHAR(64) DEFAULT NULL AFTER birth_time",
                    )
                    c.execute(
                        "UPDATE user_profile SET xiyongshen = %s, updated_at = NOW() WHERE user_id = %s",
                        [json.dumps(xiyongshen, ensure_ascii=False), user_id],
                    )
            except Exception:
                pass
    xi = xiyongshen.get("喜神") if isinstance(xiyongshen, dict) else None
    yong = xiyongshen.get("用神") if isinstance(xiyongshen, dict) else None
    return birth_date, xi, yong


def _get_user_birth_info(user_id):
    """获取用户出生日期和时辰"""
    try:
        with connection.cursor() as c:
            c.execute(
                "SELECT birth_date, birth_time FROM user_profile WHERE user_id = %s",
                [user_id],
            )
            row = c.fetchone()
    except Exception:
        try:
            with connection.cursor() as c:
                c.execute("SELECT birth_date FROM user_profile WHERE user_id = %s", [user_id])
                row = c.fetchone()
        except Exception:
            row = None
    if row and row[0]:
        birth_date = row[0].strftime("%Y-%m-%d") if hasattr(row[0], "strftime") else str(row[0])
        birth_time = (str(row[1]).strip() if len(row) > 1 and row[1] else None) or "子时"
        return birth_date, birth_time
    return None, None


@api_view(["GET"])
@permission_classes([AllowAny])
def today_fortune(request):
    """
    今日运势：根据用户出生日期，调用通义千问生成当日运势。
    需登录，且用户需已填写出生日期。每天每用户只生成一次，结果缓存于 Redis。
    """
    user_id = _user_id_from_request(request)
    if not user_id:
        return Response(_result(401, "请先登录"), status=status.HTTP_401_UNAUTHORIZED)
    birth_date, birth_time = _get_user_birth_info(user_id)
    if not birth_date:
        return Response(_result(400, "请先完善出生日期"), status=status.HTTP_400_BAD_REQUEST)

    today_str = date.today().strftime("%Y-%m-%d")
    cache_key = f"{FORTUNE_CACHE_PREFIX}{user_id}:{today_str}"
    cached = cache.get(cache_key)
    if cached is not None:
        return Response(_result(data={"content": cached, "birthDate": birth_date}))

    today = date.today().strftime("%Y年%m月%d日")
    prompt = f"""你是一位传统文化命理师。根据以下信息，为用户撰写今日运势（{today}）：
用户出生日期：{birth_date}，出生时辰：{birth_time or '未知'}。
请用简洁、温馨的语气，从事业、感情、健康、财运等方面给出 2-3 句运势建议，控制在 150 字以内。"""
    try:
        from openai import OpenAI
        client = OpenAI(
            api_key=os.getenv("DASHSCOPE_API_KEY", "sk-0c014d6601794c9dbb248ea6892dcd55"),
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        completion = client.chat.completions.create(
            model="qwen-plus",
            messages=[
                {"role": "system", "content": "你是传统文化命理师，用简洁温和的语气回答问题。"},
                {"role": "user", "content": prompt},
            ],
            timeout=60.0,
        )
        content = (completion.choices[0].message.content if completion.choices else "").strip() or "今日宜静心修养，诸事顺遂。"
        cache.set(cache_key, content, timeout=FORTUNE_CACHE_TTL)
        return Response(_result(data={"content": content, "birthDate": birth_date}))
    except Exception as e:
        logger.exception("今日运势生成失败")
        return Response(
            _result(500, f"运势生成失败：{str(e)}"),
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["POST"])
@permission_classes([AllowAny])
def fengshui_analyze(request):
    """
    风水分析：用户上传房屋图片，调用 Qwen-VL 进行风水分析。
    需登录。body: multipart/form-data，key=file（图片文件）。
    """
    user_id = _user_id_from_request(request)
    if not user_id:
        return Response(_result(401, "请先登录"), status=status.HTTP_401_UNAUTHORIZED)

    f = request.FILES.get("file")
    if not f:
        return Response(_result(400, "请上传房屋图片"), status=status.HTTP_400_BAD_REQUEST)

    ext = (os.path.splitext(f.name or "")[1] or "").lower()
    if ext not in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
        return Response(_result(400, "仅支持 jpg、png、gif、webp 格式"), status=status.HTTP_400_BAD_REQUEST)

    try:
        raw = f.read()
        if len(raw) > 10 * 1024 * 1024:  # 10MB
            return Response(_result(400, "图片大小不能超过 10MB"), status=status.HTTP_400_BAD_REQUEST)
        b64 = base64.b64encode(raw).decode("utf-8")
        mime = "image/jpeg" if ext in (".jpg", ".jpeg") else ("image/png" if ext == ".png" else "image/webp")
        data_url = f"data:{mime};base64,{b64}"
    except Exception as e:
        logger.exception("风水分析：读取图片失败")
        return Response(_result(500, "图片处理失败"), status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    prompt = """你是一位传统文化风水师。请仔细观察用户上传的这张房屋/环境图片，从传统风水角度进行分析。
请用 Markdown 格式输出，包含以下小节（使用 ## 二级标题）：
1. 整体格局与气场
2. 采光与通风
3. 布局建议（如有不妥之处可给出改善建议）
4. 吉凶方位简析
用简洁、通俗的语言，控制在 300 字以内，给出专业且易懂的风水分析报告。"""

    try:
        from openai import OpenAI
        client = OpenAI(
            api_key=os.getenv("DASHSCOPE_API_KEY", "sk-0c014d6601794c9dbb248ea6892dcd55"),
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        completion = client.chat.completions.create(
            model="qwen-vl-plus",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": data_url}},
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
            timeout=60.0,
        )
        content = (completion.choices[0].message.content if completion.choices else "").strip() or "未能生成分析结果，请稍后重试。"
        return Response(_result(data={"content": content}))
    except Exception as e:
        logger.exception("风水分析失败")
        return Response(
            _result(500, f"风水分析失败：{str(e)}"),
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


CONSTITUTION_QUESTIONS = [
    "您容易过敏（对药物，食物，气味，花粉或在季节交替，气候变化时）吗？",
    "您说话声音低弱无力吗？",
    "您容易精神紧张，焦虑不安吗？",
    "您容易健忘吗？",
    "您平时痰多，特别是咽喉部总感觉有痰堵着吗？",
    "您比一般人耐受不了寒冷（冬天的寒冷或冷空调，电扇等）吗？",
    "您比别人容易患感冒吗？",
    "您面部或鼻部有油腻或者油光发亮吗？",
    "您面色晦暗，或容易出现褐斑吗？",
    "您能适应外界自然和社会环境的变化吗？",
    "您手脚发凉吗？",
    "您容易疲倦吗？",
    "您容易便秘或者大便干燥吗？",
    "您活动量稍大就容易出汗吗？",
    "您的皮肤一抓就红，并出现抓痕吗？",
    "您容易失眠吗？",
    "您容易气短吗？",
    "您感到手脚心发热吗？",
    "您咽喉部有异物感且吐之不出，咽之不下吗？",
    "您感到闷闷不乐，情绪低沉吗？",
    "您的阴囊部位潮湿吗？（仅男性回答）",
    "您腹部饱满松软吗？",
    "您精力充沛吗？",
]
CONSTITUTION_OPTIONS = ["没有", "很少", "经常", "总是"]  # 每题四选一


@api_view(["GET"])
@permission_classes([AllowAny])
def constitution_questions(request):
    """体质检测问卷题目与选项"""
    return Response(_result(data={
        "questions": CONSTITUTION_QUESTIONS,
        "options": CONSTITUTION_OPTIONS,
        "maleOnlyIndex": 20,
    }))


@api_view(["POST"])
@permission_classes([AllowAny])
def constitution_test(request):
    """
    体质检测：性别、年龄、22 题问卷、舌图，生成体质报告。
    multipart: gender（男/女）, age, answers（JSON 数组，每题 0-4）, file（舌图）
    """
    import json
    user_id = _user_id_from_request(request)
    if not user_id:
        return Response(_result(401, "请先登录"), status=status.HTTP_401_UNAUTHORIZED)

    gender = (request.data.get("gender") or "").strip() or request.POST.get("gender", "").strip()
    if gender not in ("男", "女"):
        return Response(_result(400, "请选择性别"), status=status.HTTP_400_BAD_REQUEST)

    try:
        age = int(request.data.get("age") or request.POST.get("age") or 0)
    except (TypeError, ValueError):
        age = 25
    age = max(10, min(120, age))

    answers_raw = request.data.get("answers") or request.POST.get("answers") or "[]"
    if isinstance(answers_raw, str):
        try:
            answers = json.loads(answers_raw)
        except json.JSONDecodeError:
            return Response(_result(400, "问卷数据格式错误"), status=status.HTTP_400_BAD_REQUEST)
    else:
        answers = list(answers_raw)
    if len(answers) < 21:
        return Response(_result(400, "请完成全部问卷"), status=status.HTTP_400_BAD_REQUEST)
    # 每题四选一，选项索引 0-3
    if any(not (isinstance(v, int) and 0 <= v < len(CONSTITUTION_OPTIONS)) for v in answers[:22]):
        return Response(_result(400, "问卷选项无效"), status=status.HTTP_400_BAD_REQUEST)

    f = request.FILES.get("file")
    if not f:
        return Response(_result(400, "请上传舌头图片"), status=status.HTTP_400_BAD_REQUEST)
    ext = (os.path.splitext(f.name or "")[1] or "").lower()
    if ext not in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
        return Response(_result(400, "仅支持 jpg、png、gif、webp 格式"), status=status.HTTP_400_BAD_REQUEST)
    try:
        raw = f.read()
        if len(raw) > 10 * 1024 * 1024:
            return Response(_result(400, "图片大小不能超过 10MB"), status=status.HTTP_400_BAD_REQUEST)
        b64 = base64.b64encode(raw).decode("utf-8")
        mime = "image/jpeg" if ext in (".jpg", ".jpeg") else ("image/png" if ext == ".png" else "image/webp")
        data_url = f"data:{mime};base64,{b64}"
    except Exception:
        logger.exception("体质检测：读取舌图失败")
        return Response(_result(500, "图片处理失败"), status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    qa_lines = []
    for i, q in enumerate(CONSTITUTION_QUESTIONS):
        if i == 20 and gender == "女":
            continue
        idx = i if (i <= 20 or gender == "男") else i - 1
        if idx < len(answers):
            v = answers[idx]
            if isinstance(v, int) and 0 <= v < len(CONSTITUTION_OPTIONS):
                qa_lines.append(f"{i+1}. {q}\n   答：{CONSTITUTION_OPTIONS[v]}")
            elif isinstance(v, str) and v in CONSTITUTION_OPTIONS:
                qa_lines.append(f"{i+1}. {q}\n   答：{v}")

    qa_text = "\n".join(qa_lines) if qa_lines else "（无问卷数据）"

    prompt = f"""你是一位中医体质辨识专家。请根据用户信息、问卷答卷和舌象图片，生成一份体质检测报告。

【用户信息】
性别：{gender}，年龄：{age}岁

【问卷答卷】
{qa_text}

【任务】
请结合舌象图片的观察，用 Markdown 格式输出体质检测报告，包含：
1. 体质类型判断（如气虚、阳虚、阴虚、痰湿、湿热、血瘀、气郁、特禀、平和等）
2. 体质特点与表现
3. 调养建议（饮食、起居、运动、情志等）
4. 舌象简要分析
用专业且通俗的语言，控制在 500 字以内。"""

    try:
        from openai import OpenAI
        client = OpenAI(
            api_key=os.getenv("DASHSCOPE_API_KEY", "sk-0c014d6601794c9dbb248ea6892dcd55"),
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        completion = client.chat.completions.create(
            model="qwen-vl-plus",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": data_url}},
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
            timeout=90.0,
        )
        content = (completion.choices[0].message.content if completion.choices else "").strip() or "未能生成报告，请稍后重试。"
        return Response(_result(data={"content": content}))
    except Exception as e:
        logger.exception("体质检测失败")
        return Response(
            _result(500, f"体质检测失败：{str(e)}"),
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


def _get_ai_chat_messages(session_id):
    """从 DB 加载会话的历史消息，供 LLM 使用。"""
    messages = []
    try:
        with connection.cursor() as c:
            c.execute(
                "SELECT role, content FROM ai_master_chat_message WHERE session_id = %s ORDER BY created_at ASC",
                [session_id],
            )
            for row in c.fetchall():
                messages.append({"role": row[0], "content": (row[1] or "").strip()})
    except Exception:
        pass
    return messages


@api_view(["GET"])
@permission_classes([AllowAny])
def ai_master_chat_history(request):
    """
    获取 AI 名师聊天历史。需登录。
    GET ?session_id=xxx 指定会话；不传则返回最近一次会话的历史。
    """
    user_id = _user_id_from_request(request)
    if not user_id:
        return Response(_result(401, "请先登录"), status=status.HTTP_401_UNAUTHORIZED)

    session_id = request.GET.get("session_id")
    if session_id:
        try:
            session_id = int(session_id)
        except (TypeError, ValueError):
            session_id = None

    if not session_id:
        try:
            with connection.cursor() as c:
                c.execute(
                    "SELECT id FROM ai_master_chat_session WHERE user_id = %s ORDER BY created_at DESC LIMIT 1",
                    [user_id],
                )
                row = c.fetchone()
                session_id = row[0] if row else None
        except Exception:
            session_id = None

    if not session_id:
        return Response(_result(data={"sessionId": None, "messages": []}))

    messages = []
    try:
        with connection.cursor() as c:
            c.execute(
                "SELECT role, content, created_at FROM ai_master_chat_message WHERE session_id = %s ORDER BY created_at ASC",
                [session_id],
            )
            for row in c.fetchall():
                messages.append({
                    "role": row[0],
                    "content": (row[1] or "").strip(),
                    "createdAt": row[2].isoformat() if row[2] and hasattr(row[2], "isoformat") else str(row[2]),
                })
    except Exception:
        pass

    return Response(_result(data={"sessionId": session_id, "messages": messages}))


@api_view(["POST"])
@permission_classes([AllowAny])
def ai_master_chat_new(request):
    """创建新会话。需登录。返回 session_id。"""
    user_id = _user_id_from_request(request)
    if not user_id:
        return Response(_result(401, "请先登录"), status=status.HTTP_401_UNAUTHORIZED)

    try:
        with connection.cursor() as c:
            c.execute(
                "INSERT INTO ai_master_chat_session (user_id) VALUES (%s)",
                [user_id],
            )
            session_id = c.lastrowid
        return Response(_result(data={"sessionId": session_id}))
    except Exception:
        return Response(_result(500, "创建会话失败"), status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["POST"])
@permission_classes([AllowAny])
def ai_master_chat(request):
    """
    AI 名师对话：用户发送消息，AI 以传统文化名师身份回复，支持历史上下文。需登录。
    body: { "message": "用户输入", "sessionId": 可选，不传则创建新会话 }
    """
    user_id = _user_id_from_request(request)
    if not user_id:
        return Response(_result(401, "请先登录"), status=status.HTTP_401_UNAUTHORIZED)
    msg = (request.data.get("message") or "").strip()
    if not msg:
        return Response(_result(400, "请输入消息"), status=status.HTTP_400_BAD_REQUEST)

    session_id = request.data.get("sessionId")
    if session_id is not None:
        try:
            session_id = int(session_id)
        except (TypeError, ValueError):
            session_id = None

    if not session_id:
        try:
            with connection.cursor() as c:
                c.execute(
                    "INSERT INTO ai_master_chat_session (user_id) VALUES (%s)",
                    [user_id],
                )
                session_id = c.lastrowid
        except Exception:
            return Response(_result(500, "创建会话失败"), status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    try:
        with connection.cursor() as c:
            c.execute(
                "INSERT INTO ai_master_chat_message (session_id, role, content) VALUES (%s, 'user', %s)",
                [session_id, msg],
            )
    except Exception:
        pass

    history = _get_ai_chat_messages(session_id)
    llm_messages = [
        {"role": "system", "content": "你是传统文化名师，精通八字命理、风水、国学等，用专业且亲和的语气为用户解答。根据对话历史理解上下文，回复控制在 300 字以内。"},
    ]
    for h in history:
        llm_messages.append({"role": h["role"], "content": h["content"]})

    try:
        from openai import OpenAI
        client = OpenAI(
            api_key=os.getenv("DASHSCOPE_API_KEY", "sk-0c014d6601794c9dbb248ea6892dcd55"),
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        completion = client.chat.completions.create(
            model="qwen-plus",
            messages=llm_messages,
            timeout=60.0,
        )
        content = (completion.choices[0].message.content if completion.choices else "").strip() or "抱歉，暂未生成回复，请稍后再试。"

        try:
            with connection.cursor() as c:
                c.execute(
                    "INSERT INTO ai_master_chat_message (session_id, role, content) VALUES (%s, 'assistant', %s)",
                    [session_id, content],
                )
        except Exception:
            pass

        return Response(_result(data={"content": content, "sessionId": session_id}))
    except Exception as e:
        logger.exception("AI名师对话失败")
        return Response(
            _result(500, f"回复生成失败：{str(e)}"),
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["GET"])
@permission_classes([AllowAny])
def xiyongshen_get(request):
    """获取当前用户喜用神（若无则根据出生日期计算）。需登录且有出生日期。"""
    user_id = _user_id_from_request(request)
    if not user_id:
        return Response(_result(401, "请先登录"), status=status.HTTP_401_UNAUTHORIZED)
    birth_date, xi, yong = _get_user_xiyongshen(user_id)
    if birth_date is None:
        return Response(_result(400, "请先完善出生日期"), status=status.HTTP_400_BAD_REQUEST)
    return Response(_result(data={"birthDate": birth_date, "喜神": xi, "用神": yong}))


@api_view(["GET"])
@permission_classes([AllowAny])
def xiyongshen_match(request):
    """喜属性匹配：返回喜神或用神相同的其他用户。需登录且有出生日期。"""
    user_id = _user_id_from_request(request)
    if not user_id:
        return Response(_result(401, "请先登录"), status=status.HTTP_401_UNAUTHORIZED)
    birth_date, xi, yong = _get_user_xiyongshen(user_id)
    if birth_date is None:
        return Response(_result(400, "请先完善出生日期"), status=status.HTTP_400_BAD_REQUEST)
    if not xi and not yong:
        return Response(_result(data={"list": [], "喜神": xi, "用神": yong}))

    try:
        with connection.cursor() as c:
            c.execute(
                """
                SELECT u.id, u.nickname, u.avatar_url, up.intro, up.xiyongshen
                FROM user u
                INNER JOIN user_profile up ON up.user_id = u.id
                WHERE u.status = 1 AND u.id != %s
                AND (up.xiyongshen IS NOT NULL AND up.xiyongshen != '')
                ORDER BY u.id DESC
                LIMIT 100
                """,
                [user_id],
            )
            rows = c.fetchall()
    except Exception:
        rows = []

    import json
    items = []
    for r in rows:
        uid = r[0]
        try:
            xy = json.loads(str(r[4]).strip()) if len(r) > 4 and r[4] else {}
        except Exception:
            xy = {}
        other_xi = xy.get("喜神") or ""
        other_yong = xy.get("用神") or ""
        if (xi and xi == other_xi) or (yong and yong == other_yong) or (xi and xi == other_yong) or (yong and yong == other_xi):
            items.append({
                "userId": uid,
                "nickname": r[1] or f"用户{uid}",
                "avatarUrl": r[2] if len(r) > 2 else None,
                "intro": r[3] if len(r) > 3 else "暂无介绍",
                "喜神": other_xi,
                "用神": other_yong,
            })
    return Response(_result(data={"list": items, "喜神": xi, "用神": yong}))


@api_view(["GET"])
@permission_classes([AllowAny])
def birth_match_list(request):
    """
    时辰匹配：根据当前用户出生日期，返回同年同月同日生的其他用户列表。
    需登录且已填写出生日期。
    """
    user_id = _user_id_from_request(request)
    if not user_id:
        return Response(_result(401, "请先登录"), status=status.HTTP_401_UNAUTHORIZED)
    birth_date, birth_time = _get_user_birth_info(user_id)
    if not birth_date:
        return Response(_result(400, "请先完善出生日期"), status=status.HTTP_400_BAD_REQUEST)

    try:
        with connection.cursor() as c:
            c.execute(
                """
                SELECT u.id, u.nickname, u.avatar_url, up.intro, up.birth_time
                FROM user u
                INNER JOIN user_profile up ON up.user_id = u.id
                WHERE u.status = 1 AND u.id != %s AND up.birth_date = %s
                ORDER BY u.id DESC
                LIMIT 100
                """,
                [user_id, birth_date],
            )
            rows = c.fetchall()
    except Exception as e:
        try:
            with connection.cursor() as c:
                c.execute(
                    """
                    SELECT u.id, u.nickname, u.avatar_url, up.intro
                    FROM user u
                    INNER JOIN user_profile up ON up.user_id = u.id
                    WHERE u.status = 1 AND u.id != %s AND up.birth_date = %s
                    ORDER BY u.id DESC
                    LIMIT 100
                    """,
                    [user_id, birth_date],
                )
                rows = c.fetchall()
        except Exception:
            return Response(_result(500, "查询失败"), status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    items = []
    for r in rows:
        uid = r[0]
        nickname = r[1] or f"用户{uid}"
        avatar_url = r[2]
        intro = (r[3] or "暂无介绍") if len(r) > 3 else "暂无介绍"
        birth_time_val = str(r[4]).strip() if len(r) > 4 and r[4] else None
        items.append({
            "userId": uid,
            "nickname": nickname,
            "avatarUrl": avatar_url,
            "intro": intro,
            "birthTime": birth_time_val,
        })
    return Response(_result(data={"list": items, "birthDate": birth_date}))


# 生肖顺序（公历年份 (year-4)%12 对应索引）
ZODIAC_LIST = ["鼠", "牛", "虎", "兔", "龙", "蛇", "马", "羊", "猴", "鸡", "狗", "猪"]


def _zodiac_from_date(birth_date):
    """从出生日期得到生肖，birth_date 为 date 或 YYYY-MM-DD 字符串"""
    if birth_date is None:
        return None
    if hasattr(birth_date, "year"):
        year = birth_date.year
    else:
        try:
            year = int(str(birth_date).split("-")[0])
        except Exception:
            return None
    return ZODIAC_LIST[(year - 4) % 12]


def _age_from_date(birth_date):
    """从出生日期得到当前年龄，birth_date 为 date 或 YYYY-MM-DD 字符串"""
    if birth_date is None:
        return None
    try:
        if hasattr(birth_date, "year"):
            bd = birth_date
        else:
            from datetime import datetime
            bd = datetime.strptime(str(birth_date)[:10], "%Y-%m-%d").date()
        today = date.today()
        age = today.year - bd.year
        if (today.month, today.day) < (bd.month, bd.day):
            age -= 1
        return max(0, age)
    except Exception:
        return None


@api_view(["GET"])
@permission_classes([AllowAny])
def fate_match(request):
    """
    缘分匹配（合并时辰匹配 + 喜属性匹配）：返回同年同月同日生或喜用神相同的用户。
    筛选参数：gender（1男 2女）、age_min、age_max、zodiac（生肖）、region（地区，如 广东 深圳，仅匹配同省/同城）。
    """
    import json as _json
    user_id = _user_id_from_request(request)
    if not user_id:
        return Response(_result(401, "请先登录"), status=status.HTTP_401_UNAUTHORIZED)
    birth_date, birth_time = _get_user_birth_info(user_id)
    if not birth_date:
        return Response(_result(400, "请先完善出生日期"), status=status.HTTP_400_BAD_REQUEST)
    birth_date_str = birth_date if isinstance(birth_date, str) else (birth_date.strftime("%Y-%m-%d") if hasattr(birth_date, "strftime") else str(birth_date))
    _, xi, yong = _get_user_xiyongshen(user_id)

    gender_param = request.GET.get("gender")
    gender_filter = None
    if gender_param and str(gender_param).strip():
        try:
            g = int(gender_param)
            if g in (1, 2):
                gender_filter = g
        except (TypeError, ValueError):
            pass
    age_min = None
    age_max = None
    try:
        am = request.GET.get("age_min")
        if am is not None and str(am).strip() != "":
            age_min = int(am)
    except (TypeError, ValueError):
        pass
    try:
        am = request.GET.get("age_max")
        if am is not None and str(am).strip() != "":
            age_max = int(am)
    except (TypeError, ValueError):
        pass
    zodiac_param = request.GET.get("zodiac")
    zodiac_filter = []
    if zodiac_param and str(zodiac_param).strip():
        for z in str(zodiac_param).split(","):
            z = z.strip()
            if z and z in ZODIAC_LIST:
                zodiac_filter.append(z)

    region_filter = (request.GET.get("region") or request.GET.get("location_code") or "").strip()[:32]

    candidate_ids = set()
    match_by_birth = set()
    match_by_xiyong = set()

    try:
        with connection.cursor() as c:
            c.execute(
                """
                SELECT u.id FROM user u
                INNER JOIN user_profile up ON up.user_id = u.id
                WHERE u.status = 1 AND u.id != %s AND up.birth_date = %s
                LIMIT 200
                """,
                [user_id, birth_date_str],
            )
            for row in c.fetchall():
                candidate_ids.add(row[0])
                match_by_birth.add(row[0])
    except Exception:
        pass

    if xi or yong:
        try:
            with connection.cursor() as c:
                c.execute(
                    """
                    SELECT u.id, up.xiyongshen FROM user u
                    INNER JOIN user_profile up ON up.user_id = u.id
                    WHERE u.status = 1 AND u.id != %s
                    AND (up.xiyongshen IS NOT NULL AND up.xiyongshen != '')
                    LIMIT 300
                    """,
                    [user_id],
                )
                for row in c.fetchall():
                    uid = row[0]
                    try:
                        xy = _json.loads(str(row[1]).strip()) if row[1] else {}
                    except Exception:
                        xy = {}
                    other_xi = xy.get("喜神") or ""
                    other_yong = xy.get("用神") or ""
                    if (xi and (xi == other_xi or xi == other_yong)) or (yong and (yong == other_xi or yong == other_yong)):
                        candidate_ids.add(uid)
                        match_by_xiyong.add(uid)
        except Exception:
            pass

    if not candidate_ids:
        return Response(_result(data={
            "list": [],
            "birthDate": birth_date_str,
            "birthTime": birth_time,
            "喜神": xi,
            "用神": yong,
        }))

    ids_list = list(candidate_ids)
    placeholders = ",".join(["%s"] * len(ids_list))
    try:
        with connection.cursor() as c:
            c.execute(
                """
                SELECT u.id, u.nickname, u.avatar_url, u.gender, up.birth_date, up.birth_time, up.intro, up.xiyongshen, up.region_code
                FROM user u
                INNER JOIN user_profile up ON up.user_id = u.id
                WHERE u.id IN ({})
                """.format(placeholders),
                ids_list,
            )
            rows = c.fetchall()
    except Exception:
        rows = []

    items = []
    for r in rows:
        uid = r[0]
        nickname = r[1] or f"用户{uid}"
        avatar_url = r[2]
        u_gender = r[3]
        bd = r[4]
        birth_time_val = str(r[5]).strip() if len(r) > 5 and r[5] else None
        intro = (r[6] or "暂无介绍") if len(r) > 6 else "暂无介绍"
        try:
            xy = _json.loads(str(r[7]).strip()) if len(r) > 7 and r[7] else {}
        except Exception:
            xy = {}
        other_xi = xy.get("喜神") or ""
        other_yong = xy.get("用神") or ""
        other_region = (str(r[8]).strip() if len(r) > 8 and r[8] else None) or ""

        age = _age_from_date(bd)
        zodiac = _zodiac_from_date(bd)

        if region_filter:
            if not other_region:
                continue
            parts = [p.strip() for p in region_filter.split() if p.strip()]
            if not parts:
                continue
            if not any(p in other_region for p in parts):
                continue
        if gender_filter is not None and u_gender != gender_filter:
            continue
        if age_min is not None and (age is None or age < age_min):
            continue
        if age_max is not None and (age is None or age > age_max):
            continue
        if zodiac_filter and (zodiac is None or zodiac not in zodiac_filter):
            continue

        match_types = []
        if uid in match_by_birth:
            match_types.append("birth")
        if uid in match_by_xiyong:
            match_types.append("xiyongshen")

        bd_str = bd.strftime("%Y-%m-%d") if hasattr(bd, "strftime") else str(bd) if bd else None
        items.append({
            "userId": uid,
            "nickname": nickname,
            "avatarUrl": avatar_url,
            "intro": intro,
            "birthDate": bd_str,
            "birthTime": birth_time_val,
            "喜神": other_xi,
            "用神": other_yong,
            "matchTypes": match_types,
            "age": age,
            "gender": u_gender,
            "zodiac": zodiac,
        })

    return Response(_result(data={
        "list": items,
        "birthDate": birth_date_str,
        "birthTime": birth_time,
        "喜神": xi,
        "用神": yong,
    }))
