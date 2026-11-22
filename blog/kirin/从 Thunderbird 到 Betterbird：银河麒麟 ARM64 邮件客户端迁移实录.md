---
title: 从 Thunderbird 到 Betterbird：银河麒麟 ARM64 邮件客户端迁移实录
date: 2026-11-20
tags: [Betterbird, Thunderbird, 银河麒麟, ARM64, 邮件客户端, TemplateWing]
description: 从 Thunderbird 在银河麒麟 ARM64 上的安装、维护和搜索困境出发，完整记录 Betterbird 140 ESR 的安装、中文语言包、独立 Profile、邮件与密码迁移、搜索索引重建、TemplateWing 模板及字体签名配置。
status: published
original: https://gitee.com/digtip/notes/blob/main/blog/kirin/%E4%BB%8E%20Thunderbird%20%E5%88%B0%20Betterbird%EF%BC%9A%E9%93%B6%E6%B2%B3%E9%BA%92%E9%BA%9F%20ARM64%20%E9%82%AE%E4%BB%B6%E5%AE%A2%E6%88%B7%E7%AB%AF%E8%BF%81%E7%A7%BB%E5%AE%9E%E5%BD%95.md
---

# 从 Thunderbird 到 Betterbird：银河麒麟 ARM64 邮件客户端迁移实录

我在银河麒麟 ARM64 笔记本上使用 Thunderbird 管理邮件。账号、通讯录、过滤器和本地邮件已经积累多年，其中仅一个 POP3 账号的本地邮件就有约 15GB。这样的客户端早已不只是一个收发邮件的软件，而是日常工作资料库。

问题在于，Thunderbird 在这套环境里越来越难以维持一个省心状态：ARM64 安装与升级不如 x86 平台顺畅，系统仓库和 Flatpak 路线受版本条件限制；搜索等长期使用中的问题影响效率；要调整显示、回复模板和中文姓名匹配，又需要额外扩展和配置。更麻烦的是，一旦更换客户端，最大的风险不是安装失败，而是邮件、密码、通讯录和索引能否完整接过来。

Betterbird 是 Thunderbird 的增强分支，保留相近的使用习惯，并修复了一些上游问题。它让我有机会继续沿用原有工作流，但 ARM64 版本并不是下载后就能直接使用：官方包只有英文界面，中文语言包存在签名注册问题，默认 Profile 还可能与 Thunderbird 共用。

这篇文章记录完整迁移过程。重点不是“换一个客户端”，而是如何在不破坏 Thunderbird 原始数据的前提下，让 Betterbird 真正接管日常工作。

> 实测时间：2026 年 8 月。环境为银河麒麟 V11 ARM64、飞腾平台，Betterbird 版本为 **140.13.0esr-bb25 aarch64**。
> 原始排障和配置过程由 Qwen Code 协助完成。本文是个人实测，不代表后续版本仍需相同操作。

## 一、Thunderbird 的真实困境

### 1. 不是完全不能用，而是维护成本越来越高

在 x86 Linux 上，邮件客户端通常可以通过系统仓库、Flatpak 或官方包获得。在银河麒麟 ARM64 上，可用路线明显受限。实测系统源中的 Flatpak 版本较旧，我没有继续围绕 Flatpak 解决依赖，而是选择 Betterbird 官方 tarball。

这意味着安装、升级和桌面入口更多需要自己维护，不能完全依赖系统软件中心。

### 2. 搜索问题直接影响历史邮件价值

邮件积累越多，搜索就越重要。客户端里躺着 15GB 邮件，却不能稳定按中文姓名找到发件人，历史资料的价值就会大打折扣。

迁移后我还发现，直接复制 Thunderbird 的全局搜索数据库并不能正确衔接 Betterbird 的地址簿关联，必须重建索引。这说明“文件都复制了”不等于“功能迁移完成”。

### 3. 数据多，反而让换客户端更谨慎

Thunderbird Profile 中不只有邮件，还包括：

- 账号和服务器配置；
- 已保存的密码与证书；
- 通讯录和联系人收集记录；
- POP3 本地邮件与 IMAP 缓存；
- 邮件过滤器和虚拟文件夹；
- 签名、字体、回复位置等个人偏好。

直接让新客户端接管旧 Profile，看似省事，一旦配置写入或数据库升级出现异常，回退成本很高。因此我选择**独立 Profile 迁移，Thunderbird 原目录保持不动**。

### 4. 日常办公细节也需要迁移

我需要的不仅是“能收信”，还包括：

- 中文界面；
- 中文姓名为核心的通讯录和搜索；
- 回复时自动生成规范称谓；
- 回复、转发保留签名；
- 统一的中文字体和字号；
- 回复内容位于引用上方；
- 邮件外链交给浏览器打开。

这些细节决定了 Betterbird 能不能真正替代 Thunderbird，而不只是临时试用。

## 二、安装 Betterbird：选择官方 tarball

实测版本：

- Betterbird：`140.13.0esr-bb25`；
- 架构：ARM64 / aarch64；
- 安装形式：官方 tarball，不是 deb，也不是 Flatpak；
- 构建要求：glibc 2.31，本机银河麒麟 V11 兼容。

先确认自己的系统架构和 glibc：

```bash
uname -m
ldd --version | head -n 1
```

下面命令中的版本号和下载路径只对应本次实测。新版本应从 Betterbird 官方下载页获取，不要长期照抄旧链接。

```bash
BBVER="140.13.0esr-bb25"
curl -L -o /tmp/betterbird.tar.xz \
  "https://www.betterbird.eu/downloads/LinuxArchive/betterbird-140-linux-aarch64-built-with-glibc-2_31/betterbird-${BBVER}.en-US.linux-aarch64.tar.xz"

mkdir -p "$HOME/Applications/Betterbird"
tar -xf /tmp/betterbird.tar.xz \
  -C "$HOME/Applications/Betterbird" --strip-components=1
```

程序放在用户目录，不需要为了运行客户端修改系统目录。

## 三、先建立独立 Profile，再迁移数据

Betterbird 与 Thunderbird 同源，默认配置可能指向 Thunderbird 的 Profile。为了避免互相写入，从一开始就要明确指定独立目录：

```bash
mkdir -p "$HOME/.betterbird-profile"

"$HOME/Applications/Betterbird/betterbird" \
  -profile "$HOME/.betterbird-profile" -no-remote &
```

本次规划如下：

| 路径 | 用途 |
|---|---|
| `~/Applications/Betterbird/` | 程序目录 |
| `~/.betterbird-profile/` | Betterbird 独立数据目录 |
| `~/.thunderbird/` | Thunderbird 原始数据，保持不动 |
| `~/Desktop/Betterbird.desktop` | 桌面启动器 |
| `~/.local/share/applications/betterbird.desktop` | 应用菜单入口 |

### 桌面启动器

把下面文件中的 `你的用户名` 替换为真实用户名，也可以在终端中用 `$HOME` 生成文件；`.desktop` 的 `Exec` 不建议直接依赖 shell 变量展开。

`~/.local/share/applications/betterbird.desktop`：

```ini
[Desktop Entry]
Type=Application
Name=Betterbird
Exec=/home/你的用户名/Applications/Betterbird/betterbird -profile /home/你的用户名/.betterbird-profile -no-remote %u
Icon=/home/你的用户名/Applications/Betterbird/chrome/icons/default/default128.png
Terminal=false
Categories=Network;Email;
MimeType=x-scheme-handler/mailto;
StartupWMClass=betterbird
```

桌面入口可以复制同一份配置。若桌面图标首次不能启动，检查文件执行权限和桌面环境是否要求“允许启动”。

## 四、中文语言包：本次最容易踩的坑

Betterbird 官方 ARM64 包是英文界面，需要单独安装中文语言包。问题不在于找不到 XPI，而在于**未签名语言包通过界面安装时可能被静默拒绝**。

### 1. 下载语言包

```bash
curl -L -o /tmp/langpack-zh-CN.xpi \
  "https://www.betterbird.eu/downloads/get.php?os=all&lang=zh-CN&version=release"
```

本次实测要点：

- 正确扩展 ID 是 `langpack-zh-CN@betterbird.eu`；
- 不要使用 Thunderbird 的语言包替代；
- 实测 langpack 140.10 可配 Betterbird 140.13，manifest 的兼容范围为 `140.*`；
- 其他版本仍应检查 manifest，不能仅凭版本号接近判断兼容。

### 2. 放到程序根目录的 extensions

不是 `distribution/extensions/`，也不是 Profile 下的 `extensions/`：

```bash
mkdir -p "$HOME/Applications/Betterbird/extensions"
cp /tmp/langpack-zh-CN.xpi \
  "$HOME/Applications/Betterbird/extensions/langpack-zh-CN@betterbird.eu.xpi"
```

不要同时在应用目录和 Profile 目录放同一份语言包。实测重复放置可能造成两份都被禁用。

### 3. 配置语言包相关偏好

在 Betterbird 完全退出后，编辑 `~/.betterbird-profile/user.js`：

```javascript
user_pref("intl.multilingual.enabled", true);
user_pref("intl.multilingual.downloadEnabled", false);
user_pref("extensions.langpacks.signatures.required", false);
```

> [!warning] 签名设置的安全边界
> `extensions.langpacks.signatures.required=false` 会降低语言包签名校验要求。这里只用于来源明确的 Betterbird 官方语言包，不代表应安装来历不明的 XPI。若后续官方包已签名且能正常注册，应删除这项绕过设置，恢复默认安全策略。

### 4. 重新扫描并启用

完全退出 Betterbird 后，删除旧扩展注册信息，让它重新扫描：

```bash
rm -f "$HOME/.betterbird-profile/extensions.json"
rm -f "$HOME/.betterbird-profile/extensions.ini"

"$HOME/Applications/Betterbird/betterbird" \
  -profile "$HOME/.betterbird-profile" -no-remote &
```

如果中文仍未出现，检查 `extensions.json` 中语言包是否被标记为 `userDisabled=true`。关闭 Betterbird 后再修改注册状态，不要在程序运行时直接编辑。

随后在“设置 → 常规 → 语言”中选择 Chinese (Simplified)，重启客户端。

我不采用 `-UILocale zh-CN` 强制启动参数，因为那只是启动时指定语言，没有解决语言包注册本身的问题。

## 五、从 Thunderbird 迁移哪些数据

先在 Thunderbird 的“关于 → 配置文件”或配置目录中确认自己的实际 Profile 路径。下面的 `你的Thunderbird配置目录` 必须替换，不要照抄原笔记中的随机目录名。

| 数据 | 文件或目录 |
|---|---|
| 账号配置 | `prefs.js` 中的 `mail.*`、`mailnews.*` |
| 密码与证书 | `key4.db`、`logins.json`、`cert9.db`、`pkcs11.txt` |
| 通讯录 | `abook.sqlite`、`blist.sqlite`、`history.sqlite` |
| POP3 本地邮件 | `Mail/` 下对应账号目录 |
| IMAP 缓存 | `ImapMail/` |
| 本地文件夹 | `Mail/Local Folders/` |
| 过滤器 | 各账号目录下的 `msgFilterRules.dat` |
| 虚拟文件夹 | `virtualFolders.dat` |

> [!important] 迁移前先备份
> 完全退出 Thunderbird 和 Betterbird，再备份整个 Thunderbird Profile 和新建的 Betterbird Profile。下面的复制命令会覆盖目标 Profile 中的同名文件，只适合明确执行迁移的阶段，不是日常同步命令。

```bash
TB="$HOME/.thunderbird/你的Thunderbird配置目录"
BB="$HOME/.betterbird-profile"

# 检查两个目录确实不同，并且都存在
printf 'Thunderbird: %s\nBetterbird: %s\n' "$TB" "$BB"
test -d "$TB" && test -d "$BB"
```

### 1. 合并邮件相关偏好

Betterbird 启动后已经写入自己的默认值，因此不能简单把 Thunderbird 的 mail 配置追加到末尾。先移除目标中的同类配置，再合并：

```bash
grep -E '^user_pref\("(mail\.|mailnews\.)' "$TB/prefs.js" > /tmp/tb-mail.txt
grep -vE '^user_pref\("(mail\.|mailnews\.)' "$BB/prefs.js" > /tmp/bb-nomail.txt
cat /tmp/bb-nomail.txt /tmp/tb-mail.txt > "$BB/prefs.js"
```

操作前单独备份 `$BB/prefs.js`。合并只针对邮件配置，不要把整个旧 Profile 不加区分地覆盖过来。

### 2. 密码、证书和通讯录

先确认源文件存在；不存在的文件说明本机没有对应数据，不需要凭空创建：

```bash
cp "$TB"/{key4.db,logins.json,cert9.db,pkcs11.txt} "$BB/"
cp "$TB"/{abook.sqlite,blist.sqlite,history.sqlite} "$BB/"
```

这些文件包含敏感信息，不应上传到公开仓库或附在公开文章中。

### 3. 邮件与虚拟文件夹

```bash
cp -a "$TB/ImapMail" "$BB/"
cp -a "$TB/Mail" "$BB/"
cp "$TB/virtualFolders.dat" "$BB/"
```

15GB 数据复制需要预留足够磁盘空间。复制完成后检查文件数量和目录大小，再启动 Betterbird 验证各账号、邮件文件夹和过滤器。

### 4. 不直接迁移的内容

- `extensions/`：Thunderbird 扩展不一定兼容 Betterbird；
- `chrome/`：旧自定义样式可能干扰新界面；
- `calendar-data/`：如有日历需求，应单独核对和迁移；
- 全局搜索数据库：迁移后需要重建，下一节说明。

## 六、飞腾平台的显示与回复偏好

原 Thunderbird 配置中包含针对本机图形环境的设置。对本机而言，这些配置与稳定性有关，但不能推广为所有 ARM64 电脑都必须禁用硬件加速。

`~/.betterbird-profile/user.js`：

```javascript
// 本机飞腾环境的兼容性设置；其他电脑先测试默认值
user_pref("layers.acceleration.disabled", true);
user_pref("gfx.webrender.force-disabled", true);
user_pref("gfx.direct2d.disabled", true);
user_pref("gfx.canvas.accelerated", false);
user_pref("gfx.content.azure.backends", "cairo");
user_pref("gfx.use-gl", false);

// 外链交给浏览器
user_pref("network.protocol-handler.warn-external.http", false);
user_pref("network.protocol-handler.warn-external.https", false);

// 回复内容在引用上方，签名位于回复内容之后
user_pref("mailnews.reply_on_top", 1);
user_pref("mail.identity.default.sig_bottom", false);

// 中文语言包
user_pref("intl.multilingual.enabled", true);
user_pref("intl.multilingual.downloadEnabled", false);
user_pref("extensions.langpacks.signatures.required", false);
```

原笔记中还清空了 `ui.key.openAddressBook` 以规避快捷键冲突。若自己遇到相同冲突，再添加：

```javascript
user_pref("ui.key.openAddressBook", "");
```

不要直接复制整份旧 `user.js` 到新机器，因为它可能同时包含路径、账号和其他环境特定设置。按项目核对更稳妥。

## 七、迁移后必须重建搜索索引

复制过来的 `global-messages-db.sqlite` 不一定能与 Betterbird 地址簿正确关联。本次实测表现为：邮件存在，但按中文姓名搜索发件人找不到。

完全退出 Betterbird 后，删除索引文件并让它自动重建：

```bash
rm -f "$HOME/.betterbird-profile"/global-messages-db.sqlite*
```

重新启动后，Betterbird 会重建全局数据库。约 15GB 邮件在本机用了数分钟，实际时间取决于磁盘和邮件量。状态栏可以观察进度。

删除的是可重建索引，不是邮件本身；但仍应确保前面的 Profile 备份有效，并确认路径指向 Betterbird，而不是 Thunderbird。

## 八、必要扩展：TemplateWing 回复模板

本次真正为工作流补充的扩展是 **TemplateWing**。它用于快速插入回复模板，减少每次手写称谓和格式的重复操作。

### 1. 基本配置

实测版本为 TemplateWing 2.8.0，支持 Thunderbird 128+。安装前应重新核对当前 Betterbird 版本和扩展兼容性。

通过“附加组件管理器 → 齿轮 → 从文件安装”加载 XPI，配置模板：

```text
{RECIPIENT_NAME}你好：


&nbsp;&nbsp;&nbsp;&nbsp;
```

- 插入模式选择 **Cursor**，即光标处插入；
- 快捷键设置为 `Ctrl+Shift+1`；
- HTML 撰写模式下连续普通空格会折叠，首行缩进使用 `&nbsp;`；
- 自动插入主要对新建邮件生效，回复和转发中需要手动按快捷键。

### 2. 为什么我还修改了扩展

原版 `{RECIPIENT_NAME}` 主要从撰写窗口的收件人字段解析名字，不一定查询通讯录。某些系统邮件的 From 头把完整邮箱当作显示名，模板最终就会出现“邮箱地址你好”，而不是联系人的真实姓名。

本次基于 2.8.0 做了个人补丁：

1. 在 `manifest.json` 添加 `addressBooks` 权限；
2. 先快速搜索，再遍历通讯录，按邮箱精确匹配联系人；
3. 优先采用真实的 DisplayName，其次使用姓名组合；
4. 当解析结果为完整邮箱或邮箱前缀时，再查询通讯录替换。

这里有一个版本细节：Betterbird 140 中应使用 `addressBooks` 权限，直接写 `contacts` 会导致权限处理错误。

> [!warning] 非官方扩展补丁
> 上述修改是个人适配，不是 TemplateWing 官方版本，也不提供公开下载。修改扩展会增加升级维护成本，并涉及读取通讯录的权限。一般用户先使用官方扩展；确有相同需求时，应审查源码、保留原版 XPI，并在升级后重新验证。

## 九、签名和中文字体

### 回复、转发保留签名

```javascript
user_pref("mail.identity.default.sig_on_fwd", true);
user_pref("mail.identity.default.sig_on_reply", true);
user_pref("mail.identity.id1.htmlSigFormat", true);
```

`id1` 是账号身份编号，多账号环境可能不同。更稳妥的方式是在账号设置中确认签名选项，再把 `user.js` 当作本机配置记录，而不是通用修改清单。

签名使用 HTML 时，用 `<br>` 换行，并通过内联样式指定字体。字体只影响本机撰写和显示；收件人是否安装相同字体，会影响对方最终看到的效果。

### 字体配置示例

我使用本机已安装的“方正仿宋_GBK”。你没有该字体时，应替换为已安装且有权使用的字体：

```javascript
user_pref("font.name.sans-serif.x-western", "方正仿宋_GBK");
user_pref("font.name.serif.x-western", "方正仿宋_GBK");
user_pref("font.name.monospace.x-western", "方正仿宋_GBK");
user_pref("font.name.sans-serif.zh-CN", "方正仿宋_GBK");
user_pref("font.name.serif.zh-CN", "方正仿宋_GBK");
user_pref("font.name.monospace.zh-CN", "方正仿宋_GBK");
user_pref("font.size.variable.x-western", 20);
user_pref("font.size.fixed.x-western", 20);
```

本次正文设为 20px，签名约为 14px。字号是个人显示偏好，没有统一标准。

## 十、Thunderbird 与 Betterbird 并存

迁移期间我没有卸载 Thunderbird：

- Thunderbird 数据继续保留在 `~/.thunderbird/`；
- Betterbird 使用 `~/.betterbird-profile/`；
- 两者通过 `-no-remote` 和不同 Profile 隔离；
- IMAP 账号并存通常便于核对数据；
- POP3 账号不建议长期同时在线，避免重复收取、删除策略或状态差异造成困扰。

验证期至少应检查：

1. 各账号能否正常收发；
2. 本地邮件数量与目录是否完整；
3. 保存密码和证书是否可用；
4. 通讯录能否按中文姓名查找；
5. 全局搜索是否已重建并能找到旧邮件；
6. 过滤器和虚拟文件夹是否正常；
7. 回复、转发签名和模板是否符合预期；
8. 重启电脑后 Betterbird 是否仍使用独立 Profile。

确认稳定之前，不删除 Thunderbird，也不清理它的原始 Profile。

## 十一、推荐用法：交给 AI 协助实施

这篇文章包含较多路径、版本差异和备份要求，不建议读者不看环境就逐条复制。更方便的方式，是把完整文章交给正在操作银河麒麟电脑的 AI 编程助手或终端智能体，让 AI 先读取本机信息，再生成适配当前电脑的迁移方案。

可以把下面的要求连同文章一起交给 AI：

```text
请阅读这篇 Betterbird 安装与迁移文章，协助我在当前银河麒麟电脑上实施。

第一阶段只查询，不修改任何文件：确认系统架构、glibc、现有 Thunderbird
版本和真实 Profile，检查 Betterbird 是否已安装、磁盘剩余空间，以及邮件、
密码、通讯录、过滤器和虚拟文件夹分别位于哪里。

比较我的环境与文章实测版本，列出可以直接沿用、需要替换和不再适用的步骤。
所有“你的用户名”“你的Thunderbird配置目录”和下载版本必须换成本机真实值。

先给出完整备份与回滚方案。必须使用独立的 Betterbird Profile，不得覆盖、
移动或删除 Thunderbird 原始目录。复制邮件、合并 prefs.js、删除索引和修改
语言包签名设置之前，先说明影响并等我确认。

中文语言包只使用来源明确的官方 XPI；如果新版已经能正常安装，不沿用旧的
签名绕过设置。TemplateWing 优先安装官方版本，不自动应用文章中的个人补丁。

迁移完成后逐项验证账号收发、邮件数量、密码、通讯录、过滤器、虚拟文件夹、
中文姓名搜索、回复模板和签名。最后保存一份本机路径清单、操作记录和回滚说明。
任何一步失败都停下来报告，不继续覆盖后续文件。
```

AI 的主要价值不是替你更快地运行命令，而是把**环境检查、路径替换、备份、迁移、验证和回滚**串成闭环。尤其是删除全局索引、合并 `prefs.js` 和修改扩展配置，必须先确认当前 Profile 没有指向 Thunderbird 原目录。

## 十二、常见坑点速查

| 问题 | 原因与处理 |
|---|---|
| 中文语言包安装无反应 | 未签名 XPI 未注册；检查应用级目录和语言包偏好 |
| 放 `distribution/extensions/` 不生效 | 本次实测应放程序根目录 `extensions/` |
| 两个位置都放 XPI 后失效 | 重复注册冲突，只保留应用级一份 |
| 启动后语言包仍禁用 | 退出程序，检查 `extensions.json` 的注册状态 |
| Betterbird 改写了 Thunderbird 数据 | 未指定独立 Profile；启动参数和桌面入口都需检查 |
| 复制数据后中文姓名搜索不到 | 退出后删除全局索引并重建 |
| 强杀后提示已有实例 | 可能遗留锁文件；先确认进程确实退出，再处理 Profile 锁文件 |
| 模板显示邮箱而非姓名 | 原版变量未查通讯录，需要官方功能支持或自行适配 |
| 回复没有模板 | 本次配置采用快捷键插入，回复场景手动触发 |
| HTML 首行空格消失 | 使用不换行空格，而非连续普通空格 |

## 写在最后

从 Thunderbird 换到 Betterbird，真正耗时的是**工作流迁移**，不是解压安装包。

这次迁移最关键的几个决定是：

- 使用官方 ARM64 tarball，避开不合适的 Flatpak 路线；
- 一开始就隔离 Profile，保留完整回退路径；
- 中文语言包解决“注册”问题，而不是只强制界面语言；
- 邮件、密码、通讯录和配置分类迁移；
- 重建搜索索引，让历史邮件真正可检索；
- 用 TemplateWing、签名和字体配置恢复日常办公习惯。

Betterbird 并没有消除所有维护工作，语言包和个人扩展补丁仍需要在升级后复测。但相比直接把旧 Thunderbird Profile 交给新程序，这套方式更可控，也让我能逐步验证、随时回退。

---

> 原文首发于 Gitee：<https://gitee.com/digtip/notes/blob/main/blog/kirin/%E4%BB%8E%20Thunderbird%20%E5%88%B0%20Betterbird%EF%BC%9A%E9%93%B6%E6%B2%B3%E9%BA%92%E9%BA%9F%20ARM64%20%E9%82%AE%E4%BB%B6%E5%AE%A2%E6%88%B7%E7%AB%AF%E8%BF%81%E7%A7%BB%E5%AE%9E%E5%BD%95.md>
