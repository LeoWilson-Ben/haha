# 灵枢后端（Django）

Python Django + MySQL 8.0 + Redis，连接方式见需求文档末尾。

## 连接配置

- **MySQL**：库名 `lingshu`，用户 `root`，密码 `12345678`，端口 3306
- **Redis**：`localhost:6379`，无密码

## 环境

```bash
cd server
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 建库与表

```bash
mysql -u root -p12345678 < sql/00_create_db.sql
mysql -u root -p12345678 lingshu < sql/schema.sql
```

若使用 `sql/schema.sql` 建表，则无需执行 migrate 创建 `user` 表（本项目中 User 模型为 `managed=False`）。若希望完全由 Django 建表，可把 `apps/account/models.User` 的 `Meta.managed` 改为 `True` 并执行：

```bash
python manage.py makemigrations account
python manage.py migrate
```

**语音匹配**（需先建表）：

```bash
mysql -u root -p lingshu < sql/migrate_voice_room.sql
```

并在 `server/Agora.txt` 中配置 APPID 与证书（或设置环境变量 `AGORA_APP_ID`、`AGORA_APP_CERTIFICATE`）。

## 启动

**本机访问**：
```bash
python manage.py runserver 8080
```

**真机/模拟器访问本机时必须监听所有网卡**（否则手机会连不上）：
```bash
python manage.py runserver 0.0.0.0:8080
```
然后在 Flutter 的 `AppConstants.baseUrlOverride` 填电脑 IP，如 `http://192.168.1.219:8080`。

## 接口

- `GET /health` — 健康检查（MySQL、Redis）
- `POST /api/auth/sendCode` — 发送验证码，body: `{"mobile":"13800138000"}`
- `POST /api/auth/login` — 登录，body: `{"mobile":"13800138000","code":"123456","deviceId":"xxx"}`

开发模式下发验证码固定为 `123456`。

**语音匹配**（需登录，Bearer Token）：

- `POST /api/voice-match/join` — 加入匹配池，返回 `status`: `waiting` | `matched`（含 `roomId`）| `no_gender` | `minor_mode`
- `GET /api/voice-match/status` — 轮询匹配结果，返回 `status`: `waiting` | `matched`（含 `roomId`）
- `POST /api/voice-match/cancel` — 取消匹配
- `GET /api/voice-room/join?room_id=xxx` — 加入语音房间，返回 `rtcToken`、`channel`、`uid`、`peer`
- `POST /api/voice-room/leave` — 挂断，body: `{"room_id":"xxx"}`

## 管理后台 API

路径前缀：`/api/admin/`。所有请求需在请求头携带 `X-Admin-Token`，且与配置一致。

- **鉴权**：在 `config/settings.py` 或环境变量中设置 `ADMIN_API_KEY`。未设置时仅在 `DEBUG=True` 下允许访问。
- **示例**：生产环境可设置 `export ADMIN_API_KEY=your-secret-key`，管理端前端在「系统配置」中填写相同密钥并保存后即可请求接口。
- **接口**：仪表盘统计、名师入驻审核（列表/通过/驳回）、帖子列表/下架、举报列表/处理、提现列表/通过/驳回、用户列表/禁用启用等，见 `apps/admin_api/urls.py`。
