---
name: im-notify
description: 把耗时任务的结果主动推送到微信/企业微信/飞书/钉钉/量子密信等 IM 通道。用户说"干完通知我"、"做完了发微信"、"跑完告诉我一声"、"结果出来推给我"、"批量/定时任务跑完提醒"，或需要在长任务末尾调用本技能时使用。实现方式是向 TeleAgent 本地投递队列写入一条 proactive 投递，由官方适配器负责发送，不自行实现各平台 API。
name_cn: "IM 完成通知"
description_cn: "耗时任务跑完后把结果主动推到微信/企微/飞书等 IM 通道：向本地投递队列写一条 proactive 投递，交给官方适配器发送；含通道自检、会话窗口过期等平台限制的排错。"
version: 1.0.0
---

# IM 完成通知（主动推送）

把「任务跑完了」变成手机上一条微信，而不是让人守着窗口看进度。

## 一、什么时候用

- 用户在派活时说明要收尾通知：「做完通知我」「完成后发微信」「跑完说一声」。
- 长耗时任务（批量处理、OCR、导出、构建、爬取）收尾时，用户希望离开电脑。
- 定时任务/后台任务需要把结果发到 IM。

**注意**：本技能不是全局自动钩子。桌面端设置里没有「任务完成推 IM」的开关，**必须由用户在派活时提出，或由你在收尾前先与用户确认**。

## 二、怎么用

脚本随技能一起安装，纯标准库，无需第三方依赖：

```bash
# 只读预检，不发消息
python3 __SKILL_DIR__/scripts/notify.py "测试通知" --channel weixin --dry-run

# 真实发送
python3 __SKILL_DIR__/scripts/notify.py \
  "OCR 与汇总已完成，共 42 份，结果在 ~/Desktop/ocr_out" --channel weixin
```

通道标识：`weixin` / `wecom` / `feishu` / `dingtalk` / `quantum`（默认 `weixin`）。

退出码：`0` = 平台已确认送达；非 0 = 未送达（看 stderr 的原因）。

> 安装脚本会把上面的 `__SKILL_DIR__` 替换成技能的真实绝对路径。TeleAgent 运行时没有 `CLAUDE_SKILL_DIR` 之类变量，所以必须写绝对路径。

## 三、发送前先自检

30 秒确认通道可用：

```bash
sqlite3 ~/.local/share/TeleAgent/users/<userId>/ais/ais.db \
"SELECT b.channel, b.enabled, COUNT(d.id) AS 目标会话数
   FROM messaging_bindings b
   LEFT JOIN messaging_destinations d ON d.binding_id = b.id
  GROUP BY b.channel, b.enabled;"
```

目标通道需满足 `enabled=1` 且「目标会话数」≥ 1。不满足时**不要改数据库**，先让用户在客户端里登录该通道并和它完成过一次真实对话。

## 四、通知内容怎么写

- **写结果位置，不写敏感正文**：推荐「报告已生成：report.docx，请在本机输出目录检查」。
- **不要塞进**真实名单、账号、邮件正文、业务明细、路由令牌——通知的作用是让人回来检查，不是把敏感数据复制到第三个平台。
- **按真实结果写文案**：任务失败就写失败，不要一律写「已完成」。

## 五、失败了怎么判断

| 输出 | 含义 | 处理 |
|------|------|------|
| `状态：已送达` | 平台已确认 | 收工，在回复里说明已通知 |
| `状态：unknown` | 平台未确认 | **会话上下文过期**：让用户到该 IM 里给机器人发一句话，再重试。**不要直接重发**，可能已送达 |
| `状态：failed` 等 | 平台明确拒收 | 看错误信息，多为通道掉线或未登录；先让用户确认通道状态 |
| `找不到通道…` | 无绑定或无会话目标 | 让用户登录该通道并完成一次真实对话 |
| 超时 | 仍在处理中 | 查状态，不要盲目重发 |

## 六、原理速记（排错时用）

3.1.1 的 IM 投递队列在 **ais** 侧（`~/.local/share/TeleAgent/users/<userId>/ais/ais.db`）：

- `messaging_deliveries`：一条投递（`kind='proactive'`、`state='pending'`、`route_snapshot={"conversation":…,"reply_ref":…}`）
- `messaging_delivery_items`：投递明细（`state='pending'`），**缺它不会被取走**
- 本脚本向客户端的本地投递队列写入一条主动投递记录，ais 的派发 worker 约 2 秒扫一次并交给 im-adapter 发送，由适配器调对应平台的 SDK 投递

ais 的取件条件逆向自其二进制 SQL，升级后若投递不再被取走，先核对表名、字段与状态取值是否仍一致。

## 七、边界

- 不装服务、不改启动项、不开端口、不留常驻进程；脚本只写入投递队列的一条记录，其它数据不受影响。
- 表结构属内部实现，TeleAgent 升级后需重新核验；本技能不保证跨版本可用。
- 依赖微信一类通道的**会话窗口**：用户长时间不说话时主动推送会被平台拒收（`ret=-2 prepare failed`），这是平台限制，不是脚本故障。
