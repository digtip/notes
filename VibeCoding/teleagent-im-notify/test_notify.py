#!/usr/bin/env python3
"""teleagent-im-notify 自检：临时库 + 虚构路由，不碰真实数据库。

运行: python3 test_notify.py
"""

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
NOTIFY = HERE / "notify.py"
SKILL_COPY = HERE / "skill" / "im-notify" / "scripts" / "notify.py"

DDL_DELIVERIES = """
CREATE TABLE messaging_deliveries (
  id TEXT PRIMARY KEY, binding_id TEXT NOT NULL, destination_id TEXT NOT NULL DEFAULT '',
  turn_id TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL, caller_identity TEXT NOT NULL,
  idempotency_key TEXT NOT NULL, state TEXT NOT NULL, stream_key TEXT NOT NULL DEFAULT '',
  sequence INTEGER NOT NULL DEFAULT 0, predecessor_id TEXT NOT NULL DEFAULT '',
  replaces_delivery_id TEXT NOT NULL DEFAULT '', route_snapshot TEXT NOT NULL DEFAULT '',
  expires_at TEXT, content_digest TEXT NOT NULL DEFAULT '', safety_proof TEXT NOT NULL DEFAULT '',
  content TEXT NOT NULL DEFAULT '', claim_generation INTEGER NOT NULL DEFAULT 0,
  attempt_id TEXT NOT NULL DEFAULT '', attempt_count INTEGER NOT NULL DEFAULT 0,
  claim_expires_at TEXT, retry_mode TEXT NOT NULL DEFAULT 'none', late_report TEXT NOT NULL DEFAULT '',
  next_attempt_at TEXT, last_error TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE messaging_delivery_items (
  id TEXT PRIMARY KEY, delivery_id TEXT NOT NULL, kind TEXT NOT NULL, text_content TEXT NOT NULL DEFAULT '',
  state TEXT NOT NULL, platform_message_id TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE messaging_bindings (
  id TEXT PRIMARY KEY, channel TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
  auth_status TEXT NOT NULL DEFAULT '', external_account_id TEXT NOT NULL DEFAULT '',
  connector_id TEXT NOT NULL DEFAULT '', connection_desired INTEGER NOT NULL DEFAULT 1,
  binding_epoch INTEGER NOT NULL DEFAULT 0, last_active_destination_id TEXT NOT NULL DEFAULT '');
CREATE TABLE messaging_destinations (
  id TEXT PRIMARY KEY, binding_id TEXT NOT NULL, external_conversation_id TEXT NOT NULL DEFAULT '',
  conversation_kind TEXT NOT NULL DEFAULT '', opaque_reply_ref TEXT NOT NULL DEFAULT '',
  external_sender_id TEXT NOT NULL DEFAULT '', enabled INTEGER NOT NULL DEFAULT 1);
"""


def build_fake_home(root: Path, with_destination: bool = True) -> Path:
    """构造一个假的 TeleAgent 数据目录，返回 ais.db 路径。"""
    owner = "v1_public_test"
    users = root / "users" / owner
    (users / "ais").mkdir(parents=True, exist_ok=True)
    (root / "current-owner.json").write_text(json.dumps({"ownerDir": owner}), encoding="utf-8")
    db = users / "ais" / "ais.db"
    conn = sqlite3.connect(str(db))
    conn.executescript(DDL_DELIVERIES)
    conn.execute("INSERT INTO messaging_bindings (id,channel,enabled,connector_id) "
                 "VALUES ('mb_test','weixin',1,'official-im-adapter')")
    if with_destination:
        conn.execute("INSERT INTO messaging_destinations "
                     "(id,binding_id,external_conversation_id,opaque_reply_ref) "
                     "VALUES ('md_test','mb_test','conv_test@im.wechat','ref_test')")
    conn.commit()
    conn.close()
    return db


def run(args, home: Path):
    env = dict(os.environ)
    env["TELEAGENT_HOME"] = str(home)
    return subprocess.run([sys.executable, str(NOTIFY)] + args, env=env,
                          capture_output=True, text=True, timeout=60)


class NotifyTest(unittest.TestCase):
    def test_dry_run_does_not_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            db = build_fake_home(home)
            r = run(["--channel", "weixin", "--dry-run", "测试"], home)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("只读检查通过", r.stdout)
            conn = sqlite3.connect(str(db))
            self.assertEqual(conn.execute("SELECT count(*) FROM messaging_deliveries").fetchone()[0], 0)
            conn.close()

    def test_write_creates_delivery_and_item(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            db = build_fake_home(home)
            r = run(["--channel", "weixin", "--timeout", "2", "任务完成"], home)
            self.assertEqual(r.returncode, 1)          # 假库里没有派发 worker，只会超时
            self.assertIn("已提交", r.stdout)
            conn = sqlite3.connect(str(db))
            row = conn.execute("SELECT kind,state,route_snapshot,caller_identity "
                               "FROM messaging_deliveries").fetchone()
            item = conn.execute("SELECT kind,state,text_content FROM messaging_delivery_items").fetchone()
            conn.close()
            self.assertEqual(row[0], "proactive")
            self.assertEqual(row[1], "pending")
            self.assertEqual(json.loads(row[2]),
                             {"conversation": "conv_test@im.wechat", "reply_ref": "ref_test"})
            self.assertEqual(row[3], "local-script")
            self.assertEqual(item[0], "text")
            self.assertEqual(item[1], "pending")
            self.assertEqual(item[2], "任务完成")

    def test_missing_destination_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            build_fake_home(home, with_destination=False)
            r = run(["--channel", "weixin", "测试"], home)
            self.assertEqual(r.returncode, 1)
            self.assertIn("没有可用的绑定或会话目的地", r.stderr)

    def test_unknown_channel_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            build_fake_home(home)
            r = run(["--channel", "nosuch", "测试"], home)
            self.assertNotEqual(r.returncode, 0)

    def test_state_classification(self):
        sys.path.insert(0, str(HERE))
        import notify
        self.assertEqual(notify.classify("sent")[0], "ok")
        self.assertEqual(notify.classify("failed", "err")[0], "bad")
        self.assertEqual(notify.classify("dead_letter")[0], "bad")
        self.assertEqual(notify.classify("unknown")[0], "unknown")
        self.assertEqual(notify.classify("pending")[0], "pending")

    def test_skill_copy_matches_root(self):
        if not SKILL_COPY.is_file():
            self.skipTest("技能脚本副本不存在")
        a = hashlib.sha256(NOTIFY.read_bytes()).hexdigest()
        b = hashlib.sha256(SKILL_COPY.read_bytes()).hexdigest()
        self.assertEqual(a, b, "根目录 notify.py 与技能内副本不一致，请同步后提交")


if __name__ == "__main__":
    unittest.main(verbosity=2)
