# 独立云端采集与推送补偿

## 每日目标与触发

GitHub 保留北京时间 00:00、12:00、18:00 主采集及原有补偿 cron。Cloudflare Worker `carrier-tariff-watchdog` 另在每小时 02、12、22、32、42、52 分钟独立读取公开归档状态及推送回执，完整时直接跳过；任务运行时等待；缺失才触发 GitHub 的 `Independent Cloud Recovery` 工作流。Cloudflare cron 使用 UTC，这组每小时分钟在北京时间相同。

独立入口每次检查本时段：

- 17 个关注范围全部为 updated，采集开始和实际快照时间均不早于时段起点，才算采集完整。
- 不完整且没有运行/排队中的采集任务：以 `catch_up=true` 调用已有采集器。采集器在真正开始时再次检查，已完成则跳过。
- 采集完整但三类图片+文字推送没有成功回执：仅调用推送器 `action=recover`，不重新使用旧快照假冒新采集。
- 检查到任务尚在运行则等待；最近一次启动后至少间隔 10 分钟再尝试，避免重复排队。

本补偿服务不采资费、不生成图片、不直接调用企业微信。企业微信 Webhook 始终只在现有 GitHub Actions Secret `WECOM_WEBHOOK` 中。

## 推送续传与回执

每个已确认成功的图片、文字和附件进度会写入 `wecom-notify-state` 分支；任务终止后，恢复入口先确认原 GitHub 推送运行已经 completed，才解除残留租约并继续未完成步骤。同一采集批次的不同 attempt 使用同一续传标识。推送完成后写入 `health.json`，包含采集批次、目标时段、三种提醒类别及完成时间，不包含任何凭据。

企业微信不提供本程序可用的消息幂等键：如果远端已接受消息而连接在回执或进度落盘前断开，自动重试仍可能重复最后一条。正常已确认、已保存的消息会跳过。此机制提高补偿能力，不承诺任何云服务永不故障或严格准点。

如果所有服务长时间不可用，补偿恢复的是当前时段的实际新采集；不能伪造已过去时段的官方历史快照。

## Cloudflare 部署

源码及 Wrangler 配置在 `cloudflare/tariff-watchdog/`，Worker 名称固定为 `carrier-tariff-watchdog`。不需要域名，不需要开启付费套餐。只部署该目录的 Worker，不把现有资费站点改为 Cloudflare 托管。

唯一绑定：`GITHUB_ACTIONS_TOKEN`，类型 **Secret**。使用仅选择 `JayChou0609/carrier-tariff-personal` 的 fine-grained GitHub token，仓库权限只开 **Actions: Read and write**（Metadata 自动只读）。不要开 Contents 写权限，不要授权所有仓库。设置合理的到期日并在到期前轮换。

不要把 token 写入源码、Wrangler 文件、普通变量、Pages 或聊天。创建或更换该凭据须由账号所有者确认并直接在 Cloudflare Secret 界面保存。

部署后配置 Cron `2,12,22,32,42,52 * * * *`，通过一次 Cloudflare scheduled 测试核对 GitHub 工作流已生成。HTTP 地址仅返回服务说明，访问它不会触发任何采集或发送。

## 手动检查

GitHub → Actions → **Independent Cloud Recovery** → Run workflow → main。此入口仅补偿当前时段，已完整采集并推送会返回 `complete`。

仍需强制重采时可使用 **Scheduled Tariff Refresh**，不勾选 `catch_up`；只补偿而不强制重采则勾选 `catch_up`。现有企业微信工作流的 `send` 保留，`recover` 用于已结束失败任务的续传。

## 验证

- `python3 -B -m unittest discover -s tests -p 'test_recover_automation.py' -v`
- `python3 -B -m unittest discover -s tests -p 'test_wecom*.py' -v`
- `python3 -B -m unittest discover -s tests -p 'test_schedule_guard.py' -v`

参考：[GitHub workflow_dispatch](https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event)、[Cloudflare Cron Triggers](https://developers.cloudflare.com/workers/configuration/cron-triggers/)、[Cloudflare Secrets](https://developers.cloudflare.com/workers/configuration/secrets/)。
