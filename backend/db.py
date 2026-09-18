import os
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import metrics

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("XHS_XUANPIN_DATA_DIR", BASE_DIR.parent / "data"))
DB_PATH = DATA_DIR / "xhs_xuanpin.db"
VALID_MONITOR_STATES = {"active", "paused"}


def now_text() -> str:
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})")}


def init_db() -> None:
    with closing(connect()) as conn, conn:
        single_monitor_existed = _table_exists(conn, "single_monitor_products")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS products(
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
            CREATE TABLE IF NOT EXISTS snapshots(
              id INTEGER PRIMARY KEY,
              product_id INTEGER NOT NULL REFERENCES products(id),
              collected_at TEXT NOT NULL,
              price REAL,
              total_sales INTEGER,
              sales_raw TEXT NOT NULL DEFAULT '',
              sales_precision TEXT NOT NULL DEFAULT 'unknown'
            );
            CREATE INDEX IF NOT EXISTS idx_snapshots_product_time
              ON snapshots(product_id, collected_at, id);

            CREATE TABLE IF NOT EXISTS single_monitor_products(
              product_id INTEGER PRIMARY KEY REFERENCES products(id) ON DELETE CASCADE,
              added_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS selection_pool_products(
              product_id INTEGER PRIMARY KEY REFERENCES products(id) ON DELETE CASCADE,
              added_at TEXT NOT NULL
            );
        """)

        product_columns = _columns(conn, "products")
        if "monitor_state" not in product_columns:
            conn.execute(
                "ALTER TABLE products ADD COLUMN monitor_state TEXT NOT NULL DEFAULT 'active'"
            )

        # Before phase 1 every row in products represented a monitored product.
        # Backfill only on the first migration so later removals stay removed.
        if not single_monitor_existed:
            conn.execute("""
                INSERT OR IGNORE INTO single_monitor_products(product_id, added_at)
                SELECT id, COALESCE(NULLIF(last_collected_at,''), ?) FROM products
            """, (now_text(),))


def _normalize_collection(data: dict[str, Any]) -> tuple[str, str, str, str, int | None]:
    item_id = str(data.get("item_id") or "").strip()
    title = str(data.get("title") or "").strip()
    observed = str(data.get("observed_at") or "").strip()
    if not item_id or not title:
        raise ValueError("未取得有效商品标识或标题")
    if not observed:
        raise ValueError("未取得采集时间")
    precision = str(data.get("sales_precision") or "unknown")
    total_sales = (
        data.get("total_sales")
        if precision in {"exact", "lower_bound", "approximate"}
        else None
    )
    return item_id, title, observed, precision, total_sales


def persist(
    url: str,
    data: dict[str, Any],
    *,
    join_single: bool = True,
    expected_product_id: int | None = None,
) -> int:
    item_id, title, observed, precision, total_sales = _normalize_collection(data)

    with closing(connect()) as conn, conn:
        if expected_product_id is not None:
            expected = conn.execute(
                "SELECT id,item_id FROM products WHERE id=?", (expected_product_id,)
            ).fetchone()
            if not expected:
                raise ValueError("商品不存在")
            if str(expected["item_id"]) != item_id:
                raise ValueError("商品标识发生变化；为保护历史，本次采集未写入")

        conn.execute("""
          INSERT INTO products(
            item_id,url,title,image_url,shop_id,shop_name,price,total_sales,
            sales_raw,sales_precision,last_collected_at,monitor_state
          )
          VALUES(?,?,?,?,?,?,?,?,?,?,?,'active')
          ON CONFLICT(item_id) DO UPDATE SET
            url=excluded.url,title=excluded.title,image_url=excluded.image_url,
            shop_id=excluded.shop_id,shop_name=excluded.shop_name,price=excluded.price,
            total_sales=excluded.total_sales,sales_raw=excluded.sales_raw,
            sales_precision=excluded.sales_precision,last_collected_at=excluded.last_collected_at
        """, (
            item_id,
            url,
            title,
            data.get("image_url") or "",
            data.get("shop_id") or "",
            data.get("shop_name") or "",
            data.get("price"),
            total_sales,
            data.get("sales_raw") or "",
            precision,
            observed,
        ))

        product_id = int(
            conn.execute("SELECT id FROM products WHERE item_id=?", (item_id,)).fetchone()[0]
        )
        if expected_product_id is not None and product_id != expected_product_id:
            raise ValueError("商品标识发生变化；为保护历史，本次采集未写入")

        conn.execute("""
            INSERT INTO snapshots(
              product_id,collected_at,price,total_sales,sales_raw,sales_precision
            ) VALUES(?,?,?,?,?,?)
        """, (
            product_id,
            observed,
            data.get("price"),
            total_sales,
            data.get("sales_raw") or "",
            precision,
        ))

        if join_single:
            conn.execute(
                "INSERT OR IGNORE INTO single_monitor_products(product_id,added_at) VALUES(?,?)",
                (product_id, now_text()),
            )
            conn.execute(
                "UPDATE products SET monitor_state='active' WHERE id=?",
                (product_id,),
            )
        return product_id


def get_product(product_id: int) -> dict[str, Any] | None:
    with closing(connect()) as conn:
        row = conn.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
        return dict(row) if row else None


def is_in_single_monitor(product_id: int) -> bool:
    with closing(connect()) as conn:
        return conn.execute(
            "SELECT 1 FROM single_monitor_products WHERE product_id=?", (product_id,)
        ).fetchone() is not None


def _enrich_rows(
    conn: sqlite3.Connection,
    rows: list[dict[str, Any]],
    *,
    as_of=None,
) -> list[dict[str, Any]]:
    if not rows:
        return []
    ids = [int(row["id"]) for row in rows]
    placeholders = ",".join("?" for _ in ids)
    history: dict[int, list[dict[str, Any]]] = {product_id: [] for product_id in ids}
    for snap in conn.execute(
        f"SELECT * FROM snapshots WHERE product_id IN ({placeholders}) ORDER BY product_id,collected_at,id",
        ids,
    ):
        history[int(snap["product_id"])].append(dict(snap))
    return [
        metrics.enrich(row, history[int(row["id"])], as_of=as_of)
        for row in rows
    ]


def list_products(as_of=None) -> list[dict[str, Any]]:
    with closing(connect()) as conn:
        rows = [dict(row) for row in conn.execute("""
            SELECT
              p.*,
              sm.added_at AS monitored_at,
              CASE WHEN sp.product_id IS NULL THEN 0 ELSE 1 END AS in_selection_pool
            FROM products p
            JOIN single_monitor_products sm ON sm.product_id=p.id
            LEFT JOIN selection_pool_products sp ON sp.product_id=p.id
            ORDER BY p.last_collected_at DESC,p.id DESC
        """).fetchall()]
        return _enrich_rows(conn, rows, as_of=as_of)


def list_selection_products(as_of=None) -> list[dict[str, Any]]:
    with closing(connect()) as conn:
        rows = [dict(row) for row in conn.execute("""
            SELECT
              p.*,
              sp.added_at AS selected_at,
              CASE WHEN sm.product_id IS NULL THEN 0 ELSE 1 END AS in_single_monitor,
              1 AS in_selection_pool
            FROM products p
            JOIN selection_pool_products sp ON sp.product_id=p.id
            LEFT JOIN single_monitor_products sm ON sm.product_id=p.id
            ORDER BY sp.added_at DESC,p.last_collected_at DESC,p.id DESC
        """).fetchall()]
        return _enrich_rows(conn, rows, as_of=as_of)


def _shop_identity(product: dict[str, Any]) -> tuple[str, str]:
    shop_id = str(product.get("shop_id") or "").strip()
    shop_name = str(product.get("shop_name") or "").strip() or "店铺未识别"
    if shop_id:
        return f"id:{shop_id}", shop_name
    return f"name:{shop_name}", shop_name


def _aggregate_metric(products: list[dict[str, Any]], key: str) -> dict[str, Any]:
    metric_rows = [product.get(key) or {} for product in products]
    valid = [metric for metric in metric_rows if metric.get("value") is not None]
    approximate = any(metric.get("quality") == "approximate" for metric in valid)
    return {
        "value": sum(int(metric.get("value") or 0) for metric in valid) if valid else None,
        "quality": "approximate" if approximate else ("exact" if valid else "missing"),
        "covered": len(valid),
        "total": len(products),
        "approximate": approximate,
        "reason": (
            f"店铺内 {len(valid)}/{len(products)} 个已监控商品具备有效指标；仅汇总有效商品"
            if valid
            else "店铺内暂无商品具备可汇总的有效指标"
        ),
    }


def _shop_health(products: list[dict[str, Any]]) -> tuple[str, str]:
    if any(product.get("health") == "danger" for product in products):
        return "danger", "存在异常"
    if any(product.get("health") == "warning" for product in products):
        return "warning", "需更新"
    if products and all(product.get("monitor_state") == "paused" for product in products):
        return "muted", "已暂停"
    if any(product.get("health") == "muted" for product in products):
        return "muted", "部分暂停"
    return "success", "正常"


def list_shops(as_of=None) -> list[dict[str, Any]]:
    products = list_products(as_of=as_of)
    grouped: dict[str, dict[str, Any]] = {}
    for product in products:
        shop_key, shop_name = _shop_identity(product)
        group = grouped.setdefault(
            shop_key,
            {
                "shop_key": shop_key,
                "shop_id": str(product.get("shop_id") or ""),
                "shop_name": shop_name,
                "products": [],
            },
        )
        group["products"].append(product)

    result: list[dict[str, Any]] = []
    for group in grouped.values():
        items = group.pop("products")
        health, health_label = _shop_health(items)
        latest = max((str(item.get("last_collected_at") or "") for item in items), default="")
        result.append({
            **group,
            "product_count": len(items),
            "active_count": sum(1 for item in items if item.get("monitor_state") == "active"),
            "today": _aggregate_metric(items, "today"),
            "rolling24": _aggregate_metric(items, "rolling24"),
            "last_collected_at": latest,
            "health": health,
            "health_label": health_label,
            "products": items,
        })
    result.sort(key=lambda row: (row["last_collected_at"], row["shop_name"]), reverse=True)
    return result


def list_shop_products(shop_key: str, as_of=None) -> list[dict[str, Any]]:
    return [
        product
        for product in list_products(as_of=as_of)
        if _shop_identity(product)[0] == shop_key
    ]


def set_monitor_state(product_id: int, state: str) -> None:
    if state not in VALID_MONITOR_STATES:
        raise ValueError("无效监控状态")
    with closing(connect()) as conn, conn:
        if not conn.execute("SELECT 1 FROM products WHERE id=?", (product_id,)).fetchone():
            raise ValueError("商品不存在")
        if not conn.execute(
            "SELECT 1 FROM single_monitor_products WHERE product_id=?", (product_id,)
        ).fetchone():
            raise ValueError("商品不在单品监控中")
        conn.execute(
            "UPDATE products SET monitor_state=? WHERE id=?", (state, product_id)
        )


def remove_single_monitor(product_id: int) -> None:
    with closing(connect()) as conn, conn:
        if not conn.execute("SELECT 1 FROM products WHERE id=?", (product_id,)).fetchone():
            raise ValueError("商品不存在")
        conn.execute(
            "DELETE FROM single_monitor_products WHERE product_id=?", (product_id,)
        )


def add_selection(product_id: int) -> None:
    with closing(connect()) as conn, conn:
        if not conn.execute("SELECT 1 FROM products WHERE id=?", (product_id,)).fetchone():
            raise ValueError("商品不存在")
        conn.execute(
            "UPDATE products SET monitor_state='active' WHERE id=?",
            (product_id,),
        )
        conn.execute(
            "INSERT OR IGNORE INTO selection_pool_products(product_id,added_at) VALUES(?,?)",
            (product_id, now_text()),
        )


def remove_selection(product_id: int) -> None:
    with closing(connect()) as conn, conn:
        if not conn.execute("SELECT 1 FROM products WHERE id=?", (product_id,)).fetchone():
            raise ValueError("商品不存在")
        conn.execute(
            "DELETE FROM selection_pool_products WHERE product_id=?",
            (product_id,),
        )


def snapshot_count(product_id: int) -> int:
    with closing(connect()) as conn:
        return int(
            conn.execute(
                "SELECT COUNT(*) FROM snapshots WHERE product_id=?", (product_id,)
            ).fetchone()[0]
        )
