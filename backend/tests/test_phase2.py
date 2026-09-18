import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import db
import server


def payload(item_id, title, observed_at, *, shop_id, shop_name, sales=100, price=19.9):
    return {
        "item_id": item_id,
        "title": title,
        "image_url": "",
        "shop_id": shop_id,
        "shop_name": shop_name,
        "price": price,
        "total_sales": sales,
        "sales_raw": f"已售{sales}",
        "sales_precision": "exact",
        "observed_at": observed_at,
    }


class PhaseTwoDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="xhs-xuanpin-phase2-")
        self.old_dir, self.old_path = db.DATA_DIR, db.DB_PATH
        db.DATA_DIR = Path(self.temp.name)
        db.DB_PATH = db.DATA_DIR / "phase2.db"
        db.init_db()

    def tearDown(self):
        db.DATA_DIR, db.DB_PATH = self.old_dir, self.old_path
        self.temp.cleanup()

    def add_product(self, item_id, shop_id, shop_name, sales=100):
        return db.persist(
            f"https://xiaohongshu.com/goods-detail/{item_id}",
            payload(
                item_id,
                f"商品-{item_id}",
                "2026-09-18 10:00:00",
                shop_id=shop_id,
                shop_name=shop_name,
                sales=sales,
            ),
        )

    def test_shop_grouping_uses_only_single_monitor_membership(self):
        a = self.add_product("a", "shop-one", "同一家店", 100)
        b = self.add_product("b", "shop-one", "同一家店", 200)
        c = self.add_product("c", "shop-two", "另一家店", 300)
        db.remove_single_monitor(c)

        shops = db.list_shops(as_of="2026-09-18 10:00:00")
        self.assertEqual(len(shops), 1)
        self.assertEqual(shops[0]["shop_name"], "同一家店")
        self.assertEqual(shops[0]["product_count"], 2)

        detail = db.list_shop_products(shops[0]["shop_key"], as_of="2026-09-18 10:00:00")
        self.assertEqual({row["id"] for row in detail}, {a, b})

    def test_shop_metric_aggregation_uses_product_metrics(self):
        a = db.persist(
            "https://xiaohongshu.com/goods-detail/a",
            payload("a", "商品-a", "2026-09-17 11:00:00", shop_id="shop-one", shop_name="同一家店", sales=90),
        )
        b = db.persist(
            "https://xiaohongshu.com/goods-detail/b",
            payload("b", "商品-b", "2026-09-17 11:00:00", shop_id="shop-one", shop_name="同一家店", sales=180),
        )
        for product_id, item_id, midnight_sales, current_sales in [
            (a, "a", 100, 130),
            (b, "b", 200, 220),
        ]:
            db.persist(
                f"https://xiaohongshu.com/goods-detail/{item_id}",
                payload(item_id, f"商品-{item_id}", "2026-09-18 00:00:00", shop_id="shop-one", shop_name="同一家店", sales=midnight_sales),
                join_single=False,
                expected_product_id=product_id,
            )
            db.persist(
                f"https://xiaohongshu.com/goods-detail/{item_id}",
                payload(item_id, f"商品-{item_id}", "2026-09-18 11:00:00", shop_id="shop-one", shop_name="同一家店", sales=current_sales),
                join_single=False,
                expected_product_id=product_id,
            )

        shops = db.list_shops(as_of="2026-09-18 11:00:00")
        self.assertEqual(shops[0]["today"]["value"], 50)
        self.assertEqual(shops[0]["today"]["covered"], 2)
        self.assertEqual(shops[0]["today"]["total"], 2)
        self.assertEqual(shops[0]["rolling24"]["value"], 80)
        self.assertEqual(len(shops[0]["products"]), 2)

    def test_shop_aggregation_keeps_partial_valid_coverage(self):
        exact_id = db.persist(
            "https://xiaohongshu.com/goods-detail/exact",
            payload("exact", "精确商品", "2026-09-18 00:00:00", shop_id="shop-partial", shop_name="部分覆盖店", sales=100),
        )
        db.persist(
            "https://xiaohongshu.com/goods-detail/exact",
            payload("exact", "精确商品", "2026-09-18 10:00:00", shop_id="shop-partial", shop_name="部分覆盖店", sales=125),
            join_single=False,
            expected_product_id=exact_id,
        )
        fuzzy = payload("fuzzy", "下限商品", "2026-09-18 10:00:00", shop_id="shop-partial", shop_name="部分覆盖店", sales=13000)
        fuzzy["sales_raw"] = "已售1.3万+"
        fuzzy["sales_precision"] = "lower_bound"
        db.persist("https://xiaohongshu.com/goods-detail/fuzzy", fuzzy)

        shops = db.list_shops(as_of="2026-09-18 10:00:00")
        shop = next(row for row in shops if row["shop_name"] == "部分覆盖店")
        self.assertEqual(shop["today"]["value"], 25)
        self.assertEqual(shop["today"]["covered"], 1)
        self.assertEqual(shop["today"]["total"], 2)

    def test_selection_membership_is_independent_from_single_monitor(self):
        product_id = self.add_product("sel", "shop-sel", "选品店")
        db.remove_single_monitor(product_id)
        self.assertFalse(db.is_in_single_monitor(product_id))

        db.add_selection(product_id)
        self.assertFalse(db.is_in_single_monitor(product_id))
        self.assertEqual(db.get_product(product_id)["monitor_state"], "active")
        selected = db.list_selection_products(as_of="2026-09-18 10:00:00")
        self.assertEqual([row["id"] for row in selected], [product_id])
        self.assertEqual(selected[0]["in_single_monitor"], 0)

        snapshot_count = db.snapshot_count(product_id)
        db.remove_selection(product_id)
        self.assertEqual(db.list_selection_products(), [])
        self.assertFalse(db.is_in_single_monitor(product_id))
        self.assertEqual(db.snapshot_count(product_id), snapshot_count)
        self.assertIsNotNone(db.get_product(product_id))


class PhaseTwoApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="xhs-xuanpin-phase2-api-")
        self.old_dir, self.old_path = db.DATA_DIR, db.DB_PATH
        db.DATA_DIR = Path(self.temp.name)
        db.DB_PATH = db.DATA_DIR / "phase2-api.db"
        db.init_db()

        self.product_id = db.persist(
            "https://xiaohongshu.com/goods-detail/api-phase2",
            payload(
                "api-phase2",
                "阶段二商品",
                "2026-09-18 10:00:00",
                shop_id="shop-api",
                shop_name="阶段二店铺",
            ),
        )
        db.add_selection(self.product_id)
        self.app = server.create_app(testing=True)
        self.client = self.app.test_client()

    def tearDown(self):
        db.DATA_DIR, db.DB_PATH = self.old_dir, self.old_path
        self.temp.cleanup()

    def test_shop_and_selection_endpoints(self):
        shops = self.client.get("/api/shops")
        self.assertEqual(shops.status_code, 200)
        shop = shops.get_json()[0]
        self.assertEqual(shop["shop_name"], "阶段二店铺")
        self.assertEqual(shop["product_count"], 1)

        detail = self.client.get(
            "/api/shops/" + shop["shop_key"].replace(":", "%3A") + "/products"
        )
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.get_json()[0]["id"], self.product_id)

        selection = self.client.get("/api/selection")
        self.assertEqual(selection.status_code, 200)
        self.assertEqual(selection.get_json()[0]["id"], self.product_id)

        response = self.client.delete(f"/api/products/{self.product_id}/selection")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get("/api/selection").get_json(), [])
        self.assertTrue(db.is_in_single_monitor(self.product_id))
        self.assertEqual(db.snapshot_count(self.product_id), 1)

    def test_direct_selection_collect_does_not_join_single_monitor(self):
        direct = payload(
            "direct-selection",
            "直接选品商品",
            "2026-09-18 11:00:00",
            shop_id="shop-direct",
            shop_name="直接选品店",
        )
        with mock.patch("server.collector.collect_product", return_value=direct):
            response = self.client.post(
                "/api/products/collect",
                json={"url": "https://xiaohongshu.com/goods-detail/direct-selection", "scope": "selection"},
            )
        self.assertEqual(response.status_code, 200)
        product_id = response.get_json()["product_id"]
        self.assertFalse(db.is_in_single_monitor(product_id))
        selected = db.list_selection_products(as_of="2026-09-18 11:00:00")
        self.assertIn(product_id, [row["id"] for row in selected])


if __name__ == "__main__":
    unittest.main()
