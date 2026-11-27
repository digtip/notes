---
title: "TeleAgent 跨会话 IM 主动通知：让长任务完成后自动提醒（3.1.1 实战）"
date: 2026-11-27
tags: [TeleAgent, IM 通知, SQLite, Python, 自动化, AI Agent]
description: 在 TeleAgent 对话框里派一个耗时的活儿，干完后自动推一条微信到手机，而不是靠人守着窗口看进度；跑在云电脑上时更是刚需。本文复盘一版方案在 TeleAgent 3.1.1 上如何彻底失效，又如何逆向出新版真正的投递入口、逆向出派发队列的取件条件，并给出参数化 Python 脚本、技能打包方式、会话窗口这个隐藏坑，以及把结果交给 AI 实施的提示词模板。
status: published
original: "https://gitee.com/digtip/notes/blob/main/blog/ai/TeleAgent%20%E8%B7%A8%E4%BC%9A%E8%AF%9D%20IM%20%E4%B8%BB%E5%8A%A8%E9%80%9A%E7%9F%A5%EF%BC%9A%E8%AE%A9%E9%95%BF%E4%BB%BB%E5%8A%A1%E5%AE%8C%E6%88%90%E5%90%8E%E8%87%AA%E5%8A%A8%E6%8F%90%E9%86%92%EF%BC%883.1.1%20%E5%AE%9E%E6%88%98%EF%BC%89.md"
cover: "../../assets/teleagent-im-notify-cover.png"
---

# TeleAgent 跨会话 IM 主动通知：让长任务完成后自动提醒（3.1.1 实战）

## 一、那个最烦人的等待

在 TeleAgent 的对话框里派了个活儿：把这批扫描件 OCR 出来、归档、再生成一份汇总报告。它跑起来了，窗口里滚着日志。

然后你发现一件事——你哪儿也去不了。

这个活儿要跑二十分钟，你不能一直守着窗口；去开个会，又担心它早就失败了还在那儿空转。于是每隔十分钟你切回来看一眼：是在跑、在等你确认，还是已经卡住。

这不是「AI 还不够聪明」的问题，而是**通知方向**的问题：IM 通道默认是被动应答的——你在微信里问，它才回；而你需要的是**它干完主动叫你**。

TeleAgent 自带微信、企业微信、飞书等 IM 通道，但 3.1.1 的设置里**没有**「任务完成推 IM」这种开关（设置里的通知项只是桌面系统的弹窗和提示音，不是微信消息）。所以这件事要么自己接，要么就一直没有。

接法不难，难的是：这件事得**发生在桌面客户端里**——你是在对话框里派活的人，不是坐在终端前敲命令的人。

### 还有一种更刚需的场景：在云电脑上跑

现在可以申请免费的天翼云电脑，把 TeleAgent 装到云端跑。这个场景下，前面那套等待的痛点会被放大：

- 云电脑不在手边，屏幕没法一直盯着；
- 云机会话可能被挂起、被回收，长任务到底跑没跑完，你完全不知道；
- 而手机是唯一一直在你身上的设备。

于是「跑完在微信上叫你」在这里不是省事，而是**唯一能把这件事闭环的信号**。

实现上仍是同一套：会话里的 Agent 在收尾时执行通知脚本，脚本往 TeleAgent 自己的投递队列写一条主动投递，由官方适配器发到你手机上那个 IM 账号——你在哪个平台用它、在哪儿用，都不影响消息送到手上。

需要按平台调整的只有一处：脚本定位投递队列的路径。本文实测环境是 Linux ARM64（容器部署）；云电脑上跑通常是 Windows 环境，数据目录与 Python 运行时都不同，定位逻辑要按目标机器改。但**方法本身不挑平台**——它挑的是「找到当前版本的投递入口」这件事，而这正是后面第五到七节在做的事。

这篇文章记录一次完整的实现与踩坑过程：我的第一版方案在新版本上**彻底失效**，我又把它挖了出来，并且拿到了一个能用的新方案。中间有三件事比最后的脚本更值得写下来。

> [!note]
> 文中所有路径、SQL、脚本均在 **TeleAgent 3.1.1**（Linux ARM64，KARE 容器部署）上实测通过。真实路由 ID、上下文令牌、账号 ID 已全部用占位符替代，脚本也不内置任何真实值。


> [!tip] 三分钟版
> - **你要的效果**：在对话框里派的活儿干完后，微信自动收到一条「完成了」。
> - **前提**：客户端里登录好微信通道，并**跟机器人说过一句话**。
> - **最短命令**：`python3 notify.py "任务完成" --channel weixin`（脚本见第九节）
> - **怎么接进日常**：在派活的那段话里加一句「完成后执行 `python3 ~/bin/notify.py "..." --channel weixin`」，Agent 做完会自己发；更省事的做法是把它做成一个技能，之后说一句「跑完通知我」即可（详见第二节）。
> - **背后原理**：把通知写进客户端自己的投递队列，由官方适配器发到微信——不自己实现微信 API，所以令牌、限流、消息格式都不用你管。
> - **最容易踩的坑**：微信的会话上下文会过期，通知会停在 `unknown`；解法是先去微信说一句话。

## 二、先跑起来：桌面端里怎么用

TeleAgent 是桌面客户端，日常用法是在对话框里派活。所以「应用起来」只有一个问题：

> **怎么让会话里的 Agent，在长任务干完之后，顺手给你发一条微信。**

有两种接法：**(A) 每次派活时写一句收尾命令**，立刻可用；**(B) 把它做成一个技能**，装一次之后一句话就能触发。推荐 B。

### 前提：三件事，缺一不可

1. **客户端里这个 IM 通道已经登录**（微信、企业微信、飞书、钉钉、量子密信任选其一）。
2. **你跟它聊过一次**——哪怕只发一句「你好」。这一步会生成一段"会话上下文"，主动推送要靠它；跳过这步，后面必然失败。
3. **该通道在客户端里处于启用状态**。

30 秒自检：

```bash
# <userId> 是 ~/.local/share/TeleAgent/users/ 下的目录名
sqlite3 ~/.local/share/TeleAgent/users/<userId>/ais/ais.db \
"SELECT b.channel, b.enabled, COUNT(d.id) AS 目标会话数
   FROM messaging_bindings b
   LEFT JOIN messaging_destinations d ON d.binding_id = b.id
  GROUP BY b.channel, b.enabled;"
```

期望看到你打算用的那一行是 `enabled=1`，且「目标会话数」≥ 1。

### 第一步：确认脚本放在 Agent 够得着的地方

TeleAgent 跑在 KARE 容器里，但容器把整个 `/home` 与宿主机共享（同一块数据盘），而且自带 Python 3.8。所以放在家目录下的脚本，会话里的 Agent 用 Bash 工具就能直接执行——这也是为什么这件事在桌面端能成立，而不用去折腾容器。

**最省事：从代码仓库一键安装**（脚本 + 技能一次装好）。

仓库地址（本文配套代码，含 Linux / Windows 安装脚本与自检用例）：

```text
https://gitee.com/digtip/notes/tree/main/VibeCoding/teleagent-im-notify
```

```bash
# Linux / macOS
git clone https://gitee.com/digtip/notes.git
cd notes/VibeCoding/teleagent-im-notify && bash install.sh
```

```powershell
# Windows
git clone https://gitee.com/digtip/notes.git
cd notes\VibeCoding\teleagent-im-notify
powershell -ExecutionPolicy Bypass -File install.ps1
```

安装脚本会把 `notify.py` 放到 `~/bin/notify.py`（Windows 为 `$HOME\bin\notify.py`），并把技能装进当前账号的技能目录，同时把技能文档里的占位符替换成真实绝对路径。

**如果你更想手动来**：把第九节的脚本存成 `~/bin/notify.py`（或任意家目录下的路径）：

```bash
mkdir -p ~/bin && chmod +x ~/bin/notify.py
```

### 第二步：先自己发一条，确认通道是通的

```bash
python3 ~/bin/notify.py "第一条测试通知 ✅" --channel weixin
# 通知已提交：dlv_local_1755...
# 状态：已送达
```

微信里应该同时收到这条消息。

> [!warning] 如果状态停在 `unknown`
> 这不是脚本坏了，是**会话上下文过期**：微信只允许机器人在一个还活着的会话窗口里回话，而你手上的是上一次对话留下的旧上下文。
> 解法：**先去微信给机器人发一句话**，它进到客户端后会刷新上下文，回来重跑本步即可。

### 接法 A：每次派活时写一句收尾命令

在给 Agent 派活的那段话里，**直接写清楚收尾要做什么**：

```text
把 ~/Desktop/ocr 下的 42 份扫描件 OCR 成文本，按申请人姓名归档，并生成一份汇总表。

预计要跑十几分钟。任务完成后必须执行：
    python3 ~/bin/notify.py "OCR 与汇总已完成，共 42 份，结果在 ~/Desktop/ocr_out" --channel weixin
通知失败不影响任务本身，但要在最终回复里说明通知是否发送成功。
```

Agent 做完之后会自己执行这条命令，你在微信上就收到了。

如果你每次派活的开场白都差不多，把它写进那段固定模板里，就等于一次配置、长期生效。

### 接法 B：做成一个技能（推荐，装一次用很久）

TeleAgent 内置技能系统。把上面那套「脚本 + 用法 + 排错」打包成一个技能，之后在对话框里说一句「跑完通知我微信」，模型就会自动命中并调用它。

#### 技能放在哪

3.x 的技能按账号隔离：

```text
~/.config/TeleAgent/users/<userId>/skills/<技能名>/SKILL.md
```

目录长这样：

```text
im-notify/
├── SKILL.md
└── scripts/
    └── notify.py        ← 仓库完整版；支持跨平台路径与 --file 参数
```

#### SKILL.md 怎么写才路由得到

frontmatter 有四个关键字段：

| 字段 | 作用 |
|------|------|
| `name` | 英文短名，与目录名一致 |
| `description` | **模型靠这个字段判断要不要启用技能**，必须写清「什么时候用」，并把用户可能说的话原文列进去 |
| `name_cn` / `description_cn` | 技能页展示用 |

`description` 是路由的关键，本技能实际这么写：

```yaml
---
name: im-notify
description: 把耗时任务的结果主动推送到微信/企业微信/飞书/钉钉/量子密信等 IM 通道。用户说"干完通知我"、"做完了发微信"、"跑完告诉我一声"、"结果出来推给我"、"批量/定时任务跑完提醒"，或需要在长任务末尾调用本技能时使用。实现方式是向 TeleAgent 本地投递队列写入一条 proactive 投递，由官方适配器负责发送，不自行实现各平台 API。
name_cn: "IM 完成通知"
description_cn: "耗时任务跑完后把结果主动推到微信/企微/飞书等 IM 通道：向本地投递队列写一条 proactive 投递，交给官方适配器发送；含通道自检、会话窗口过期等平台限制的排错。"
---
```

正文部分写清楚四件事：**什么时候用**（触发场景）、**怎么用**（脚本路径与参数）、**发送前自检**（通道是否 enabled、有无会话目标）、**失败了怎么判断**（`unknown` = 会话过期，别重发）。

#### 完整 SKILL.md（可直接复制）

> 仓库里已经带了这份文件（`skill/im-notify/SKILL.md`），用上面的安装脚本即可，无需手工复制。下面保留全文，方便你理解每个字段的作用，或在没有仓库时直接取用。

把下面内容存为 `~/.config/TeleAgent/users/<userId>/skills/im-notify/SKILL.md`（`<userId>` 换成实际目录名），并把第九节的脚本放到同目录的 `scripts/notify.py`：

````markdown
---
name: im-notify
description: 把耗时任务的结果主动推送到微信/企业微信/飞书/钉钉/量子密信等 IM 通道。用户说"干完通知我"、"做完了发微信"、"跑完告诉我一声"、"结果出来推给我"、"批量/定时任务跑完提醒"，或需要在长任务末尾调用本技能时使用。实现方式是向 TeleAgent 本地投递队列写入一条 proactive 投递，由官方适配器负责发送，不自行实现各平台 API。
name_cn: "IM 完成通知"
description_cn: "耗时任务跑完后把结果主动推到微信/企微/飞书等 IM 通道：向本地投递队列写一条 proactive 投递，交给官方适配器发送；含通道自检、会话窗口过期等平台限制的排错。"
---

# IM 完成通知（主动推送）

把「任务跑完了」变成手机上一条微信，而不是让人守着窗口看进度。

## 一、什么时候用

- 用户在派活时说明要收尾通知：「做完通知我」「完成后发微信」「跑完说一声」。
- 长耗时任务（批量处理、OCR、导出、构建、爬取）收尾时，用户希望离开电脑。
- 定时任务/后台任务需要把结果发到 IM。

**注意**：本技能不是全局自动钩子。桌面端设置里没有「任务完成推 IM」的开关，**必须由用户在派活时提出，或由你在收尾前先与用户确认**。

## 二、怎么用

脚本在本技能目录内，用容器自带的 python3 即可运行（纯标准库，无需第三方包）：

```bash
# 只读预检，不发消息
python3 ~/.config/TeleAgent/users/<userId>/skills/im-notify/scripts/notify.py \
  "测试通知" --channel weixin --dry-run

# 真实发送
python3 ~/.config/TeleAgent/users/<userId>/skills/im-notify/scripts/notify.py \
  "OCR 与汇总已完成，共 42 份，结果在 ~/Desktop/ocr_out" --channel weixin
```

通道标识：`weixin` / `wecom` / `feishu` / `dingtalk` / `quantum`（默认 `weixin`）。

退出码：`0` = 平台已确认送达；非 0 = 未送达（看 stderr 的原因）。

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
- ais 派发 worker 约 2 秒扫一次并交给 im-adapter 发送；官方接口 `CreateProactiveDelivery` 需要 plugin token，外部脚本拿不到，所以本技能走写库路径

ais 的取件条件逆向自其二进制 SQL，升级后若投递不再被取走，先核对表名、字段与状态取值是否仍一致。

## 七、边界

- 不装服务、不改启动项、不开端口；回退只需删除本技能目录。
- 表结构属内部实现，TeleAgent 升级后需重新核验；本技能不保证跨版本可用。
- 依赖微信一类通道的**会话窗口**：用户长时间不说话时主动推送会被平台拒收（`ret=-2 prepare failed`），这是平台限制，不是脚本故障。
````

#### 技能里怎么引用自己的脚本（这里有个坑）

Claude Code 的技能习惯用 `${CLAUDE_SKILL_DIR}` 引用自带脚本，但 **TeleAgent 的运行时里没有这个变量**（在二进制里检索不到任何 `*_SKILL_DIR`）。所以技能里必须写绝对路径：

```bash
python3 ~/.config/TeleAgent/users/<userId>/skills/im-notify/scripts/notify.py \
  "任务完成摘要" --channel weixin
```

#### 装完要让它被扫到

新放进去的技能不会立刻生效：客户端在启动时扫描技能目录并写入 `skills-metadata.json`。所以**装完要重启一次 TeleAgent**（或打开技能页触发扫描），技能列表里才能看到它。

#### 技能也不是全局钩子

即使装成了技能，桌面端**不会**「每次任务结束都自动通知」——客户端设置里只有桌面系统的弹窗和提示音，没有「任务完成推 IM」这种开关（ais 的 `settings_config` 里只有 `notification_enabled` / `notification_sound_enabled`）。

技能靠 `description` 路由命中，所以派活时仍然要带一句「跑完通知我」。区别只在于：命令不用你手写了。

### 第四步：想更省事，可以让它自己记住

派活时顺带说一句「把这条收尾规则记在工作空间的 `notify-rule.md` 里，以后本工作空间的耗时任务都照做」，Agent 会把规则落到工作空间的文件里，之后新会话里提一句「按 notify-rule.md 的规则收尾」即可。

不过要清楚一点：这是**约定**，不是**机制**。它依赖 Agent 记得读那份文件，不同版本、不同会话未必稳定。真正稳定的还是每次派活都写明，或者装成技能。

### 另外两种形态

**如果你更习惯脚本**：把通知挂在自己跑的长任务后面即可，和桌面端互不影响：

```bash
python3 long_task.py && python3 ~/bin/notify.py "任务完成：<结果位置>" --channel weixin
```

**如果你在做自己的工具**：核心就是一条 INSERT 加一条明细（务必用参数绑定，不要拼字符串）：

```python
conn.execute(
    """INSERT INTO messaging_deliveries
         (id, binding_id, destination_id, turn_id, kind, caller_identity,
          idempotency_key, state, route_snapshot, expires_at, content_digest,
          safety_proof, content, retry_mode, created_at, updated_at)
       VALUES (?, ?, ?, '', 'proactive', 'my-tool', ?, 'pending', ?, ?, ?, '', ?, 'none', ?, ?)""",
    (delivery_id, binding_id, destination_id, idempotency_key,
     json.dumps({"conversation": conversation, "reply_ref": reply_ref}),
     expires, digest, message, ts, ts))
# 再往 messaging_delivery_items 插一条 state='pending' 的文本明细，才会被取走
```

绑定与目的地要从 `messaging_bindings` / `messaging_destinations` 查，路由 JSON 的键名是 `conversation` 与 `reply_ref`——取件条件见第七节。

## 三、问题的本质：不是「能不能回复」，而是「能不能主动开始一条消息」

先摆清楚 IM 通道的默认流程：

```text
用户在 IM 里发消息
        ↓
Agent 收到请求并处理
        ↓
回复沿原通道返回
```

整条链路是**被动**的：没有外部输入，就没有输出。桌面会话和 IM 会话又是两个上下文——会话里的 Agent 即便知道「某个 IM 已经连着」，也没有任何理由在任务结束时自己开口。

要让通知跑起来，得同时满足三件事：

1. **找到投递入口**。自己实现微信/企微/飞书的发送 API，意味着你要处理平台适配、令牌、限流、幂等、平台规则变化——客户端已经做过一遍了，没必要重写。
2. **拿到目标会话的路由**。知道「往哪儿发」，而不只是「往微信发」。
3. **能区分「写入成功」和「用户已收到」**。这两件事之间隔着一次真实的网络发送和一次平台侧确认。

第 3 点最容易被糊弄过去，也是很多「自动通知」脚本的假成功来源。

## 四、第一版方案：复用客户端自己的本地消息队列

2026 年 8 月，我在 TeleAgent 2.1 上做过一次实操。思路很直接：**客户端里已经有一个专门负责把消息投到 IM 的 worker，与其自己实现一套，不如把通知塞进它的队列。**

2.1 的 IM 服务跑在 Electron 主进程里，底层有一个 SQLite 库和一张消息表，表里有一列 `status`，取值像 `to_submit → collecting → to_deliver → delivered`。其中 `to_deliver` 表示「回复已生成，等待投递到 IM」。

于是一次主动通知就变成了：往表里插一行 `status='to_deliver'` 的记录，worker 每秒扫一次表，把它推出去。

```text
桌面会话里的 Agent 完成任务
        ↓
写入一行 status='to_deliver' 的消息
        ↓
push-phone worker 每秒轮询到它
        ↓
按 channel 调用对应平台 API
        ↓
delivered / failed
```

当时的实测结果：**微信、飞书、企业微信三个通道全部投递成功，延迟约 1 秒。**

这个方案的妙处在于它完全没有自己实现任何平台逻辑——令牌怎么管、限流怎么处理、消息格式怎么拼、失败了怎么重试，全部由客户端自己的适配层负责。脚本只干了「投递队列入口」这一件事。

**它还有一个当时没被重视、后来要命的性质：它依赖的是内部实现，不是公开 API。**

## 五、三个月后：它在新版本上悄无声息地失效了

11 月底，TeleAgent 已经升到 3.1.1。我按老脚本试了一下——插进去的那行记录，**二十多秒过去，状态纹丝不动**。

```text
t=2s   ('to_deliver', '', '')
t=4s   ('to_deliver', '', '')
...
t=24s  ('to_deliver', '', '')
```

没有报错，没有失败日志，就是没有 worker 来取。

于是开始查。这次的排查过程本身比结论更有价值，所以完整写出来。

### 5.1 先确认「谁还在用这个表」

最直接的办法是翻程序包。TeleAgent 的 Electron 主程序打成一个 asar 归档，用 `strings` 扫一遍关键词：

```bash
# 3.1.1 的 asar 在 KARE 合并层里
ASAR=/opt/kare-applications/v10sp1/merge/opt/TeleAgent/resources/app.asar
strings "$ASAR" | grep -c "push-phone"     # 0
strings "$ASAR" | grep -c "to_deliver"     # 0
```

两个都是 0。说明新版本里**既没有那个 worker，也没有那个状态值**——不是 worker 停了，是整条链路换了实现。

### 5.2 再确认「旧表变成了什么」

有意思的是，新版本的数据库里**那张表还在**，字段几乎没变。但它已经被降级成了历史遗留物，只在迁移时被读一次，用来恢复路由：

```sql
-- 这段 SQL 来自 ais 二进制中的字符串，是 3.1.1 里唯一还提到 to_deliver 的地方
SELECT route_target, inbound_sender_user_id, created_at FROM im_message
 WHERE channel = ? AND inbound_source = 'channel_bot'
   AND status IN ('collecting','to_deliver','delivered','skipped')
```

`messaging_route_states` 表里的 `switch_operation_id` 也留着迁移痕迹，值是 `legacy-im-v1:<binding_id>`。

翻译成人话：**旧方案不是「暂时坏了」，而是被显式归档成了 legacy。新消息不再写它，也没有任何组件轮询它。**

### 5.3 顺便回答一个悬案

这版方案最初是谁做的，我一直记不清——是 Qwen Code 还是 Claude Code？翻出当时的文档署名和当天的日志，两处都写着 **TeleAgent 自带的助手**。这次查证的另一个副产品是：很多「AI 写的方案」，作者其实是产品内置的那个 AI。

### 5.4 这一节的教训

> [!warning]
> 内部结构不是承诺，升级即可能消失。
>
> 依赖内部实现的自动化方案，正确做法不是「记住它」，而是**每次都重新读当前版本的实现**。文章、脚本、笔记里的一切路径和表名，都要当作「上次验证时的快照」而不是「事实」。

## 六、3.1.1 的新架构：谁在管投递

新版本把整个 IM 能力拆成了三层（`ais` 是客户端内部负责 IM 中转与投递状态的后端服务，`im-adapter` 是负责对接各平台 SDK 的适配进程）：

```text
┌──────────────────────────────────────────────┐
│  im-adapter（独立 Node 进程）                │
│  微信 / 企微 / 飞书 / 钉钉 / 量子密信 SDK     │
│  只做平台事件 ↔ 协议翻译，不持有状态          │
└───────────────┬──────────────────────────────┘
                │ 私有 gRPC 桥（unix socket + Bearer 令牌）
                │ ClaimOutbound 领取 / ReportDelivery 回报
                ▼
┌──────────────────────────────────────────────┐
│  ais（Go 后端）—— 唯一的投递状态持有者        │
│  Binding / Session / Turn / Delivery         │
│  投递队列：ais.db 的 messaging_deliveries    │
└───────────────┬──────────────────────────────┘
                │ WatchOutbound 推送
                ▼
        用户的微信 / 企微 / 飞书
```

和 2.1 相比，有五个变化值得记住：

| | 2.1 | 3.1.1 |
|---|---|---|
| 投递队列 | Electron 侧的 SQLite 消息表 | ais 侧的 `messaging_deliveries` 表 |
| 谁来取 | Electron 内置 worker | ais 的派发 worker |
| 谁来发 | Electron 进程直接调平台 API | 独立的 im-adapter 进程 |
| 通道数 | 3 | 5（新增钉钉、量子密信） |
| 数据目录 | 应用根目录下固定位置 | 按账号隔离的 `users/<租户_用户>/` |

新版本还提供了一个**正式接口**：

```
POST /ais.v1.MessagingService/CreateProactiveDelivery
{ "destinationId": "md_xxx", "textParts": ["正文"], "idempotencyKey": "唯一键" }
→ { "deliveryId": "dlv_xxx" }
```

这正是「主动投递」的官方语义。但它是插件面接口，需要带 account/runtime/plugin/capabilities 声明的 **plugin token**，由桌面端启动时注入，外部脚本拿不到。实测用适配器自己的连接器令牌去调：

```
401 Unauthorized
invalid plugin credential
```

所以本地脚本这条路，只能走下面的办法。

## 七、逆向出「怎样写才会被自动取走」（本文最硬的一段）

既然取件逻辑在 ais 里，那就去读 ais 的实现。ais 是一个 Go 二进制，SQL 字符串都躺在 `data` 段里。`strings` 之后按上下文截取，就能把完整的语句捞出来：

```bash
# 从二进制里捞 SQL 上下文
python3 - <<'EOF'
import re
data = open('ais', 'rb').read().decode('latin-1')
for m in re.finditer('messaging_deliveries', data):
    frag = data[max(0, m.start()-300): m.start()+300]
    if 'SELECT' in frag and 'next_attempt_at' in frag:
        print(re.sub(r'[^\x20-\x7e]', ' ', frag))
EOF
```

捞出来的那条，就是派发 worker 的取件条件：

```sql
SELECT d.id FROM messaging_deliveries d
JOIN messaging_bindings b ON b.id = d.binding_id
WHERE b.connector_id = ? AND b.enabled = 1 AND d.state = ?
  AND (d.next_attempt_at IS NULL OR d.next_attempt_at <= ?)
  AND (d.predecessor_id = '' OR EXISTS (
        SELECT 1 FROM messaging_deliveries p WHERE p.id = d.predecessor_id
          AND p.state IN ('sent','delivered','failed','suppressed','expired','dead_letter')))
  AND (d.expires_at IS NULL OR d.expires_at > ?)
  AND EXISTS (SELECT 1 FROM messaging_delivery_items i
               WHERE i.delivery_id = d.id AND i.state IN ('pending', ...))
```

翻译成人话，一条主动投递要成立，需要：

1. `binding.connector_id` 是官方适配器、`binding.enabled = 1`；
2. 投递记录 `state = 'pending'`，且没有过期时间或未过期；
3. **至少有一条 `pending` 状态的投递明细**（`messaging_delivery_items`）；
4. `route_snapshot` 里带着会话信息（`{"conversation": ..., "reply_ref": ...}`）；
5. `caller_identity + idempotency_key` 唯一，避免重复投递。

比「往表里插一行」复杂，但每一项都有明确含义，而且都是**当前版本的真实约束**。

## 八、三个反直觉的坑

### 8.1 坑一：会话窗口——「你最近说过话吗」

第一次按上面的条件写完一条投递，状态在两秒内从 `pending` 变成 `sending`，然后——停住了，最终落在一个叫 `unknown` 的状态。

第一反应是脚本写错了。换个思路：不用脚本，直接拿同一份凭据调平台发送接口，看平台怎么说：

```text
带旧 context_token：  HTTP 200  {"ret":-2,"errmsg":"prepare failed"}
不带 context_token：   HTTP 200  {"ret":-2,"errmsg":"prepare failed"}
```

`prepare failed`。平台既不接受过期令牌，也不接受「没有上下文的主动消息」。

原来微信这类通道的会话是有**时效**的：机器人只能在一个还活着的会话窗口里回话。而 3.1.1 里的会话上下文来自上一次真实对话——我这条目的上下文是**一个月前**的，早过期了。

解决办法有点反直觉：**让使用者在微信里先说一句话**。这条消息进到 ais 后，会话上下文被刷新，然后主动推送立刻就通了：

```text
[等待] 检测微信入站……
[命中] 新会话上下文 @ 2026-11-27T02:02:05Z
[投递] dlv_e2e_…
  t=2s  delivery=('sending', attempt_count=1)
  t=4s  delivery=('sent',    attempt_count=1)
```

从「用户说一句话」到「通知送达」，两秒。

> [!important]
> 这是整个方案里最反直觉、也最容易漏掉的一条：**主动推送不是随时可发的，它依赖一个仍然有效的会话上下文。**
>
> 排查「推送没出去」时，先问一句：目标会话最近一次真实对话是什么时候？如果是很久以前，那么问题不在脚本，也不在平台连通性，而在会话窗口。

### 8.2 坑二：`unknown` 不是 `failed`，而且绝对不能谎报

平台拒收时，适配器回报的是 `unknown` 而不是 `failed`。看上去像 bug，其实是有意为之。

理由在适配器的失败映射规则里：只有平台**明确拒绝**（比如鉴权失败、参数非法）才能报 `failed`；网络抖动、超时、分类不明的错误，都可能是「消息其实已经发出去了，只是回执丢了」。如果此时谎报失败，上层很可能会重试——**结果是使用者收到两条一样的通知**。

所以策略是 fail-closed：不确定就冻结，等人工判断。这条规则值得抄到任何自建推送方案里。

### 8.3 坑三：「写入成功」不等于「用户已收到」

从 `pending` 到用户手机上的通知，中间还有 `sending`、`sent`，以及可能的 `failed`、`unknown`、`suppressed`、`expired`、`dead_letter`。

写完数据库就打印「通知已发送」是自欺欺人。脚本必须**轮询状态**，并把每种终态区分开：

| 状态 | 含义 | 该做什么 |
|---|---|---|
| `sent` | 平台已接受 | 收工 |
| `failed` | 平台明确拒收 | 看错误信息，勿盲目重试 |
| `unknown` | 平台未确认 | 查会话窗口；**不要重发** |
| `suppressed` / `expired` / `dead_letter` | 被抑制 / 过期 / 死信 | 重新走一遍前置条件 |

## 九、可直接使用的通知脚本

下面是 3.1.1 上实测通过的核心版本。它只做一件事：找到目标会话的路由，写一条主动投递，然后**轮询到终态**。配套仓库中的 `notify.py` 保留了相同投递逻辑，并增加 Windows 数据目录定位、`--file` 正文读取和集中状态分类；日常使用建议直接安装仓库完整版。

```python
#!/usr/bin/env python3
"""Send a proactive IM notification through the local AIS delivery queue."""

import argparse
import hashlib
import json
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path.home() / ".local/share/TeleAgent"
CHANNELS = ("weixin", "wecom", "feishu", "dingtalk", "quantum")


def resolve_db() -> Path:
    """Locate the per-account AIS database of the currently signed-in owner."""
    owner = BASE / "current-owner.json"
    if owner.is_file():
        d = json.loads(owner.read_text(encoding="utf-8"))["ownerDir"]
        p = BASE / "users" / d / "ais" / "ais.db"
        if p.is_file():
            return p
    hits = sorted((BASE / "users").glob("*/ais/ais.db"))
    if not hits:
        raise FileNotFoundError("找不到 ais.db，请先启动一次客户端")
    return hits[-1]


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=10)
    conn.execute("PRAGMA busy_timeout = 8000")
    return conn


def load_target(conn: sqlite3.Connection, channel: str):
    """The channel must be enabled and must have a known conversation target."""
    row = conn.execute(
        """SELECT b.id, d.id, d.external_conversation_id, d.opaque_reply_ref
             FROM messaging_bindings b
             JOIN messaging_destinations d ON d.binding_id = b.id
            WHERE b.channel = ? AND b.enabled = 1""",
        (channel,),
    ).fetchone()
    if not row:
        raise RuntimeError(
            f"通道 {channel} 没有可用的绑定或会话目的地："
            "先在客户端里登录该通道，并和它完成过一次真实对话"
        )
    return row


def notify(message: str, channel: str, timeout: int, dry_run: bool) -> None:
    if not message.strip():
        raise ValueError("通知内容不能为空")

    db_path = resolve_db()
    with connect(db_path) as conn:
        binding_id, dest_id, conversation, reply_ref = load_target(conn, channel)

    if dry_run:
        print(f"只读检查通过：通道={channel}，目标会话已就绪，未写入数据库")
        return

    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H:%M:%S.%f000Z")
    expires = (now + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S.%f000Z")
    delivery_id = f"dlv_local_{int(time.time() * 1000)}"
    item_id = f"dli_local_{int(time.time() * 1000)}"
    idempotency_key = f"local-{int(time.time() * 1000)}"

    with connect(db_path) as conn:
        conn.execute(
            """INSERT INTO messaging_deliveries (
                 id, binding_id, destination_id, turn_id, kind, caller_identity,
                 idempotency_key, state, stream_key, sequence, predecessor_id,
                 replaces_delivery_id, route_snapshot, expires_at, content_digest,
                 safety_proof, content, claim_generation, attempt_id, attempt_count,
                 claim_expires_at, retry_mode, late_report, next_attempt_at,
                 last_error, created_at, updated_at
               ) VALUES (?, ?, ?, '', 'proactive', 'local-script', ?, 'pending',
                         '', 0, '', '', ?, ?, ?, '', ?, 0, '', 0, NULL, 'none',
                         '', NULL, '', ?, ?)""",
            (delivery_id, binding_id, dest_id, idempotency_key,
             json.dumps({"conversation": conversation, "reply_ref": reply_ref}),
             expires, hashlib.sha256(message.encode()).hexdigest(), message, ts, ts),
        )
        conn.execute(
            """INSERT INTO messaging_delivery_items (
                 id, delivery_id, kind, text_content, state, platform_message_id,
                 created_at, updated_at
               ) VALUES (?, ?, 'text', ?, 'pending', '', ?, ?)""",
            (item_id, delivery_id, message, ts, ts),
        )
    print(f"通知已提交：{delivery_id}（通道：{channel}）")

    deadline = time.monotonic() + timeout
    state = "pending"
    while time.monotonic() < deadline:
        time.sleep(1)
        with connect(db_path) as conn:
            row = conn.execute(
                "SELECT state, last_error FROM messaging_deliveries WHERE id = ?",
                (delivery_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("轮询时找不到刚写入的投递记录")
        state, error = row
        if state == "sent":
            print("状态：已送达")
            return
        if state in ("failed", "suppressed", "expired", "dead_letter"):
            raise RuntimeError(f"投递未成功：state={state}，{error or '无错误详情'}")
        if state == "unknown":
            raise RuntimeError(
                "平台未确认（unknown）：通常是会话上下文已过期。"
                "请先在该 IM 里让机器人回一句话，再重试；不要直接重发。"
            )
    raise TimeoutError(f"等待 {timeout} 秒后仍未送达，当前状态：{state}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("message", help="通知内容")
    parser.add_argument("--channel", choices=CHANNELS, default="weixin")
    parser.add_argument("--timeout", type=int, default=30, help="等待送达秒数")
    parser.add_argument("--dry-run", action="store_true", help="只读检查，不写入")
    args = parser.parse_args()
    if args.timeout < 1:
        parser.error("--timeout 必须大于等于 1")
    try:
        notify(args.message, args.channel, args.timeout, args.dry_run)
        return 0
    except Exception as exc:
        print(f"失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
```

### 先做只读预检

```bash
python3 notify.py "测试通知" --channel weixin --dry-run
```

预检只查通道绑定和会话目标，不写任何东西。看到「只读检查通过」再决定是否真实发送。

### 执行通知

```bash
python3 notify.py "数据整理已完成，可以回来检查结果。" --channel weixin
python3 notify.py "报告已生成。" --channel weixin --timeout 20
```

注意输出里有两个不同的「成功」：`通知已提交` 只代表写进了队列，`状态：已送达` 才代表平台确认。脚本两者都会打印，退出码也只有在送达时才为 0。

### 通道可用性

能不能主动推送，取决于三件事：该通道**已登录**、绑定**已启用**、且**存在会话目标**。3.1.1 实测：

| 通道 | 绑定启用 | 有会话目标 | 可否主动推送 |
|---|---|---|---|
| 微信 | 是 | 有 | 可以（需会话窗口有效） |
| 企业微信 | 是 | 无 | 先和它对话一次 |
| 量子密信 | 是 | 无 | 先和它对话一次 |
| 飞书 | 否 | 有 | 先在客户端启用 |
| 钉钉 | 未配置 | 无 | 先登录 |

## 十、桌面端使用的三个细节

（最快路径见第二节；这一节讲三个容易踩的细节。）

### 1. 通知是「收尾动作」，不是「结果」

```bash
python3 generate_report.py && \
python3 notify.py "报告生成成功，请查看输出目录。" --channel weixin
```

`&&` 很重要：只有主任务成功才发「完成」。主任务失败却收到一条「已完成」，比不通知更糟。

要分别报告成败，就让 Agent 按真实退出码选文案，不要一律写成「完成」。

### 2. 通知里写结果位置，不写敏感正文

```text
推荐：报告已生成：report.docx，请在本机输出目录检查。
不推荐：把名单、账号、邮件正文、业务明细或令牌塞进 IM 通知。
```

通知的作用是让人回来检查，不是把敏感数据复制到第三个平台。

### 3. 多通道要逐个确认

多个通道分别调用、分别看退出码。并行地把错误输出混在一起，你根本不知道是哪个通道失败了。

## 十一、验证：把「写入成功」和「用户收到」分开验

这类方案最容易出事的地方，是验证只做了一半。建议按下面四层推进，每层都能独立停下来：

| 层次 | 做什么 | 能证明什么 |
|---|---|---|
| ① 只读 | 扫程序包关键词、查进程打开的数据库、捞二进制里的 SQL | 当前版本到底还有没有这套机制 |
| ② 结构 | 核对表名、字段、状态取值与取件条件 | 你写的记录会不会被自动取走 |
| ③ 逻辑 | 用临时库或虚构路由跑脚本，验证成功/失败/超时/缺前置条件各分支 | 脚本本身不会误报成功 |
| ④ 真实 | 单条、无敏感内容、真发一次，并轮询到终态 | 平台真的收到了 |

第 ① 层最容易被跳过，也最致命——2026 年 8 月那次就是因为跳过了它，方案在三个月后静默失效。

第 ③ 层的分支至少要覆盖：写入成功但 worker 不取、平台拒收、超时、目标缺失、路由信息非法。

### 本次实测记录

| 步骤 | 动作 | 结果 |
|---|---|---|
| ① | 写 `to_deliver` 到旧表 | 24 秒无人领取，状态不变 |
| ② | 写 `kind='proactive'` 投递 | 2 秒 `sending`，最终 `unknown` |
| ③ | 同上，但不带 `reply_ref` | 仍 `unknown` |
| ④ | 直连平台发送接口 | `{"ret":-2,"errmsg":"prepare failed"}` |
| ⑤ | 使用者在微信发一条消息 | 会话上下文刷新 |
| ⑥ | 紧接着再次投递 | 2 秒 `sending`，4 秒 `sent`，微信收到 |
| ⑦ | 直接运行本文脚本 | 已送达 |

## 十二、安全与回退边界

1. **内部实现不是公开 API**。表名、字段、状态机随时会变，升级后必须重新核验，本文脚本不保证跨版本可用。
2. **不要构造真实路由**。脚本只读取本机已有的会话信息，路由、令牌、账号 ID 都不内置、不上传、不写进日志。
3. **幂等键要唯一**。`caller_identity + idempotency_key` 唯一，否则可能被当成重复投递直接丢弃。
4. **插入成功撤不回**。删除数据库记录不等于撤回已送达的消息，也会破坏本地的审计链。
5. **不自动改表结构**。缺表、缺列、字段异常就停下，不要 `ALTER TABLE`、不要清表重建。
6. **失败不要批量重试**。`unknown` 尤其不能重发——可能已经送达了。
7. **回退成本极低**：删掉脚本本身即可。它不装服务、不改启动项、不开端口、不写系统目录。
8. **正式接口优先**。当前绕开的是插件面鉴权；将来若桌面端开放本地调用 `CreateProactiveDelivery`，应第一时间切回去。

## 十三、推荐用法：把实施交给 AI

如果你想在自己的环境里复现，下面这段提示词可以直接用。它把「先只读核验、再动手」的顺序写死了，避免 AI 直接照抄文章里的 SQL：

```text
请协助我给 TeleAgent 桌面端加一个「长任务完成后推微信」的能力，但必须先核验版本和实现，不能直接照抄文章。

第一阶段只读，不做任何修改：
1. 查询正在运行的 TeleAgent 版本、真实进程、安装路径和已打开的数据库。
2. 核对本文环境：3.1.1 + ais 投递队列；不要把其它版本当成兼容版本。
3. 在程序包里检索关键实现标识（如 push-phone、to_deliver、messaging_deliveries），
   确认当前版本用的是哪条投递链路。
4. 不输出 route、reply_ref、令牌、用户 ID、真实通知内容或数据库中的业务消息。
5. 如果版本或结构不一致，立即停止写库方案，改查当前版本的官方接口。

只有确认结构一致后，才进入第二阶段：
1. 先复制脚本到工作目录，运行 --dry-run。
2. 所有可变值使用 SQLite 参数绑定，不拼接 SQL。
3. 先用临时数据库和虚构路由测试各分支，不修改真实数据库。
4. 真实测试前告诉我将写入的表、通知内容和回退边界，等待确认。
5. 第一次只提交一条无敏感信息的通知，并检查终态，而不是只看插入成功。
6. 若状态停在 unknown，先排查会话上下文是否过期，不要直接重发。
7. 任一路径、字段、状态或结果与预期不符，立即停止，不自行改表结构、不批量重试。

第三阶段（把脚本接进桌面端的日常使用）：
1. 把脚本放到家目录下（例如 ~/bin/notify.py），确认容器内的会话 Agent 能直接执行它。
2. 给我一段「派活提示词」模板：包含任务描述、收尾时执行的通知命令、以及通知失败时的说明要求。
3. 模板里只用占位符，不写真实路由、令牌或业务内容。
4. 更有用的是把它打包成一个技能：~/.config/TeleAgent/users/<userId>/skills/im-notify/，
   SKILL.md 的 description 里写清触发词（干完通知我 / 做完了发微信 / 跑完告诉我一声…），
   scripts/ 下放同一个脚本；提醒我装完需要重启客户端才会被扫描。

通知内容不得包含真实名单、账号、邮件、路由令牌或业务明细。
```

> [!note]
> 第三阶段的关键产出不是脚本，而是**那段派活模板**（或者把它做成技能）。桌面端没有全局的「任务收尾必发通知」开关，Agent 也不会凭空知道你要这个收尾动作——写进你每次派活的固定模板、或者交给技能按 description 自动路由，才是这条链路在日常使用中真正稳定下来的方式。

## 写在最后

这次折腾下来，最有价值的不是某一段 SQL，而是三点认知：

**第一，客户端往往已经具备完整的投递能力，缺的只是「把任务结果接进去的那个入口」。** 找到它，比自己实现一套省事得多，也稳得多。

**第二，入口会消失。** 内部结构随版本重构而变是常态，不是意外。所以任何依赖内部实现的方案，验证都必须**现场做**，不能靠三个月前的笔记。

**第三，「写入成功」和「用户收到」之间隔着一个真实世界。** 会话窗口、平台静默拒收、失败分类策略——这些东西不会在写入时告诉你，只会在你诚实地区分状态时才暴露。

而这三点的适用面，远不止 IM 通知：任何「让程序在另一个通道上替我说话」的自动化，都会撞上同一堵墙。

> **先读当前版本的实现，再决定怎么接；先分清「写进去了」和「发出去了」，再宣布成功。**

---

**配套代码与技能**（安装脚本、自检用例、跨平台脚本）：

```text
https://gitee.com/digtip/notes/tree/main/VibeCoding/teleagent-im-notify
```

原文链接：<https://gitee.com/digtip/notes/blob/main/blog/ai/TeleAgent%20%E8%B7%A8%E4%BC%9A%E8%AF%9D%20IM%20%E4%B8%BB%E5%8A%A8%E9%80%9A%E7%9F%A5%EF%BC%9A%E8%AE%A9%E9%95%BF%E4%BB%BB%E5%8A%A1%E5%AE%8C%E6%88%90%E5%90%8E%E8%87%AA%E5%8A%A8%E6%8F%90%E9%86%92%EF%BC%883.1.1%20%E5%AE%9E%E6%88%98%EF%BC%89.md>
