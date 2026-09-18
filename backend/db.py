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
            CREATE TABLE IF NOT EXISTS shops(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              platform_shop_id TEXT,
              name TEXT NOT NULL,
              display_name TEXT,
              rating TEXT,
              brand_name TEXT,
              brand_fans_count INTEGER,
              brand_notes_count INTEGER,
              shop_user_id TEXT,
              platform_status TEXT,
              created_at TEXT NOT NULL,
              last_collected_at TEXT
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_shops_platform_shop_id
              ON shops(platform_shop_id)
              WHERE platform_shop_id IS NOT NULL AND platform_shop_id<>'';
            CREATE TABLE IF NOT EXISTS shop_monitor_products(
              shop_id INTEGER NOT NULL REFERENCES shops(id) ON DELETE CASCADE,
              product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
              added_at TEXT NOT NULL,
              PRIMARY KEY(shop_id,product_id)
            );
            CREATE INDEX IF NOT EXISTS idx_shop_monitor_products_product
              ON shop_monitor_products(product_id);
        """)

        product_columns = _columns(conn, "products")
        product_additions = {
            "monitor_state": "TEXT NOT NULL DEFAULT 'active'",
            "last_attempt_at": "TEXT",
            "last_attempt_status": "TEXT",
            "last_attempt_error": "TEXT",
        }
        for name, declaration in product_additions.items():
            if name not in product_columns:
                conn.execute(f"ALTER TABLE products ADD COLUMN {name} {declaration}")

        snapshot_columns = _columns(conn, "snapshots")
        snapshot_additions = {
            "is_midnight": "INTEGER NOT NULL DEFAULT 0",
            "baseline_day": "TEXT",
        }
        for name, declaration in snapshot_additions.items():
            if name not in snapshot_columns:
                conn.execute(f"ALTER TABLE snapshots ADD COLUMN {name} {declaration}")

        conn.executescript("""
            CREATE TABLE IF NOT EXISTS settings(
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS jobs(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              kind TEXT NOT NULL DEFAULT 'collect',
              scope TEXT NOT NULL DEFAULT 'all',
              status TEXT NOT NULL DEFAULT 'queued',
              created_at TEXT NOT NULL,
              started_at TEXT,
              finished_at TEXT,
              cancel_requested INTEGER NOT NULL DEFAULT 0,
              is_midnight INTEGER NOT NULL DEFAULT 0,
              error TEXT,
              parent_id INTEGER
            );
            CREATE TABLE IF NOT EXISTS job_items(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
              product_id INTEGER,
              url TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'queued',
              message TEXT,
              started_at TEXT,
              finished_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status,id);
            CREATE INDEX IF NOT EXISTS idx_job_items_job ON job_items(job_id,id);
        """)
        defaults = {
            "auto_enabled": "1",
            "auto_interval_minutes": "60",
            "midnight_enabled": "1",
            "day_tolerance_minutes": "5",
            "window_tolerance_minutes": "30",
            "stale_minutes": "120",
        }
        conn.executemany(
            "INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)",
            list(defaults.items()),
        )

        # Before phase 1 every row in products represented a monitored product.
        # Backfill only on the first migration so later removals stay removed.
        if not single_monitor_existed:
            conn.execute("""
                INSERT OR IGNORE INTO single_monitor_products(product_id, added_at)
                SELECT id, COALESCE(NULLIF(last_collected_at,''), ?) FROM products
            """, (now_text(),))


def get_settings() -> dict[str, str]:
    with closing(connect()) as conn:
        return {
            str(row["key"]): str(row["value"])
            for row in conn.execute("SELECT key,value FROM settings")
        }


def set_settings(values: dict[str, str]) -> None:
    with closing(connect()) as conn, conn:
        conn.executemany(
            """
            INSERT INTO settings(key,value) VALUES(?,?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            [(key, str(value)) for key, value in values.items()],
        )


def get_monitored_products_raw(scope: str = "all") -> list[dict[str, Any]]:
    conditions = {
        "single": "EXISTS(SELECT 1 FROM single_monitor_products sm WHERE sm.product_id=p.id)",
        "shop": "EXISTS(SELECT 1 FROM shop_monitor_products sh WHERE sh.product_id=p.id)",
        "selection": "EXISTS(SELECT 1 FROM selection_pool_products sp WHERE sp.product_id=p.id)",
        "all": """(
            EXISTS(SELECT 1 FROM single_monitor_products sm WHERE sm.product_id=p.id)
            OR EXISTS(SELECT 1 FROM shop_monitor_products sh WHERE sh.product_id=p.id)
            OR EXISTS(SELECT 1 FROM selection_pool_products sp WHERE sp.product_id=p.id)
        )""",
    }
    if scope not in conditions:
        raise ValueError("无效采集范围")
    with closing(connect()) as conn:
        return [
            dict(row)
            for row in conn.execute(
                "SELECT p.* FROM products p WHERE p.monitor_state='active' AND "
                + conditions[scope]
                + " ORDER BY p.id"
            )
        ]


def mark_product_error(product_id: int, message: str) -> None:
    safe = str(message or "采集失败")[:800]
    with closing(connect()) as conn, conn:
        conn.execute(
            """
            UPDATE products
            SET last_attempt_at=?,last_attempt_status='failed',last_attempt_error=?
            WHERE id=?
            """,
            (now_text(), safe, product_id),
        )


def _shop_membership(conn: sqlite3.Connection, product_id: int, data: dict[str, Any]) -> int:
    shop_name = str(data.get("shop_name") or "").strip()
    platform_shop_id = str(data.get("shop_id") or "").strip()
    if not shop_name:
        raise ValueError("未识别店铺名称；无法加入店铺监控")

    shop = (
        conn.execute(
            "SELECT * FROM shops WHERE platform_shop_id=?",
            (platform_shop_id,),
        ).fetchone()
        if platform_shop_id
        else None
    )
    if not shop and not platform_shop_id:
        shop = conn.execute(
            """
            SELECT * FROM shops
            WHERE COALESCE(display_name,name)=?
              AND (platform_shop_id IS NULL OR platform_shop_id='')
            ORDER BY id LIMIT 1
            """,
            (shop_name,),
        ).fetchone()

    if shop:
        shop_id = int(shop["id"])
    else:
        shop_id = int(
            conn.execute(
                """
                INSERT INTO shops(platform_shop_id,name,display_name,created_at)
                VALUES(?,?,?,?)
                """,
                (platform_shop_id or None, shop_name, shop_name, now_text()),
            ).lastrowid
        )

    conn.execute(
        "DELETE FROM shop_monitor_products WHERE product_id=? AND shop_id<>?",
        (product_id, shop_id),
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO shop_monitor_products(shop_id,product_id,added_at)
        VALUES(?,?,?)
        """,
        (shop_id, product_id, now_text()),
    )
    conn.execute(
        """
        UPDATE shops
        SET display_name=?,
            rating=COALESCE(NULLIF(?,''),rating),
            brand_name=COALESCE(NULLIF(?,''),brand_name),
            brand_fans_count=COALESCE(?,brand_fans_count),
            brand_notes_count=COALESCE(?,brand_notes_count),
            shop_user_id=COALESCE(NULLIF(?,''),shop_user_id),
            platform_status=COALESCE(NULLIF(?,''),platform_status),
            last_collected_at=?
        WHERE id=?
        """,
        (
            shop_name,
            data.get("shop_score") or data.get("rating") or "",
            data.get("shop_brand_name") or "",
            data.get("shop_fans_count"),
            data.get("shop_notes_count"),
            data.get("shop_user_id") or "",
            data.get("shop_status") or "",
            now_text(),
            shop_id,
        ),
    )
    return shop_id


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
    join_shop: bool = False,
    expected_product_id: int | None = None,
    is_midnight: bool = False,
    baseline_day: str | None = None,
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
            url=excluded.url,
            title=excluded.title,
            image_url=COALESCE(NULLIF(excluded.image_url,''),products.image_url),
            shop_id=COALESCE(NULLIF(excluded.shop_id,''),products.shop_id),
            shop_name=COALESCE(NULLIF(excluded.shop_name,''),products.shop_name),
            price=COALESCE(excluded.price,products.price),
            total_sales=CASE
              WHEN excluded.sales_precision IN ('exact','lower_bound','approximate')
                   AND excluded.total_sales IS NOT NULL
              THEN excluded.total_sales ELSE products.total_sales END,
            sales_raw=CASE
              WHEN excluded.sales_precision IN ('exact','lower_bound','approximate')
                   AND excluded.total_sales IS NOT NULL
              THEN excluded.sales_raw ELSE products.sales_raw END,
            sales_precision=CASE
              WHEN excluded.sales_precision IN ('exact','lower_bound','approximate')
                   AND excluded.total_sales IS NOT NULL
              THEN excluded.sales_precision ELSE products.sales_precision END,
            last_collected_at=excluded.last_collected_at
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

        conn.execute(
            "UPDATE products SET last_attempt_at=?,last_attempt_status='success',last_attempt_error='' WHERE id=?",
            (now_text(), product_id),
        )
        conn.execute("""
            INSERT INTO snapshots(
              product_id,collected_at,price,total_sales,sales_raw,sales_precision,is_midnight,baseline_day
            ) VALUES(?,?,?,?,?,?,?,?)
        """, (
            product_id,
            observed,
            data.get("price"),
            total_sales,
            data.get("sales_raw") or "",
            precision,
            int(is_midnight),
            baseline_day if is_midnight else None,
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

        already_in_shop = conn.execute(
            "SELECT 1 FROM shop_monitor_products WHERE product_id=?",
            (product_id,),
        ).fetchone() is not None
        if join_shop or already_in_shop:
            _shop_membership(conn, product_id, data)

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


def is_in_selection(product_id: int) -> bool:
    with closing(connect()) as conn:
        return conn.execute(
            "SELECT 1 FROM selection_pool_products WHERE product_id=?", (product_id,)
        ).fetchone() is not None


def is_in_shop_monitor(product_id: int) -> bool:
    with closing(connect()) as conn:
        return conn.execute(
            "SELECT 1 FROM shop_monitor_products WHERE product_id=?", (product_id,)
        ).fetchone() is not None


def is_monitored_product(product_id: int) -> bool:
    with closing(connect()) as conn:
        return conn.execute(
            """
            SELECT 1
            FROM products p
            WHERE p.id=? AND (
              EXISTS(SELECT 1 FROM single_monitor_products sm WHERE sm.product_id=p.id)
              OR EXISTS(SELECT 1 FROM shop_monitor_products sh WHERE sh.product_id=p.id)
              OR EXISTS(SELECT 1 FROM selection_pool_products sp WHERE sp.product_id=p.id)
            )
            """,
            (product_id,),
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
    cfg = {
        str(row["key"]): str(row["value"])
        for row in conn.execute("SELECT key,value FROM settings")
    }
    def number(key: str, fallback: int) -> int:
        try:
            return int(cfg.get(key, fallback))
        except (TypeError, ValueError):
            return fallback
    return [
        metrics.enrich(
            row,
            history[int(row["id"])],
            as_of=as_of,
            day_tolerance=number("day_tolerance_minutes", 5),
            window_tolerance=number("window_tolerance_minutes", 30),
            stale_minutes=number("stale_minutes", 120),
        )
        for row in rows
    ]


def list_products(as_of=None) -> list[dict[str, Any]]:
    with closing(connect()) as conn:
        rows = [dict(row) for row in conn.execute("""
            SELECT
              p.*,
              sm.added_at AS monitored_at,
              CASE WHEN sp.product_id IS NULL THEN 0 ELSE 1 END AS in_selection_pool,
              CASE WHEN EXISTS(
                SELECT 1 FROM shop_monitor_products sh WHERE sh.product_id=p.id
              ) THEN 1 ELSE 0 END AS in_shop_monitor
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
              CASE WHEN EXISTS(
                SELECT 1 FROM shop_monitor_products sh WHERE sh.product_id=p.id
              ) THEN 1 ELSE 0 END AS in_shop_monitor,
              1 AS in_selection_pool
            FROM products p
            JOIN selection_pool_products sp ON sp.product_id=p.id
            LEFT JOIN single_monitor_products sm ON sm.product_id=p.id
            ORDER BY sp.added_at DESC,p.last_collected_at DESC,p.id DESC
        """).fetchall()]
        return _enrich_rows(conn, rows, as_of=as_of)


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


def _shop_monitor_products(as_of=None) -> list[dict[str, Any]]:
    with closing(connect()) as conn:
        rows = [
            dict(row)
            for row in conn.execute(
                """
                SELECT
                  p.*,
                  sh.shop_id AS monitor_shop_id,
                  sh.added_at AS shop_monitored_at,
                  CASE WHEN sm.product_id IS NULL THEN 0 ELSE 1 END AS in_single_monitor,
                  CASE WHEN sp.product_id IS NULL THEN 0 ELSE 1 END AS in_selection_pool,
                  1 AS in_shop_monitor
                FROM products p
                JOIN shop_monitor_products sh ON sh.product_id=p.id
                LEFT JOIN single_monitor_products sm ON sm.product_id=p.id
                LEFT JOIN selection_pool_products sp ON sp.product_id=p.id
                ORDER BY sh.added_at DESC,p.last_collected_at DESC,p.id DESC
                """
            ).fetchall()
        ]
        return _enrich_rows(conn, rows, as_of=as_of)


def list_shops(as_of=None) -> list[dict[str, Any]]:
    products = _shop_monitor_products(as_of=as_of)
    grouped: dict[int, list[dict[str, Any]]] = {}
    for product in products:
        grouped.setdefault(int(product["monitor_shop_id"]), []).append(product)

    with closing(connect()) as conn:
        shop_rows = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM shops ORDER BY COALESCE(last_collected_at,created_at) DESC,id DESC"
            )
        ]

    result: list[dict[str, Any]] = []
    for shop in shop_rows:
        items = grouped.get(int(shop["id"]), [])
        if not items:
            continue
        health, health_label = _shop_health(items)
        product_latest = max(
            (str(item.get("last_collected_at") or "") for item in items),
            default="",
        )
        latest = max(product_latest, str(shop.get("last_collected_at") or ""))
        result.append({
            "shop_key": str(shop["id"]),
            "shop_db_id": int(shop["id"]),
            "shop_id": str(shop.get("platform_shop_id") or ""),
            "shop_name": str(shop.get("display_name") or shop.get("name") or "店铺未识别"),
            "rating": shop.get("rating"),
            "brand_name": shop.get("brand_name"),
            "brand_fans_count": shop.get("brand_fans_count"),
            "brand_notes_count": shop.get("brand_notes_count"),
            "shop_user_id": shop.get("shop_user_id"),
            "platform_status": shop.get("platform_status"),
            "product_count": len(items),
            "active_count": sum(1 for item in items if item.get("monitor_state") == "active"),
            "today": _aggregate_metric(items, "today"),
            "rolling24": _aggregate_metric(items, "rolling24"),
            "last_collected_at": latest,
            "health": health,
            "health_label": health_label,
            "products": items,
        })
    result.sort(
        key=lambda row: (row["last_collected_at"], row["shop_name"]),
        reverse=True,
    )
    return result


def list_shop_products(shop_key: str, as_of=None) -> list[dict[str, Any]]:
    try:
        shop_id = int(shop_key)
    except (TypeError, ValueError):
        return []
    return [
        product
        for product in _shop_monitor_products(as_of=as_of)
        if int(product.get("monitor_shop_id") or 0) == shop_id
    ]


def set_monitor_state(product_id: int, state: str) -> None:
    if state not in VALID_MONITOR_STATES:
        raise ValueError("无效监控状态")
    with closing(connect()) as conn, conn:
        if not conn.execute("SELECT 1 FROM products WHERE id=?", (product_id,)).fetchone():
            raise ValueError("商品不存在")
        monitored = conn.execute(
            """
            SELECT 1 FROM products p
            WHERE p.id=? AND (
              EXISTS(SELECT 1 FROM single_monitor_products sm WHERE sm.product_id=p.id)
              OR EXISTS(SELECT 1 FROM shop_monitor_products sh WHERE sh.product_id=p.id)
              OR EXISTS(SELECT 1 FROM selection_pool_products sp WHERE sp.product_id=p.id)
            )
            """,
            (product_id,),
        ).fetchone()
        if not monitored:
            raise ValueError("商品不在持续监控范围中")
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


def add_shop_monitor(product_id: int) -> int:
    with closing(connect()) as conn, conn:
        product = conn.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
        if not product:
            raise ValueError("商品不存在")
        return _shop_membership(conn, product_id, dict(product))


def remove_shop_monitor(product_id: int) -> None:
    with closing(connect()) as conn, conn:
        if not conn.execute("SELECT 1 FROM products WHERE id=?", (product_id,)).fetchone():
            raise ValueError("商品不存在")
        conn.execute(
            "DELETE FROM shop_monitor_products WHERE product_id=?",
            (product_id,),
        )


def add_selection(product_id: int) -> None:
    with closing(connect()) as conn, conn:
        if not conn.execute("SELECT 1 FROM products WHERE id=?", (product_id,)).fetchone():
            raise ValueError("商品不存在")
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
