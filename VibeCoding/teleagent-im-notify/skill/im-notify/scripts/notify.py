#!/usr/bin/env python3
"""TeleAgent 跨会话 IM 主动通知。

向 TeleAgent 自己的投递队列写一条 kind='proactive' 的投递，由官方适配器
(im-adapter) 发到目标 IM 通道；本脚本不实现任何平台 API。

用法:
    python3 notify.py "任务完成" --channel weixin
    python3 notify.py --channel weixin --dry-run "测试通知"
    python3 notify.py --channel weixin --file report.txt

退出码:
    0  平台已确认送达
    1  未送达（通道不可用 / 平台拒收 / 会话上下文过期 / 超时）
"""

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

CHANNELS = ("weixin", "wecom", "feishu", "dingtalk", "quantum")
DEFAULT_CHANNEL = "weixin"
TIMEOUT_DEFAULT = 30


def teleagent_home() -> Path:
    """定位 TeleAgent 的用户数据根目录（Linux / Windows 通用）。"""
    env = os.environ.get("TELEAGENT_HOME")
    if env:
        return Path(env).expanduser()
    if sys.platform.startswith("win"):
        for var in ("LOCALAPPDATA", "APPDATA"):
            base = os.environ.get(var)
            if base:
                p = Path(base) / "TeleAgent"
                if p.is_dir():
                    return p
        return Path.home() / "AppData" / "Roaming" / "TeleAgent"
    return Path.home() / ".local" / "share" / "TeleAgent"


def resolve_db() -> Path:
    """定位当前账号的 ais.db（投递队列所在）。"""
    base = teleagent_home()
    owner_file = base / "current-owner.json"
    if owner_file.is_file():
        try:
            owner_dir = json.loads(owner_file.read_text(encoding="utf-8"))["ownerDir"]
            p = base / "users" / owner_dir / "ais" / "ais.db"
            if p.is_file():
                return p
        except (ValueError, KeyError, OSError):
            pass
    hits = sorted((base / "users").glob("*/ais/ais.db"), key=lambda p: p.stat().st_mtime)
    if not hits:
        sys.exit("找不到 ais.db，请确认 TeleAgent 已启动过，或设置 TELEAGENT_HOME 指向其数据目录")
    return hits[-1]


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=10)
    conn.execute("PRAGMA busy_timeout = 8000")
    return conn


def load_target(conn: sqlite3.Connection, channel: str):
    """通道必须已启用，且要有过一次真实对话产生的会话目标。"""
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
            "请先在客户端里登录该通道，并和它完成过一次真实对话"
        )
    return row


def utc_stamp(offset_seconds: int = 0) -> str:
    t = datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)
    return t.strftime("%Y-%m-%dT%H:%M:%S.%f000Z")


def classify(state: str, error: str = ""):
    """把投递状态翻译成 (结果码, 提示语)。

    结果码: ok=已送达, bad=明确失败, unknown=平台未确认, pending=仍在处理中。
    """
    if state == "sent":
        return "ok", "状态：已送达 ✓"
    if state in ("failed", "suppressed", "expired", "dead_letter"):
        return "bad", f"状态：{state} ✗（{error or '无错误详情'}）"
    if state == "unknown":
        return ("unknown",
                "状态：unknown ✗ —— 平台未确认，通常是会话上下文过期：\n"
                "        请先在该 IM 里让机器人回一句话，刷新 context_token 后重试；不要直接重发。")
    return "pending", f"状态：{state}"


def notify(message: str, channel: str, timeout: int, dry_run: bool) -> int:
    if not message.strip():
        raise ValueError("通知内容为空")

    db_path = resolve_db()
    with connect(db_path) as conn:
        binding_id, dest_id, conversation, reply_ref = load_target(conn, channel)

    if dry_run:
        print(f"只读检查通过：通道={channel}，目标会话已就绪，未写入数据库")
        return 0

    ts = utc_stamp()
    expires = utc_stamp(7200)
    stamp = int(time.time() * 1000)
    delivery_id = f"dlv_local_{stamp}"
    item_id = f"dli_local_{stamp}"

    with connect(db_path) as conn:
        conn.execute(
            """INSERT INTO messaging_deliveries
                 (id, binding_id, destination_id, turn_id, kind, caller_identity,
                  idempotency_key, state, stream_key, sequence, predecessor_id,
                  replaces_delivery_id, route_snapshot, expires_at, content_digest,
                  safety_proof, content, claim_generation, attempt_id, attempt_count,
                  claim_expires_at, retry_mode, late_report, next_attempt_at,
                  last_error, created_at, updated_at)
               VALUES (?, ?, ?, '', 'proactive', 'local-script', ?, 'pending', '', 0,
                       '', '', ?, ?, ?, '', ?, 0, '', 0, NULL, 'none', '', NULL, '', ?, ?)""",
            (delivery_id, binding_id, dest_id, f"local-{stamp}",
             json.dumps({"conversation": conversation, "reply_ref": reply_ref}),
             expires, hashlib.sha256(message.encode("utf-8")).hexdigest(), message, ts, ts),
        )
        conn.execute(
            """INSERT INTO messaging_delivery_items
                 (id, delivery_id, kind, text_content, state, platform_message_id,
                  created_at, updated_at)
               VALUES (?, ?, 'text', ?, 'pending', '', ?, ?)""",
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
        code, message = classify(state, error)
        if code == "ok":
            print(message)
            return 0
        if code == "bad":
            print(message, file=sys.stderr)
            return 1
        if code == "unknown":
            print(message, file=sys.stderr)
            return 1
    print(f"状态：超时（{timeout}s 后仍为 {state}）", file=sys.stderr)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="TeleAgent 跨会话 IM 主动通知")
    parser.add_argument("text", nargs="?", help="通知内容")
    parser.add_argument("--channel", choices=CHANNELS, default=DEFAULT_CHANNEL, help="目标 IM 通道")
    parser.add_argument("--file", help="从文件读取通知内容")
    parser.add_argument("--timeout", type=int, default=TIMEOUT_DEFAULT, help="等待送达秒数")
    parser.add_argument("--dry-run", action="store_true", help="只读检查，不写入数据库")
    args = parser.parse_args()

    if args.timeout < 1:
        parser.error("--timeout 必须大于等于 1")
    if args.file and args.text:
        parser.error("--file 与位置参数不能同时使用")

    body = Path(args.file).read_text(encoding="utf-8") if args.file else (args.text or "")
    try:
        return notify(body, args.channel, args.timeout, args.dry_run)
    except Exception as exc:
        print(f"失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
