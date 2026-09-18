import csv
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

from openpyxl import load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import db
import exporter
import server


class ExporterTests(unittest.TestCase):
    def test_csv_has_utf8_bom_and_chinese_headers(self):
        data, mimetype, filename = exporter.build_export(
            "single",
            "csv",
            [{
                "title": "中文商品",
                "shop_name": "测试店铺",
                "url": "https://example.invalid/item",
                "price": 19.9,
                "total_sales": 123,
                "today": 5,
                "rolling24": 8,
                "increment": 2,
                "interval_hours": 0.6,
                "updated_at": "2026-09-19 01:00:00",
                "status": "数据已更新",
            }],
        )
        self.assertTrue(data.startswith(b"\xef\xbb\xbf"))
        self.assertIn("text/csv", mimetype)
        self.assertTrue(filename.endswith(".csv"))
        text = data.decode("utf-8-sig")
        rows = list(csv.reader(io.StringIO(text)))
        self.assertEqual(rows[0][0], "商品标题")
        self.assertEqual(rows[1][0], "中文商品")
        self.assertEqual(rows[1][8], "0.6")

    def test_xlsx_preserves_chinese_and_numeric_values(self):
        data, mimetype, filename = exporter.build_export(
            "shops",
            "xlsx",
            [{
                "shop_name": "测试店铺",
                "shop_id": "shop-1",
                "rating": "4.9",
                "brand_name": "测试品牌",
                "brand_fans_count": 12000,
                "brand_notes_count": 321,
                "product_count": 1,
                "shop_today": 5,
                "shop_today_coverage": "1/1",
                "shop_rolling24": 8,
                "shop_rolling24_coverage": "1/1",
                "product_title": "中文商品",
                "product_url": "https://example.invalid/item",
                "price": 19.9,
                "total_sales": 123,
                "today": 5,
                "rolling24": 8,
                "increment": 2,
                "interval_hours": 0.6,
                "updated_at": "2026-09-19 01:00:00",
                "product_status": "数据已更新",
            }],
        )
        self.assertIn("spreadsheetml", mimetype)
        self.assertTrue(filename.endswith(".xlsx"))
        workbook = load_workbook(io.BytesIO(data), data_only=True)
        sheet = workbook["店铺监控"]
        self.assertEqual(sheet["A1"].value, "店铺名称")
        self.assertEqual(sheet["A2"].value, "测试店铺")
        self.assertEqual(sheet["L2"].value, "中文商品")
        self.assertEqual(sheet["Q2"].value, 8)
        self.assertEqual(sheet["S2"].value, 0.6)


class ExportApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="xhs-xuanpin-phase4-")
        self.old_dir, self.old_path = db.DATA_DIR, db.DB_PATH
        db.DATA_DIR = Path(self.temp.name)
        db.DB_PATH = db.DATA_DIR / "phase4.db"
        db.init_db()
        self.app = server.create_app(testing=True)
        self.client = self.app.test_client()

    def tearDown(self):
        db.DATA_DIR, db.DB_PATH = self.old_dir, self.old_path
        self.temp.cleanup()

    def test_export_api_returns_attachment_for_json_and_form(self):
        rows = [{
            "title": "导出商品",
            "shop_name": "中文店铺",
            "url": "https://example.invalid/item",
            "price": 9.9,
            "total_sales": 10,
            "today": 1,
            "rolling24": 2,
            "increment": 1,
            "interval_hours": 1.0,
            "updated_at": "2026-09-19 01:00:00",
            "status": "数据已更新",
        }]
        response = self.client.post(
            "/api/export",
            json={"module": "single", "format": "csv", "rows": rows},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response.headers["Content-Disposition"])
        self.assertTrue(response.data.startswith(b"\xef\xbb\xbf"))
        self.assertIn("导出商品", response.data.decode("utf-8-sig"))

        payload = json.dumps(
            {"module": "selection", "format": "xlsx", "rows": rows},
            ensure_ascii=False,
        )
        response = self.client.post("/api/export", data={"payload": payload})
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response.headers["Content-Disposition"])
        workbook = load_workbook(io.BytesIO(response.data), data_only=True)
        self.assertEqual(workbook["选品中心"]["A2"].value, "导出商品")

    def test_export_api_rejects_invalid_format(self):
        response = self.client.post(
            "/api/export",
            json={"module": "single", "format": "pdf", "rows": []},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("仅支持", response.get_json()["error"])


if __name__ == "__main__":
    unittest.main()
