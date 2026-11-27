# TeleAgent IM 完成通知（通用脱敏版）

让 TeleAgent 桌面会话里的**长任务跑完后主动推一条微信**（也支持企业微信 / 飞书 / 钉钉 / 量子密信），而不是让人守着窗口看进度。

实现方式：不自己实现任何平台 API，而是向 TeleAgent 自己的投递队列写一条 `kind='proactive'` 的投递，由官方适配器（im-adapter）负责发送。

> 本目录不包含任何真实路由 ID、上下文令牌、账号 ID 或业务数据。脚本只从本机读取已有的会话信息，不内置任何凭据。

## 文件

- `notify.py`：通知脚本，纯标准库，无第三方依赖；Linux / Windows 通用。
- `skill/im-notify/SKILL.md`：TeleAgent 技能定义（`description` 决定模型何时路由到它）。
- `skill/im-notify/scripts/notify.py`：与根目录 `notify.py` 完全一致的副本（技能内自带脚本）。
- `install.sh`：Linux / macOS 安装脚本。
- `install.ps1`：Windows 安装脚本（PowerShell）。
- `test_notify.py`：自检脚本，用临时库和虚构路由跑各分支，不碰真实数据库。

## 安装

Linux / macOS：

```bash
cd VibeCoding/teleagent-im-notify
bash install.sh
```

Windows（PowerShell）：

```powershell
cd VibeCoding/teleagent-im-notify
powershell -ExecutionPolicy Bypass -File install.ps1
```

安装脚本做三件事：

1. 把 `notify.py` 复制到 `~/bin/notify.py`（Windows 为 `$HOME\bin\notify.py`），方便在终端和定时任务里直接调用；
2. 把技能装到当前账号的技能目录 `~/.config/TeleAgent/users/<账号>/skills/im-notify/`（Windows 优先使用 `%APPDATA%\TeleAgent\users\<账号>\skills\im-notify\`）；
3. 把 `SKILL.md` 里的 `__SKILL_DIR__` 替换成技能的真实绝对路径。

**装完需要重启一次 TeleAgent**：技能在客户端启动时扫描目录才会被索引，写进 `skills-metadata.json`。

回退：删除上述两处文件即可，不涉及服务、启动项、端口或系统目录。

## 使用

### 一、确认通道可用（30 秒）

```bash
sqlite3 ~/.local/share/TeleAgent/users/<userId>/ais/ais.db \
"SELECT b.channel, b.enabled, COUNT(d.id) AS 目标会话数
   FROM messaging_bindings b
   LEFT JOIN messaging_destinations d ON d.binding_id = b.id
  GROUP BY b.channel, b.enabled;"
```

目标通道需要 `enabled=1` 且「目标会话数」≥ 1。通道还要**登录过**，并且你**跟它聊过一次**——主动推送依赖那次对话产生的会话上下文。

### 二、预检与发送

```bash
python3 notify.py "测试通知" --channel weixin --dry-run
python3 notify.py "任务完成：结果在 ~/Desktop/ocr_out" --channel weixin
```

参数：`--channel weixin|wecom|feishu|dingtalk|quantum`（默认 weixin）、`--timeout 30`（等待送达秒数）、`--dry-run`（只读检查）、`--file <路径>`（从文件读正文）。

退出码 `0` 表示平台已确认送达；非 0 表示未送达，原因在 stderr。

### 三、接进桌面会话

在派活的那段话里写清收尾动作：

```text
把 ~/Desktop/ocr 下的 42 份扫描件 OCR 成文本并生成汇总表。

任务完成后必须执行：
    python3 ~/.config/TeleAgent/users/<userId>/skills/im-notify/scripts/notify.py \
      "OCR 与汇总已完成，共 42 份，结果在 ~/Desktop/ocr_out" --channel weixin
通知失败不影响任务本身，但要在最终回复里说明通知是否发送成功。
```

装成技能后，在对话框里说「跑完通知我微信」也会被模型路由到本技能。

## 测试

`test_notify.py` 使用系统临时目录与虚构路由，检查：

- `--dry-run` 真的不写库；
- 写入后的投递记录与明细字段正确（`kind='proactive'`、`state='pending'`、路由 JSON 的键名）；
- 缺少会话目标、通道不存在时明确报错并返回非 0；
- 投递状态到结果的映射（已送达 / 明确失败 / 未确认 / 处理中）；
- 根目录脚本与技能内副本逐字节一致。

```bash
python3 test_notify.py
```

看到 `Ran 6 tests ... OK` 表示全部通过。测试不读取也不修改真实数据库。

## 安全边界

- 不装服务、不改启动项、不开端口、不写系统目录；只写用户目录下的脚本、技能和 TeleAgent 投递队列。
- 不内置任何凭据；路由信息只从本机数据库读取，不上传、不写日志。
- 通知内容不要放真实名单、账号、邮件正文、业务明细或令牌——通知的作用是让人回来检查。
- 投递表与状态机属于 TeleAgent 内部实现，**升级后可能变化**，需重新核验；本项目不保证跨版本可用。
- 依赖平台侧的会话窗口：微信一类通道长时间无对话时主动推送会被平台拒收（`ret=-2 prepare failed`），这是平台限制，不是脚本故障。
- `unknown` 表示平台未确认，**不要直接重发**——消息可能已经送达，重发会收到两条。

## 原理速记

3.1.1 的 IM 投递队列在 ais 侧（`~/.local/share/TeleAgent/users/<userId>/ais/ais.db`）：

- `messaging_deliveries`：一条投递（`kind='proactive'`、`state='pending'`、`route_snapshot={"conversation":…,"reply_ref":…}`）
- `messaging_delivery_items`：投递明细（`state='pending'`），缺它不会被取走
- ais 派发 worker 约 2 秒扫一次，交给 im-adapter 发送，再由 ais 落终态
- 官方接口 `CreateProactiveDelivery` 需要 plugin token，外部脚本拿不到，因此本项目走写库路径
