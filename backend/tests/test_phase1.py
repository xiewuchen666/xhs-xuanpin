import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import db
import metrics
import server


def payload(
    item_id: str,
    title: str,
    observed_at: str,
    *,
    sales: int = 100,
    price: float = 19.9,
    shop_name: str = "测试店铺",
) -> dict:
    return {
        "item_id": item_id,
        "title": title,
        "image_url": "https://example.invalid/image.jpg",
        "shop_id": "shop-" + item_id,
        "shop_name": shop_name,
        "price": price,
        "total_sales": sales,
        "sales_raw": f"已售{sales}",
        "sales_precision": "exact",
        "observed_at": observed_at,
    }


class MetricCompatibilityTests(unittest.TestCase):
    def test_legacy_metric_rules_for_exact_snapshots(self):
        product = {"id": 1, "monitor_state": "active", "last_collected_at": "2026-09-18 10:00:00"}
        snapshots = [
            {"id": 1, "product_id": 1, "collected_at": "2026-09-17 10:00:00", "total_sales": 100, "sales_raw": "已售100", "sales_precision": "exact", "price": 10},
            {"id": 2, "product_id": 1, "collected_at": "2026-09-18 00:00:00", "total_sales": 120, "sales_raw": "已售120", "sales_precision": "exact", "price": 10},
            {"id": 3, "product_id": 1, "collected_at": "2026-09-18 10:00:00", "total_sales": 150, "sales_raw": "已售150", "sales_precision": "exact", "price": 10},
        ]
        result = metrics.enrich(product, snapshots, as_of="2026-09-18 10:00:00")
        self.assertEqual(result["today"]["value"], 30)
        self.assertEqual(result["rolling24"]["value"], 50)
        self.assertEqual(result["increment"]["value"], 30)
        self.assertEqual(result["health_label"], "数据已更新")

    def test_lower_bound_sales_are_not_faked_into_growth(self):
        product = {"id": 1, "monitor_state": "active", "last_collected_at": "2026-09-18 10:00:00"}
        snapshots = [
            {"id": 1, "product_id": 1, "collected_at": "2026-09-18 09:00:00", "total_sales": 13000, "sales_raw": "已售1.3万+", "sales_precision": "lower_bound", "price": 10},
            {"id": 2, "product_id": 1, "collected_at": "2026-09-18 10:00:00", "total_sales": 13000, "sales_raw": "已售1.3万+", "sales_precision": "lower_bound", "price": 10},
        ]
        result = metrics.enrich(product, snapshots, as_of="2026-09-18 10:00:00")
        self.assertIsNone(result["today"]["value"])
        self.assertIsNone(result["rolling24"]["value"])
        self.assertIsNone(result["increment"]["value"])
        self.assertEqual(result["health_label"], "下限值")


class PhaseOneDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="xhs-xuanpin-phase1-")
        self.old_dir, self.old_path = db.DATA_DIR, db.DB_PATH
        db.DATA_DIR = Path(self.temp.name)
        db.DB_PATH = db.DATA_DIR / "phase1.db"
        db.init_db()

    def tearDown(self):
        db.DATA_DIR, db.DB_PATH = self.old_dir, self.old_path
        self.temp.cleanup()

    def test_monitor_state_selection_and_remove_preserve_history(self):
        product_id = db.persist(
            "https://xiaohongshu.com/goods-detail/one",
            payload("sku-one", "商品一", "2026-09-18 10:00:00"),
        )
        self.assertTrue(db.is_in_single_monitor(product_id))
        self.assertEqual(db.snapshot_count(product_id), 1)

        db.set_monitor_state(product_id, "paused")
        listed = db.list_products()
        self.assertEqual(listed[0]["monitor_state"], "paused")

        db.add_selection(product_id)
        listed = db.list_products()
        self.assertEqual(listed[0]["in_selection_pool"], 1)

        db.remove_single_monitor(product_id)
        self.assertFalse(db.is_in_single_monitor(product_id))
        self.assertEqual(db.list_products(), [])
        self.assertIsNotNone(db.get_product(product_id))
        self.assertEqual(db.snapshot_count(product_id), 1)

        with closing(db.connect()) as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM selection_pool_products WHERE product_id=?",
                    (product_id,),
                ).fetchone()[0],
                1,
            )

    def test_collect_update_does_not_change_paused_state(self):
        product_id = db.persist(
            "https://xiaohongshu.com/goods-detail/two",
            payload("sku-two", "商品二", "2026-09-18 10:00:00"),
        )
        db.set_monitor_state(product_id, "paused")
        db.persist(
            "https://xiaohongshu.com/goods-detail/two",
            payload("sku-two", "商品二", "2026-09-18 11:00:00", sales=130),
            join_single=False,
            expected_product_id=product_id,
        )
        self.assertEqual(db.get_product(product_id)["monitor_state"], "paused")
        self.assertEqual(db.snapshot_count(product_id), 2)


class PhaseOneApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="xhs-xuanpin-api-")
        self.old_dir, self.old_path = db.DATA_DIR, db.DB_PATH
        db.DATA_DIR = Path(self.temp.name)
        db.DB_PATH = db.DATA_DIR / "api.db"
        db.init_db()
        self.product_id = db.persist(
            "https://xiaohongshu.com/goods-detail/api-one",
            payload("sku-api", "API 商品", "2026-09-18 10:00:00"),
        )
        self.app = server.create_app(testing=True)
        self.client = self.app.test_client()

    def tearDown(self):
        db.DATA_DIR, db.DB_PATH = self.old_dir, self.old_path
        self.temp.cleanup()

    def test_state_selection_and_remove_api(self):
        response = self.client.post(
            f"/api/products/{self.product_id}/state", json={"state": "paused"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get("/api/products").get_json()[0]["monitor_state"], "paused")

        response = self.client.post(f"/api/products/{self.product_id}/selection", json={})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get("/api/products").get_json()[0]["in_selection_pool"], 1)

        response = self.client.delete(f"/api/products/{self.product_id}/monitor")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get("/api/products").get_json(), [])
        self.assertEqual(db.snapshot_count(self.product_id), 1)

    def test_collect_one_adds_snapshot_and_paused_product_is_blocked(self):
        collected = payload(
            "sku-api",
            "API 商品",
            "2026-09-18 11:00:00",
            sales=125,
            price=18.8,
        )
        with mock.patch.object(server.collector, "collect_product", return_value=collected):
            response = self.client.post(f"/api/products/{self.product_id}/collect", json={})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(db.snapshot_count(self.product_id), 2)
        self.assertEqual(db.get_product(self.product_id)["total_sales"], 125)

        self.client.post(
            f"/api/products/{self.product_id}/state", json={"state": "paused"}
        )
        with mock.patch.object(server.collector, "collect_product") as collect_mock:
            response = self.client.post(f"/api/products/{self.product_id}/collect", json={})
        self.assertEqual(response.status_code, 409)
        collect_mock.assert_not_called()


class PhaseOneMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="xhs-xuanpin-migrate-")
        self.old_dir, self.old_path = db.DATA_DIR, db.DB_PATH
        db.DATA_DIR = Path(self.temp.name)
        db.DB_PATH = db.DATA_DIR / "legacy.db"
        db.DATA_DIR.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        db.DATA_DIR, db.DB_PATH = self.old_dir, self.old_path
        self.temp.cleanup()

    def test_existing_products_are_backfilled_once(self):
        conn = sqlite3.connect(db.DB_PATH)
        try:
            conn.executescript("""
                CREATE TABLE products(
                  id INTEGER PRIMARY KEY,
                  item_id TEXT NOT NULL UNIQUE,
                  url TEXT NOT NULL,
                  title TEXT NOT NULL,
                  image_url TEXT NOT NULL DEFAULT '',
                  shop_id TEXT NOT NULL DEFAULT '',
                  shop_name TEXT NOT NULL DEFAULT '',
                  price REAL,
                  total_sales INTEGER,
                  sales_raw TEXT NOT NULL DEFAULT '',
                  sales_precision TEXT NOT NULL DEFAULT 'unknown',
                  last_collected_at TEXT NOT NULL
                );
                CREATE TABLE snapshots(
                  id INTEGER PRIMARY KEY,
                  product_id INTEGER NOT NULL REFERENCES products(id),
                  collected_at TEXT NOT NULL,
                  price REAL,
                  total_sales INTEGER,
                  sales_raw TEXT NOT NULL DEFAULT '',
                  sales_precision TEXT NOT NULL DEFAULT 'unknown'
                );
                INSERT INTO products(
                  id,item_id,url,title,last_collected_at
                ) VALUES(
                  7,'legacy-sku','https://xiaohongshu.com/goods-detail/legacy',
                  '旧商品','2026-09-18 09:00:00'
                );
            """)
            conn.commit()
        finally:
            conn.close()

        db.init_db()
        products = db.list_products()
        self.assertEqual(len(products), 1)
        self.assertEqual(products[0]["id"], 7)
        self.assertEqual(products[0]["monitor_state"], "active")

        db.remove_single_monitor(7)
        db.init_db()
        self.assertEqual(db.list_products(), [])


if __name__ == "__main__":
    unittest.main()
