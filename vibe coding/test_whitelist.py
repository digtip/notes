import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("本地白名单管理系统.py")
SPEC = importlib.util.spec_from_file_location("local_whitelist", MODULE_PATH)
wl = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(wl)


class WhitelistTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        wl.DATA_JSON = str(root / "白名单数据.json")
        wl.XLSX_FILE = str(root / "白名单.xlsx")
        wl.BACKUP_DIR = str(root / "备份")
        wl.HTML_FILE = str(root / "whitelist.html")

    def tearDown(self):
        self.tmp.cleanup()

    def test_empty_directory_initializes_without_seed_data(self):
        data = wl.load_data()
        self.assertEqual(data["records"], [])
        self.assertTrue(Path(wl.DATA_JSON).is_file())
        self.assertTrue(Path(wl.XLSX_FILE).is_file())
        self.assertEqual(json.loads(Path(wl.DATA_JSON).read_text())["records"], [])

    def test_blank_json_is_initialized(self):
        Path(wl.DATA_JSON).write_text("  \n", encoding="utf-8")
        self.assertEqual(wl.load_data()["records"], [])

    def test_parse_distinguishes_new_duplicate_existing_and_invalid(self):
        text = (
            "示例甲 13800000001 示例单位A\n"
            "重复 13800000001 示例单位B\n"
            "已有 13800000002 示例单位C\n"
            "无效记录"
        )
        result = wl.parse_lines(text, {"13800000002"})
        self.assertEqual(
            [row["status"] for row in result],
            ["new", "dup", "exist", "invalid"],
        )

    def test_save_creates_excel_and_backup_before_next_write(self):
        data = wl.load_data()
        data["records"].append({
            "id": 1,
            "name": "示例甲",
            "phone": "13800000001",
            "company": "示例单位A",
            "addDate": "2026-01-15",
            "updatedAt": "",
            "status": "active",
        })
        wl.save_data(data)
        _, backup = wl.save_data(data)
        self.assertEqual(len(backup), 2)
        # 第一次保存已备份初始化时的空 JSON 和空 Excel，第二次再各备份一份。
        self.assertEqual(len(list(Path(wl.BACKUP_DIR).iterdir())), 4)

    def test_malformed_json_is_not_silently_overwritten(self):
        path = Path(wl.DATA_JSON)
        path.write_text("{broken", encoding="utf-8")
        with self.assertRaises(SystemExit):
            wl.load_data()
        self.assertEqual(path.read_text(encoding="utf-8"), "{broken")


if __name__ == "__main__":
    unittest.main()
