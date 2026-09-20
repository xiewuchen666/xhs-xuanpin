import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import db
import jobs
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

    def test_sales_trend_uses_day_boundaries_and_breaks_irregular_hours(self):
        snapshots = [
            {"id": 1, "collected_at": "2026-09-18 00:00:00", "total_sales": 102, "sales_raw": "已售102", "sales_precision": "exact"},
            {"id": 2, "collected_at": "2026-09-18 01:00:00", "total_sales": 107, "sales_raw": "已售107", "sales_precision": "exact"},
            {"id": 3, "collected_at": "2026-09-18 02:00:00", "total_sales": 111, "sales_raw": "已售111", "sales_precision": "exact"},
            {"id": 4, "collected_at": "2026-09-19 00:00:00", "total_sales": 150, "sales_raw": "已售150", "sales_precision": "exact"},
            {"id": 5, "collected_at": "2026-09-19 00:05:00", "total_sales": 151, "sales_raw": "已售151", "sales_precision": "exact"},
            {"id": 6, "collected_at": "2026-09-19 01:00:00", "total_sales": 156, "sales_raw": "已售156", "sales_precision": "exact"},
            {"id": 7, "collected_at": "2026-09-19 03:30:00", "total_sales": 170, "sales_raw": "已售170", "sales_precision": "exact"},
        ]

        trend = metrics.sales_trend(snapshots, as_of="2026-09-19 03:30:00")
        by_day = {point["date"]: point for point in trend["daily"]}

        self.assertEqual(by_day["2026-09-18"]["value"], 48)
        self.assertEqual(by_day["2026-09-19"]["value"], 20)
        self.assertTrue(by_day["2026-09-19"]["partial"])
        self.assertEqual([point["value"] for point in trend["hourly"]], [None, 5, None])
        self.assertNotIn("00:05", [point["label"] for point in trend["hourly"]])
        self.assertTrue(trend["hourly"][-1]["gap"])
        self.assertEqual(trend["hourly"][-1]["gap_total"], 14)
        self.assertEqual(trend["hourly"][-1]["average_hourly"], 5.6)
        self.assertIn("2.5 小时", trend["hourly"][-1]["reason"])

    def test_hourly_trend_ignores_midnight_baseline_samples(self):
        snapshots = [
            {"id": 1, "collected_at": "2026-09-18 23:55:00", "total_sales": 100, "sales_raw": "已售100", "sales_precision": "exact"},
            {"id": 2, "collected_at": "2026-09-19 00:00:00", "total_sales": 80, "sales_raw": "已售80", "sales_precision": "exact", "is_midnight": 1, "baseline_day": "2026-09-19", "baseline_slot": "0000"},
            {"id": 3, "collected_at": "2026-09-19 00:05:00", "total_sales": 90, "sales_raw": "已售90", "sales_precision": "exact", "is_midnight": 1, "baseline_day": "2026-09-19", "baseline_slot": "0005"},
            {"id": 4, "collected_at": "2026-09-19 00:10:00", "total_sales": 101, "sales_raw": "已售101", "sales_precision": "exact", "is_midnight": 1, "baseline_day": "2026-09-19", "baseline_slot": "0010"},
            {"id": 5, "collected_at": "2026-09-19 00:55:00", "total_sales": 102, "sales_raw": "已售102", "sales_precision": "exact"},
        ]

        trend = metrics.sales_trend(snapshots, as_of="2026-09-19 00:55:00")

        self.assertEqual([point["label"] for point in trend["hourly"]], ["23:55", "00:55"])
        self.assertEqual([point["value"] for point in trend["hourly"]], [None, 2])

    def test_rolling_window_stays_anchored_to_latest_sample_between_runs(self):
        product = {"id": 1, "monitor_state": "active", "last_collected_at": "2026-09-18 10:00:00"}
        snapshots = [
            {"id": 1, "product_id": 1, "collected_at": "2026-09-17 10:00:00", "total_sales": 100, "sales_raw": "已售100", "sales_precision": "exact", "price": 10},
            {"id": 2, "product_id": 1, "collected_at": "2026-09-18 10:00:00", "total_sales": 150, "sales_raw": "已售150", "sales_precision": "exact", "price": 10},
        ]

        result = metrics.enrich(product, snapshots, as_of="2026-09-18 10:31:00")

        self.assertEqual(result["rolling24"]["value"], 50)
        self.assertEqual(result["rolling24"]["to_time"], "2026-09-18 10:00:00")

    def test_new_product_uses_first_sample_until_full_day_exists(self):
        product = {"id": 1, "monitor_state": "active", "last_collected_at": "2026-09-18 18:00:00"}
        snapshots = [
            {"id": 1, "product_id": 1, "collected_at": "2026-09-18 10:00:00", "total_sales": 100, "sales_raw": "已售100", "sales_precision": "exact", "price": 10},
            {"id": 2, "product_id": 1, "collected_at": "2026-09-18 18:00:00", "total_sales": 125, "sales_raw": "已售125", "sales_precision": "exact", "price": 10},
        ]

        partial = metrics.enrich(product, snapshots, as_of="2026-09-18 18:00:00")

        self.assertEqual(partial["today"]["value"], 25)
        self.assertTrue(partial["today"]["partial"])
        self.assertEqual(partial["rolling24"]["value"], 25)
        self.assertTrue(partial["rolling24"]["partial"])
        self.assertEqual(partial["rolling24"]["hours"], 8)

        snapshots.append(
            {"id": 3, "product_id": 1, "collected_at": "2026-09-19 10:00:00", "total_sales": 150, "sales_raw": "已售150", "sales_precision": "exact", "price": 10}
        )
        product["last_collected_at"] = "2026-09-19 10:00:00"
        full_day = metrics.enrich(product, snapshots, as_of="2026-09-19 10:00:00")

        self.assertEqual(full_day["rolling24"]["value"], 50)
        self.assertFalse(full_day["rolling24"].get("partial", False))

    def test_2355_baseline_ignores_midnight_and_ordinary_drops_until_recovery(self):
        product = {"id": 1, "monitor_state": "active", "last_collected_at": "2026-09-19 01:10:00"}
        snapshots = [
            {"id": 1, "product_id": 1, "collected_at": "2026-09-18 23:55:00", "total_sales": 8707, "sales_raw": "已售8707", "sales_precision": "exact", "price": 10, "is_midnight": 1, "baseline_day": "2026-09-19", "baseline_slot": "2355"},
            {"id": 2, "product_id": 1, "collected_at": "2026-09-19 00:00:00", "total_sales": 8573, "sales_raw": "已售8573", "sales_precision": "exact", "price": 10, "is_midnight": 1, "baseline_day": "2026-09-19", "baseline_slot": "0000"},
            {"id": 3, "product_id": 1, "collected_at": "2026-09-19 00:05:00", "total_sales": 8580, "sales_raw": "已售8580", "sales_precision": "exact", "price": 10, "is_midnight": 1, "baseline_day": "2026-09-19", "baseline_slot": "0005"},
            {"id": 4, "product_id": 1, "collected_at": "2026-09-19 00:12:00", "total_sales": 8590, "sales_raw": "已售8590", "sales_precision": "exact", "price": 10},
            {"id": 5, "product_id": 1, "collected_at": "2026-09-19 01:10:00", "total_sales": 8711, "sales_raw": "已售8711", "sales_precision": "exact", "price": 10},
        ]

        waiting = metrics.enrich(product, snapshots[:-1], as_of="2026-09-19 00:12:00")
        self.assertIsNone(waiting["today"]["value"])
        self.assertEqual(waiting["counter_state"], "pending_drop")

        recovered = metrics.enrich(product, snapshots, as_of="2026-09-19 01:10:00")

        self.assertEqual(recovered["today"]["value"], 4)
        self.assertEqual(recovered["today"]["from_time"], "2026-09-18 23:55:00")
        self.assertEqual(recovered["counter_state"], "stable")

    def test_2355_is_used_even_when_legacy_0000_snapshot_is_higher(self):
        product = {"id": 1, "monitor_state": "active", "last_collected_at": "2026-09-19 00:55:00"}
        snapshots = [
            {"id": 1, "product_id": 1, "collected_at": "2026-09-18 23:55:00", "total_sales": 100, "sales_raw": "已售100", "sales_precision": "exact", "price": 10, "is_midnight": 1, "baseline_day": "2026-09-19", "baseline_slot": "2355"},
            {"id": 2, "product_id": 1, "collected_at": "2026-09-19 00:00:00", "total_sales": 102, "sales_raw": "已售102", "sales_precision": "exact", "price": 10, "is_midnight": 1, "baseline_day": "2026-09-19", "baseline_slot": "0000"},
            {"id": 3, "product_id": 1, "collected_at": "2026-09-19 00:55:00", "total_sales": 105, "sales_raw": "已售105", "sales_precision": "exact", "price": 10},
        ]
        result = metrics.enrich(product, snapshots, as_of="2026-09-19 00:55:00")
        self.assertEqual(result["today"]["value"], 5)
        self.assertEqual(result["today"]["from_time"], "2026-09-18 23:55:00")

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

    def test_single_counter_drop_is_ignored_after_recovery(self):
        product = {"id": 1, "monitor_state": "active", "last_collected_at": "2026-09-19 00:35:05"}
        snapshots = [
            {"id": 1, "product_id": 1, "collected_at": "2026-09-18 00:35:05", "total_sales": 8000, "sales_raw": "已售8000", "sales_precision": "exact", "price": 10},
            {"id": 2, "product_id": 1, "collected_at": "2026-09-18 23:55:13", "total_sales": 8707, "sales_raw": "已售8707", "sales_precision": "exact", "price": 10},
            {"id": 3, "product_id": 1, "collected_at": "2026-09-19 00:00:10", "total_sales": 8573, "sales_raw": "已售8573", "sales_precision": "exact", "price": 10},
            {"id": 4, "product_id": 1, "collected_at": "2026-09-19 00:35:05", "total_sales": 8711, "sales_raw": "已售8711", "sales_precision": "exact", "price": 10},
        ]
        result = metrics.enrich(product, snapshots, as_of="2026-09-19 00:35:05")
        self.assertEqual(result["today"]["value"], 4)
        self.assertEqual(result["rolling24"]["value"], 711)
        self.assertEqual(result["increment"]["value"], 4)
        self.assertAlmostEqual(result["increment"]["hours"], 2392 / 3600, places=6)
        self.assertEqual(result["counter_state"], "stable")
        self.assertEqual(result["health_label"], "数据已更新")

    def test_first_counter_drop_waits_for_confirmation(self):
        product = {"id": 1, "monitor_state": "active", "last_collected_at": "2026-09-19 00:00:10"}
        snapshots = [
            {"id": 1, "product_id": 1, "collected_at": "2026-09-18 23:55:13", "total_sales": 8707, "sales_raw": "已售8707", "sales_precision": "exact", "price": 10},
            {"id": 2, "product_id": 1, "collected_at": "2026-09-19 00:00:10", "total_sales": 8573, "sales_raw": "已售8573", "sales_precision": "exact", "price": 10},
        ]
        result = metrics.enrich(product, snapshots, as_of="2026-09-19 00:00:10")
        self.assertIsNone(result["today"]["value"])
        self.assertIsNone(result["increment"]["value"])
        self.assertEqual(result["counter_state"], "pending_drop")
        self.assertEqual(result["health_label"], "销量回落待确认")
        self.assertIn("回落待确认", result["increment"]["reason"])

    def test_two_low_readings_reset_baseline_and_restart_increment(self):
        product = {"id": 1, "monitor_state": "active", "last_collected_at": "2026-09-19 00:35:00"}
        snapshots = [
            {"id": 1, "product_id": 1, "collected_at": "2026-09-18 23:55:00", "total_sales": 8707, "sales_raw": "已售8707", "sales_precision": "exact", "price": 10},
            {"id": 2, "product_id": 1, "collected_at": "2026-09-19 00:00:00", "total_sales": 8573, "sales_raw": "已售8573", "sales_precision": "exact", "price": 10},
            {"id": 3, "product_id": 1, "collected_at": "2026-09-19 00:35:00", "total_sales": 8580, "sales_raw": "已售8580", "sales_precision": "exact", "price": 10},
        ]
        reset = metrics.enrich(product, snapshots, as_of="2026-09-19 00:35:00")
        self.assertIsNone(reset["today"]["value"])
        self.assertIsNone(reset["increment"]["value"])
        self.assertEqual(reset["counter_state"], "reset_baseline")
        self.assertEqual(reset["health_label"], "销量基线已重置")
        self.assertIn("基线已重置", reset["increment"]["reason"])

        snapshots.append(
            {"id": 4, "product_id": 1, "collected_at": "2026-09-19 01:35:00", "total_sales": 8600, "sales_raw": "已售8600", "sales_precision": "exact", "price": 10}
        )
        product["last_collected_at"] = "2026-09-19 01:35:00"
        restarted = metrics.enrich(product, snapshots, as_of="2026-09-19 01:35:00")
        self.assertEqual(restarted["increment"]["value"], 20)
        self.assertEqual(restarted["increment"]["hours"], 1.0)
        self.assertIsNone(restarted["today"]["value"])
        self.assertEqual(restarted["counter_state"], "stable")


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
        self.assertEqual(self.client.get("/api/selection").get_json()[0]["id"], self.product_id)
        self.assertEqual(db.snapshot_count(self.product_id), 1)

    def test_product_trend_api_serves_every_monitor_scope(self):
        response = self.client.get(f"/api/products/{self.product_id}/trend")
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["product"]["id"], self.product_id)
        self.assertEqual(len(body["daily"]), 30)
        self.assertIn("hourly", body)

        db.add_selection(self.product_id)
        db.remove_single_monitor(self.product_id)
        self.assertEqual(
            self.client.get(f"/api/products/{self.product_id}/trend").status_code,
            200,
        )

        db.remove_selection(self.product_id)
        db.add_shop_monitor(self.product_id)
        self.assertEqual(
            self.client.get(f"/api/products/{self.product_id}/trend").status_code,
            200,
        )

        db.remove_shop_monitor(self.product_id)
        self.assertEqual(
            self.client.get(f"/api/products/{self.product_id}/trend").status_code,
            404,
        )

    def test_collect_one_adds_snapshot_and_paused_product_is_blocked(self):
        collected = payload(
            "sku-api",
            "API 商品",
            "2026-09-18 11:00:00",
            sales=125,
            price=18.8,
        )
        response = self.client.post(f"/api/products/{self.product_id}/collect", json={})
        self.assertEqual(response.status_code, 202)
        job_id = response.get_json()["job_id"]
        self.assertEqual(db.snapshot_count(self.product_id), 1)
        self.assertTrue(jobs.process_next(lambda _url: collected))
        self.assertEqual(jobs.get_job(job_id)["status"], "success")
        self.assertEqual(db.snapshot_count(self.product_id), 2)
        self.assertEqual(db.get_product(self.product_id)["total_sales"], 125)

        self.client.post(
            f"/api/products/{self.product_id}/state", json={"state": "paused"}
        )
        response = self.client.post(f"/api/products/{self.product_id}/collect", json={})
        self.assertEqual(response.status_code, 409)

    def test_duplicate_share_link_keeps_history_and_removed_product_can_rejoin(self):
        changed = payload(
            "sku-api",
            "不应覆盖的标题",
            "2026-09-18 11:00:00",
            sales=999,
        )
        new_url = "https://xiaohongshu.com/goods-detail/another-share-link"

        with mock.patch("server.collector.collect_product", return_value=changed):
            response = self.client.post(
                "/api/products/collect",
                json={"url": new_url, "scope": "single"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["duplicate"])
        self.assertEqual(response.get_json()["message"], "已加入监控")
        product = db.get_product(self.product_id)
        self.assertEqual(product["url"], "https://xiaohongshu.com/goods-detail/api-one")
        self.assertEqual(product["title"], "API 商品")
        self.assertEqual(product["total_sales"], 100)
        self.assertEqual(db.snapshot_count(self.product_id), 1)

        db.remove_single_monitor(self.product_id)
        with mock.patch("server.collector.collect_product", return_value=changed):
            response = self.client.post(
                "/api/products/collect",
                json={"url": new_url, "scope": "single"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()["duplicate"])
        self.assertTrue(response.get_json()["restored"])
        self.assertEqual(response.get_json()["message"], "已恢复监控")
        self.assertTrue(db.is_in_single_monitor(self.product_id))
        self.assertEqual(db.get_product(self.product_id)["url"], "https://xiaohongshu.com/goods-detail/api-one")
        self.assertEqual(db.snapshot_count(self.product_id), 1)


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
