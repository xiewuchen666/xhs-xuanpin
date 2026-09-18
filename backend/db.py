import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("XHS_XUANPIN_DATA_DIR", BASE_DIR.parent / "data"))
DB_PATH = DATA_DIR / "xhs_xuanpin.db"


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with closing(connect()) as conn, conn:
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
        """)


def persist(url: str, data: dict[str, Any]) -> int:
    item_id, title = str(data.get("item_id") or "").strip(), str(data.get("title") or "").strip()
    if not item_id or not title:
        raise ValueError("未取得有效商品标识或标题")
    observed = str(data.get("observed_at") or "").strip()
    if not observed:
        raise ValueError("未取得采集时间")
    precision = str(data.get("sales_precision") or "unknown")
    total_sales = data.get("total_sales") if precision in {"exact", "lower_bound", "approximate"} else None
    with closing(connect()) as conn, conn:
        conn.execute("""
          INSERT INTO products(item_id,url,title,image_url,shop_id,shop_name,price,total_sales,sales_raw,sales_precision,last_collected_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?)
          ON CONFLICT(item_id) DO UPDATE SET
            url=excluded.url,title=excluded.title,image_url=excluded.image_url,
            shop_id=excluded.shop_id,shop_name=excluded.shop_name,price=excluded.price,
            total_sales=excluded.total_sales,sales_raw=excluded.sales_raw,
            sales_precision=excluded.sales_precision,last_collected_at=excluded.last_collected_at
        """, (item_id, url, title, data.get("image_url") or "", data.get("shop_id") or "",
              data.get("shop_name") or "", data.get("price"), total_sales,
              data.get("sales_raw") or "", precision, observed))
        product_id = int(conn.execute("SELECT id FROM products WHERE item_id=?", (item_id,)).fetchone()[0])
        conn.execute("INSERT INTO snapshots(product_id,collected_at,price,total_sales,sales_raw,sales_precision) VALUES(?,?,?,?,?,?)",
                     (product_id, observed, data.get("price"), total_sales, data.get("sales_raw") or "", precision))
        return product_id


def list_products() -> list[dict[str, Any]]:
    with closing(connect()) as conn, conn:
        return [dict(row) for row in conn.execute("SELECT * FROM products ORDER BY last_collected_at DESC,id DESC")]
