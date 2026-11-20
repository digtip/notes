---
title: DJI Mic Mini 在银河麒麟上反复断连、抢输出？我的排障过程与双麦切换脚本
date: 2026-11-19
tags: [DJI Mic Mini, 银河麒麟, Linux, 蓝牙, PulseAudio]
description: 记录 DJI Mic Mini 在银河麒麟 ARM64 上约 15 秒断连、连接后扬声器无声、重启后蓝牙不上电、双麦切换和语音识别中断等问题，并给出排查命令、修复方法与脚本模板。
status: published
original: https://gitee.com/digtip/notes/blob/main/blog/kirin/DJI%20Mic%20Mini%20%E5%9C%A8%E9%93%B6%E6%B2%B3%E9%BA%92%E9%BA%9F%E4%B8%8A%E5%8F%8D%E5%A4%8D%E6%96%AD%E8%BF%9E%E3%80%81%E6%8A%A2%E8%BE%93%E5%87%BA%EF%BC%9F%E6%88%91%E7%9A%84%E6%8E%92%E9%9A%9C%E8%BF%87%E7%A8%8B%E4%B8%8E%E5%8F%8C%E9%BA%A6%E5%88%87%E6%8D%A2%E8%84%9A%E6%9C%AC.md
---

# DJI Mic Mini 在银河麒麟上反复断连、抢输出？我的排障过程与双麦切换脚本

我使用 DJI Mic Mini 的目的不是拍摄视频，而是在银河麒麟笔记本上进行语音听写：除了日常文字录入，更主要的场景是 **Vibe Coding**——用语音向 AI 编程助手描述需求、补充上下文、解释报错、口述修改意见，以及在不方便长时间敲键盘时继续推进开发任务。

相比输入一两句普通文字，Vibe Coding 往往需要连续讲述较长的需求，中间还会夹杂英文函数名、文件名、路径和技术术语。因此，麦克风能否稳定连接、两台设备能否在电量不足时快速轮换、语音识别中断后能否恢复，都会直接影响使用体验。

实际接入后，遇到的问题比预想多：麦克风连接约 15 秒就断、一连蓝牙扬声器就没声、重启后所有蓝牙设备都连不上、两台麦克风切换时音频服务异常，以及语音只识别出一两个字。

这些问题表面上都像是“蓝牙不稳定”，实际却分属桌面蓝牙服务、PulseAudio 路由、蓝牙适配器上电策略、HFP 通话通道和语音应用桥接几个层面。只重连设备或重启电脑，很难真正解决。

这篇文章把排障过程和最终使用的脚本整理在一起。脚本不能直接照搬到所有机器，但排查顺序和修改位置可以复用。

> 实测环境：银河麒麟 V11 ARM64、飞腾 FTG340 笔记本、BlueZ、原生 PulseAudio 16.1、fcitx5-vinput。
> 记录时间：2026 年 9 月。本文是个人实测，不代表所有银河麒麟版本都会出现同样问题。
> 设备说明：麦克风为 DJI Mic Mini，**当时未记录发射器固件版本和 DJI Mic Mini 套装的具体硬件批次**。我无法据此判断后续固件、其他银河麒麟版本或 UKUI 更新是否已修复断连问题。

> [!warning] 复现前必读：不要直接照抄系统级命令
> 本文脚本中的 MAC、声卡名、输入源和服务名都必须先换成你自己的值。尤其不要在没有检查日志、没有备份配置的情况下停用 `ukui-bluetooth.service`。如果新版系统或新固件已经修复问题，就不需要这些绕过措施。优先使用系统图形界面和官方驱动；以下方案只适用于已经复现相同故障、理解副作用并愿意自行维护脚本的用户。

## 一、推荐用法：把文章交给 AI，而不是逐条照抄

> [!important] 当前最优使用方式
> **把这篇文章完整交给正在操作银河麒麟电脑的 AI 编程助手或终端智能体，让 AI 先阅读故障背景，再结合本机信息完成适配。不要把它当作需要逐条照抄的命令清单。**

它更像一份包含根因、限制、脚本和回滚方法的**排障知识包**。AI 可以利用上下文判断当前问题对应哪一层，避免用户在一堆命令中自行挑选，也避免把其他电脑的声卡名和服务名直接复制过来。

可以把下面这段要求连同文章一起交给 AI：

```text
请阅读这篇 DJI Mic Mini 排障文章，并在我当前电脑上处理类似问题。

先只执行查询命令，记录系统版本、DJI 固件信息（如果能获取）、
蓝牙 Profile、MAC 地址、PulseAudio 输入输出和相关服务状态。
不要立即停用服务或修改配置。

将我的环境与文章实测环境对比，判断哪些结论适用、哪些不适用。
然后给出修改方案和需要替换的脚本参数。涉及 sudo、停用 UKUI
蓝牙服务、重启 PulseAudio 或重启语音桥接时，先解释影响和回滚方法，
等我确认后再执行。完成后验证麦克风、扬声器、重启后的蓝牙状态，
并保存一份适配我本机的脚本和配置说明。
```

这样做有几个好处：

- AI 会把占位 MAC、声卡名和输入源换成本机真实值；
- 没有 sidecar 或 vinput 时，会删除无关步骤；
- 能先检查新版系统是否已经修复，避免继续沿用旧绕过方案；
- 能把查询、修改、验证和回滚串成完整流程；
- 出现新报错时，可以结合当前日志调整，而不是机械执行全文。

即便交给 AI，也不建议一开始开放无人确认的高权限执行。尤其是 `sudo systemctl disable`、删除配置和重启音频服务，仍应保留人工审核。

## 二、开始前：先记录自己的设备信息

建议先执行以下命令，把输出保存在自己的排障笔记中：

```bash
# 系统、内核与处理器架构
hostnamectl
uname -a

# 已配对蓝牙设备及 MAC 地址
bluetoothctl devices

# 蓝牙适配器是否上电
bluetoothctl show

# PulseAudio 版本与当前默认输入、输出
pactl info
pactl get-default-source
pactl get-default-sink

# 声卡、输入源、输出和播放流的真实名称
pactl list cards
pactl list short sources
pactl list short sinks
pactl list short sink-inputs

# 两个相关服务的状态
systemctl status bluetooth.service --no-pager
systemctl status ukui-bluetooth.service --no-pager
```

DJI 固件版本请通过当时使用的 DJI 官方应用或设备管理工具查询并补充。不要用其他用户、其他批次的固件表现推断自己的设备。

### 本文脚本中需要替换的参数

| 占位内容 | 含义 | 从哪里取得 |
|---|---|---|
| `AA:BB:CC:DD:EE:01` | 第一台 DJI 的 MAC | `bluetoothctl devices` |
| `AA:BB:CC:DD:EE:02` | 第二台 DJI 的 MAC | `bluetoothctl devices` |
| `noiseReduceSource` | 本机内置或降噪输入源 | `pactl list short sources` 第二列 |
| `alsa_output.platform-PHYT0006_00.stereo-fallback` | 本机飞腾板载输出，**其他电脑通常不同** | `pactl list short sinks` 第二列 |
| `pipewire-sidecar.service` | 我的语音桥接用户服务 | 没安装该架构就删除相关命令 |
| `vinput-daemon.service` | 我的本地识别用户服务 | 没使用 vinput 就删除相关命令 |

如果只有一台麦克风，应删除第二台相关配置和循环，不要为了凑脚本结构虚构第二台设备。若电脑没有名为 `noiseReduceSource` 的降噪源，就把 `BUILTIN_SOURCE` 改成自己的内置输入，例如实际查询到的 `alsa_input...`，不要照抄。

## 三、先明确：DJI Mic Mini 在这台电脑上走的是 HFP

在这套环境中，DJI Mic Mini 作为蓝牙通话麦克风使用，PulseAudio 对应：

- 声卡 Profile：`handsfree_head_unit`；
- 编码：mSBC；
- 音频规格：16 kHz、单声道；
- 不出现可播放音乐的 A2DP Profile。

16 kHz 单声道不适合追求高保真音乐，但对语音识别足够，因为本地语音识别模型通常也会把输入转换为单声道、16 kHz。

这里有一个关键点：**HFP 是双向音频协议。**即使麦克风本身没有扬声器，BlueZ 和 PulseAudio 仍可能同时创建 `bluez_source` 与 `bluez_sink`。系统把它当成耳麦，而不是一个“纯输入设备”。后面的“扬声器被抢输出”正与此有关。

### 为什么选择 HFP，而不是强行切换 A2DP

A2DP 主要用于高质量单向音频播放，典型方向是电脑向蓝牙耳机或音箱发送声音；HFP/HSP 面向通话，支持双向语音，电脑才能把蓝牙设备当作通话麦克风使用。

我的目标是语音听写，需要麦克风上行采集，因此选择 `handsfree_head_unit`，不是为了听音乐，也不是主动把设备“降级”。在本机当前 BlueZ、固件和系统组合下，DJI Mic Mini 暴露给系统的可用 Profile 只有 `off` 和 `handsfree_head_unit`，没有可直接切换的 A2DP 采集模式。

这意味着：

1. **不能通过 `pactl set-card-profile ... a2dp_sink` 把它变成高质量麦克风**。A2DP Sink 通常是电脑向外播放音频的方向，而且本机设备未暴露该 Profile，强行执行只会报 Profile 不可用。
2. **音质受通话链路限制**。本机实测为 mSBC、16 kHz、单声道，适合语音识别，不应当作高保真录音方案。
3. **HFP 可能同时创建输入和输出节点**。即使只使用输入，系统也可能创建蓝牙输出，因此需要单独处理默认扬声器路由。
4. **两台同时连接不等于两路同时录音**。本机这块蓝牙适配器只能维持一路 HFP/SCO 通话音频，所以脚本让一台保持 HFP、另一台设为 `off`。这个限制是本次实测结果，不应推广为所有适配器和系统的统一结论。
5. **接收器连接方式可能不同**。本文只讨论这台 DJI Mic Mini 通过电脑蓝牙直接连接的方式，不涵盖 USB 接收器、USB 声卡模式、3.5 mm 连接或手机应用中的行为。

可以用下面的命令核实自己的设备到底支持哪些 Profile：

```bash
pactl list cards | sed -n '/bluez_card/,/^\s*$/p'
```

重点看设备块中的 `handsfree_head_unit`、`a2dp_sink`、`off` 及 `active profile`。如果输出与本文不同，应以自己的查询结果为准。

可以用以下命令查看实际 Profile 和音频节点：

```bash
pactl list cards
pactl list short sources
pactl list short sinks
```

## 四、问题一：连接约 15 秒后自动断开

### 现象

DJI Mic Mini 能配对、能连接，也能短暂看到麦克风输入，但大约 15 秒后连接自动消失。重新连接后，故障重复出现。

### 根因

本机的 `ukui-bluetooth.service` 会在音频设备连接后尝试重连 A2DP。DJI Mic Mini 在当前环境中没有 A2DP，连续几次返回 `br-connection-profile-unavailable` 后，桌面服务主动断开了设备。

因此，问题不在麦克风电量，也不是 PulseAudio 或 PipeWire 本身导致。

### 处理方法

我最终停用了桌面蓝牙服务：

```bash
sudo systemctl disable --now ukui-bluetooth.service
```

底层蓝牙协议栈由另一个服务提供：

```bash
systemctl status bluetooth.service
```

停用 UKUI 服务后，配对、连接和 HFP 输入仍然可用，麦克风不再每 15 秒被踢断。

### 代价与回滚

代价是控制中心的蓝牙面板、托盘和部分飞行模式联动可能不可用。因此，这不是所有人都应直接执行的通用命令，应先确认日志中确实存在相同的 A2DP 重连行为。

恢复桌面服务：

```bash
sudo systemctl enable --now ukui-bluetooth.service
```

## 五、问题二：麦克风一连接，扬声器反而没声

### 现象

连接 DJI Mic Mini 后，音乐播放器仍在播放，进度也在前进，但笔记本扬声器没有声音。

### 原因

PulseAudio 的 `module-switch-on-connect` 会在新设备出现时自动切换默认输出。HFP 建立后产生的 `bluez_sink` 被当成新输出设备，正在播放的音频流也可能被移过去。

这与“板载声卡损坏”是两回事。先看播放流去了哪里：

```bash
pactl get-default-sink
pactl list short sinks
pactl list short sink-inputs
```

如果播放流落在 `bluez_sink`，就是路由被切换。

### 临时恢复

将 `<板载输出>` 替换为 `pactl list short sinks` 中真实的内置扬声器名称：

```bash
pactl set-default-sink <板载输出>
```

已经存在的播放流还需要单独移动：

```bash
pactl move-sink-input <播放流索引> <板载输出索引>
```

### 持久处理

我不希望任何蓝牙耳麦连接后都自动抢输出，因此在用户配置中停用了这个模块：

`~/.config/pulse/default.pa`：

```pactl
.include /etc/pulse/default.pa
unload-module module-switch-on-connect
```

运行时立即卸载：

```bash
pactl unload-module module-switch-on-connect
```

此后蓝牙麦克风仍可作为输入使用，但默认扬声器需要由用户明确选择。真要用蓝牙耳机听音乐时，在音量设置里手动切换即可。

回滚时删除上述用户配置中的 `unload-module` 行，再重启用户级 PulseAudio：

```bash
systemctl --user restart pulseaudio
```

## 六、问题三：重启后蓝牙全部连不上

### 现象

重启后，DJI Mic Mini、蓝牙键盘和遥控器都无法连接。最初看起来像是设备缺电，实际检查发现是主机蓝牙适配器没有上电：

```bash
bluetoothctl show | grep Powered
```

输出：

```text
Powered: no
```

### 根因

本机 `/etc/bluetooth/main.conf` 中设置了 `AutoEnable=false`。过去由 UKUI 蓝牙服务在登录后上电，但该服务为了解决 DJI 断连问题已被停用，于是重启后没有人执行 `power on`。

### 用户级解决脚本

不修改系统区，新增用户服务：

`~/.config/systemd/user/bluetooth-poweron.service`：

```ini
[Unit]
Description=Power on Bluetooth adapter after login
After=default.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/bash -c 'for i in $(seq 1 30); do bluetoothctl show >/dev/null 2>&1 && break; sleep 1; done; bluetoothctl power on'

[Install]
WantedBy=default.target
```

启用：

```bash
systemctl --user daemon-reload
systemctl --user enable --now bluetooth-poweron.service
```

验证：

```bash
bluetoothctl show | grep Powered
systemctl --user status bluetooth-poweron.service
```

如果输出 `Powered: yes`，已配对设备通常可以自动回连，不需要重新配对。

## 七、问题四：两台 DJI Mic Mini 如何轮换

我的两台麦克风轮换使用，从不同时占用通话通道。在这套蓝牙适配器上，同一时刻只保留一路 HFP/SCO，切换顺序很重要：

1. 将录音流和默认输入先切回内置麦克风；
2. 将另一台 DJI 的 Profile 设为 `off`；
3. 连接目标设备并启用 `handsfree_head_unit`；
4. 等待蓝牙输入节点出现，再额外等待约 2 秒；
5. 将默认输入设为目标 `bluez_source`；
6. 如果使用语音应用桥接服务，最后再重启桥接与识别进程；
7. 检查扬声器输出仍落在板载声卡。

不要一边切换 HFP Profile，一边重启音频桥接。实测这种操作可能让 PulseAudio 进入 `Connection refused` 状态。

## 八、双麦切换脚本模板

下面脚本根据我的实际脚本脱敏、改编。使用前必须替换：

- `MIC1_MAC`、`MIC2_MAC`：自己的设备 MAC；
- `BUILTIN_SOURCE`：内置或默认降噪输入；
- `BOARD_SINK`：自己的板载扬声器；
- 如果没有 PipeWire sidecar 和 vinput，删除脚本末尾两个重启命令。

查询名称：

```bash
bluetoothctl devices
pactl list short sources
pactl list short sinks
```

保存为 `dji-mic-use.sh`：

```bash
#!/bin/bash
# 用法：dji-mic-use.sh 1|2
set -u
export PATH=/usr/bin:/bin

BUILTIN_SOURCE="noiseReduceSource"
BOARD_SINK="alsa_output.platform-PHYT0006_00.stereo-fallback"
MIC1_MAC="AA:BB:CC:DD:EE:01"
MIC2_MAC="AA:BB:CC:DD:EE:02"

notify() {
  command -v notify-send >/dev/null && notify-send "DJI Mic" "$1"
}

pin_output() {
  pactl set-default-sink "$BOARD_SINK" 2>/dev/null
  local sink_id
  sink_id=$(LANG=C pactl list short sinks 2>/dev/null |
    awk -v n="$BOARD_SINK" '$2==n {print $1; exit}')
  [ -n "$sink_id" ] || return 0

  LANG=C pactl list short sink-inputs 2>/dev/null |
    while read -r input_id current_sink _; do
      [ "$current_sink" != "$sink_id" ] &&
        pactl move-sink-input "$input_id" "$sink_id" 2>/dev/null
    done
}

case "${1:-}" in
  1) MAC="$MIC1_MAC"; TAG="1 号" ;;
  2) MAC="$MIC2_MAC"; TAG="2 号" ;;
  *) echo "用法：$0 1|2"; exit 2 ;;
esac

MAC_ID=$(echo "$MAC" | tr ':' '_')
CARD="bluez_card.${MAC_ID}"
SOURCE="bluez_source.${MAC_ID}.handsfree_head_unit"

# 1. 释放当前输入，避免切换时仍占用蓝牙通话通道
pactl set-default-source "$BUILTIN_SOURCE" 2>/dev/null

# 2. 关闭另一台设备的 HFP
for OTHER_MAC in "$MIC1_MAC" "$MIC2_MAC"; do
  OTHER_ID=$(echo "$OTHER_MAC" | tr ':' '_')
  OTHER_CARD="bluez_card.${OTHER_ID}"
  [ "$OTHER_CARD" != "$CARD" ] &&
    pactl set-card-profile "$OTHER_CARD" off 2>/dev/null
done

# 3. 连接目标设备并启用 HFP
bluetoothctl connect "$MAC" >/dev/null 2>&1
pactl set-card-profile "$CARD" handsfree_head_unit 2>/dev/null

# 4. 等待输入节点出现
READY=""
for _ in $(seq 1 40); do
  if LANG=C pactl list short sources 2>/dev/null | grep -q "$SOURCE"; then
    READY=1
    break
  fi
  sleep 0.5
done

if [ -z "$READY" ]; then
  notify "$TAG 连接失败"
  exit 1
fi

sleep 2
pin_output
pactl set-default-source "$SOURCE"

# 5. 仅在使用相应语音桥接时保留以下两行
systemctl --user restart pipewire-sidecar.service
sleep 8
systemctl --user restart vinput-daemon.service

pin_output
notify "已切换到麦克风 $TAG"
```

增加执行权限：

```bash
chmod +x dji-mic-use.sh
./dji-mic-use.sh 1
```

脚本中的 MAC 只是示例，公开分享时也不要直接暴露自己的设备标识。

## 九、断开脚本

保存为 `dji-mic-off.sh`：

```bash
#!/bin/bash
export PATH=/usr/bin:/bin

BUILTIN_SOURCE="noiseReduceSource"
BOARD_SINK="alsa_output.platform-PHYT0006_00.stereo-fallback"
MIC1_MAC="AA:BB:CC:DD:EE:01"
MIC2_MAC="AA:BB:CC:DD:EE:02"

for MAC in "$MIC1_MAC" "$MIC2_MAC"; do
  MAC_ID=$(echo "$MAC" | tr ':' '_')
  pactl set-card-profile "bluez_card.${MAC_ID}" off 2>/dev/null
  bluetoothctl disconnect "$MAC" >/dev/null 2>&1
done

pactl set-default-source "$BUILTIN_SOURCE" 2>/dev/null
pactl set-default-sink "$BOARD_SINK" 2>/dev/null

command -v notify-send >/dev/null &&
  notify-send "DJI Mic" "已断开，切回内置麦克风"
```

如果还有其他录音流需要迁移，应先通过 `pactl list short source-outputs` 确认流索引，再单独移动，避免误动其他应用的录音。

## 十、问题五：语音只识别一两个字

这个问题只出现在我的 fcitx5-vinput 场景中，与 DJI 本身不是同一层故障。

系统使用原生 PulseAudio，而语音识别组件通过用户态 PipeWire sidecar 读取音频。蓝牙 Profile 或默认输入变化后，音频隧道节点可能消失，但识别进程没有退出，于是继续读取空数据，表现为“能弹出录音条，却只识别一两个字”。

检查用户服务：

```bash
systemctl --user status pipewire-sidecar.service
systemctl --user status vinput-daemon.service
```

手动恢复：

```bash
systemctl --user restart pipewire-sidecar.service
sleep 8
systemctl --user restart vinput-daemon.service
```

如果没有使用这套语音架构，不需要执行上述命令。普通应用应先检查默认输入、音量和实际录音电平。

## 十一、如果扬声器已切回板载，仍然没有声音

还要区分另一种故障：播放流已经在板载输出上，音量正常，但测试音仍卡住或提示“排空流失败：超时”。

我在飞腾板载声卡上遇到过这种情况，用户级重启 PulseAudio 后恢复：

```bash
systemctl --user restart pulseaudio
```

这会重新枚举音频设备，蓝牙 HFP 也可能短暂断开。它不应成为日常切换脚本的固定步骤，只用于确认音频服务异常后的恢复。

排查顺序建议：

1. `pactl list short sink-inputs`：播放流是否存在；
2. 播放流是否落在 `bluez_sink`；
3. 默认输出是否已回到真实板载声卡；
4. 测试音是否出现排空超时；
5. 必要时再重启用户级 PulseAudio。

## 十二、完整排查清单

| 现象 | 优先检查 | 处理方向 |
|---|---|---|
| 约 15 秒断连 | UKUI 是否反复尝试 A2DP | 确认日志后处理桌面蓝牙服务 |
| 麦克风连接后音乐无声 | 默认输出和播放流位置 | 移回板载输出，必要时禁用自动切换 |
| 重启后所有蓝牙不可用 | `Powered: yes/no` | 用户服务自动上电 |
| 双麦互相抢通道 | 两台声卡 Profile | 一台 off，另一台 HFP |
| 切换时 PA 异常 | 是否同时重启音频桥接 | 等 HFP 稳定后再重启桥接 |
| 只识别一两个字 | sidecar 隧道是否存在 | 重启桥接和识别服务 |
| 已在板载输出仍无声 | 测试音是否排空超时 | 用户级重启 PulseAudio |

## 写在最后

这次排障最大的收获，是不要把所有现象都归为“蓝牙兼容性差”。同一台 DJI Mic Mini 上出现的多个问题，实际分别来自：

- 桌面服务对 A2DP 的错误假设；
- PulseAudio 自动切换输出；
- 蓝牙适配器无人上电；
- HFP 单通道与切换时序；
- 语音应用自己的桥接状态。

先确定故障发生在哪一层，再决定改服务、改路由还是改脚本，比反复重连和重启系统有效得多。

文中的服务名、声卡名和脚本都带有本机环境特征。复用时请先查询自己的设备名称，保留回滚方式，不要直接覆盖系统音频配置。

---

> 原文首发于 Gitee：<https://gitee.com/digtip/notes/blob/main/blog/kirin/DJI%20Mic%20Mini%20%E5%9C%A8%E9%93%B6%E6%B2%B3%E9%BA%92%E9%BA%9F%E4%B8%8A%E5%8F%8D%E5%A4%8D%E6%96%AD%E8%BF%9E%E3%80%81%E6%8A%A2%E8%BE%93%E5%87%BA%EF%BC%9F%E6%88%91%E7%9A%84%E6%8E%92%E9%9A%9C%E8%BF%87%E7%A8%8B%E4%B8%8E%E5%8F%8C%E9%BA%A6%E5%88%87%E6%8D%A2%E8%84%9A%E6%9C%AC.md>
