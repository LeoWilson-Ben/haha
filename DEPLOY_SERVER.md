# 在服务器上启动后端

按下面步骤在服务器上一次性准备好环境并启动 Django 后端。

---

## 一、环境准备

### 1. 安装 MySQL 8.0 与 Redis

**Ubuntu/Debian 示例：**
```bash
sudo apt update
sudo apt install -y mysql-server redis-server
sudo systemctl start mysql redis-server
sudo systemctl enable mysql redis-server
```

**CentOS/RHEL 示例：**
```bash
sudo yum install -y mysql-server redis
sudo systemctl start mysqld redis
sudo systemctl enable mysqld redis
```

设置 MySQL root 密码（若未设置）：
```bash
sudo mysql -e "ALTER USER 'root'@'localhost' IDENTIFIED WITH mysql_native_password BY '你的密码'; FLUSH PRIVILEGES;"
```

### 2. 安装 Python 3.10+

```bash
# Ubuntu/Debian
sudo apt install -y python3 python3-venv python3-pip

# 或使用 pyenv/conda 等
python3 --version   # 建议 3.10+
```

---

## 二、部署代码并初始化数据库

### 1. 上传/克隆项目到服务器

例如放到 `/opt/xuanyu` 或 `~/XuanYu`，确保有 `server` 目录。

### 2. 初始化数据库（一次性）

```bash
cd /path/to/XuanYu/server

# 使用合并后的初始化脚本（推荐）
mysql -u root -p < sql/init_db.sql
# 按提示输入 MySQL root 密码
```

若希望用环境变量传密码（仅临时）：
```bash
export MYSQL_PWD=你的密码
mysql -u root < sql/init_db.sql
unset MYSQL_PWD
```

### 3. 修改数据库连接（如需要）

若 MySQL 不是本机或密码不是 `12345678`，编辑 `config/settings.py` 中 `DATABASES`，或使用环境变量（需在代码里读环境变量）。当前配置为：

- 库名：`lingshu`
- 用户：`root`
- 密码：`12345678`
- 主机：`localhost`，端口：`3306`

---

## 三、Python 依赖与启动

### 1. 创建虚拟环境并安装依赖

```bash
cd /path/to/XuanYu/server
python3 -m venv .venv
source .venv/bin/activate   # Linux/macOS
# Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

### 2. 启动方式一：开发/简单运行（runserver）

**只在本机访问：**
```bash
source .venv/bin/activate
python manage.py runserver 8080
```

**允许外网/手机访问（监听所有网卡）：**
```bash
python manage.py runserver 0.0.0.0:8080
```

此时后端地址为：`http://服务器IP:8080`，例如 `http://192.168.1.100:8080`。

- 健康检查：`curl http://服务器IP:8080/health`
- 注意：`runserver` 不适合高并发生产环境，仅适合内网或低流量。

### 3. 启动方式二：生产环境（Gunicorn + systemd）

**安装 Gunicorn：**
```bash
source .venv/bin/activate
pip install gunicorn
```

**直接前台运行 Gunicorn：**
```bash
cd /path/to/XuanYu/server
source .venv/bin/activate
gunicorn config.wsgi:application --bind 0.0.0.0:8080 --workers 2 --chdir /path/to/XuanYu/server
```

**用 systemd 守护进程（推荐）：**

新建服务文件：
```bash
sudo vim /etc/systemd/system/xuanyu-backend.service
```

写入（把 `/path/to/XuanYu/server` 换成实际路径）：

```ini
[Unit]
Description=XuanYu Django Backend
After=network.target mysql.service redis.service

[Service]
Type=notify
User=www-data
Group=www-data
WorkingDirectory=/path/to/XuanYu/server
Environment="PATH=/path/to/XuanYu/server/.venv/bin"
ExecStart=/path/to/XuanYu/server/.venv/bin/gunicorn config.wsgi:application --bind 127.0.0.1:8080 --workers 2
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

若希望直接对公网监听 8080，把 `--bind 127.0.0.1:8080` 改为 `--bind 0.0.0.0:8080`。生产更推荐 Gunicorn 只监听 127.0.0.1，前面用 Nginx 反代并做 HTTPS。

启用并启动：
```bash
sudo systemctl daemon-reload
sudo systemctl enable xuanyu-backend
sudo systemctl start xuanyu-backend
sudo systemctl status xuanyu-backend
```

查看日志：
```bash
sudo journalctl -u xuanyu-backend -f
```

---

## 四、启动前检查

| 检查项 | 命令 |
|--------|------|
| MySQL 库是否存在 | `mysql -u root -p -e "USE lingshu; SHOW TABLES;"` |
| Redis 是否正常 | `redis-cli ping`（应返回 PONG） |
| 健康接口 | `curl http://服务器IP:8080/health` |

---

## 五、生产环境建议环境变量

在 systemd 的 `[Service]` 里加 `Environment=`，或写进 `.env` 再在启动前 `source`：

```bash
export DEBUG=0
export DJANGO_SECRET_KEY=你的随机长字符串
export ADMIN_API_KEY=管理后台接口密钥
# 短信/OSS 等见 config/settings.py，可按需设置
# export APP_SMS_DEV_MODE=0
# export ALIYUN_OSS_ENABLED=1
```

---

## 六、常见问题

- **端口被占用**：换一个端口，如 `8081`，或 `sudo lsof -i :8080` 查占用进程。
- **MySQL 连不上**：确认 MySQL 已启动、密码正确、`config/settings.py` 里 HOST/PORT/USER/PASSWORD 与当前环境一致。
- **Redis 连不上**：`sudo systemctl status redis-server`，确认监听 `127.0.0.1:6379`。
- **外网访问不了**：检查防火墙是否放行 8080：`sudo ufw allow 8080`（若用 ufw），云服务器需在安全组放行 8080。

按上述步骤即可在服务器上完成数据库初始化并启动后端；生产环境建议使用 Gunicorn + systemd，前面加 Nginx 做反向代理和 HTTPS。
