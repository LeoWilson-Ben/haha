# 部署初始化：Python 依赖与数据库

部署到新服务器时，按本文执行一次即可。

---

## 一、Python 依赖

在项目根目录 `server/` 下执行：

```bash
cd /path/to/server
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### requirements.txt 内容（与仓库一致）

```
# 需求：MySQL 8.0 + Redis，连接方式见 config/settings.py
Django>=5.0,<6
djangorestframework>=3.14
django-cors-headers>=4.3
PyMySQL>=1.1
redis>=5.0
django-redis>=5.4
openai>=1.0
alibabacloud_dypnsapi20170525>=2.0.0,<3.0.0
alibabacloud_tea_openapi>=0.3.0
oss2>=2.18.0
```

---

## 二、数据库初始化

**前提**：已安装 MySQL 8.0，并准备好 root 密码（示例中为 `12345678`，生产请改环境变量或 `-p` 输入）。

在 `server/` 目录下执行，**严格按顺序**：

```bash
# 1. 创建库 lingshu
mysql -u root -p12345678 < sql/00_create_db.sql

# 2. 建主表结构（user、user_profile、post、im_* 等）
mysql -u root -p12345678 lingshu < sql/schema.sql

# 3. 以下为增量迁移（若某列/表已存在会报错，可忽略该条继续）
mysql -u root -p12345678 lingshu < sql/add_profile_fields.sql
mysql -u root -p12345678 lingshu < sql/migrate_birth_time.sql
mysql -u root -p12345678 lingshu < sql/migrate_user_code.sql
mysql -u root -p12345678 lingshu < sql/migrate_teacher.sql
mysql -u root -p12345678 lingshu < sql/migrate_group_public.sql
mysql -u root -p12345678 lingshu < sql/migrate_post_allow_comment.sql
mysql -u root -p12345678 lingshu < sql/migrate_post_media_cover_urls.sql
mysql -u root -p12345678 lingshu < sql/migrate_xiyongshen.sql
mysql -u root -p12345678 lingshu < sql/run_migrate.sql
```

若 root 密码不是 `12345678`，将 `-p12345678` 改为 `-p`，执行时输入密码；或使用环境变量（不推荐长期使用）：

```bash
export MYSQL_PWD=你的密码
mysql -u root < sql/00_create_db.sql
mysql -u root lingshu < sql/schema.sql
# ... 其余同上，把 -p12345678 去掉
unset MYSQL_PWD
```

### 执行顺序说明

| 顺序 | 文件 | 说明 |
|------|------|------|
| 1 | `00_create_db.sql` | 创建库 `lingshu`，utf8mb4 |
| 2 | `schema.sql` | 主表结构（用户、帖子、IM、钱包等） |
| 3 | `add_profile_fields.sql` | user_profile 增加 birth_date（若 schema 已含可跳过） |
| 4 | `migrate_birth_time.sql` | user_profile 增加 birth_time（出生时辰） |
| 5 | `migrate_user_code.sql` | user 表增加 user_code 及唯一键 |
| 6 | `migrate_teacher.sql` | 名师相关：user_profile 字段 + teacher_apply 表 |
| 7 | `migrate_group_public.sql` | im_group.is_public + group_join_apply 表 |
| 8 | `migrate_post_allow_comment.sql` | post.allow_comment |
| 9 | `migrate_post_media_cover_urls.sql` | post.media_cover_urls_json |
| 10 | `migrate_xiyongshen.sql` | user_profile.xiyongshen |
| 11 | `run_migrate.sql` | notification 表 + post.tags_json |

---

## 三、Django 迁移（可选）

本项目主要表由 `sql/schema.sql` 及上述迁移文件创建，多数模型为 `managed=False`。若你新增了 Django 管理的表，再执行：

```bash
source .venv/bin/activate
python manage.py migrate
```

---

## 四、启动前检查

- MySQL：库 `lingshu` 存在，表齐全。
- Redis：`redis://127.0.0.1:6379/0` 可连（`redis-cli ping` 返回 PONG）。
- 环境变量（生产建议设置）：`DJANGO_SECRET_KEY`、`DEBUG=0`、`ADMIN_API_KEY`、阿里云 OSS/短信相关等，见 `config/settings.py`。
