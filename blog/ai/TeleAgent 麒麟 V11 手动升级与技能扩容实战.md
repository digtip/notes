---
title: TeleAgent 在银河麒麟 V11 升级失败：KARE 容器手动部署与技能上限解除实战
date: 2026-11-20
tags: [TeleAgent, 银河麒麟, KARE, Electron, ARM64, 信创, 二进制补丁]
description: TeleAgent 在银河麒麟 V11 ARM64 上无法通过官方通道升级（kysec 签名强制、退出码 16），本文记录从 2.4 到 3.1.1 十余次版本的手动解包部署流程、dpkg 元数据同步，以及技能启用数量三层拦截（Electron asar、Go 二进制、SQLite 触发器）的完整解除方案与回滚方法。
status: published
original: https://gitee.com/digtip/notes/blob/main/blog/ai/TeleAgent%20%E9%BA%92%E9%BA%9F%20V11%20%E6%89%8B%E5%8A%A8%E5%8D%87%E7%BA%A7%E4%B8%8E%E6%8A%80%E8%83%BD%E6%89%A9%E5%AE%B9%E5%AE%9E%E6%88%98.md
---

# TeleAgent 在银河麒麟 V11 升级失败：KARE 容器手动部署与技能上限解除实战

TeleAgent 是中国电信推出的 AI 办公助手，Electron 壳 + Go 后端架构，提供桌面端 deb 安装包。在 x86 主流发行版上双击安装即可，但在**银河麒麟 V11 ARM64（飞腾平台）**上，从 2.4.1 版本开始，官方 deb 全部无法通过正常通道安装或升级。

这套方案由我在日常使用中与 Qwen Code 多轮排障、验证并持续沉淀，涉及版本差异比较、日志分析、部署脚本编写和二进制补丁定位。文章是在这些原始记录基础上整理的公开版，AI 参与分析和组织，但关键命令、补丁与验证结果均来自本机实测。

我从 2026 年 9 月到 11 月在同一台机器上手动跟进了十余个版本（2.5.0 → 2.7.1 → 3.0.0 系列 RC → 3.0.0 正式版 → 3.0.1 → 3.1.0 → 3.1.1），形成了一套稳定的手动部署流程。3.0 之后又新增了"技能同时启用数量上限"的多层拦截，需要另外处理。本文把两部分的完整方案、命令和坑点一次整理清楚。

> 实测环境：银河麒麟桌面 V11（2603，OSTree）ARM64、飞腾 FTG340、KARE v10sp1 容器、TeleAgent 2.4.1–3.1.1 arm64 deb。
> 本文是个人实测记录，路径和偏移随版本变化，**不能保证在其他麒麟版本或后续 TeleAgent 版本上原样可用**。

> [!warning] 先读这一段
> 本文涉及绕过系统签名校验、重打包应用、修改 Go 二进制和应用数据库，属于**非官方修改**，可能影响软件稳定性、升级维护与厂商支持，安全软件也可能告警。所有操作前先备份，仅建议在理解每一步作用、愿意自行维护的个人机器上用于学习研究。生产环境请联系厂商获取带麒麟签名的安装包。

## 一、问题现象：官方安装通道为什么全部走不通

### 1.1 报错长什么样

TeleAgent 是以 KARE 容器应用形态安装的，正常通道是 `kare -i`：

```bash
sudo kare -i TeleAgent-3.1.1-arm64.deb -e v10sp1
```

实测从 2.4.1 起，该命令秒退，退出码 **16**，核心报错：

```text
dpkg: 处理归档 /tmp/kare-tmp.deb (--install)时出错：
软件包/tmp/kare-tmp.deb验证失败，拒绝安装！
The software package ... verification failed, refuse to install!
```

宿主机侧日志可以在 `/var/log/kare/kare-install.log` 和 `/var/log/kare/kare-dpkg-wrapper.log` 看到 dpkg.real 的拒绝记录。

### 1.2 根因：麒麟定制 dpkg 的 kysec 签名强制

这不是普通的依赖问题，而是编译进麒麟定制 dpkg 的**系统级强制钩子**。安装时 dpkg 会调用 kysec 内核安全模块做 deb 签名校验，链路涉及：

- `kysec_check_pkg_sign`（libkysec / libkysec_extend）
- `BJCA_dodebverify` / `dodebverify2`（北京 CA 验签库 libkylin_signtool）
- 白名单库 libkysecwhlist / libkylin_bwlist

**没有携带麒麟/BJCA 可信签名的第三方 deb 一律拒绝**。可以用 strings 在 dpkg.real 里直接看到这些符号：

```bash
strings /var/opt/kare-applications/v10sp1/merge/usr/bin/dpkg.real | grep -iE 'kysec|BJCA|signtool|refuse'
```

### 1.3 常规绕过为什么无效

遇到"验证失败"，直觉上会去找 dpkg 的跳过参数，实测全部无效：

| 尝试 | 结果 |
|---|---|
| 注释容器内 `dpkg.cfg` 的 `verify-kylinsign`、加 `force-bad-verify` | 仍拒绝。这些开关只管标准 debsig，kysec 校验独立强制 |
| `dpkg --force-bad-verify` / `--no-debsig` | 对 kysec 无效 |
| `apt-get -f install ./xxx.deb` | 报 "0 upgraded, 0 newly installed"，apt 同样不接受 |
| 关闭 kysec | 属于内核安全策略变更，需要维护模式，**不应为装一个软件去关** |

既然安装通道被系统级锁死，而应用文件本身只是普通的 Electron 目录，思路就变成：**不经过 dpkg，把 deb 解包后手动摆放到 KARE 容器的 overlay 文件系统里，再把 dpkg 元数据补齐**。

## 二、背景知识：KARE 容器与 overlay 布局

KARE 是麒麟的应用容器方案。TeleAgent 容器的真实文件落在：

```text
/var/opt/kare-applications/v10sp1/merge/        # 常驻 overlay 的 merge 视图（= /opt/kare-applications/... 绑定挂载）
├── opt/TeleAgent/                               # 应用全部 payload 都在这里
├── usr/share/applications/teleagent.desktop     # 容器内桌面入口（Exec 直跑真二进制）
├── usr/share/icons/hicolor/...                  # 图标
├── etc/alternatives/teleagent                   # alternatives 链路
├── usr/bin/teleagent                            # 软链
└── var/lib/dpkg/                                # 容器自己的 dpkg 数据库
    ├── info/teleagent.{list,md5sums,postinst,postrm}
    └── status
```

要点：

1. merge 是常驻 overlay，对它的写入实际落到 upper 层，**重启不丢**。
2. 宿主导出层（菜单图标、`/opt/kare/...` shim）与版本无关，升级时不用动。
3. 容器内有一套**独立的 dpkg 数据库**，手动摆文件后必须同步，否则以后查询版本、文件归属都会错乱。
4. 桌面入口实际用的是宿主导出的 `/opt/kare/usr/share/applications/teleagent.desktop`，其 Exec 为：

```text
/usr/bin/kare run teleagent /opt/TeleAgent/teleagent %U
```

**不要用 deb 包内自带的 desktop 文件覆盖这两份定制入口**，否则菜单启动方式会变。

## 三、获取安装包：应用内更新器是唯一可靠渠道

### 3.1 手动猜 URL 行不通

TeleAgent 的 electron-updater 配置（`resources/app-update.yml`）是 generic provider，地址为 `https://agent.teleai.com.cn/superCowork/sapi/downloads`。但标准更新清单在 Linux arm64 上全部不可用，实测：

- `latest-linux-arm64.yml`、`latest-linux.yml`、`latest-linux-arm64.yaml` → 全部 404（响应体 "file not found"）
- `latest.yml` → 只有一份陈旧的 Windows x64 2.3.1 清单
- asar 内只能 grep 到 sapi base URL，Linux arm64 的更新元数据走自定义接口，**无法靠拼 URL 直接 curl 到 deb**

### 3.2 可行分工：应用下载，人工安装

应用内的更新器本身能正常工作，只是下载完调 dpkg 安装时被 kysec 拒绝。所以固定分工是：

1. 在应用内点"下载更新"，**不要点重启安装**；
2. deb 会落到 `~/.cache/teleagent-updater/pending/`，同目录还有 `update-info.json`（含 sha512）；
3. 人工接管，核验后手动部署。

下载后先做完整性核验。`update-info.json` 里给的是 base64 编码的 sha512：

```bash
cd ~/.cache/teleagent-updater/pending
openssl dgst -sha512 -binary TeleAgent-3.1.1-arm64.deb | base64
# 与 update-info.json 中的 sha512 字段逐字符比对，一致再继续
cp TeleAgent-3.1.1-arm64.deb ~/下载/   # 留档
```

## 四、手动解包部署（完整流程）

下面以 3.1.0 → 3.1.1 为例。所有 root 操作建议写成一个脚本，用 `pkexec bash 脚本.sh` 执行——本机 `sudo -n` 不可用，pkexec 会弹图形认证窗（支持密码/指纹）。**绝不要裸跑无参数 pkexec，会在无 tty 环境挂死**。

### 4.1 解包 deb

deb 是 ar 归档，内含 `control.tar.xz`（维护脚本与元数据）和 `data.tar.xz`（实际文件）：

```bash
mkdir -p /tmp/ta-work && cd /tmp/ta-work
ar x ~/下载/TeleAgent-3.1.1-arm64.deb
mkdir root ctrl
tar xJf data.tar.xz    -C root
tar xJf control.tar.xz -C ctrl

# 从 postinst 的 heredoc 里提取官方 launcher（不同大版本可能变，必须用新包内的）
sed -n '14,134p' ctrl/postinst > launcher-new.sh
bash -n launcher-new.sh   # 语法自检
```

TeleAgent 的全部 payload 都在 `root/opt/TeleAgent/` 下。先核对 control 里的版本信息，部署脚本要用：

```bash
grep -E '^(Version|Installed-Size):' ctrl/control
```

### 4.2 确认应用已退出

```bash
pgrep -x teleagent    # 应无输出、退出状态为 1；从菜单/托盘正常退出，不要 pkill
```

### 4.3 备份当前版本（只保留最近一次）

把整个现网目录改名移走，同时备份 desktop、dpkg 元数据和当前 asar：

```bash
BASE=/var/opt/kare-applications/v10sp1/merge
BAK=$BASE/opt/teleagent-backup-$(date +%Y%m%d)
mkdir -p "$BAK/dpkg-info"

mv "$BASE/opt/TeleAgent" "$BAK/TeleAgent-3.1.0"
cp -a "$BASE/usr/share/applications/teleagent.desktop"  "$BAK/desktop-merge.teleagent.desktop"
cp -a /opt/kare/usr/share/applications/teleagent.desktop "$BAK/desktop-host.teleagent.desktop"
cp -a root/usr/share/applications/teleagent.desktop     "$BAK/desktop-payload-3.1.1.teleagent.desktop"
cp -a "$BASE/var/lib/dpkg/info/teleagent."* "$BAK/dpkg-info/"
cp -a "$BASE/var/lib/dpkg/status"           "$BAK/dpkg-status"
cp -a "$BAK/TeleAgent-3.1.0/resources/app.asar" "$BAK/app.asar.bak-limit299-3.1.0"
```

备份策略是**始终只留最新一份**，验证新版本稳定后删除上一份（本文案例中最终只保留 `teleagent-backup-20261120/`，约 1.6G）。

### 4.4 部署 payload 并复刻 postinst 动作

```bash
# 主程序（cp -a 会保留普通用户属主，必须 chown 回 root）
cp -a root/opt/TeleAgent "$BASE/opt/TeleAgent"
chown -R 0:0 "$BASE/opt/TeleAgent"

# 官方 launcher（libgbm 兼容包装，内含 Wayland 强制 x11、输入法变量等逻辑）
install -m 0755 -o root -g root launcher-new.sh \
  "$BASE/opt/TeleAgent/teleagent-launcher"

# libgbm 私有兼容软链
install -d -m 0755 "$BASE/opt/TeleAgent/libgbm-compat"
ln -sfn /usr/lib/aarch64-linux-gnu/libgbm.so.1 \
  "$BASE/opt/TeleAgent/libgbm-compat/libgbm.so.1"

# chrome-sandbox 必须是 root:root 4755
chown root:root "$BASE/opt/TeleAgent/chrome-sandbox"
chmod 4755     "$BASE/opt/TeleAgent/chrome-sandbox"
```

图标全套尺寸复制到 merge 与宿主导出位：

```bash
for sz in 16 24 32 48 64 96 128 256 512; do
  install -D -m 644 "root/usr/share/icons/hicolor/${sz}x${sz}/apps/teleagent.png" \
    "$BASE/usr/share/icons/hicolor/${sz}x${sz}/apps/teleagent.png"
done
install -D -m 644 root/usr/share/icons/hicolor/256x256/apps/teleagent.png \
  /opt/kare/usr/share/icons/hicolor/256x256/apps/teleagent.png
install -D -m 644 root/usr/share/doc/teleagent/changelog.gz \
  "$BASE/usr/share/doc/teleagent/changelog.gz"
chown -R root:root "$BASE/usr/share/icons" "$BASE/usr/share/doc"
```

### 4.5 同步容器 dpkg 元数据

这一步让容器内的 dpkg 认为 teleagent 是"正常安装"的新版本：

```bash
DEB="/home/你的用户名/下载/TeleAgent-3.1.1-arm64.deb"
# 必须替换为真实用户目录：root 脚本中的 ~ 会展开为 /root

# 文件清单：data.tar 成员名 ./usr/... 转成绝对路径形式
ar p "$DEB" data.tar.xz | tar tJ | sed 's|^\./|/|; s|^\.$|/|' \
  > "$BASE/var/lib/dpkg/info/teleagent.list"

# md5sums 与维护脚本直接用 control 归档里的
cp -a ctrl/md5sums  "$BASE/var/lib/dpkg/info/teleagent.md5sums"
cp -a ctrl/postinst "$BASE/var/lib/dpkg/info/teleagent.postinst"
cp -a ctrl/postrm   "$BASE/var/lib/dpkg/info/teleagent.postrm"
chmod 0755 "$BASE/var/lib/dpkg/info/teleagent.post"*
chown root:root "$BASE/var/lib/dpkg/info/teleagent".*

# status 中只改 teleagent 这一段的两个字段
sed -i '/^Package: teleagent$/,/^$/ {
    s|^Version: .*|Version: 3.1.1-1|
    s|^Installed-Size: .*|Installed-Size: 1089580|
}' "$BASE/var/lib/dpkg/status"
```

### 4.6 alternatives 链路自检与缓存清理

```bash
# 链路应指向容器内 launcher
readlink "$BASE/etc/alternatives/teleagent"
# 期望：/opt/TeleAgent/teleagent-launcher
[ -L "$BASE/usr/bin/teleagent" ] || echo "ABORT: 软链缺失"

# 以下缓存属于桌面用户，应在普通用户会话执行，不要在 root 脚本中直接使用 ~
# Electron 渲染层旧代码缓存必须清，否则可能跑旧 JS
rm -rf ~/.local/share/TeleAgent/'Code Cache' ~/.local/share/TeleAgent/GPUCache
```

### 4.7 首次启动验证

用 setsid 脱离当前进程组启动（Agent/终端场景下必须，否则终端退出会带走 GUI）：

```bash
setsid /usr/bin/kare run teleagent /opt/TeleAgent/teleagent \
  >/tmp/ta-launch.log 2>&1 < /dev/null &
```

> [!warning] 启动日志含敏感环境变量
> `kare run` 会把宿主完整环境（含 API key 一类变量）转储到 stdout。重定向的日志文件用完立即删除，不要留档、不要提交到仓库。

验证命令：

```bash
pgrep -x teleagent                       # 进程数，正常 10 个左右
curl -s http://127.0.0.1:4397/ready      # 期望 {"data":{"status":"ready"}}
cat ~/.local/share/TeleAgent/updater.json  # lastVersion 应自动翻到新版本
```

## 五、技能启用数量上限：三层拦截的来龙去脉

TeleAgent 的"技能（skills）"类似自定义工具/插件，每个技能带一个 SKILL.md。早期版本（2.x）同时启用上限是 **50**，3.0 RC 起提高到 **100**，并且从 3.0.1 开始拦截从单层变成了**三层**。只改前端数字已经不够。

### 5.1 三层结构

| 层 | 位置 | 职责 | 处理方式 |
|---|---|---|---|
| Electron 渲染层 | `resources/app.asar` 内主 bundle 的常量 `MAX_ACTIVE_SKILLS` | UI 开关拦截、toast 提示 | 重打包 asar，100 → 299 |
| ais 服务 | `~/.local/share/TeleAgent/runtimes/ais/bin/ais`（Go 二进制，gRPC over ais.sock） | 技能状态机，超限构造 `SKILL_ACTIVE_LIMIT` 业务错误并静默钳制 | 二进制补丁 + SQLite 触发器 |
| super-agent | 127.0.0.1:4397 的 Go 服务 | 运行时配置 `/global/config`，真正决定工具可用性 | 不直接拦，无需修改 |

### 5.2 第一层：asar 重打包

#### 为什么不能直接 sed

`MAX_ACTIVE_SKILLS:100` 改成 `:299` 虽然是**等长替换**（都是三位数字，文件大小不变），但 asar 头里每个文件带 per-file integrity 字段，改了内容就必须重算，否则 Electron 加载时校验失败。

两个基础事实（实测确认，网上说法有坑）：

1. asar 头部是 pickle 结构，前 16 字节四个小端 uint32：`(4, aligned_json+8, aligned_json+4, json_len)`，JSON 头后零填充到 4 字节对齐，之后才是文件数据；
2. integrity 算法：顶层 `hash` 是**整个文件的 SHA256**（不是块哈希拼接后再哈希！），`blocks` 是每 4MB 一块各自的 SHA256，**空文件 blocks 数也是 1**。

#### 定位补丁点

asar 里 `MAX_ACTIVE_SKILLS:100` 带冒号的定义全局唯一（另有两处是不带冒号的属性引用），主 bundle 文件名每版都变（如 3.1.0 是 `main-CdWdvwas.js`，3.1.1 是 `main-cgNTJRhd.js`），按内容定位而不是按文件名：

```bash
npx @electron/asar extract app.asar app-extracted
grep -abo 'MAX_ACTIVE_SKILLS:100' app-extracted/dist/assets/main-*.js
```

#### 两种重打包路线

- **标准工具路线**：改完 bundle 后用官方工具重打包；先通过 `npx @electron/asar --help` 确认当前工具版本是否支持 integrity 相关选项，并按工具说明启用：

```bash
npx @electron/asar pack app-extracted app.asar.new --integrity
```

- **严格保字节路线（本文采用）**：离线环境 npm 不稳定，自写 Python 解析 asar 头、只替换目标 bundle 的那 3 个字节、按 header 树顺序重建全部 offset，非目标条目保留原始字节与原 integrity，目标条目重算 hash/blocks。完成后必须做全量自校验：所有非目标条目逐字节一致、offset 连续无空洞、全部 integrity 有效、补丁计数 `299×1 / 100×0`。

部署后核验：

```bash
ASAR=$BASE/opt/TeleAgent/resources/app.asar
grep -a -c 'MAX_ACTIVE_SKILLS:299' "$ASAR"   # 期望 1
grep -a -c 'MAX_ACTIVE_SKILLS:100' "$ASAR"   # 期望 0
```

### 5.3 第二层：ais Go 二进制补丁

#### 拦截逻辑

ais 的 `mapToolFindings` 函数里，当已启用计数 ≥ 上限（结构体偏移 0xb0 处的 cap）时：

1. 构造 business_error `SKILL_ACTIVE_LIMIT`，写入 `skill_operations.state=failed`，前端弹硬窗；
2. `SetSkillEnabled` 同步路径还有一处**静默钳制**：把数据库里的 `desired_enabled` 钉回 0，表现为开关拨上去又弹回来。

#### 补丁思路（ARM64）

在 3.0.1 上定位到两处指令（ELF 虚拟地址 vaddr = 文件偏移 fileoff + 0x10000）：

| 补丁 | 原指令 | 改为 | 作用 |
|---|---|---|---|
| 补丁 A | `b.le`（小等于则跳超限分支，小端码 `5400036d`） | `B` 同目标无条件跳转（`1400001b`） | 跳过超限分支，弹窗不再构造 |
| 补丁 B | `tbz`（位测试，`36000b0b`） | NOP（`d503201f`，ARM64 标准空指令） | 抹掉残留判断 |

两处共改 7 字节，文件大小不变。补丁后用 objdump 反汇编验证跳转目标与原条件分支完全一致。

> [!warning] 偏移量每版都可能失效
> 3.0.1 → 3.1.0 时 ais 是全新构建，旧偏移全部失效，整个函数平移了 0x1b10。**不要背偏移，要背方法**：用旧版的特征指令序列（分支指令用通配符）对新二进制做全文件扫描，靠上下文唯一命中定位，再核对窗口内非分支指令的结构同型性。每次都要重新反汇编验证。
>
> 也有省事的情况：3.1.1 的 ais 与 3.1.0 原版二进制**逐字节相同**（sha256 一致，只是 tar.gz 重压缩），现成补丁直接复制即可，零逆向工作量。判断方法就是解包后先比哈希。

#### 两阶段部署：ensureRuntimes 机制

ais 不是静态文件，Electron 启动时的 `ensureRuntimes` 会管理它：

- 只比对 `runtimes/.version.json` 里的 `version / aisFile / aisChecksum` 三个字段，决定是否从 asar 内的 `teleagent-ais-linux-arm64.tar.gz` 重新解压；
- **不实时校验磁盘上 ais 的哈希**（实时完整性检查只覆盖 superAgentCode）。

这决定了替换补丁必须走两阶段：

1. **首启**：让应用把原版 ais 解压出来（日志出现 `Need to extract ... ais → Finished extracting`），此时磁盘是原版；
2. 完全退出应用，覆盖二进制（用户目录操作，不需要 root），`.version.json` 一字节不动：

```bash
cp -a ~/.local/share/TeleAgent/patch-work/ais-patched \
      ~/.local/share/TeleAgent/runtimes/ais/bin/ais
```

3. **第二次启动**：日志出现 `[Runtime] All versions match, skipping extraction.` 即表示补丁持久化成功，以后重启不会被覆盖。

补丁工作目录放在 `~/.local/share/TeleAgent/patch-work/`（应用升级不清这里），原版和补丁版各留一份，原版就是回滚点。

### 5.4 第三层：SQLite 触发器（对付静默钳制）

灭掉弹窗后开关仍回弹，说明 Go 内存里的钳制逻辑还在把 `desired_enabled` 写回 0。与其继续硬刚混淆严重的 Go 二进制，不如在数据层用触发器纠正——触发器存在数据库里，**天然抗二进制重解压和重启**。

数据库位置：

```text
~/.local/share/TeleAgent/users/v1_public_<你的用户ID>/ais/ais.db
```

关键两张表：

- `skill_operations`：每次启用/停用操作的流水，字段含 `kind`(enable/disable)、`resource_name`、`target_enabled`(0/1)、`state`(succeeded/failed)；
- `skill_installations`：技能安装态与 `desired_enabled`。

在 `skill_operations` 上建 AFTER UPDATE 触发器（操作到达终态 succeeded 时，按用户的真实意图回写）：

```sql
CREATE TRIGGER trg_skill_op_sync_upd
AFTER UPDATE ON skill_operations FOR EACH ROW
WHEN NEW.state='succeeded'
 AND NEW.kind IN ('enable','disable')
 AND NEW.target_enabled IS NOT NULL
BEGIN
  UPDATE skill_installations SET desired_enabled = NEW.target_enabled
  WHERE tenant_id = NEW.tenant_id
    AND user_id   = NEW.user_id
    AND name      = NEW.resource_name
    AND state     = 'active';
END;
```

再建一个结构完全相同的 `AFTER INSERT` 触发器 `trg_skill_op_sync_ins` 做兜底。

> [!important] 为什么必须挂 skill_operations 而不是 skill_installations
> installation 行的写入早于 operation 置 succeeded，挂 installation 表有时序竞态，会读到旧 operation，甚至误伤用户主动的 disable 操作。挂 operation 终态才能保证拿到的是这次操作的真实意图。

这个方案还有一个附带好处：**应用升级不碰用户数据目录，触发器一次建立、跨所有版本存活**，实测从 3.0.1 到 3.1.1 无需重建。

### 5.5 已知残留瑕疵

超过 100 个技能后，每个技能**第一次**点启用可能仍会回弹（ais 只写库就返回，没有向 super-agent 下发 `/global/config` PATCH），但触发器已把数据库纠正为启用态，**再点一次**即正常点亮并稳定；disable 方向一次到位。这是 Go 侧短路路径的行为，补丁只消灭了弹窗和钳制，没有修这个时序瑕疵，实际使用中可以接受。

## 六、完整验证清单

部署和补丁全部完成后，按这张表逐项验收（均为只读命令）。执行前先把 `BASE`、`app.asar` 和 `ais.db` 展开为本机真实绝对路径；不要直接照抄带 `$BASE` 的表格命令：

| 验证项 | 命令 | 期望结果 |
|---|---|---|
| 服务就绪 | `curl -s http://127.0.0.1:4397/ready` | `{"data":{"status":"ready"}}` |
| dpkg 版本 | `awk '/^Package: teleagent$/,/^$/' $BASE/var/lib/dpkg/status` | Version 为新版本 |
| asar 补丁 | `grep -a -c 'MAX_ACTIVE_SKILLS:299' app.asar` / `:100` | 1 / 0 |
| ais 持久化 | 二启后查主日志 | `All versions match, skipping extraction` |
| ais 哈希 | `sha256sum runtimes/ais/bin/ais` | 与补丁版一致，重启不变 |
| 触发器 | `sqlite3 ais.db "SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'trg_skill%';"` | 两个触发器都在 |
| 启用技能数 | `SELECT COUNT(*) FROM skill_installations WHERE desired_enabled=1 AND state='active';` | 可超过 100（本机 104） |
| 超限报错 | 主日志 grep `SKILL_ACTIVE_LIMIT` | 补丁后零新增 |
| 更新器状态 | `cat ~/.local/share/TeleAgent/updater.json` | lastVersion 为新版本 |
| socket | `ls ~/.local/share/TeleAgent/ais/*.sock` | ais.sock、im.sock 存在 |

## 七、回滚方案

三层修改各有独立回滚点，按影响面从小到大：

1. **ais 回滚**：用 patch-work 里的原版二进制覆盖 `runtimes/ais/bin/ais`，`.version.json` 不动，重启即可；
2. **asar 回滚**：备份目录里有升级前的 asar 原件（`app.asar.bak-limit299-*`），root 权限覆盖回 resources 目录；
3. **整版本回滚**：备份目录里有上一版完整 `TeleAgent/` 目录，把当前目录改名、备份目录移回，再还原 dpkg 元数据与 status 文件即可，用户数据（`~/.local/share/TeleAgent`、`~/.config/TeleAgent`）全程不受影响；
4. **触发器回滚**：`DROP TRIGGER trg_skill_op_sync_upd;` / `..._ins;`（未遇到需要回滚的场景）。

## 八、坑点汇总

1. **kysec 是系统级强制，不要在 dpkg 参数上浪费时间**，也不要为装软件关 kysec；
2. **desktop 文件别用包内的覆盖**，菜单入口必须保持 `kare run` 形式；
3. `cp -a` 进 overlay 后记得 `chown -R 0:0`，chrome-sandbox 必须 4755；
4. 改渲染层 JS 后清 `Code Cache` 和 `GPUCache`，否则 Electron 跑旧缓存；
5. asar integrity 的顶层 hash 是整文件 SHA256，空文件 blocks=1，头部 pickle 四元组别写错（写错会表现为全部文件哈希失败的假象）；
6. ais 补丁偏移随构建变化，**用特征序列扫描定位，不要复用旧偏移**；先比新旧二进制哈希，相同就直接省掉逆向；
7. 替换 ais 必须两阶段，首启解压、退出替换、二启确认 skipping extraction；
8. DB 触发器挂 `skill_operations` 终态，不能挂 `skill_installations`；
9. `kare run` 日志含环境密钥，重定向文件用完即删；
10. 备份只留最近一份，验证稳定后 pkexec 删除旧备份释放空间（每份 1.5G 左右）；
11. 升级 deb 在 `~/.cache/teleagent-updater/pending/`，应用会自行管理缓存，不必手动干预；
12. Agent/脚本里启动 GUI 用 `setsid ... &` 脱离进程组，提权用 `pkexec bash 脚本.sh`，不要裸 pkexec。

## 九、推荐用法：把文章交给 AI 执行

这套流程命令多、版本差异点碎，手工逐条执行容易漏步。更稳的方式是把本文完整交给运行在麒麟机器上的终端智能体，并附上类似下面的约束：

```text
阅读这篇 TeleAgent 手动升级文章，在本机完成新版本部署。
先只做查询：确认 TeleAgent 已退出、核对 deb 的 sha512、解包并比对版本信息、
检查备份目录与磁盘空间。不要先改任何系统文件。
所有 root 操作写成一个脚本，用 pkexec 执行，执行前向我说明改动范围和回滚方法。
ais 补丁先比对新旧二进制哈希，相同则复用，不同再做特征扫描定位。
每一步完成后按文章的验证清单核验，结果如实报告，失败就停下不要继续。
```

AI 可以把路径、版本号、偏移量按本机实际值替换，把查询、备份、部署、两阶段补丁和验证串成闭环；但 pkexec 提权、删除备份这类不可逆动作，仍应保留人工确认。

## 十、总结

麒麟 V11 上 TeleAgent 升级问题的本质，是**系统签名策略与第三方未签名 deb 之间的硬冲突**。既然 dpkg 通道被 kysec 锁死，就绕开它：解包 deb → 手动摆放 payload 到 KARE overlay → 复刻 postinst 动作 → 补齐容器 dpkg 元数据，应用本身的运行不受任何影响。

技能上限则是另一个维度的问题：3.0.1 之后厂商把拦截拆成了前端常量、Go 服务弹窗/钳制、数据库状态三层，需要 asar 重打包、二进制补丁、SQLite 触发器三件套分别应对，而 ensureRuntimes 的三字段比对机制又决定了 ais 替换必须走两阶段。

整套方案从 2.5.0 到 3.1.1 历经十余个版本验证，每次升级的增量工作通常只有：核对差异、重打 asar、确认 ais 是否需要重新定位补丁。理解机制之后，这不再是"黑魔法"，而是一套可重复、可回滚、可交给 AI 执行的常规运维流程。

---

> 本文原文托管于 Gitee：
> https://gitee.com/digtip/notes/blob/main/blog/ai/TeleAgent%20%E9%BA%92%E9%BA%9F%20V11%20%E6%89%8B%E5%8A%A8%E5%8D%87%E7%BA%A7%E4%B8%8E%E6%8A%80%E8%83%BD%E6%89%A9%E5%AE%B9%E5%AE%9E%E6%88%98.md
> GitHub 为只读镜像备份。
