---
title: "银河麒麟 V11 系统盘爆满治理：把 56G 的 var-opt 迁到数据盘（bind mount 全流程）"
date: 2026-11-24
tags: [银河麒麟, V11, OSTree, 磁盘空间, bind-mount, rsync, 系统运维]
description: 银河麒麟 V11 OSTree 系统盘占用 81% 告警，根因是 KARE 容器和办公软件在 /var/opt 堆了 56G。本文记录把 /var/opt 整体迁移到数据盘并 bind 挂载回原位的完整工程：停容器、rsync 校验、OSTree fstab 基线持久化、分批清理旧备份释放 53G，以及迁移后挂载竞态、输入法失效两个连锁坑的修复。
cover: "../../assets/kylin-varopt-56g-migration-cover.png"
status: published
original: https://gitee.com/digtip/notes/blob/main/blog/kirin/%E9%93%B6%E6%B2%B3%E9%BA%92%E9%BA%9F%20V11%20%E7%B3%BB%E7%BB%9F%E7%9B%98%E7%88%86%E6%BB%A1%E6%B2%BB%E7%90%86%EF%BC%9A%E6%8A%8A%2056G%20%E7%9A%84%20var-opt%20%E8%BF%81%E5%88%B0%E6%95%B0%E6%8D%AE%E7%9B%98%EF%BC%88bind%20mount%20%E5%85%A8%E6%B5%81%E7%A8%8B%EF%BC%89.md
---

# 银河麒麟 V11 系统盘爆满治理：把 56G 的 var-opt 迁到数据盘（bind mount 全流程）

系统盘红了是运维里最经典的告警之一。在普通 Linux 上，处理方式无非是删日志、清缓存、挪大目录；但在银河麒麟 V11 的 OSTree 不可变系统上，这件事多了两层特殊性：系统目录只读、`/etc/fstab` 的运行时修改重启可能丢失，再加上 KARE 容器和开明容器在 `/var/opt` 下堆了几十个 GB 的应用层，直接 `rm` 或 `mv` 都可能把容器系统搞挂。

本文记录一台飞腾 ARM64 麒麟 V11 机器的完整治理过程：系统盘占用从 **75G/81% 降到 22G/24%，净释放 53G**，三个月后回看依然稳定。全文包含迁移前的容器停机流程、rsync 校验方法、OSTree 特有的 fstab 基线持久化深坑、旧备份的分批安全清理，以及迁移后引发的两个连锁故障及其修复。

> [!warning] 涉及 root 操作与开机挂载，先读完全文再动手
> 本文操作需要 root，且修改开机自动挂载配置，任何一步出错都可能导致应用无法启动甚至进不了桌面。请务必：先在测试机或低峰期操作、保留旧副本直到验证完毕、严格按"先停容器再复制、先校验再切换、先挂好再删旧"的顺序执行。文中所有命令均来自真机实操，但磁盘分区和容器布局因机而异，执行前先用 `lsblk`、`findmnt`、`df -h` 核对自己的环境。

## 一、背景：系统盘为什么会红

先看告警时的磁盘状况：

```text
$ df -h /
文件系统        大小  已用  可用  已用% 挂载点
/dev/nvme0n1p3   98G   75G   19G   81% /
```

98G 的系统盘用掉 75G，而机器里明明还有一块 800G 数据盘只用了不到一半。用 `du` 逐层定位，空间大头非常集中：

| 目录 | 占用 | 内容 |
|---|---:|---|
| `/var/opt/kaiming/` | 26G | 开明容器共享运行时（layers 17G + repo 8.9G），所有开明应用共用 |
| `/var/opt/kare-applications/` | 23G | KARE 容器层：v10sp1 14G + base 4.5G + shadow 3.2G 等 |
| `/var/opt/kingsoft/` | 2.8G | WPS Office |
| `/var/opt/apps/` | 2.3G | /opt/apps 应用树（安全客户端、讯飞输入法、红莲花浏览器等） |
| `/var/opt/kare/` | 1.0G | KARE 容器运行时本身 |
| 其余独立软件 | ~1.7G | 量子密信、Cherry Studio、飞书、Draw.io、AionUi、TeleAgent 等 |
| **合计** | **约 56G** | 占系统盘已用空间的四分之三 |

结论很清楚：不是日志或缓存膨胀，删东西解决不了问题——这些都是正在使用的应用程序。正确方向是**把整个 `/var/opt` 迁到数据盘，再用 bind mount 接回原路径**，应用完全无感知。

## 二、环境信息与磁盘布局

| 项目 | 实测值 |
|---|---|
| 系统 | 银河麒麟桌面 V11 ARM64，飞腾平台，OSTree 不可变系统 |
| 系统盘 | nvme0n1p3，SYSROOT，98G，挂载 `/`（`/var` 在其上） |
| 数据盘 | nvme0n1p6，DATA，803G，挂载 `/data` |
| 其他分区 | p1 ESP、p4 KYLIN-BACKUP 恢复分区（勿动）、p5 swap |
| 出厂 bind | `/data/home → /home`、`/data/root → /root`（fstab 自带） |
| 关键软链 | `/opt -> var/opt`，应用经 `/opt` 访问的文件实际落在 `/var/opt` |
| 容器运行时 | 开明 `kaiming`、KARE 容器（crun），应用多为 Electron |

先理解两个出厂设计，迁移方案就是顺着它们做的：

1. **`/opt` 是指向 `var/opt` 的符号链接**，所以应用"装在 /opt"和"装在 /var/opt"是一回事，这给迁移留了天然的解耦点；
2. **数据盘已经通过 bind mount 承接了 `/home` 和 `/root`**，说明"数据盘建目录 + fstab bind 回系统路径"是这台机器验证过的官方模式，照做即可。

## 三、迁移前必须停干净：容器不是 pkill 能解决的

普通应用 `pkill` 进程就行，容器化应用不行——容器停了但 overlay 挂载还挂在 `/var/opt` 下面，此时复制或移动目录会得到不一致的数据，`umount` 原目录也会报 target busy。停机分三层：

```bash
# 1. 开明容器服务先停
systemctl stop org.kylin.kaiming.service

# 2. 开明容器实例：先列出 PID 再逐个 kill
kaiming ps | awk 'NR>1 && NF>=3 {print $3}' | while read pid; do
  kill "$pid" 2>/dev/null
done

# 3. KARE 的 crun 容器：pkill 应用名不够，必须走运行时
for c in $(crun list -q); do
  crun kill "$c" SIGTERM
done
sleep 4
# 宽限期后还活着的强杀
for c in $(crun list -q); do
  crun kill "$c" SIGKILL
done
sleep 2
for c in $(crun list -q); do
  crun delete -f "$c"
done
```

然后等待并清理残留的 overlay 挂载，**确认挂载计数归零才能继续**：

```bash
# 轮询等待容器挂载释放（最多 15 秒）
for i in $(seq 1 15); do
  n=$(mount | grep -cE '/var/opt/(kare-applications|kaiming)/' || true)
  [ "$n" -eq 0 ] && break
  sleep 1
done

# 仍有空闲残留挂载则惰性卸载
for m in $(awk '{print $2}' /proc/mounts \
           | grep -E '^/var/opt/(kare-applications|kaiming)/' | sort -r); do
  umount "$m" 2>/dev/null || umount -l "$m" 2>/dev/null
done

# 硬性门禁：不为零就中止，此时尚未改动任何数据
n=$(mount | grep -cE '/var/opt/(kare-applications|kaiming)/' || true)
[ "$n" -ne 0 ] && { echo "仍有容器挂载，中止"; exit 1; }
```

> [!important] 中止门禁比成功路径更重要
> 迁移脚本里所有危险步骤前都要有"不满足条件就 exit 1"的检查。上面这道门保证：只要还有容器引用旧目录，后续的 `mv` 和 bind 切换就不会执行，数据原封不动。

## 四、完整迁移流程（六步）

### 第 1 步：rsync 全量复制到数据盘

目标目录放在数据盘的 `/data/sysdata/var-opt`。参数选择有讲究：

```bash
mkdir -p /data/sysdata
rsync -aHAX --numeric-ids /var/opt/ /data/sysdata/var-opt/
```

- `-a` 归档模式保留权限、属主、时间戳、软链；
- `-H` 保留硬链接（容器层里大量硬链接，漏了会翻倍占空间）；
- `-A` `-X` 保留 ACL 和扩展属性，安全软件和容器元数据依赖它们；
- `--numeric-ids` 按 UID/GID 数字而非用户名映射，避免两套 passwd 不一致导致属主错乱；
- 源路径结尾的斜杠 `/var/opt/` 表示复制目录**内容**而非目录本身。

实测中 rsync 报过一类 `filename overflows max-path len` 错误，来自 `kare-applications/shadow/merge/opt/shadow/merge/...` 这种超深嵌套目录。排查确认那是历史挂载递归事故留下的垃圾目录，正常状态下无法访问、容器运行时又被挂载遮盖，**不复制没有任何影响**，不用为它中断迁移。

### 第 2 步：dry-run 校验复制完整性

切换前先做一次"只比对不写入"的校验，差异输出应为空：

```bash
rsync -aHAXn --numeric-ids --delete /var/opt/ /data/sysdata/var-opt/ | head -30
du -sh /var/opt /data/sysdata/var-opt   # 两边大小应基本一致
```

`-n` 是 dry-run，`--delete` 让它同时报告目标侧多余文件。这一步是回滚信心的来源：确认数据盘副本与源逐字节对齐后再动原目录。

### 第 3 步：改名留备份，建空目录并 bind 挂载

不删除原目录，而是改名成 `.old` 作为回滚保险：

```bash
mv /var/opt /var/opt.old
mkdir /var/opt
mount --bind /data/sysdata/var-opt /var/opt
findmnt /var/opt    # 应显示 /dev/nvme0n1p6[/sysdata/var-opt] ext4 rw
```

此时应用访问 `/var/opt`（以及经 `/opt` 软链访问）看到的已经是数据盘副本，而系统盘上的完整旧数据原地保留在 `/var/opt.old`。

### 第 4 步：写入 fstab —— OSTree 上最大的坑

普通系统往 `/etc/fstab` 追加一行就完事，OSTree 上这样做**重启后会丢**。

实测机理：麒麟 V11 的 `/etc` 是一个 overlay（`findmnt /etc` 可见 lowerdir 是 `/root/etc` 加 ostree pkgs 层，upperdir 在 `/sysroot/ostree/pkgs/ovl-*/etc-ovl/etc-upper`）。OSTree 在部署更新或某些重启场景下会用只读基线 **`/usr/etc/fstab`** 重新合成运行时的 `/etc/fstab`，运行时手工追加的行随之消失。迁移完成后第一次重启，bind 挂载没有自动建立，讯飞输入法立刻打不出汉字——根因就是 fstab 行丢了。

正确做法是**两处都写，基线为准**：

```bash
# 运行时 fstab：当前立即生效（先备份）
cp -a /etc/fstab "/etc/fstab.bak-varopt-$(date +%Y%m%d%H%M)"
cat >> /etc/fstab <<'EOF'

# /var/opt relocated to data disk (bind mount)
/data/sysdata/var-opt  /var/opt  none  defaults,bind  0 0
EOF
```

基线 `/usr/etc/fstab` 在只读分区上，需要进入维护模式（`/usr` 对 root 可写）后追加同一行，出厂的 `/data/home`、`/data/root` 两行也在这个文件里，放一起即可。写完重启验证：

```bash
# 重启后检查，两行 fstab 内容应一致，bind 自动建立
grep bind /etc/fstab /usr/etc/fstab
findmnt /var/opt
```

> [!note] 普通 /etc 文件与 fstab 的持久化差别
> 不是所有写 `/etc` 的东西都会丢。systemd 单元、普通配置文件写在 overlay upper 层可以扛过重启和小版本更新；唯独 fstab 这类 OSTree 部署时要从基线重新合成的文件，定制必须落到 `/usr/etc` 基线。判断准则：凡是开机早期、挂载建立之前就要读到的配置，都要检查它是否由基线生成。

### 第 5 步：恢复容器服务并验证应用

```bash
systemctl start org.kylin.kaiming.service
systemctl is-active org.kylin.kaiming.service
```

然后逐个打开实际应用验证：输入法能否切出汉字、WPS 能否打开历史文档、微信/会议软件能否登录、KARE 容器应用菜单入口是否正常。注意应用的**用户数据在 `/home`（数据盘另一个 bind）里，不在 `/var/opt`**，迁移的只是程序和容器层，登录态不受影响。

### 第 6 步：重启做最终确认

主动重启一次，确认开机后 bind 自动挂载、容器服务自启、全部应用正常。这一步通过后，迁移本身才算完成，但先别急着删 `.old`——下一节的清理要分批做。

## 五、旧备份清理：三道安全检查与分批释放

55G 的 `/var/opt.old` 躺在系统盘上，告警并没有真正解除。但删除不可逆，必须建立"确认 live 副本健康 → 确认旧副本无引用 → 确认用户实际用过迁移后的软件"的三道防线，分批删除、每批观察。

### 删除前的三道硬性检查

```bash
# 1. live 的 /var/opt 必须确实 bind 在数据盘上（防止误删 live）
findmnt -n /var/opt | grep -q nvme0n1p6 || { echo "未挂数据盘，中止"; exit 1; }

# 2. .old 下不能有任何挂载点（有挂载说明还有东西在用它）
[ -z "$(findmnt -R -n /var/opt.old)" ] || { echo ".old 下有挂载，中止"; exit 1; }

# 3. fstab 基线必须有持久化行（防止下次重启挂载丢失后无备份可救）
grep -q 'sysdata/var-opt' /usr/etc/fstab || { echo "基线缺失，中止"; exit 1; }
```

脚本里再加一道人工确认：打印待删清单和预计释放量，要求输入 `yes` 才执行。另外扫描 `/proc/*/cwd` 确认没有进程工作目录落在 `.old` 下。

### 为什么要分批而不是一次删光

`.old` 是迁移时刻的静态快照，之后新安装的软件只存在于 live 副本。分批策略让每个软件都在 live 上实际运行验证过后，才删除它对应的旧副本：

| 批次 | 内容 | 释放 | 前置确认 |
|---|---|---:|---|
| 批 1 | WPS、Cherry Studio、腾讯会议、微信 native 库 | 3G | 四款软件迁移后均实际用过 |
| 批 4a | kaiming 开明运行时 | 24G | 记事本/相机/音乐/扫描等多个开明应用实测正常 |
| 批 4b | 整个 `.old`（KARE 容器层、apps 树、其余独立软件） | 26G | 飞书、密文客户端、红莲花、量子密信、AionUi 等全部确认用过 |

每批之间正常使用几天，`df -h /` 看系统盘稳步下降，出问题随时可以从 `.old` 里捞回单个目录。最终一批删除后：

```text
系统盘：75G/81%（可用 19G）→ 22G/24%（可用 72G），累计释放 53G
```

### 一个容易混淆的安全事实

`/var/opt` 是独立挂载点，`/var/opt.old` 是系统盘上的普通目录，两者在挂载命名空间里完全隔离。对 `.old` 执行 `rm -rf` 不会触及数据盘上的 live 副本——但这正是第一道检查（确认 live 确实挂着）不可或缺的原因：万一 bind 丢失，`/var/opt` 会露出底层空目录，而 `.old` 就成了唯一副本。

## 六、迁移引发的两个连锁故障

### 故障 1：KARE 容器的 root 服务开机不自启

迁移后出现一个隐蔽问题：某零信任客户端的后台 daemon 开机后完全没被拉起（journal 里连 Starting 记录都没有），手动 `systemctl start` 却一切正常。

根因是**挂载时序竞态**：

1. 该服务的单元文件在 `/opt/kare/...` 之下，即数据盘 bind 挂载之后才可见；
2. systemd 在开机极早阶段构建启动事务时，`/var/opt` 的 bind 尚未挂好，底层根分区的空占位目录里没有单元文件；
3. 单元悬空被跳过，systemd 不会在挂载完成后重试。

修复：在开机即就绪的根分区 `/etc/systemd/system/` 放一份单元副本遮蔽原单元，并显式声明挂载排序：

```ini
[Unit]
After=var-opt.mount data.mount local-fs.target
Wants=var-opt.mount
RequiresMountsFor=/opt/kare/lib/systemd/system/<svc>.service.bin
```

再把 wants 软链指向根分区副本。凡是单元文件位于 bind 挂载路径之下的服务，都要按这个模式检查一遍，`systemd-analyze verify` 可离线校验语法。

### 故障 2：讯飞输入法打不出汉字

重启后 fcitx5 切不出讯飞输入法。排查链路：

```text
fcitx5 引擎软链：/usr/lib/aarch64-linux-gnu/fcitx5/iflyime.so
  → /opt/apps/com.iflytek.iflyime/lib/iflyime.so
    → /opt 是 /var/opt 的软链
      → bind 丢失时目标不存在，引擎加载失败
```

也就是第四节 fstab 基线问题的外在表现。补写 `/usr/etc/fstab` 基线并 `mount --bind` 恢复后立即痊愈。这个案例说明：**排查"某软件突然找不到文件"类故障时，先 `findmnt` 看它依赖的路径是不是挂载点、挂载还在不在**，往往比查软件配置快得多。

## 七、迁移三个月后的长期效果

治理完成约三个月后回看磁盘数据：

```text
$ df -h / /data
文件系统        大小  已用  可用  已用% 挂载点
/dev/nvme0n1p3   98G   29G   65G   31% /
/dev/nvme0n1p6  803G  486G  277G   64% /data
```

系统盘占用从 81% 长期稳定在 31%（期间正常的系统更新让它从 22G 缓涨到 29G，属于健康范围），新增的容器应用全部自然落到数据盘，再没出现过空间告警。方案本身零维护成本：bind 挂载由 fstab 基线保证，应用经 `/opt` 软链透明访问，日常使用完全无感。

## 八、命令清单（按阶段汇总）

```bash
# —— 阶段 0：勘察 ——
lsblk && df -h / /data
findmnt /var/opt /etc
du -sh /var/opt/* | sort -rh | head

# —— 阶段 1：停容器、释放挂载 ——
systemctl stop org.kylin.kaiming.service
kaiming ps | awk 'NR>1{print $3}' | xargs -r kill
for c in $(crun list -q); do crun kill "$c" SIGTERM; done
sleep 4
for c in $(crun list -q); do crun kill "$c" SIGKILL; done
mount | grep -cE '/var/opt/(kare-applications|kaiming)/'   # 必须为 0

# —— 阶段 2：复制与校验 ——
rsync -aHAX --numeric-ids /var/opt/ /data/sysdata/var-opt/
rsync -aHAXn --numeric-ids --delete /var/opt/ /data/sysdata/var-opt/

# —— 阶段 3：切换 bind ——
mv /var/opt /var/opt.old
mkdir /var/opt
mount --bind /data/sysdata/var-opt /var/opt
findmnt /var/opt

# —— 阶段 4：fstab 双写（基线需维护模式）——
cp -a /etc/fstab /etc/fstab.bak
echo '/data/sysdata/var-opt /var/opt none defaults,bind 0 0' >> /etc/fstab
# 维护模式下向 /usr/etc/fstab 追加同一行

# —— 阶段 5：清理前三道检查 ——
findmnt -n /var/opt | grep nvme0n1p6
findmnt -R -n /var/opt.old
grep sysdata/var-opt /usr/etc/fstab
# 全部通过后分批 rm -rf /var/opt.old/<已验证目录>
```

## 九、坑点与排错

### 1. 先判故障类型：空间问题还是只读问题

`df` 看到使用率高是容量问题，迁移或清理；`Read-only file system` 是 OSTree 只读限制，要用 bind 挂载或用户级覆盖解决。两类问题的手法不能混用。

### 2. 容器挂载不释放，一切后续操作都免谈

`pkill` 应用进程不等于容器停止。认准 `kaiming ps` 和 `crun list` 两个运行时接口，挂载计数归零是硬性前置条件，宁可多等几个轮询周期也不要带挂载复制。

### 3. rsync 参数一个都不能省

漏 `-H` 硬链接翻倍、漏 `--numeric-ids` 属主漂移、漏 `-X` 安全软件扩展属性丢失，都是当时不报、运行时才爆的问题。

### 4. fstab 只写 /etc 等于没写

OSTree 的 fstab 由 `/usr/etc` 基线合成，重启丢失会引发连锁故障（本机以输入法失效的形式暴露）。涉及开机挂载的配置，基线和运行时两处都要写，并重启验证。

### 5. 不要在 agent/远程会话里等图形提权

实测 agent 会话中 `pkexec` 会报 `No session for cookie` 弹不出认证窗。需要 root 的脚本让用户在自己的终端执行 `sudo bash <脚本>`（生物识别/密码认证），脚本内部做好检查和确认提示。

### 6. 回滚方法要提前写进脚本头部

迁移脚本开头就应注明回滚路径：`umount /var/opt && rmdir /var/opt && mv /var/opt.old /var/opt`（若已重启还要先删掉 fstab 里的 bind 行）。有旧副本在，回滚就是几条命令；旧副本一旦删除，程序层损坏只能重装软件。

## 十、把文章交给 AI 执行（提示词模板）

> [!important]
> 磁盘迁移属于高风险操作，AI 应只负责勘察、生成脚本和检查清单，实际 root 执行由用户在自己的终端完成。

```text
请阅读《银河麒麟 V11 系统盘爆满治理：把 56G 的 var-opt 迁到数据盘》，
协助我把系统盘上的大目录迁移到数据盘。

要求：
1. 先只读勘察：lsblk、df -h、findmnt 输出分区与挂载现状，du 定位占用
   大头，确认数据盘余量充足、目标目录不存在冲突，不要立即修改。
2. 对照文章确认我的环境是否同类（OSTree、/opt→var/opt 软链、kaiming/
   crun 容器）；布局不同先报告差异，不要硬套路径。
3. 生成迁移脚本而不是直接执行：包含容器停机、挂载归零门禁、
   rsync -aHAX --numeric-ids、dry-run 校验、mv 留 .old、bind 切换、
   fstab 双写提示，脚本头部写明回滚命令。
4. 明确提示 fstab 基线 /usr/etc/fstab 需要维护模式写入，只改
   /etc/fstab 重启会丢；给我重启后的验证命令清单。
5. 清理 .old 必须生成独立脚本，带三道安全检查（live 挂数据盘、
   .old 无挂载、fstab 基线存在）和 yes 人工确认，按软件分批，
   每批之间由我实际使用验证后再继续。
6. 所有 root 操作我在自己终端 sudo 执行，你不要调用 pkexec，
   也不要一次性删除整个 .old。
7. 任何检查不通过立即中止并保留现场，不尝试强制卸载或强制删除。
```

## 写在最后

这次治理的核心思路其实只有一句话：**把数据从"它不该在的地方"搬到"系统设计上就允许它在的地方"，再用挂载把路径接回去。** 麒麟 V11 的出厂布局已经暗示了答案——`/home`、`/root` 本就是数据盘 bind 过来的，`/opt` 本就是 `/var/opt` 的软链，迁移只是把同样的模式应用到容器应用层。

真正值得记住的是工程纪律而非具体命令：迁移前让挂载计数归零、复制后做 dry-run 校验、切换时保留完整旧副本、持久化写到 OSTree 基线、删除前三道检查加分批验证。磁盘空间问题从来不是最难的技术题，但每一步都带着不可逆性，慢一点、分批做、留好退路，53G 就能安全地回来。

---

> 原文首发于 Gitee：<https://gitee.com/digtip/notes/blob/main/blog/kirin/%E9%93%B6%E6%B2%B3%E9%BA%92%E9%BA%9F%20V11%20%E7%B3%BB%E7%BB%9F%E7%9B%98%E7%88%86%E6%BB%A1%E6%B2%BB%E7%90%86%EF%BC%9A%E6%8A%8A%2056G%20%E7%9A%84%20var-opt%20%E8%BF%81%E5%88%B0%E6%95%B0%E6%8D%AE%E7%9B%98%EF%BC%88bind%20mount%20%E5%85%A8%E6%B5%81%E7%A8%8B%EF%BC%89.md>
