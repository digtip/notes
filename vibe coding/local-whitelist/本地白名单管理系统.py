#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本地白名单管理系统 · 通用脱敏版
================================
适用于个人在本机维护号码白名单：
  1) 批量粘贴录入：按手机号与库内比对去重，新号追加并记录入库日期
     （可多批次），支持按日期（缺省当日）导出新增号码 Excel 提交工单审批
  2) 条件查询已有记录，单个/批量更新，记录更新时间
  3) 每次写操作前自动备份原数据（带日期时间标记），再写主数据并同步
     重新生成 Excel

用法:
    python3 本地白名单管理系统.py          # 默认端口 8210
    python3 本地白名单管理系统.py 8211     # 指定端口
浏览器访问:
    http://127.0.0.1:8210/whitelist.html

文件说明:
    白名单数据.json —— 主数据；首次运行自动创建，已有 Excel 时可导入
    白名单.xlsx —— 首次运行自动创建，每次变更后重新生成
    备份/ —— 每次写操作前的 JSON+Excel 备份（带时间戳）

安全说明:
    默认仅监听 127.0.0.1，不提供无鉴权的局域网访问。
    面向单用户、低频率操作，不替代数据库、权限和审批系统。
"""
import json
import os
import re
import shutil
import sys
import datetime
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, quote

try:
    import openpyxl
except ImportError:
    print("缺少 openpyxl，请先安装：pip install openpyxl")
    sys.exit(1)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_JSON = os.path.join(BASE_DIR, "白名单数据.json")
XLSX_FILE = os.path.join(BASE_DIR, "白名单.xlsx")
BACKUP_DIR = os.path.join(BASE_DIR, "备份")
HTML_FILE = os.path.join(BASE_DIR, "whitelist.html")
SHEET_NAME = "白名单"
DEFAULT_PORT = 8210

def now_ts():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def today_str():
    return datetime.date.today().isoformat()


def norm_phone(p):
    """手机号标准化：仅保留数字"""
    if p is None:
        return ""
    s = str(p).strip()
    if s.endswith(".0"):
        s = s[:-2]
    s = re.sub(r"\D", "", s)
    return s


def valid_phone(p):
    return bool(re.fullmatch(r"1\d{10}", p or ""))


def fmt_date(d):
    if d is None:
        return ""
    if isinstance(d, datetime.datetime):
        return d.date().isoformat()
    if isinstance(d, datetime.date):
        return d.isoformat()
    s = str(d).strip()
    return s[:10] if s else ""


# ==================== 数据层 ====================

def read_xlsx_records():
    """从原始 Excel 解析：真实记录列 + AIGC 水印行（原样保留）"""
    wb = openpyxl.load_workbook(XLSX_FILE, data_only=True)
    ws = wb[SHEET_NAME] if SHEET_NAME in wb.sheetnames else wb.active
    records, watermark = [], None
    for row in ws.iter_rows(min_row=2, values_only=True):
        vals = (list(row) + [None] * 4)[:4]
        name, phone, company, adddate = vals
        if all(v is None or str(v).strip() == "" for v in vals):
            continue  # 空行
        p = norm_phone(phone)
        if str(name or "").startswith("AIGC:") or not valid_phone(p):
            # 平台AIGC水印行或无法解析的行：非真实数据，原样保留为水印
            watermark = [name, phone, company, adddate]
            continue
        records.append({
            "name": str(name).strip() if name else "",
            "phone": p,
            "company": str(company).strip() if company else "",
            "addDate": fmt_date(adddate) or today_str(),
            "updatedAt": "",
        })
    # 重新编号
    for i, r in enumerate(records, 1):
        r["id"] = i
    return records, watermark


def write_xlsx(data):
    """按主数据重新生成 Excel（保留表头/列宽/表尾AIGC水印行）"""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = SHEET_NAME
    ws.append(["姓名", "手机号", "公司", "入库日期"])
    for r in data["records"]:
        if r.get("status") == "removed":
            continue  # 已退出的号码不进在用主表
        phone = int(r["phone"]) if valid_phone(r["phone"]) else r["phone"]
        d = r["addDate"]
        try:
            d = datetime.date(*[int(x) for x in d.split("-")])
        except Exception:
            pass
        ws.append([r["name"] or None, phone, r["company"] or None, d])
    wm = data.get("watermark")
    if wm:
        for _ in range(5):  # 与原表布局一致：水印行前保留5个空行
            ws.append([None] * 4)
        ws.append(list(wm))
    for col, w in zip("ABCDE", (12.63, 12.63, 40.0, 10.58, 9.0)):
        ws.column_dimensions[col].width = w
    wb.save(XLSX_FILE)


def _uniq_path(fp):
    """同名备份已存在时追加序号，避免同秒操作互相覆盖"""
    if not os.path.exists(fp):
        return fp
    root, ext = os.path.splitext(fp)
    i = 2
    while os.path.exists(f"{root}_{i}{ext}"):
        i += 1
    return f"{root}_{i}{ext}"


def backup_before_write():
    """写操作前备份当前 JSON 与 Excel（带日期时间标记，防冲突）"""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = now_ts()
    saved = []
    if os.path.exists(DATA_JSON):
        dst = _uniq_path(os.path.join(BACKUP_DIR, f"白名单数据_{ts}.json"))
        shutil.copy2(DATA_JSON, dst)
        saved.append(os.path.basename(dst))
    if os.path.exists(XLSX_FILE):
        dst = _uniq_path(os.path.join(BACKUP_DIR, f"白名单_{ts}.xlsx"))
        shutil.copy2(XLSX_FILE, dst)
        saved.append(os.path.basename(dst))
    return ts, saved


def normalize_records(data):
    """历史数据统一补 status 字段（在用/已退出）"""
    for r in data.get("records", []):
        if not r.get("status"):
            r["status"] = "active"
        if r["status"] == "removed" and not r.get("removedDate"):
            r["removedDate"] = r.get("updatedAt", "")[:10] or today_str()
    return data


def write_json(data):
    """先写临时文件再替换，避免写入中断留下半个 JSON。"""
    tmp = DATA_JSON + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, DATA_JSON)


def initialize_data():
    """首次运行：有 Excel 则导入；完全没有数据文件则创建空库。"""
    if os.path.exists(XLSX_FILE) and os.path.getsize(XLSX_FILE) > 0:
        records, watermark = read_xlsx_records()
        source = f"从 Excel 导入 {len(records)} 条记录"
    else:
        records, watermark = [], None
        source = "创建空白数据库"
    data = {"version": 1, "records": records, "watermark": watermark}
    write_json(data)
    if os.path.exists(XLSX_FILE):
        backup_before_write()  # 保留初始化前的原始文件
    write_xlsx(data)
    print(f"初始化完成：{source}")
    return data


def load_data():
    if not os.path.exists(DATA_JSON):
        return initialize_data()
    # 0 字节或只有空白的数据文件视为尚未初始化。
    with open(DATA_JSON, encoding="utf-8") as f:
        raw = f.read()
    if not raw.strip():
        return initialize_data()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"主数据不是有效 JSON（第 {exc.lineno} 行）。为防止误覆盖，程序未自动清空；"
            "请先从备份恢复或修复文件。"
        ) from exc
    if not isinstance(data, dict) or not isinstance(data.get("records"), list):
        raise SystemExit("主数据结构不正确：应包含 records 数组。程序未修改原文件。")
    return normalize_records(data)


def save_data(data):
    """备份 → 原子写入 JSON → 重新生成 Excel。"""
    ts, saved = backup_before_write()
    for i, r in enumerate(data["records"], 1):
        r["id"] = i
    write_json(data)
    write_xlsx(data)
    return ts, saved


# ==================== 业务逻辑 ====================

def parse_lines(text, existing_phones):
    """解析粘贴文本（每行：姓名 手机号 公司），返回逐行结果"""
    results = []
    seen_in_batch = {}
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        # 制表符/空格混合分隔
        tokens = [t for t in re.split(r"[\t,，]+|\s+", line) if t]
        phone_idx, phone = None, ""
        for i, tok in enumerate(tokens):
            p = norm_phone(tok)
            if valid_phone(p):
                phone_idx, phone = i, p
                break
        if phone_idx is None:
            results.append({"line": line, "name": "", "phone": "", "company": "",
                            "status": "invalid", "reason": "未识别到11位手机号"})
            continue
        name = " ".join(tokens[:phone_idx]).strip()
        company = " ".join(tokens[phone_idx + 1:]).strip()
        if phone in existing_phones:
            results.append({"line": line, "name": name, "phone": phone, "company": company,
                            "status": "exist", "reason": "库中已有"})
        elif phone in seen_in_batch:
            results.append({"line": line, "name": name, "phone": phone, "company": company,
                            "status": "dup", "reason": "本批次重复"})
        else:
            seen_in_batch[phone] = True
            results.append({"line": line, "name": name, "phone": phone, "company": company,
                            "status": "new", "reason": ""})
    return results


def build_removed_xlsx(records, date):
    """生成指定日期退出清单 Excel（工单审批用：含原号码与去向备注）"""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "退出白名单"
    ws.append(["姓名", "原手机号", "公司", "退出日期", "备注（如更换为新号码）"])
    n = 0
    for r in records:
        if r.get("status") == "removed" and r.get("removedDate") == date:
            ws.append([r["name"] or None, int(r["phone"]), r["company"] or None,
                       r["removedDate"], r.get("removedNote", "")])
            n += 1
    for col, w in zip("ABCDE", (12.63, 14, 24, 14, 26)):
        ws.column_dimensions[col].width = w
    return wb, n


def build_newadd_xlsx(records, date):
    """生成指定日期新增号码的 Excel（提交工单用：仅电话号码一列，无表头）"""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "新增白名单"
    n = 0
    for r in records:
        if r.get("addDate") == date:
            ws.append([int(r["phone"])])
            n += 1
    ws.column_dimensions["A"].width = 16.0
    return wb, n


# ==================== HTTP ====================

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE_DIR, **kwargs)

    def handle_one_request(self):
        try:
            super().handle_one_request()
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True

    def log_message(self, fmt, *args):
        sys.stderr.write("[白名单] %s" + "\n",  *args) if False else sys.stderr.write("[白名单] %s\n" % (fmt % args))

    def _json(self, obj, code=200, raw=None):
        body = raw if raw is not None else json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        return json.loads(self.rfile.read(length).decode("utf-8") or "{}")

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path in ("/", "/whitelist.html"):
            self.path = "/whitelist.html"
            return super().do_GET()
        if path == "/api/data":
            data = load_data()
            recs = data["records"]
            active = [r for r in recs if r.get("status") != "removed"]
            removed = [r for r in recs if r.get("status") == "removed"]
            self._json({
                "ok": True,
                "total": len(active),
                "removedTotal": len(removed),
                "todayNew": sum(1 for r in active if r.get("addDate") == today_str()),
                "today": today_str(),
                "records": recs,
            })
            return
        if path == "/api/export":
            q = parse_qs(parsed.query)
            date = (q.get("date", [""])[0] or "").strip() or today_str()
            etype = (q.get("type", ["new"])[0] or "new").strip()
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
                self._json({"ok": False, "error": "日期格式应为 YYYY-MM-DD"}, 400)
                return
            data = load_data()
            if etype == "removed":
                wb, n = build_removed_xlsx(data["records"], date)
                fname = quote(f"白名单退出清单_{date}.xlsx")
            else:
                wb, n = build_newadd_xlsx(data["records"], date)
                fname = quote(f"白名单新增_{date}.xlsx")
            import io
            buf = io.BytesIO()
            wb.save(buf)
            payload = buf.getvalue()
            self.send_response(200)
            self.send_header("Content-Type",
                             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            self.send_header("Content-Disposition",
                             f"attachment; filename*=UTF-8''{fname}")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        return super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/parse":
                body = self._read_body()
                data = load_data()
                existing = {r["phone"] for r in data["records"]}
                res = parse_lines(body.get("text", ""), existing)
                stat = {"new": 0, "exist": 0, "dup": 0, "invalid": 0}
                for r in res:
                    stat[r["status"]] += 1
                self._json({"ok": True, "results": res, "stat": stat})
                return
            if parsed.path == "/api/commit":
                body = self._read_body()
                items = body.get("items", [])
                add_date = (body.get("addDate") or "").strip() or today_str()
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", add_date):
                    self._json({"ok": False, "error": "入库日期格式应为 YYYY-MM-DD"}, 400)
                    return
                if not isinstance(items, list) or not items:
                    self._json({"ok": False, "error": "无可入库记录"}, 400)
                    return
                data = load_data()
                existing = {r["phone"] for r in data["records"]}
                added = []
                for it in items:
                    p = norm_phone(it.get("phone", ""))
                    if not valid_phone(p) or p in existing:
                        continue  # 服务端二次校验，防并发窗口
                    data["records"].append({
                        "name": str(it.get("name", "") or "").strip(),
                        "phone": p,
                        "company": str(it.get("company", "") or "").strip(),
                        "addDate": add_date,
                        "updatedAt": "",
                    })
                    existing.add(p)
                    added.append(p)
                if added:
                    ts, saved = save_data(data)
                    self._json({"ok": True, "added": len(added), "total": len(data["records"]),
                                "backup": saved})
                else:
                    self._json({"ok": True, "added": 0, "total": len(data["records"]),
                                "backup": []})
                return
            if parsed.path == "/api/update":
                body = self._read_body()
                rid, name = body.get("id"), body.get("name", "")
                phone = norm_phone(body.get("phone", ""))
                company = body.get("company", "")
                if not valid_phone(phone):
                    self._json({"ok": False, "error": "手机号无效"}, 400)
                    return
                data = load_data()
                target = next((r for r in data["records"] if r.get("id") == rid), None)
                if not target:
                    self._json({"ok": False, "error": "记录不存在"}, 404)
                    return
                other = next((r for r in data["records"]
                              if r["phone"] == phone and r is not target), None)
                if other:
                    self._json({"ok": False,
                                "error": f"手机号已存在于：{other['name'] or other['company']}"}, 400)
                    return
                changed = (target["name"] != name or target["phone"] != phone
                           or target["company"] != company)
                if not changed:
                    self._json({"ok": True, "changed": False})
                    return
                target.update({"name": name.strip(), "phone": phone,
                               "company": company.strip(),
                               "updatedAt": datetime.datetime.now().isoformat(timespec="seconds")})
                ts, saved = save_data(data)
                self._json({"ok": True, "changed": True, "backup": saved})
                return
            if parsed.path == "/api/remove":
                body = self._read_body()
                rid = body.get("id")
                rdate = (body.get("removedDate") or "").strip() or today_str()
                note = (body.get("note") or "").strip()
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", rdate):
                    self._json({"ok": False, "error": "退出日期格式应为 YYYY-MM-DD"}, 400)
                    return
                data = load_data()
                target = next((r for r in data["records"] if r.get("id") == rid), None)
                if not target:
                    self._json({"ok": False, "error": "记录不存在"}, 404)
                    return
                if target.get("status") == "removed":
                    self._json({"ok": False, "error": "该号码已是退出状态"}, 400)
                    return
                # 防误退：换号场景中新号若已入库，备注里通常会写；这里只校验重复退出
                target["status"] = "removed"
                target["removedDate"] = rdate
                target["removedNote"] = note
                target["updatedAt"] = datetime.datetime.now().isoformat(timespec="seconds")
                ts, saved = save_data(data)
                self._json({"ok": True, "phone": target["phone"], "backup": saved})
                return
            if parsed.path == "/api/restore":
                body = self._read_body()
                rid = body.get("id")
                data = load_data()
                target = next((r for r in data["records"] if r.get("id") == rid), None)
                if not target:
                    self._json({"ok": False, "error": "记录不存在"}, 404)
                    return
                if target.get("status") != "removed":
                    self._json({"ok": False, "error": "该号码是在用状态"}, 400)
                    return
                target["status"] = "active"
                target["removedDate"] = ""
                target["removedNote"] = ""
                target["updatedAt"] = datetime.datetime.now().isoformat(timespec="seconds")
                ts, saved = save_data(data)
                self._json({"ok": True, "phone": target["phone"], "backup": saved})
                return
            if parsed.path == "/api/update_batch":
                body = self._read_body()
                ids = body.get("ids", [])
                company = str(body.get("company", "") or "").strip()
                if not ids or not company:
                    self._json({"ok": False, "error": "请选择记录并填写公司"}, 400)
                    return
                data = load_data()
                now = datetime.datetime.now().isoformat(timespec="seconds")
                n = 0
                for r in data["records"]:
                    if r.get("id") in ids:
                        r["company"] = company
                        r["updatedAt"] = now
                        n += 1
                if n:
                    ts, saved = save_data(data)
                    self._json({"ok": True, "updated": n, "backup": saved})
                else:
                    self._json({"ok": True, "updated": 0, "backup": []})
                return
            self._json({"ok": False, "error": "not found"}, 404)
        except Exception as e:
            self._json({"ok": False, "error": str(e)}, 500)


def main():
    if len(sys.argv) > 2:
        raise SystemExit("用法：python3 本地白名单管理系统.py [端口]")
    try:
        port = int(sys.argv[1]) if len(sys.argv) == 2 else DEFAULT_PORT
    except ValueError as exc:
        raise SystemExit("端口必须是整数，例如 8210。") from exc
    if not 1 <= port <= 65535:
        raise SystemExit("端口必须在 1—65535 之间。")
    print("=" * 60)
    print("  本地白名单管理系统 · 服务已启动")
    print(f"  管理页面:  http://127.0.0.1:{port}/whitelist.html")
    print("  访问限制:  仅本机（未启用认证，请勿改为 0.0.0.0）")
    print(f"  主数据:    {DATA_JSON}")
    print(f"  Excel:     自动同步 {os.path.basename(XLSX_FILE)}")
    print(f"  备份目录:  {BACKUP_DIR}")
    print("  停止服务:  Ctrl+C")
    print("=" * 60)
    load_data()  # 初始化/校验主数据
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)  # 默认仅本机访问
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止。数据与备份均保留在磁盘。")
        server.server_close()


if __name__ == "__main__":
    main()