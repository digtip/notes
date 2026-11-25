---
title: "银河麒麟 V11 OSTree 只读系统装软件指南：软链接、bind mount 与用户级覆盖的六种手法"
date: 2026-11-24
tags: [银河麒麟, V11, OSTree, bind-mount, 软链接, KARE, 不可变系统]
description: 银河麒麟 V11 的 OSTree 不可变系统把 /usr 挂成只读，常规 apt/dpkg 安装频频被拦。本文用真机实测的六个案例讲清可写性地图，以及用户级覆盖、可写分区软链接、systemd bind mount、fstab 数据盘迁移、KARE overlay 解包、包管理补救六种应对手法，附坑点与恢复方法。
cover: "../../assets/kylin-v11-ostree-six-methods-cover.png"
status: published
original: https://gitee.com/digtip/notes/blob/main/blog/kirin/%E9%93%B6%E6%B2%B3%E9%BA%92%E9%BA%9F%20V11%20OSTree%20%E5%8F%AA%E8%AF%BB%E7%B3%BB%E7%BB%9F%E8%A3%85%E8%BD%AF%E4%BB%B6%E6%8C%87%E5%8D%97%EF%BC%9A%E8%BD%AF%E9%93%BE%E6%8E%A5%E3%80%81bind%20mount%20%E4%B8%8E%E7%94%A8%E6%88%B7%E7%BA%A7%E8%A6%86%E7%9B%96%E7%9A%84%E5%85%AD%E7%A7%8D%E6%89%8B%E6%B3%95.md
---

# 银河麒麟 V11 OSTree 只读系统装软件指南：软链接、bind mount 与用户级覆盖的六种手法

在银河麒麟 V11 上装软件，经常会遇到一类诡异问题：`dpkg -i` 报只读文件系统错误、`apt` 提示软件包需要重新安装却不让删、第三方 deb 被"验证失败，拒绝安装"、应用在维护模式下一切正常、回到普通模式就崩溃。

这些现象的共同根源是 **OSTree 不可变系统架构**：系统目录以只读方式挂载，传统 Linux"往 `/usr` 里写文件"的安装方式被从文件系统层面封死。但只读不等于什么都做不了——系统同时留下了多层可写区域和正规的覆盖入口。

本文把我在一台飞腾 ARM64 麒麟 V11 机器上实测过的应对手法整理成六个层次，从完全免 root 的用户级覆盖，到需要 root 的 bind mount 和容器 overlay 解包，每个手法都给出真机案例和恢复方式。

> [!warning] 非官方定制，先评估再动手
> 本文记录的是绕过只读限制的系统定制手法，不是麒麟官方推荐流程。手法二到五需要 root，会改变开机挂载或服务行为，生产或涉密机器请先在测试机验证。所有案例都给出了回滚方法，操作前请按"修改范围 → 备份 → 恢复命令"的顺序确认自己能接受后果。系统大版本升级（OSTree deployment 切换）后，定制项需要逐一复核。

## 一、背景：只读到底是怎么实现的

OSTree 用"内容寻址 + 部署快照"管理系统：每个系统版本是一份不可变的部署树，开机后把系统目录只读挂载，升级等于切换到一棵新树，回滚就是切回旧树。

在本机上用 `findmnt` 可以直接看到 `/usr` 是**双层只读**结构：

```text
$ findmnt /usr
TARGET SOURCE                        FSTYPE  OPTIONS
/usr   /dev/nvme0n1p3[/ostree/...]   ext4    ro,relatime
/usr   overlay                       overlay ro,relatime,lowerdir=.../usr-ovl/usr-lower:/root/usr
```

第一层是 OSTree 部署树本身（ext4 子卷，`ro`），第二层是系统包覆盖层（overlay，同样 `ro`）。任何对 `/usr` 的写入都会收到 `EROFS, Read-only file system`。

而传统发行版常识里"管理员可写"的 `/usr/local`，在这台机器上**没有独立挂载点，继承 `/usr` 的只读属性**——这是第一个反直觉点，很多崩溃就源于厂商软件硬往 `/usr/local` 写运行数据。

## 二、环境信息与可写性地图

实测环境：

| 项目 | 实测值 |
|---|---|
| 系统 | 银河麒麟桌面 V11 ARM64，飞腾平台，OSTree 部署 |
| 内核 | 6.6.0-63-generic |
| 磁盘 | 系统盘 nvme0n1p3（SYSROOT）+ 数据盘 nvme0n1p6（挂载于 `/data`） |
| 包管理 | 定制 dpkg（含 kysec 签名校验）+ `ostree-pkgs-guard` 防护 |
| 容器 | KARE v10sp1 / shadow 两套应用兼容容器 |

动手前先用 `findmnt` 摸清自己机器的可写性，这是所有后续手法的决策依据。本机实测：

| 路径 | 挂载方式 | 读写 | 用途 |
|---|---|---|---|
| `/usr` | ext4 ro 子卷 + ro overlay | **只读** | 系统程序、库、图标、desktop |
| `/usr/local` | 无独立挂载，随 `/usr` | **只读** | 传统本地安装目录，本机不可写 |
| `/etc` | rw overlay（upper 在 ostree pkgs 层） | 可写 | 配置、systemd 单元、fstab，改动持久 |
| `/var` | rw overlay（var-ovl） | 可写 | 运行数据、日志、`/var/lib`、`/var/opt` |
| `/home` | 数据盘 bind（`/data/home`） | 可写 | 用户数据，独立于系统快照 |
| `/opt` | 出厂软链 → `var/opt` | 可写 | 第三方应用主程序实际落地处 |
| `/var/opt` | 数据盘 bind（`/data/sysdata/var-opt`） | 可写 | KARE 容器、WPS 等大块应用 |

三条结论先记住：

1. **凡是写 `/usr` 的需求，都要改道到 `/etc`、`/var`、`/home` 或 `/opt`（即 `/var/opt`）**；
2. `/etc` 和 `/var` 虽然是 overlay，但 upper 层由 OSTree 持久管理，重启不丢，小版本升级也保留；
3. 用户家目录完全不受系统快照影响，是最安全的定制层。

## 三、手法一：用户级 XDG 目录覆盖（免 root，首选）

### 原理

遵循 XDG 规范的桌面组件会按优先级搜索用户目录，且**用户目录优先于系统目录**。既然 `/usr/share` 不可写，就把同名资源放进 `~/.local/share` 对应位置，桌面环境自动采用用户副本，系统原版原封不动。

### 案例 A：覆盖 UKUI 托盘 widget

UKUI 的 widget 框架搜索路径包含 `~/.local/share/ukui/widgets`，优先级高于 `/usr/share/ukui/widgets`。把系统托盘 widget 整体复制到家目录后改 QML，即可在免 root、免维护模式的前提下修改面板行为：

```bash
mkdir -p ~/.local/share/ukui/widgets
cp -r /usr/share/ukui/widgets/org.ukui.systemTray \
      ~/.local/share/ukui/widgets/
# 然后编辑 ~/.local/share/ukui/widgets/org.ukui.systemTray/ui/ 下的 QML
```

恢复方式就是删掉用户副本并重启面板，系统原版立即生效：

```bash
rm -rf ~/.local/share/ukui/widgets/org.ukui.systemTray
pkill -x ukui-panel
sleep 3
setsid ukui-panel >/dev/null 2>&1 </dev/null & disown
```

### 案例 B：用户级图标与桌面快捷方式

第三方应用往 `/usr/share/icons` 和 `/usr/share/applications` 写文件失败时，对应用户级路径是：

```text
~/.local/share/icons/hicolor/<尺寸>/apps/    # 图标
~/.local/share/applications/<app>.desktop    # 菜单入口
~/Desktop/<app>.desktop                      # 桌面快捷方式
```

desktop 文件的 `Exec` 指向可写区里的真实程序即可。本机多个 Electron 应用（AionUi、Cherry Studio、Betterbird 等）的菜单入口都在 `~/.local/share/applications/`，系统升级不影响它们。

### 适用边界

只对遵循 XDG 搜索路径的组件有效（图标、desktop、字体、widget、bash 补全等）。硬编码 `/usr` 绝对路径的程序不吃这一套，需要用后面的手法。

## 四、手法二：可写分区 + 软链接，绿色解包安装

### 原理

本机出厂就把 `/opt` 做成了指向 `var/opt` 的符号链接：

```text
$ ls -ld /opt
lrwxrwxrwx 1 root root 7 ... /opt -> var/opt
```

也就是说所有"安装到 `/opt`"的应用，实际都落在可写的数据盘 `/var/opt`。对于只有图标和 desktop 落在 `/usr` 的 deb 包，可以**完全绕开 dpkg**：手动解包、主程序放进 `/var/opt`，入口走用户级 desktop。

### 案例：量子密信（zdxlz-app）免维护模式升级

该应用的 deb 在普通模式安装时，dpkg 写 `/usr/share/icons` 和 `/usr/share/applications` 失败而中断。实测升级流程：

```bash
# 1. 解包到临时目录（不需要 root 读 deb）
dpkg-deb -x lzmx_<新版本>.deb /tmp/zdxlz-new

# 2. 退出旧版应用
pkill -f '/var/opt/量子密信/zdxlz-app'

# 3. 替换可写区里的主程序（需要 root 写 /var/opt）
sudo mv /var/opt/量子密信 /var/opt/量子密信.bak-<旧版本>
sudo cp -a /tmp/zdxlz-new/opt/量子密信 /var/opt/量子密信
sudo chown -R root:root /var/opt/量子密信
# chrome-sandbox 必须 setuid root，否则沙箱起不来
sudo chmod 4755 /var/opt/量子密信/chrome-sandbox

# 4. 从用户级 desktop 启动（~/.local/share/applications/ 下已存在）
setsid -f /var/opt/量子密信/zdxlz-app
```

两个关键点：

- `cp -a` 会保留解包时的普通用户属主，落盘后必须 `chown -R root:root` 归位；
- Electron 类应用的 `chrome-sandbox` 依赖 4755 setuid 位，绿部部署最容易漏这一步。

### 同类做法：容器内补命令软链

KARE 容器的 root 文件系统也是 overlay，缺系统命令时可以在可写层直接补软链。某零信任客户端缺少 `ip` 命令导致引流路由失败，修复方式是在容器 overlay 里建链：

```text
/usr/sbin/ip -> /usr/lib/initramfs-tools/bin/busybox
```

该软链落在 overlay upper 层，应用重装不会被冲掉。

## 五、手法三：bind mount 给只读路径"垫"可写层

### 原理

当程序**硬编码**要往 `/usr` 下的某个目录写运行数据（锁文件、socket、数据库、登录态），软链接和 XDG 覆盖都无能为力。此时用 systemd mount 单元把一个可写目录 bind 挂载到只读路径上：挂载点之下程序看到的是可写副本，挂载点之外系统目录保持原样。

### 案例：融合 4A（aTrust + ffcs4a）普通模式 EROFS 崩溃

深信服 aTrust 的运行数据写 `/usr/share/sangfor/.aTrust`，ffcs4a 的可执行文件和配置写 `/usr/local/ffcs/bin`。deb 在维护模式装进 `/usr` 后，回到普通模式 `/usr` 只读，服务日志狂刷 `flock init failed, errcode is 30`——厂商日志里的 errcode 30 就是 EROFS，服务每 5 秒重启一次。

修复不需要维护模式：`/etc` 和 `/var/lib` 都可写，普通模式即可完成。

**第一步，把现有数据复制到可写区并清掉旧 socket：**

```bash
sudo mkdir -p /var/lib/sangfor/atrust-share /var/lib/sangfor/ffcs-bin
sudo cp -a /usr/share/sangfor/.aTrust/. /var/lib/sangfor/atrust-share/
sudo cp -a /usr/local/ffcs/bin/.        /var/lib/sangfor/ffcs-bin/
sudo find /var/lib/sangfor -type s -delete
```

**第二步，写两个 systemd mount 单元。** 本机实际在用的单元原文（`/etc/systemd/system/usr-share-sangfor-.aTrust.mount`）：

```ini
[Unit]
Description=Bind-mount writable backing for Sangfor .aTrust data dir (Kylin OSTree /usr ro workaround)
RequiresMountsFor=/var/lib
Before=aTrustDaemon.service

[Mount]
What=/var/lib/sangfor/atrust-share
Where=/usr/share/sangfor/.aTrust
Type=none
Options=bind

[Install]
WantedBy=local-fs.target
```

第二个单元 `usr-local-ffcs-bin.mount` 结构相同，`What=/var/lib/sangfor/ffcs-bin`、`Where=/usr/local/ffcs/bin`。

**第三步，启用并重启服务：**

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now usr-share-sangfor-.aTrust.mount
sudo systemctl enable --now usr-local-ffcs-bin.mount
sudo systemctl restart aTrustDaemon
```

三个设计要点：

1. **单元放 `/etc/systemd/system/`**：该目录在可写 overlay 里，重启持久，且优先级高于厂商自带单元；
2. `RequiresMountsFor=/var/lib` 和 `Before=aTrustDaemon.service` 保证挂载先于依赖它的服务完成，否则服务会在挂载空窗期崩溃重试；
3. 旧 unix socket 不能复制到新目录，`find -type s -delete` 这一步不能省，程序会自行重建。

验证用 `findmnt` 能看到只读路径已被 bind 覆盖，回滚则 `systemctl disable --now` 两个单元后重启。

## 六、手法四：数据盘 bind 迁移与 fstab 持久化

### 原理

系统盘容量有限，而 KARE 容器、办公套件动辄几十 GB。既然 `/var/opt` 本来就是独立可写挂载点，可以把它整体迁到数据盘，再用 fstab bind 回原路径，应用完全无感知。

### 案例：/var/opt 迁移到数据盘

```bash
# 1. 数据盘上建目录，完整同步（保留权限/属主/软链）
sudo mkdir -p /data/sysdata/var-opt
sudo rsync -aHAX /var/opt/ /data/sysdata/var-opt/

# 2. fstab 追加 bind 行（/etc 在可写 overlay，持久保存）
echo '/data/sysdata/var-opt  /var/opt  none  defaults,bind  0 0' \
  | sudo tee -a /etc/fstab

# 3. 挂载并验证
sudo mount /var/opt
findmnt /var/opt
```

本机同类型的出厂 bind 还有 `/data/home → /home`、`/data/root → /root`，`/etc/fstab` 里可以看到完整清单。fstab 之所以在 OSTree 系统上仍然有效，是因为 `/etc` 本身是 rw overlay，写入会落到 ostree pkgs 的 etc-upper 层持久保存。

### 坑点：bind 挂载竞态导致服务开机不自启

迁移后出现过一个典型时序问题：KARE 容器里的 root 后台服务开机后**完全没被拉起**（journal 里连 Starting 记录都没有），手动 `systemctl start` 却正常。

根因链：

1. 服务单元文件在 `/opt/kare/...`（即数据盘 bind 挂载之下）；
2. systemd 在开机极早阶段构建启动事务时，`/var/opt` 的 bind 还没挂好，底层根分区的占位空目录里没有这些单元文件；
3. 单元悬空被跳过，systemd **不会在挂载完成后重试**。

修复是在根分区 `/etc/systemd/system/` 放单元副本（开机即就绪），并显式声明挂载排序：

```ini
[Unit]
After=var-opt.mount data.mount local-fs.target
Wants=var-opt.mount
RequiresMountsFor=/opt/kare/lib/systemd/system/<svc>.service.bin
```

再把 wants 软链指向根分区副本：

```bash
sudo ln -sf /etc/systemd/system/<svc>.service \
   /etc/systemd/system/multi-user.target.wants/<svc>.service
```

凡是依赖 bind 挂载路径下文件的服务，都要检查这个时序，`systemd-analyze verify` 可以离线校验单元语法。

## 七、手法五：KARE 容器 overlay 手动解包，绕过签名墙

### 原理

麒麟 V11 的定制 dpkg 集成了 kysec 内核安全模块，安装时强制做 BJCA 签名校验，**不带麒麟可信签名的第三方 deb 一律拒绝**（退出码 16，"验证失败，拒绝安装"），改 dpkg 配置、加 `--force` 参数均无效——这是编译进 dpkg 的独立钩子。

但 KARE 容器应用（TeleAgent、飞书等）的真实文件全部在可写 overlay 里：

```text
/var/opt/kare-applications/v10sp1/merge/opt/<App>/
```

`merge` 是常驻 overlay，写入落到 upper 层。于是可以绕开 dpkg 的安装路径，直接把 deb 解包进 overlay，再手工补齐 dpkg 元数据。宿主导出的 shim（`/opt/kare/usr/bin/<pkg>`，内容是 `kare run` 包装）与版本无关，全程不用动。

### 通用步骤（TeleAgent / 飞书实测通用）

```bash
# 1. 解包 deb
ar p <app>.deb data.tar.xz | tar xJ -C /tmp/staging

# 2. 备份旧版本后替换主程序（merge/opt 可写，需要 root）
sudo mv /var/opt/kare-applications/v10sp1/merge/opt/<App> \
        /var/opt/kare-applications/v10sp1/merge/opt/<App>-backup-<日期>
sudo cp -a /tmp/staging/opt/<App> /var/opt/kare-applications/v10sp1/merge/opt/
sudo chown -R 0:0 /var/opt/kare-applications/v10sp1/merge/opt/<App>

# 3. 同步容器内 dpkg 元数据，让包管理状态自洽
#    .list 用文件清单重建，维护脚本从 control.tar.xz 提取，
#    merge/var/lib/dpkg/status 里改 Version / Installed-Size

# 4. 通过宿主 shim 启动（不要直接跑容器内二进制）
setsid /opt/kare/usr/bin/<app>
```

注意事项：

- 容器内的 `/usr/bin/systemctl` 是只记日志不干活的空壳脚本，root 服务由宿主真 systemd 经 `.bin` 包装拉起；
- 只更新容器内 dpkg status，**宿主 dpkg 仍显示旧版本是预期现象**，不影响运行；
- 包内自带的 desktop 如果是 `Exec=<二进制>` 原版，不能覆盖 KARE 定制版（`Exec=/usr/bin/kare run ...`），否则菜单入口失效；
- 备份只留最近一份，回滚就是停进程、用备份目录覆盖回去、status 改回旧版本号。

## 八、手法六：包管理补救与官方维护模式

前五招解决"怎么装"，这一招解决"装坏了怎么收场"。

### 1. 损坏包不要强删，先 apt-mark hold

第三方包装坏后，apt 可能报 `E: 软件包 xxx 需要重新安装，但是我无法找到相应的安装文件`。OSTree 下所有 `dpkg --remove/--purge`、`apt remove` 都会被 `ostree-pkgs-guard` 拦截（退出码 256）。正确处理：

```bash
sudo apt-mark hold <损坏包名>   # 锁定后 apt 不再尝试修复它
sudo apt install -f             # 验证 apt 恢复正常
```

锁定不影响软件使用，也不再阻断其他包的安装升级。确需彻底卸载，再走维护模式。

### 2. 维护模式：官方的 /usr 可写窗口

OSTree 系统保留了维护模式（部分版本命令为 `sudo kylin-mm enable` 进入、`sudo kylin-mm disable` 退出，各重启一次；也有版本从开机引导菜单或控制中心进入）。进入后 `/usr` 对 root 可写，可以正常 `apt install`、卸载损坏包。

> [!note] 入口随版本变化，先核实再操作
> 本文写作时在当前 V11 版本上未检索到 `kylin-mm` 命令，不同小版本的维护模式入口可能不同。执行前先 `which kylin-mm` 或查阅本机版本文档确认，不要照搬命令。维护模式写 `/usr` 仍然需要 sudo，且退出后要验证定制项（bind 单元、容器 overlay）是否仍然生效。

### 3. 优先用系统自带替代命令

有些需求根本不值得动包管理。例如 `traceroute` 默认未装且安装被拦，系统自带的 `tracepath` 功能基本等价，直接用即可。动手前先 `which`/`apropos` 找替代品，是成本最低的方案。

## 九、命令清单（按手法汇总）

```bash
# —— 手法一：用户级覆盖 ——
ls ~/.local/share/applications/                 # 用户级菜单入口
ls ~/.local/share/icons/hicolor/                # 用户级图标
cp -r /usr/share/ukui/widgets/<widget> \
      ~/.local/share/ukui/widgets/              # widget 覆盖
rm -rf ~/.local/share/ukui/widgets/<widget>     # 一键恢复

# —— 手法二：绿部解包 ——
dpkg-deb -x <pkg>.deb /tmp/staging              # 免 root 解包
sudo chown -R root:root /var/opt/<App>          # 属主归位
sudo chmod 4755 /var/opt/<App>/chrome-sandbox   # Electron setuid

# —— 手法三：bind mount 垫可写层 ——
findmnt /usr                                    # 先确认只读结构
sudo cp -a /usr/<ro-path>/. /var/lib/<backing>/
sudo find /var/lib/<backing> -type s -delete    # 清旧 socket
sudo systemctl enable --now <unit>.mount

# —— 手法四：数据盘迁移 ——
sudo rsync -aHAX /var/opt/ /data/sysdata/var-opt/
echo '/data/sysdata/var-opt /var/opt none defaults,bind 0 0' | sudo tee -a /etc/fstab
sudo mount /var/opt && findmnt /var/opt

# —— 手法六：损坏包止血 ——
sudo apt-mark hold <损坏包名>
sudo apt install -f
```

## 十、坑点与排错

### 1. 报错先区分 EROFS 还是签名拦截

- `Read-only file system` / 厂商自定义 errcode 30 → 只读限制，用手法三、四改道；
- `验证失败，拒绝安装` / 退出码 16 → kysec 签名墙，用手法五解包或找厂商要签名包；
- `需要重新安装但找不到安装文件` / 退出码 256 → 包状态损坏，用手法六的 hold 止血。

### 2. bind 挂载的三个必备动作

复制数据后清 socket、单元里写 `RequiresMountsFor` 排序、`enable --now` 后用 `findmnt` 验证。漏任何一个，症状都可能表现为服务静默重启而不是挂载失败，极难排查。

### 3. cp -a 的属主与权限陷阱

普通用户解包再 `cp -a` 到系统目录，文件属主还是普通用户，服务可能拒绝读取；Electron 应用额外检查 chrome-sandbox 的 setuid 位。落盘后固定动作：`chown -R 0:0` + 核对特殊权限位。

### 4. 容器里 systemctl 是假的

KARE 容器内 `systemctl start` 返回成功但什么都没发生，root 服务必须在宿主侧管理。同理，容器诊断优先读日志文件，不要依赖交互式 systemctl。

### 5. 维护模式正常、普通模式崩溃

这是 OSTree 排障的标志性线索：维护模式下 `/usr` 可写所以一切正常，回普通模式只读就崩。看到这个模式，直接排查应用是否在写 `/usr`，上 bind mount，不要在应用配置里白费功夫。

### 6. 定制项的生命周期

用户级覆盖（手法一）和 `/home` 数据随账号永久保留；`/etc`、`/var` 的 overlay 改动扛得住重启和小版本更新，但 **OSTree 大版本切换部署树后需要逐项复核**；容器 overlay upper 层在容器重装时可能受影响，重要定制要留书面记录和备份。

## 十一、把文章交给 AI 执行（提示词模板）

> [!important]
> 本文手法分层明显，风险从低到高。让 AI 执行时应要求它先做只读勘察、给出手法选型理由，再动手。

```text
请阅读《银河麒麟 V11 OSTree 只读系统装软件指南》，协助我在 OSTree
不可变系统上安装/修复一个软件。

要求：
1. 第一阶段只做只读勘察：findmnt 确认 /usr、/etc、/var、/opt、/home
   的挂载与读写属性，ls -ld /opt 确认软链，查看报错是 EROFS、签名
   拦截还是包状态损坏，不要立即修改任何东西。
2. 按风险从低到高选手法：能用用户级 XDG 覆盖就不用 root；能绿部
   解包到 /var/opt 就不碰 /usr；只有硬编码写 /usr 的程序才用
   bind mount，并说明挂载单元的排序依据。
3. 任何修改前列出：改动路径清单、备份位置、一键恢复命令。涉及
   /etc/systemd/system 或 /etc/fstab 的改动，先给我看完整文件内容。
4. 注意 cp -a 后 chown root:root、Electron chrome-sandbox 的 4755、
   bind 副本里删除旧 unix socket、服务单元加 RequiresMountsFor。
5. 不尝试关闭 kysec、不强行 dpkg --remove 被 ostree-pkgs-guard
   拦截的包；损坏包先用 apt-mark hold 止血。
6. 维护模式入口以本机实际版本为准，先 which/查文档确认，不照搬
   文章里的版本化命令。
7. 每步执行后用 findmnt、systemctl status、进程号和实际窗口验证，
   任何一步与文章现象不符立即停止并报告，不自行发明其他绕过手段。
```

## 写在最后

OSTree 的只读设计不是给用户添堵，而是用不可变的系统树换来了"升级即切树、故障可回滚"的可靠性。理解这一点后，应对它的思路就不应该是"怎么把只读墙凿开"，而是**顺着它的分层设计走**：用户定制进家目录，应用程序进 `/var/opt`，运行数据进 `/var/lib`，系统配置进 `/etc` overlay，实在绕不开的 `/usr` 硬编码路径，才用 bind mount 精确垫一层可写 backing。

六种手法本质上是同一句话：**把写操作引导到系统预留的可写层，再用软链接、bind 挂载和搜索路径优先级把它们接回应用期望的位置。** 掌握了可写性地图这张底牌，大多数"只读系统装不了软件"的问题都能在不破坏系统完整性的前提下解决。

---

> 原文首发于 Gitee：<https://gitee.com/digtip/notes/blob/main/blog/kirin/%E9%93%B6%E6%B2%B3%E9%BA%92%E9%BA%9F%20V11%20OSTree%20%E5%8F%AA%E8%AF%BB%E7%B3%BB%E7%BB%9F%E8%A3%85%E8%BD%AF%E4%BB%B6%E6%8C%87%E5%8D%97%EF%BC%9A%E8%BD%AF%E9%93%BE%E6%8E%A5%E3%80%81bind%20mount%20%E4%B8%8E%E7%94%A8%E6%88%B7%E7%BA%A7%E8%A6%86%E7%9B%96%E7%9A%84%E5%85%AD%E7%A7%8D%E6%89%8B%E6%B3%95.md>
