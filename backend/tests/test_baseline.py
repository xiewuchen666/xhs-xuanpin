import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import collector
import db


class CollectorParserTests(unittest.TestCase):
    def test_sales_and_url_contracts(self):
        self.assertEqual(collector.parse_sales("已售1.3万+")["total_sales"], 13000)
        self.assertEqual(collector.parse_sales("月售120")["sales_precision"], "unknown")
        self.assertEqual(collector.validate_url("https://xhslink.com/a/abc"), "https://xhslink.com/a/abc")
        with self.assertRaises(ValueError):
            collector.validate_url("http://127.0.0.1/private")

    def test_detail_parser(self):
        body = {"data": {"template_data": [{
            "descriptionH5": {"skuId": "sku-1", "name": "测试商品"},
            "sellerH5": {"id": "shop-1", "name": "测试店铺", "logo": {"url": "//img.example.com/shop.png"}},
            "priceH5": {"dealPrice": {"price": "24.90"}, "itemAnalysisDataText": "已售100"}
        }]}}
        result = collector.parse_detail_response(body)
        self.assertEqual((result["item_id"], result["price"], result["total_sales"]), ("sku-1", 24.9, 100))
        self.assertEqual(result["shop_logo_url"], "https://img.example.com/shop.png")
        self.assertEqual(collector._pick_shop_logo({"logo": "javascript:alert(1)"}), "")
        self.assertEqual(collector._pick_shop_logo({"logo": "https://127.0.0.1/logo.png"}), "")

        diagnostics = {}
        self.assertIsNone(collector.parse_detail_response({}, diagnostics=diagnostics))
        self.assertEqual(diagnostics["reason"], "响应缺少 data.template_data")


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="xhs-xuanpin-")
        self.old_dir, self.old_path = db.DATA_DIR, db.DB_PATH
        db.DATA_DIR = Path(self.temp.name)
        db.DB_PATH = db.DATA_DIR / "test.db"
        db.init_db()

    def tearDown(self):
        db.DATA_DIR, db.DB_PATH = self.old_dir, self.old_path
        self.temp.cleanup()

    def test_persist_is_upsert_with_history(self):
        payload = {"item_id": "sku-1", "title": "测试商品", "shop_name": "测试店铺",
                   "price": 24.9, "total_sales": 100, "sales_raw": "已售100",
                   "sales_precision": "exact", "observed_at": "2026-09-18 10:00:00"}
        first = db.persist("https://xiaohongshu.com/goods-detail/abc", payload)
        payload.update(total_sales=110, sales_raw="已售110", observed_at="2026-09-18 11:00:00")
        second = db.persist("https://xiaohongshu.com/goods-detail/abc", payload)
        self.assertEqual(first, second)
        self.assertEqual(db.list_products()[0]["total_sales"], 110)
        with closing(db.connect()) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0], 2)


if __name__ == "__main__":
    unittest.main()
