# 验证码服务配置清单

接入**阿里云短信验证码**（Dypnsapi：发送 + 核验）时，需要你提供下面这些信息，才能完成配置。

---

## 一、阿里云账号与开通

1. **阿里云账号**  
   已注册并完成实名认证。

2. **开通「短信验证码」产品**  
   - 产品：**号码认证服务 / 短信验证码**（Dypnsapi）  
   - 文档：<https://help.aliyun.com/product/75010.html>  
   - 在控制台开通后，才能使用 `SendSmsVerifyCode` / `CheckSmsVerifyCode`。

---

## 二、需要你提供的配置项

把下面表格里的每一项都填好（或从阿里云控制台查到），发给我或放到配置里，我就可以帮你把主服务和 VerifyCodeServer 配好。

| 序号 | 配置项 | 说明 | 示例 / 你填 |
|------|--------|------|-------------|
| 1 | **AccessKey ID** | 阿里云访问密钥 ID（建议用 RAM 子账号的 AK） | `LTAI5t...` |
| 2 | **AccessKey Secret** | 对应上述 AK 的 Secret | `xxxxxxxx` |
| 3 | **短信签名名称** | 在「短信服务」里申请的签名，发短信时显示在短信开头 | 如：`玄遇`、`速通互联验证码` |
| 4 | **短信模板 Code** | 在「短信服务」里申请的「验证码」类模板的模板 CODE | 如：`SMS_123456789` 或示例里的 `100001` |
| 5 | **模板变量格式** | 模板里验证码占位符的写法，用于替换成真实验证码 | 常见：`{"code":"123456"}` 或 `##code##`（示例里用 `##code##`） |
| 6 | **验证码有效期（分钟）** | 验证码多少分钟内有效，需和模板/文案一致 | 如：`5` |

说明：

- **签名、模板**：在阿里云控制台 → 短信服务 → 国内消息 → 签名管理 / 模板管理 里申请，审核通过后才能用。
- **无 AK 方式**：如果要用环境变量或实例角色（不把 AK 写进代码），也可以说明，我按「无 AK」方式给你写配置与示例。

---

## 三、当前项目里会动到的地方

1. **主服务（Django）**  
   - `server/config/settings.py`：  
     - 关闭开发模式：`APP_SMS_DEV_MODE = False`  
     - 新增阿里云相关配置：如 `ALIYUN_ACCESS_KEY_ID`、`ALIYUN_ACCESS_KEY_SECRET`、签名、模板 Code、有效期等。  
   - `server/apps/account/views.py` 的 `send_code`：  
     - 在非开发模式下调用阿里云 Dypnsapi 的「发送验证码」接口（或你本机 VerifyCodeServer 的发送接口），并把验证码按你现有逻辑写入 Redis（供登录/注册校验）。

2. **VerifyCodeServer（可选）**  
   - `send_verify/alibabacloud_sample/sample.py`：  
     - 把 `sign_name`、`template_code`、`template_param`、`phone_number` 等改成从配置/环境变量读取，用你提供的签名、模板 Code、模板变量格式。  
   - 若主服务是「主服务直接调阿里云」，则 VerifyCodeServer 仅作独立测试用；若主服务是「调本机 VerifyCodeServer 再发短信」，则还需要在 VerifyCodeServer 里用你提供的 AK、签名、模板做配置。

3. **核验方式（二选一或组合）**  
   - **当前方式**：主服务自己生成验证码、存 Redis、登录/注册时自己校验。  
   - **可选**：改用阿里云 `CheckSmsVerifyCode` 核验（需要发送时拿到并保存 `RequestId` 等，核验时传给阿里云）。  
   你只要告诉我：继续「自建 Redis 校验」还是「改为阿里云核验」，我按你的选择写具体代码和配置。

---

## 四、你需要给我的信息汇总（复制填空即可）

发给我时，可以按下面格式填（敏感信息可打码或写「已提供」）：

```
1. AccessKey ID：___________
2. AccessKey Secret：___________
3. 短信签名名称：___________
4. 短信模板 Code：___________
5. 模板里验证码参数名（如 code）：___________
6. 验证码有效期（分钟）：___________
7. 主服务发短信方式：A) Django 直接调阿里云  B) Django 调本机 VerifyCodeServer
8. 核验方式：A) 继续用 Redis 自建校验  B) 改用阿里云 CheckSmsVerifyCode
```

你提供以上信息后，我可以按你的环境写出具体配置和修改步骤（含要改的文件和代码位置）。
