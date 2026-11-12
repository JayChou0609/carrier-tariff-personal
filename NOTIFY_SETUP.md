# 📮 接入你自己的通知通道（钉钉 / 飞书 / 企业微信 / 邮件）

## 本仓库企业微信云端推送（2026-11-11）

企业微信使用独立工作流 **WeCom Tariff Notifications**（`.github/workflows/wecom-notify.yml`）。
本机推送任务已停用。Webhook 只存储于仓库 **Settings → Secrets and variables → Actions → Secrets → New repository secret**，名称为 `WECOM_WEBHOOK`；不要填入 Variables、网页、源码、issue 或工作流输入。

- 北京时间每天 **00:00、12:00、18:00** 启动 **Scheduled Tariff Refresh** 采集，**仅在本轮采集成功并完成归档后自动推送本轮结果**。已取消独立定时推送入口，不提前读取上一轮快照发送摘要。17个范围均需更新成功且资费文件与本轮归档一致；保留旧数据、缺失或失败均不自动发送正式资费提醒。实际发送时间随 GitHub 调度、排队和采集耗时顺延，不保证整点送达。
- 每小时 07、27、47 分做采集补偿检查，当期 17 个范围已经完整更新则跳过。没有本轮新归档的检查不会进入正式通知队列，也不会发送旧快照。手动运行采集仍强制重新采集。
- 三类提醒：**今日上线**（官方上线日期为今天）、**明日下线**、**今日下线**。采集日期及 `firstConfirmTimeStr` 不作为上线日期。
- 每条尚未以卡片提醒的资费发送**一张图片＋对应文字**，展示运营商、名称、方案编号、资费标准、适用范围、适用地区、上线/重新上线/下线日期和官方确认时间。重新上线日期只取已确认的历史生命周期事件；普通官方确认时间不标成“二次上线”。图片使用JPEG，发送前校验不超过2MB，消息间隔至少3.3秒；每张图片、每条文字均记录发送进度，避免失败续发时重复。
- 范围：四家全国，以及甘肃移动、江苏四家、上海移动/电信/联通、浙江电信、河北/河南/四川/广东联通。
- 每个完整采集批次发送分类摘要，有尚未发送或内容变化的资费时附 CSV；同一批次相同内容不重复发送；新完成的完整批次会重新发送三类摘要，明细资费继续去重。缺失、过期、保留旧快照的来源会注明，不会把全部读取失败当作零条消息。
- 首次配置 Secret 后，在 Actions 选择 **WeCom Tariff Notifications → Run workflow → action=verify → main**。验证发送一条文本和一个测试 CSV，再发送尚未提醒的数据。`preview` 不推送；`send` 要求已验证目标群。
- 旧 `dingtalk-summary.yml`、`province-notify.yml` 的企业微信入口已关闭；其他通道保留。

发送记录保存于独立 **wecom-notify-state** 分支的 `state.json`，仅含凭据哈希、业务版本、已发送时段和未完成消息，不含 Webhook、key 或 GitHub token。首次迁移沿用本机已发送记录，防止重新群发。当前文件保留45天活动去重记录，Git提交保留此前版本；资费完整历史仍由 `tariff-history` 分支保存。

推送前先写入持久发送标记。如果 runner 被中断或最后的状态写入失败，后续发送会停止，避免盲目重试。失败任务会保存经过凭据检查的 `wecom-checkpoint-recovery-*` 恢复文件（7天）；核对已发送消息后恢复 `state.json`，再运行 `verify`。不要直接清空记录。

Secret 仅注入发送步骤；工作流仅允许本仓库主分支和可信采集完成事件，第三方 Actions 固定提交版本。能修改主分支工作流的管理员仍能通过修改代码使用 Secret，因此应保护账号和仓库写入权限。公开仓库的标准 runner 可免费运行，但定时任务不保证准点；长时间无活动可能被 GitHub 暂停。

以下是项目原有多通道说明；本仓库企业微信以本节的独立入口为准。

> 本项目已开源。任何人 fork 后，填入**自己的**凭据，
> 资费变化就能推送到**自己的**钉钉 / 飞书 / 企业微信 / 邮箱。
>
> 你填的密钥只存在你自己的仓库里，**作者和其他人都看不到**。
> 四个通道可任意组合：配几个就推几个，没配的自动跳过。

---

## 一、填在哪里

### 方式 A：GitHub Actions 云端（推荐，全自动）

1. **Fork 本仓库**
2. **Settings → Secrets and variables → Actions → New repository secret**
3. 按需添加下表的变量（**只填你要用的通道**）
4. **Actions** → 选 **Tariff Notify** → **Run workflow** → 约 14 秒后收到

> 🔒 Secrets 加密存储、**只写不读**——存进去后连你自己都看不到原文，
> 运行时自动注入，日志里显示为 `***`。

### 方式 B：本地 / 自己的服务器

```bash
git clone https://github.com/<你的用户名>/carrier-tariff-site.git
cd carrier-tariff-site
cp .env.example .env
# 编辑 .env 填入你的凭据（.env 已被 .gitignore 排除，不会误提交）
python3 scripts/notify.py --test      # 测试所有已配置通道
python3 scripts/dingtalk_summary.py   # 正式推送汇总
```

---

## 二、四个通道怎么拿凭据

### 🔵 钉钉机器人

1. 钉钉群 →「群设置」→「智能群助手」→「添加机器人」→「自定义」
2. 安全设置**建议勾选「加签」**
3. 拿到 Webhook 地址与加签密钥（`SEC` 开头）

| Secret | 值 |
|---|---|
| `DINGTALK_WEBHOOK` | `https://oapi.dingtalk.com/robot/send?access_token=xxx` |
| `DINGTALK_SECRET` | `SECxxx`（没开加签可留空） |

---

### 🟦 飞书机器人

1. 飞书群 →「设置」→「群机器人」→「添加机器人」→「自定义机器人」
2. 安全设置可设「签名校验」
3. 拿到 Webhook 地址与签名密钥

| Secret | 值 |
|---|---|
| `FEISHU_WEBHOOK` | `https://open.feishu.cn/open-apis/bot/v2/hook/xxx` |
| `FEISHU_SECRET` | 签名密钥（没开可留空） |

> 飞书以**卡片消息**推送，支持 Markdown 渲染。

---

### 🟩 企业微信机器人

1. 企业微信群 → 右上角「…」→「群机器人」→「添加」
2. 直接复制 Webhook 地址（企业微信机器人无加签，靠地址本身保密）

| Secret | 值 |
|---|---|
| `WECOM_WEBHOOK` | `https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx` |

> 内容超长时会自动降级为纯文本，避免被接口拒绝。

---

### 📧 邮件（SMTP）

以 QQ 邮箱为例：设置 → 账户 → 开启 **SMTP 服务** → 生成**授权码**（不是登录密码）。

| Secret | 值 | 示例 |
|---|---|---|
| `SMTP_HOST` | SMTP 服务器 | `smtp.qq.com` |
| `SMTP_PORT` | 端口 | `465`（SSL）/ `587`（STARTTLS） |
| `SMTP_USER` | 发件邮箱 | `123456@qq.com` |
| `SMTP_PASS` | **授权码** | `abcdefghijklmnop` |
| `MAIL_TO` | 收件人，多个用逗号 | `a@qq.com,b@163.com` |
| `MAIL_FROM` | 发件人显示（可选，默认同 `SMTP_USER`） | |
| `MAIL_FROM_NAME` | 发件人名称（可选） | `资费监控` |

常用 SMTP：

| 邮箱 | Host | Port |
|---|---|---|
| QQ | `smtp.qq.com` | 465 |
| 163 | `smtp.163.com` | 465 |
| Gmail | `smtp.gmail.com` | 587 |
| Outlook | `smtp.office365.com` | 587 |

> 邮件同时发送**纯文本 + HTML** 两个版本，手机上排版正常。

---

## 三、通用可选项

| Secret | 作用 | 默认 |
|---|---|---|
| `FOCUS_SEC` | 明细只列哪个省（拼音） | `hunan` |
| `SITE_URL` | 消息末尾的站点链接 | 本项目 Pages |
| `SINCE_HOURS` | 统计最近 N 小时 | `24` |

省份拼音示例：`guangdong`、`zhejiang`、`beijing`、`hunan`、`quanguo`（全网）

---

## 四、验证

```bash
python3 scripts/notify.py --test
```

输出类似：

```
  ✅ 钉钉：errcode=0 ok
  ⏭  飞书：未配置（FEISHU_WEBHOOK 为空），跳过
  ⏭  企业微信：未配置（WECOM_WEBHOOK 为空），跳过
  ❌ 邮件：[Errno 110] Connection timed out

测试完成：成功 1 / 已配置 2（钉钉）
```

云端则直接跑 **Actions → Tariff Notify → Run workflow**，看日志里同样的输出。

---

## 五、推送长什么样

```
## 资费变化汇总

**统计范围**：09-12 16:27 ~ 09-13 16:27 (北京时间)

- 🔵 移动：新增 340、下架 284、修改 1196
  - 湖南：无变化
- 🟠 联通：无变化
- 🟢 电信：新增 7、下架 8、修改 0
  - 湖南：新增7 下架8 修改0
- 🟣 广电：新增 5、下架 1、修改 1
  - 湖南：无变化

**合计**：新增 352、下架 293、修改 1197

🔗 查看完整资费站
```

---

## 六、自动推送时间

默认每天两次（北京 **10:00** / **20:00**），各统计前 24 小时。
改时间编辑 `.github/workflows/dingtalk-summary.yml`：

```yaml
schedule:
  - cron: "0 2 * * *"     # 北京 10:00（UTC + 8）
  - cron: "0 12 * * *"    # 北京 20:00
```

---

## 七、常见问题

**Q：收不到？**
先跑 `--test` 看具体报错。钉钉若用「自定义关键词」安全设置，消息里必须含那个关键词。

**Q：签名不匹配？**
钉钉/飞书的密钥填错了。注意飞书是「签名校验」里那串，钉钉是 `SEC` 开头那串，两者算法不同、别混用。

**Q：邮件发不出？**
- 用的是**授权码**不是登录密码
- 465 配 SSL、587 配 STARTTLS，别混
- 部分邮箱需在设置里单独开启 SMTP

**Q：密钥会被看到吗？**
不会。Secrets 只写不读、日志脱敏；脚本本身**不含任何硬编码凭据**（全走环境变量）。

**Q：都不配会怎样？**
抓取照常，只是不推送，站点数据一样更新。

---

## 八、安全建议

1. 钉钉/飞书**开启加签**
2. 不要把密钥写进代码或提交 `.env`
3. 公开仓库开启 **Settings → Actions → Fork pull request workflows →
   Require approval for all outside collaborators**，
   防止他人通过 PR 改动 workflow 窃取 Secrets
