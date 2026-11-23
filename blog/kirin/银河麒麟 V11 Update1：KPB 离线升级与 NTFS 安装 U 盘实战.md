---
title: 银河麒麟 V11 Update1：KPB 离线升级与 NTFS 安装 U 盘实战
date: 2026-11-20
tags: [银河麒麟, V11, Update1, OSTree, KPB, Rufus, NTFS, ARM64]
description: 整合银河麒麟 V11 2603 Update1 两条路线：同代系统通过 ISO 内 KPB 离线升级，全新安装使用 NTFS/UEFI:NTFS U 盘，并记录升级前备份、already mounted 根因、手工制作和验证方法。
status: published
original: https://gitee.com/digtip/notes/blob/main/blog/kirin/%E9%93%B6%E6%B2%B3%E9%BA%92%E9%BA%9F%20V11%20Update1%EF%BC%9AKPB%20%E7%A6%BB%E7%BA%BF%E5%8D%87%E7%BA%A7%E4%B8%8E%20NTFS%20%E5%AE%89%E8%A3%85%20U%20%E7%9B%98%E5%AE%9E%E6%88%98.md
---

# 银河麒麟 V11 Update1：KPB 离线升级与 NTFS 安装 U 盘实战

围绕银河麒麟 V11 2603 Update1，我分别处理过两个问题：

1. 已经运行 2603 的电脑要离线升级，但“麒麟离线升级”工具无法选择下载到的 ISO；
2. 给另一台机器全新安装 Update1 时，分区级 `dd` 制作的 U 盘反复报 `already mounted on /target`，换成 NTFS/UEFI:NTFS 形态后安装成功。

这两个问题经常被混在一起，其实对应完全不同的路线：

> [!important] 先选对路线
> **2603 同代更新：提取 ISO 内的 `.kpb`，使用离线升级工具，不需要制作安装 U 盘，也不需要进入维护模式。**
> **全新安装或重装：才需要制作安装 U 盘。本文的 NTFS 方案用于解决特定安装介质下的挂载冲突。**

> 实测时间：2026 年 9 月 14 日。环境为银河麒麟桌面 V11 2603 OSTree ARM64、飞腾 FTG340。
> 原版本为 Build 20260212，目标介质为 Update1 20260818。离线升级完成升级前准备并核验机制；NTFS U 盘已在实际安装中验证可绕过本次故障。
> 不同硬件、镜像和安装器版本可能表现不同，不要把本文包名、校验值和分区参数套到其他版本。

> [!warning] 数据安全
> 系统升级和制作启动盘都可能造成数据丢失。升级前备份个人文件与配置；制作 U 盘会清空目标整盘，必须通过型号、容量和序列信息反复确认设备。全新安装还会清空目标电脑磁盘，不能把“制作 U 盘”和“选择安装目标盘”混为一步。

## 一、Update1 是什么，为什么值得考虑升级

### 1. 它是 V11 2603 的阶段性功能更新

Update1 不是 V12，也不是把 2603 改成另一条产品分支，而是银河麒麟桌面 V11 2603 基础上的一次阶段性更新。它同时以完整安装镜像和离线升级包等形式提供，因此既可用于新装，也可让符合条件的 2603 机器升级。

本次 ARM64 镜像名中的 **20260818** 是镜像构建日期，即 **2026 年 8 月 18 日**；openKylin 官方论坛的“银河麒麟桌面操作系统 V11（2603 Update1）上线”公告发布于 **2026 年 9 月 5 日**（公告系统时间为 9 月 4 日 UTC）。这两个日期含义不同，不应把构建日期直接写成公告发布日期。

官方更新入口：<https://bbs.openkylin.top/t/topic/173568>。

### 2. 官方说明中的主要改进

官方将这次更新定义为“功能更新包”，总体目标是优化重要组件，提升使用体验、安全性、稳定性和兼容性。公告按 PU 补丁列出了几类变化：

- **安全修复**：修复多项 Linux 软件包及内核安全漏洞，其中包含严重和高危漏洞；具体 CVE/KVE 编号以官方公告和麒麟安全门户为准。
- **包管理与运维策略**：支持用户模式下使用 apt，调整包安装器在运维模式下的安装策略，以及用户模式下 dpkg 卸载软件包的权限策略。
- **KARE 应用兼容**：官方明确写有“解决系列应用兼容的问题”，有助于改善依赖 KARE 运行的部分旧应用。
- **AI 能力**：支持端侧 8B 大语言模型，AI 助手增加知识库管理与 RAG 问答，优化系统控制逻辑、模型调度和端侧语音模型体验。
- **桌面与生态**：后续 PU 条目继续修复生态兼容、桌面环境和用户体验问题。

> [!note] KARE 修复公开到什么程度
> 公开公告只概括了“解决系列应用兼容的问题”，没有逐项给出完整的 KARE 缺陷编号和代码级说明。网上流传的 `ld.so` 搜索顺序、X11 焦点、输入法、剪贴板、DBus、USB 和实例生命周期等详细修复清单，目前不能仅凭二手回答认定为官方事实。本文不把这些条目写成 Update1 已确认修复项；如果你的升级目的就是解决某个具体 KARE 应用，应保留旧部署并逐项实测。

KARE 可以理解为 V11 上的应用兼容运行环境，用来承载部分依赖旧系统库和运行环境的应用。它不等同于 Windows 兼容层，也不能解决所有旧软件问题，尤其不能替代缺失的内核驱动或专用硬件支持。

### 3. 升级必要性取决于你的使用情况

**更值得升级的情况：**

- 当前 2603 需要获得官方安全修复，尤其是联网办公或安全要求较高的环境；
- 正在使用 KARE 中的应用，并遇到兼容性、启动或运行异常；
- 需要官方更新带来的包管理和运维策略调整；
- 会使用端侧 AI、知识库或 RAG 问答，希望获得对应改进；
- 单位镜像基线、运维规范或软件适配明确要求 Update1。

**不必只凭“版本更新”盲目升级的情况：**

- 当前系统承载关键业务，且没有充分备份和回退窗口；
- 专用硬件、驱动或行业软件尚未确认兼容 Update1；
- 只是想解决一个具体应用问题，却没有证据表明它与本次更新相关；
- 当前并不是 2603 基线，无法确认这个 KPB 是否适用。

因此，升级价值可以概括为：**安全修复是普遍收益，KARE 和 AI 改进取决于实际使用，业务兼容性则必须验证。**版本更新不是性能提升的保证，本文也不会承诺升级后所有旧软件都会恢复正常。

## 二、路线 A：2603 同代离线升级

### 1. 为什么工具不识别 ISO

本机“麒麟离线升级”程序 `/usr/bin/kylin-offline-upgrade` 的文件过滤器只接受：

```text
SQU files(*.squashfs);;KPB files(*.kpb)
```

因此，在文件选择窗口里看不到或不能选择 `.iso`，不代表镜像损坏，也不代表工具故障。正确升级源位于 ISO 内部：

```text
Kylin-Desktop-V11-2603-Release-Update1-20260818-ARM64.iso
└─ patches/
   └─ Kylin-Desktop-V11-General-2603-Offline_upgrade-Function3.0-20260807-arm64.kpb
```

本次提取出的 `.kpb` 约 1.6GB，本体为 SquashFS 4.0，内部包含 OSTree 静态增量所需的 objects、deltas 和 commit 等内容。

包名中的 `General-2603` 表明它适用于 2603 基线。V10、2303、2403 或其他版本不能使用同一个包，必须获取与当前系统和目标版本对应的升级介质。

### 2. 挂载 ISO 并提取 KPB

先确认 ISO 来自可信渠道，并按发布方提供的校验值核验。把文件名替换为本机实际名称：

```bash
ISO="$HOME/下载/Kylin-Desktop-V11-2603-Release-Update1-20260818-ARM64.iso"
udisksctl loop-setup -r -f "$ISO"
```

命令会输出 loop 设备，例如 `/dev/loopN`。继续挂载：

```bash
udisksctl mount -b /dev/loopN
```

把实际挂载点代入：

```bash
cp /实际挂载点/patches/*.kpb "$HOME/下载/"
unsquashfs -s "$HOME/下载/实际升级包.kpb"
```

如果 `unsquashfs -s` 能识别为有效的 SquashFS，说明文件结构基本可读。它不是对来源和完整性的替代验证，官方哈希仍应单独核对。

用完后卸载并释放 loop：

```bash
udisksctl unmount -b /dev/loopN
udisksctl loop-delete -b /dev/loopN
```

### 3. 为什么不需要维护模式

本次离线升级工具会把升级包放到 `/var/lib/offlinesource`，只读挂载到 `/media/OfflineSource`，再执行 OSTree 升级。

OSTree 会创建一个新的系统部署，重启时切换引导目标，不是直接在当前运行的 `/usr` 上逐包覆盖。维护模式用于就地修改当前系统；这条 OSTree 部署路线不需要进入维护模式。

旧部署通常会保留，可以在启动菜单选择历史部署回退。但“有旧部署”不等于“不需要备份”：用户误操作、磁盘故障、分区调整和应用数据问题仍可能超出 OSTree 回滚能力。

### 4. 升级前的备份清单

备份应放在独立分区或外部存储，不要只放在准备升级的同一个系统目录里。

建议至少保存：

| 类别 | 建议内容 |
|---|---|
| 个人文件 | 文档、桌面、下载、项目、知识库和其他不可重建数据 |
| 系统配置 | `/etc/fstab`、网络、蓝牙、systemd 自定义单元与 drop-in |
| 软件清单 | `dpkg -l`、KARE 应用、Flatpak、用户目录应用 |
| 驱动清单 | `dkms status`、当前内核和关键硬件信息 |
| 用户服务 | `systemctl --user list-unit-files` 及自定义服务文件 |
| 启动与分区 | `lsblk -f`、`findmnt`、`efibootmgr`（可读取时） |
| 恢复材料 | 必要的安装包、许可证、恢复脚本和备份说明 |

可使用以下命令生成基础清单，目录自行替换：

```bash
BACKUP="/外部备份位置/pre-update1-$(date +%F)"
mkdir -p "$BACKUP"

dpkg -l > "$BACKUP/dpkg-list.txt"
dkms status > "$BACKUP/dkms-status.txt" 2>&1
lsblk -f > "$BACKUP/lsblk.txt"
findmnt > "$BACKUP/findmnt.txt"
systemctl list-unit-files > "$BACKUP/system-units.txt"
systemctl --user list-unit-files > "$BACKUP/user-units.txt"
cp -a /etc/fstab "$BACKUP/fstab"
```

还要备份实际文件，而不只是配置清单。备份完成后抽查能否打开，外部存储要安全卸载。

### 5. 哪些内容通常会保留，哪些必须复验

在本机布局中，`/home`、`/root` 和 `/data` 位于持久数据区域，KARE 容器数据也有独立持久位置。OSTree 会对 `/etc` 做三方合并，用户目录应用和个人配置通常不随新部署消失。

但不要据此推断所有机器都相同。先用以下命令确认自己的挂载布局：

```bash
findmnt /home /root /data /var /var/opt
```

新部署会更换 `/usr` 相关内容，因此升级后重点检查：

- 自己手工建立在 `/usr` 下的软链或文件；
- `/usr/local` 中由厂商包部署的内容；
- DKMS 驱动与新内核是否匹配；
- 声卡、显卡、指纹、蓝牙和其他专用硬件；
- KARE 容器及 `/opt` 下第三方应用；
- 用户级输入法、音频和快捷键服务。

如果某项软件依赖手工修改 `/usr`，应提前准备官方安装包或恢复方法，不要指望 OSTree 保留这类非标准改动。

### 6. 执行升级

1. 接通电源，保存工作并关闭重要应用；
2. 开始菜单搜索并打开“离线升级”；
3. 文件类型选择 `KPB files (*.kpb)`；
4. 选择刚从 ISO 提取的升级包；
5. 核对目标版本为 Update1 / 20260818；
6. 开始升级，按提示完成 polkit 授权；
7. 按工具提示重启，等待新部署完成。

本次记录预计升级和重启阶段约 30–60 分钟，实际时间取决于设备和镜像。过程中不要强制关机。

### 7. 升级后验收

```bash
cat /etc/kylin-build
uname -a
dkms status
systemctl --user --failed
systemctl --failed
lsblk -f
```

再按实际使用情况检查：

- 声音、麦克风、显卡和外部显示；
- 蓝牙设备与快捷键；
- 指纹、人脸等登录方式；
- 输入法、语音听写和音频服务；
- 常用第三方应用及容器；
- 个人文件和备份是否仍可读取。

如果新部署异常，优先通过启动菜单回到旧部署，再分析原因。不要在故障状态下继续大量修改，把两个部署都弄得难以回退。

## 三、路线 B：制作 Update1 全新安装 U 盘

### 1. 为什么不用 FAT32

本次 ARM64 ISO 约 9.4GB，其中 `casper/filesystem.squashfs` 约 6.9GB，超过 FAT32 单文件 4GB 上限。因此，不能只格式化一个 FAT32 U 盘再复制全部文件。

实测 ISO 不是可以直接按普通混合镜像理解的 isohybrid 介质。分区级 `dd` 可以复刻原始 GPT 布局，但在某些预装过麒麟的目标机上触发了安装器挂载冲突。

### 2. 故障现象

安装末段报错：

```text
mount: /dev/nvme0n1p3 already mounted on /target.
dmesg may have more information after failed mount system call.
```

这里的设备名只是目标机实例，读者电脑可能完全不同。

安装日志显示，同一阶段连续执行了两个挂载脚本：

```text
13mount-target
13mount-target-custom
```

第一个脚本已把 root 分区挂到 `/target`，第二个脚本又尝试挂载同一分区，于是失败。

进一步比较发现，基础版与 Update1 的这两个脚本在实测镜像中逐字节相同，不能简单归因于 Update1 新引入的脚本回归。

自定义脚本依赖 `/tmp/ky-installer.cfg` 中的 `disk-custom` 决定是否提前返回。实测 GUI 安装生成的配置缺少该键，使标准分支和自定义分支都继续执行。介质根目录的模板配置中存在 `disk-custom=false`，而安装器是否采用介质配置与介质形态有关。

实测结果是：UDF/分区级 `dd` 盘触发问题，Rufus 或手工 NTFS/UEFI:NTFS 盘能够稳定通过同一故障点。抹盘、重复格式化和更换文件系统都没有解决双挂载，因为 `mkfs` 已成功，失败发生在后续挂载阶段。

这是基于本次日志和介质对比得出的结论，不应推广为所有 `already mounted` 的唯一根因。

### 3. NTFS/Rufus 式布局

目标 U 盘采用 GPT 两个分区：

| 分区 | 大小 | 文件系统 | 用途 |
|---|---|---|---|
| p1 | 除末尾约 1MiB 外的空间 | NTFS | 保存 ISO 全部文件 |
| p2 | 2079 扇区，约 1MiB | FAT12/16 | UEFI:NTFS 引导加载器 |

p2 使用卷标 `RUFUS_BOOT`，包含 ARM64 的 `EFI/Boot/bootaa64.efi`。固件先加载 UEFI:NTFS，再访问 NTFS 分区并链式加载麒麟的 GRUB。

本次已核实 ISO 中的 `grubaa64.efi` 内置 NTFS 支持。UEFI:NTFS 是 Rufus 使用的开源组件，项目地址为 <https://github.com/pbatard/uefi-ntfs>。

如果有 Windows 电脑，优先使用与当前镜像兼容的 Rufus 官方版本制作，并按实际提示选择模式。下面的 Linux 手工流程用于理解结构和排查，不是唯一方法。

## 四、Linux 手工制作 NTFS 安装盘

> [!danger] 以下命令会清空整块设备
> `/dev/sdX` 只是占位符。执行前用 `lsblk -o NAME,SIZE,LABEL,MODEL,SERIAL,MOUNTPOINTS` 确认目标 U 盘，拔掉其他不需要的移动盘。不要根据设备字母顺序猜测，也不要在目标设备仍有挂载分区时继续。

### 1. 准备 ISO 和工具

```bash
ISO="$HOME/下载/Kylin-Desktop-V11-2603-Release-Update1-20260818-ARM64.iso"
sudo mkdir -p /mnt/iso
sudo mount -o loop,ro "$ISO" /mnt/iso
```

需要 `sfdisk`、`mkfs.ntfs`、`ntfs-3g`、`dd`、`partprobe`、`unsquashfs` 等工具。先检查是否存在：

```bash
command -v sfdisk mkfs.ntfs ntfs-3g partprobe unsquashfs
```

UEFI:NTFS 的 1MiB 分区镜像可以从可信的现有 Rufus 盘对应小分区提取，或按官方项目说明获取。不要使用来历不明的 EFI 文件。

假设已准备：

```bash
UEFI_NTFS_IMG="$HOME/软件/rufus-uefi-ntfs-aa64-1MiB.img"
```

把这个路径换成实际文件，并确认它是适用于 ARM64 目标引导链的镜像。

### 2. 计算分区几何

```bash
DEV=/dev/sdX
lsblk -o NAME,SIZE,LABEL,MODEL,SERIAL,MOUNTPOINTS "$DEV"

N=$(cat "/sys/block/${DEV##*/}/size")
P2=$((N-2112))
P1=$((P2-2048-36))
printf '总扇区=%s，p1大小=%s，p2起点=%s\n' "$N" "$P1" "$P2"
```

GPT 末尾要保留 33 个扇区。这里让 p2 的末端落在 `N-34`，避免分区末尾与备份 GPT 冲突。

p2 固定为 2079 扇区，p1 起始为 2048。不同 util-linux 版本可能给出不同提示，执行后必须检查实际布局。

### 3. 清空目标盘并创建 GPT

再次确认 `DEV` 是 U 盘后再执行：

```bash
sudo wipefs -a "$DEV"
sudo partprobe "$DEV"
sleep 1

sudo sfdisk "$DEV" <<EOF
label: gpt
start=2048,size=$P1,type=EBD0A0A2-B9E5-4433-87C0-68B6B72699C7,name="Main Data Partition"
start=$P2,size=2079,type=EBD0A0A2-B9E5-4433-87C0-68B6B72699C7,name="UEFI:NTFS"
EOF

sudo partprobe "$DEV"
sleep 1
sudo sfdisk --part-attrs "$DEV" 2 60,63
```

本次系统的 `sfdisk` 不接受 dump 脚本中的行内 `attrs=`，所以先创建分区，再单独设置 p2 的只读和隐藏属性。

上述 `${DEV}1`、`${DEV}2` 形式适用于 `sdX`。如果设备是 `nvme*` 或 `mmcblk*`，实际分区名通常带 `p1`、`p2`，必须按 `lsblk` 输出调整，不能机械拼接。

### 4. 格式化并写入引导分区

```bash
sudo mkfs.ntfs -f -L Kylin-Desktop-V11 "${DEV}1"
sudo dd if="$UEFI_NTFS_IMG" of="${DEV}2" bs=512 status=progress
sudo partprobe "$DEV"
sleep 1
sudo blkid "${DEV}1" "${DEV}2"
```

这里再次强调：`dd` 的输出必须是 U 盘的第二分区，不是系统盘，也不是目标电脑的内部 NVMe。

### 5. 复制 ISO 全部内容

```bash
sudo mkdir -p /mnt/ntfs
sudo ntfs-3g -o rw,uid=0,gid=0,umask=022 "${DEV}1" /mnt/ntfs
sudo cp -a --no-preserve=xattr /mnt/iso/. /mnt/ntfs/
sudo sync
```

本次检查的关键文件包括：

```text
EFI/BOOT/BOOTAA64.EFI
EFI/BOOT/grubaa64.efi
boot/grub/grub.cfg
casper/vmlinuz
casper/initrd.lz
casper/filesystem.squashfs
ky-installer.cfg
```

本次 ISO 内没有需要保留的符号链接，复制到 NTFS 未造成这类元数据问题。其他镜像应重新检查，不能默认相同。

`sync` 可能持续十几分钟，尤其是在低速 U 盘和 NTFS/FUSE 组合下。只要写入仍在推进且没有 I/O 错误，就不要强行拔盘。

## 五、制作后的完整校验

```bash
S=/mnt/iso
D=/mnt/ntfs

echo "ISO:  $(find "$S" -type f | wc -l)"
echo "NTFS: $(find "$D" -type f | wc -l)"
```

比较所有文件的大小清单：

```bash
(cd "$S" && find . -type f -printf '%s %p\n' | sort -k2) > /tmp/iso-files.txt
(cd "$D" && find . -type f -printf '%s %p\n' | sort -k2) > /tmp/ntfs-files.txt
diff /tmp/iso-files.txt /tmp/ntfs-files.txt
```

`diff` 无输出表示相对路径与大小一致。再核对关键引导文件：

```bash
for f in EFI/BOOT/BOOTAA64.EFI EFI/BOOT/grubaa64.efi boot/grub/grub.cfg casper/vmlinuz; do
  sha256sum "$S/$f" "$D/$f"
done
```

最重要的大文件应做字节级校验：

```bash
sha256sum "$S/casper/filesystem.squashfs" "$D/casper/filesystem.squashfs"
unsquashfs -s "$D/casper/filesystem.squashfs"
```

两个 SHA256 必须一致。本文实测镜像的哈希只用于当时核验，不能作为其他镜像的期望值，因此不要求读者与本文旧值比较。

## 六、安全卸载

root 通过 `ntfs-3g` 挂载后，文件管理器的“弹出”未必能处理全部挂载，使用命令行确认：

```bash
sudo umount /mnt/ntfs
sudo umount /mnt/iso
udisksctl unmount -b "${DEV}2" 2>/dev/null || true
lsblk -o NAME,LABEL,MOUNTPOINTS "$DEV"
```

确认 U 盘各分区挂载点为空，再物理拔出。

安装到目标电脑时，还要单独核对安装目标磁盘和分区。U 盘制作成功只解决介质问题，不代表可以忽略安装器中的数据清除提示。

## 七、常见坑点速查

| 问题 | 判断与处理 |
|---|---|
| 离线升级工具看不到 ISO | 正常，提取 ISO 内 `.kpb` 后选择 |
| 把 Update1 KPB 用到其他基线 | 不可混用，核对 2603 与架构 |
| 同代升级还要不要维护模式 | 本 OSTree 路线不需要 |
| 有 OSTree 旧部署是否无需备份 | 错，个人文件与配置仍需独立备份 |
| FAT32 复制大文件失败 | 单文件超过 4GB，改用 NTFS 路线 |
| `sfdisk` 报最后可用扇区冲突 | 给备份 GPT 留 33 扇区，重算 p2 |
| 行内 `attrs=` 不被接受 | 提交分区后用 `--part-attrs` 单独设置 |
| `sync` 很久不动 | 可能是慢速落盘，检查写入进度和 I/O 错误 |
| 文件管理器无法弹出 | 手动卸载所有挂载点并检查 |
| `already mounted` 就反复格式化目标盘 | 先看安装日志，本次根因是双挂载而非 mkfs 失败 |
| 所有相同报错都换 NTFS | 不一定，本文只覆盖日志中双脚本冲突的情况 |

## 八、推荐用法：交给 AI 协助实施

本文同时包含系统升级和整盘写操作，不适合让 AI 无人确认地一口气执行。更合理的方式是把完整文章交给正在操作制作机或目标电脑的 AI 编程助手，让它先区分路线、只读检查，再逐步实施。

可复制以下要求：

```text
请阅读这篇银河麒麟 V11 Update1 离线升级与安装 U 盘文章，先判断我需要的是
2603 同代 KPB 升级，还是全新安装。不要为了同代升级制作安装盘，也不要把两条
路线连续执行。

第一阶段只查询：记录 /etc/kylin-build、架构、OSTree 部署、挂载布局、ISO 文件、
磁盘空间、现有备份和全部块设备。不要挂载可写分区、不要 wipefs、不要 dd、
不要重启，也不要修改任何系统文件。

如果走 KPB 升级：核对基线和架构，先验证备份真实可用，列出 /usr 手工改动、
DKMS 和应用复验清单，再协助提取 KPB。升级、重启和回退前先等我确认。

如果走 NTFS U 盘：先让我拔掉无关移动盘，再根据 lsblk 的型号、容量和序列信息
确认目标设备。把 DEV 替换为真实 U 盘，逐个显示将执行的分区和写入命令。
wipefs、mkfs、dd 以及安装目标盘选择必须分别等待我明确确认。

制作后比较文件数量、大小和关键 SHA256，确认 sync 结束、所有挂载点卸载后才拔盘。
升级后验证版本、驱动、音频、蓝牙、输入法和常用应用。任何校验失败或设备识别
不一致都立即停止，不尝试换设备继续执行。
```

AI 可以帮助计算分区、比较哈希和整理验收，但无法替人承担选错磁盘的后果。设备确认、整盘清除、升级重启和安装目标选择必须保留人工检查。

## 写在最后

这次两个经验可以浓缩为两句话：

- **同代更新不要把 ISO 当升级包，真正需要的是其中的 KPB。**
- **全新安装遇到挂载冲突时先看日志，本次有效方案是 NTFS/UEFI:NTFS 介质，不是反复抹盘。**

一条路线依赖 OSTree 新部署，重点是备份和升级后复验；另一条路线依赖启动介质结构，重点是分区几何、完整校验和目标盘安全。分清边界，才能避免为了一个简单更新重装系统，也避免在安装故障中反复做无效的格式化。

---

> 原文首发于 Gitee：<https://gitee.com/digtip/notes/blob/main/blog/kirin/%E9%93%B6%E6%B2%B3%E9%BA%92%E9%BA%9F%20V11%20Update1%EF%BC%9AKPB%20%E7%A6%BB%E7%BA%BF%E5%8D%87%E7%BA%A7%E4%B8%8E%20NTFS%20%E5%AE%89%E8%A3%85%20U%20%E7%9B%98%E5%AE%9E%E6%88%98.md>
