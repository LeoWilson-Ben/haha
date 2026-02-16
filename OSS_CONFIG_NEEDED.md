# 阿里云 OSS 配置说明

用于**头像、帖子图片、舌象等文件**上传到阿里云对象存储。当前为**私有读**，返回**签名 URL**，防止资源泄漏。

---

## 一、当前配置（已写入 settings）

| 配置项 | 值 | 说明 |
|--------|-----|------|
| **Bucket** | `xuanyuapp` | 北京地域 |
| **Endpoint** | `oss-cn-beijing.aliyuncs.com` | 可用环境变量覆盖 |
| **凭据** | `VerifyCodeServer/1771223142676.txt` | 与短信共用 AK |
| **读权限** | 私有 | 不设公共读，上传后返回带过期时间的签名 URL |

---

## 二、已接入方式

1. **settings.py** 中（均可被环境变量覆盖）：
   - `ALIYUN_OSS_ENABLED`：`"1"` 时启用 OSS，默认 `"0"` 仍走本地
   - `ALIYUN_OSS_CREDENTIAL_FILE`：默认同短信的 `1771223142676.txt`
   - `ALIYUN_OSS_BUCKET`：默认 `xuanyuapp`
   - `ALIYUN_OSS_ENDPOINT`：默认 `oss-cn-beijing.aliyuncs.com`
   - `ALIYUN_OSS_SIGNED_URL_EXPIRES`：签名 URL 有效期（秒），默认 `604800`（7 天）

2. **上传接口** `POST /api/system/upload`：
   - 当 `ALIYUN_OSS_ENABLED=1` 且 Bucket 已配置时：文件上传到 OSS，返回**签名 URL**（私有读，过期后需由业务侧重新申请新 URL，或调用后端「刷新签名 URL」接口若有）。
   - 否则：仍存到本地 `MEDIA_ROOT`，返回本地 URL。

3. **依赖**：`oss2`（见 `requirements.txt`），执行 `pip install -r requirements.txt`。

---

## 三、启用步骤

1. 安装依赖：`pip install -r requirements.txt`。
2. 设置环境变量（或直接改 `config/settings.py`）：
   - `ALIYUN_OSS_ENABLED=1`
   - 其余 Bucket/Endpoint/凭据已按你的信息写好，一般无需再改。
3. 在 OSS 控制台将 Bucket **读权限设为私有**（不设公共读），写权限保持私有，仅服务端用 AK 上传。

不启用时保持 `ALIYUN_OSS_ENABLED=0`，上传继续走本地。

---

## 四、关于签名 URL

- 返回的 `url` 带签名和过期时间，仅在有效期内可访问，过期后需重新向后端申请（例如上传时保存 object key，由后端按 key 再签一次 URL）。
- 如需更长/更短有效期，可设置 `ALIYUN_OSS_SIGNED_URL_EXPIRES`（单位：秒）。
