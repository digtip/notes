#!/usr/bin/env bash
# 安装 TeleAgent IM 完成通知脚本与技能。
# 用法: bash install.sh
# 作用范围: 仅用户家目录（~/bin 与 ~/.config/TeleAgent/users/<账号>/skills/），不碰系统目录。
# 回退:     删除上述两处文件即可。
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_NAME="im-notify"

# --- 定位当前账号 ---
# 账号信息在数据目录 current-owner.json 里；技能装在 Electron 的 userData 目录下的 skills/。
resolve_owner_dir() {
    local base
    for base in "${TELEAGENT_HOME:-}" "$HOME/.local/share/TeleAgent" "$HOME/.config/TeleAgent"; do
        [[ -z "$base" ]] && continue
        if [[ -f "$base/current-owner.json" ]]; then
            sed -n 's/.*"ownerDir"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$base/current-owner.json" | head -1
            return
        fi
    done
    echo ""
}

resolve_skills_root() {
    local owner_dir="$1"
    local base
    for base in "${TELEAGENT_SKILLS_HOME:-}" "$HOME/.config/TeleAgent" "$HOME/.local/share/TeleAgent"; do
        [[ -z "$base" ]] && continue
        if [[ -d "$base/users/$owner_dir/skills" ]]; then
            echo "$base/users/$owner_dir/skills"
            return
        fi
    done
    # 都没有就按 Linux 约定创建
    echo "$HOME/.config/TeleAgent/users/$owner_dir/skills"
}

OWNER_DIR="$(resolve_owner_dir)"
if [[ -z "$OWNER_DIR" ]]; then
    echo "找不到 current-owner.json，请先启动一次 TeleAgent，或设置 TELEAGENT_HOME" >&2
    exit 1
fi
SKILLS_ROOT="$(resolve_skills_root "$OWNER_DIR")"
SKILL_DIR="$SKILLS_ROOT/$SKILL_NAME"

echo "==> 账号: $OWNER_DIR"
echo "==> 目标技能目录: $SKILL_DIR"

# 1) 独立脚本（方便在终端/定时任务里直接调用）
BIN_DIR="$HOME/bin"
mkdir -p "$BIN_DIR"
cp -f "$SRC_DIR/notify.py" "$BIN_DIR/notify.py"
chmod +x "$BIN_DIR/notify.py"
echo "==> 已安装脚本: $BIN_DIR/notify.py"

# 2) 技能（SKILL.md + scripts/notify.py），并把 __SKILL_DIR__ 替换成真实绝对路径
mkdir -p "$SKILL_DIR/scripts"
cp -f "$SRC_DIR/notify.py" "$SKILL_DIR/scripts/notify.py"
chmod +x "$SKILL_DIR/scripts/notify.py"
sed "s|__SKILL_DIR__|$SKILL_DIR|g" "$SRC_DIR/skill/$SKILL_NAME/SKILL.md" > "$SKILL_DIR/SKILL.md"
echo "==> 已安装技能: $SKILL_DIR"

cat <<EOF

完成。接下来：
1. 重启 TeleAgent（技能在启动时扫描目录才会被索引）；
2. 在对话框里说「跑完通知我微信」，即可让会话里的 Agent 在任务收尾时自动推送。

快速自检：
    python3 "$SKILL_DIR/scripts/notify.py" "测试" --channel weixin --dry-run
EOF
