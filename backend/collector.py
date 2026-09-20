import logging
import os
import re
import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

BASE_DIR = Path(__file__).resolve().parent
PROFILE_DIR = Path(os.environ.get("XHS_XUANPIN_DATA_DIR", BASE_DIR.parent / "data")) / "browser_profile"
COLLECT_LOCK = threading.Lock()
DETAIL_API = "/api/store/jpd/edith/detail/h5/toc"
logger = logging.getLogger(__name__)


def parse_sales(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    result = {"total_sales": None, "sales_raw": raw, "sales_precision": "unknown"}
    match = re.fullmatch(r"已售\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)\s*([千万]?)\s*(\+?)\s*(?:件|单)?", raw)
    if not match:
        return result
    number, unit, plus = match.groups()
    try:
        value = Decimal(number.replace(",", "")) * {"": 1, "千": 1000, "万": 10000}[unit]
        if not value.is_finite() or value < 0 or value > 10**15 or value != value.to_integral_value():
            return result
        if "." in number and not unit:
            return result
        result.update(total_sales=int(value), sales_precision="lower_bound" if plus else ("approximate" if unit else "exact"))
    except (InvalidOperation, ValueError):
        pass
    return result


def validate_url(url: str) -> str:
    raw = str(url or "").strip()
    try:
        parts = urlsplit(raw)
        host = (parts.hostname or "").lower().rstrip(".")
        allowed = any(host == domain or host.endswith("." + domain) for domain in ("xiaohongshu.com", "xhslink.com"))
        if len(raw) > 4096 or parts.scheme not in {"https", "http"} or not allowed or parts.username or parts.password or parts.port not in {None, 80, 443}:
            raise ValueError
    except (ValueError, TypeError):
        raise ValueError("仅支持小红书商品链接及 xhslink.com 分享链接；不允许本机、内网或其他站点")
    return raw


def extract_share_urls(text: str) -> list[str]:
    raw = str(text or "").strip()
    if not raw:
        return []
    candidates = re.findall(
        r"https?://(?:[A-Za-z0-9-]+\.)?(?:xiaohongshu\.com|xhslink\.com)/[^\s<>\"']+",
        raw,
        flags=re.IGNORECASE,
    )
    if not candidates:
        candidates = re.findall(
            r"(?:[A-Za-z0-9-]+\.)?(?:xiaohongshu\.com|xhslink\.com)/[^\s<>\"']+",
            raw,
            flags=re.IGNORECASE,
        )
        candidates = ["https://" + candidate for candidate in candidates]

    result: list[str] = []
    for candidate in candidates:
        candidate = candidate.rstrip("，。；;、）)]}！!？?")
        try:
            validated = validate_url(candidate)
        except ValueError:
            continue
        if validated not in result:
            result.append(validated)
    return result


def _display_price(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        price = Decimal(str(value).strip().replace("¥", "").replace("￥", "").replace(",", ""))
        return float(price) if price.is_finite() and 0 <= price <= 100000000 else None
    except (InvalidOperation, ValueError):
        return None


def _pick_item_id(data: dict[str, Any], url: str) -> str:
    desc = data.get("descriptionH5") or data.get("descriptionMain") or {}
    item_id = str(desc.get("skuId") or desc.get("sku_id") or "").strip()
    if item_id:
        return item_id
    match = re.search(r"/goods-detail/([0-9a-fA-F]{20,32})", url or "")
    return match.group(1) if match else ""


def _pick_main_image(data: dict[str, Any]) -> str:
    images = (data.get("carouselH5") or data.get("carouselMain") or {}).get("images") or []
    if not images:
        return ""
    first = images[0]
    url = first if isinstance(first, str) else (first.get("url") or first.get("url_default") or first.get("imageUrl") or first.get("image_url") or "") if isinstance(first, dict) else ""
    url = str(url).strip()
    return "https:" + url if url.startswith("//") else url


def parse_detail_response(
    body: dict[str, Any],
    page_url: str = "",
    diagnostics: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    try:
        template_data = body.get("data", {}).get("template_data") or []
        if not template_data:
            if diagnostics is not None:
                diagnostics["reason"] = "响应缺少 data.template_data"
            return None
        data = template_data[0]
        desc = data.get("descriptionH5") or data.get("descriptionMain") or {}
        seller = data.get("sellerH5") or data.get("sellerMain") or {}
        price_h5 = data.get("priceH5") or {}
        deal = price_h5.get("dealPrice") or {}
        price_raw = deal.get("price")
        price_source = "priceH5.dealPrice.price"
        if price_raw is None:
            price_raw = price_h5.get("highlightPrice")
            price_source = "priceH5.highlightPrice"
        price = _display_price(price_raw)
        price_quality = "display_price" if price is not None else "missing"
        if price_raw is None:
            price_raw = (data.get("bottomBarMainH5") or {}).get("price")
            if price_raw is not None:
                price_source, price_quality, price = "bottomBarMainH5.price", "unverified_unit", None
        fans_count = seller.get("fansAmount") or seller.get("fansCount") or ""
        if isinstance(fans_count, str):
            fans_count = re.sub(r"^\s*粉丝数\s*", "", fans_count).strip()
        result = {
            "item_id": _pick_item_id(data, page_url),
            "title": str(desc.get("name") or "").strip(),
            "shop_id": str(seller.get("id") or "").strip(),
            "shop_name": str(seller.get("name") or "").strip(),
            "fans_count": fans_count,
            "rating": seller.get("sellerScore") or seller.get("score") or "",
            "image_url": _pick_main_image(data),
            "price": price,
            "price_raw": str(price_raw) if price_raw is not None else "",
            "price_source": price_source,
            "price_quality": price_quality,
            "identity_basis": "sku" if desc.get("skuId") or desc.get("sku_id") else "url",
            "counter_scope": "unverified",
            "collector_version": "2.0",
            **parse_sales(str(price_h5.get("itemAnalysisDataText") or "")),
        }
        if not result["item_id"] or not result["title"]:
            if diagnostics is not None:
                missing = "商品标识" if not result["item_id"] else "商品标题"
                diagnostics["reason"] = "响应缺少有效" + missing
            return None
        return result
    except Exception as exc:
        if diagnostics is not None:
            diagnostics["reason"] = "响应结构解析异常：" + type(exc).__name__
        return None


def _collect_shop_details(page, shop_id: str) -> dict[str, Any]:
    if not shop_id:
        return {}
    try:
        payload = page.evaluate("""
            async (shopId) => {
              const response = await fetch(`/api/store/vs/${shopId}/details`, {
                credentials: 'include', signal: AbortSignal.timeout(8000)
              });
              if (!response.ok) return null;
              return await response.json();
            }
        """, shop_id)
        data = (payload or {}).get("data") or {}
        brand, popup = data.get("brand") or {}, data.get("popup_shop_info") or {}
        return {
            "shop_score": data.get("shop_score") or data.get("grade") or "",
            "shop_brand_name": str(brand.get("name") or "").strip(),
            "shop_fans_count": brand.get("fans_num"),
            "shop_notes_count": brand.get("notes_num"),
            "shop_user_id": str((data.get("user_info") or {}).get("user_id") or brand.get("id") or "").strip(),
            "shop_status": str(popup.get("status") or "").strip(),
        }
    except Exception:
        return {}


def collect_product(url: str, timeout_ms: int = 30000) -> dict[str, Any]:
    url = validate_url(url)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Playwright 尚未安装") from exc
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    with COLLECT_LOCK:
        captured: dict[str, Any] = {}
        last_status = None
        detail_seen = False
        parse_reason = ""
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR), channel="chrome", headless=True,
                locale="zh-CN", viewport={"width": 1365, "height": 900})
            try:
                page = context.pages[0] if context.pages else context.new_page()

                def guard_navigation(route):
                    if route.request.is_navigation_request():
                        try:
                            validate_url(route.request.url)
                        except ValueError:
                            route.abort()
                            return
                    route.continue_()

                def on_response(response):
                    nonlocal detail_seen, last_status, parse_reason
                    try:
                        validate_url(response.url)
                    except ValueError:
                        return
                    if DETAIL_API in response.url and "/variant" not in response.url:
                        detail_seen = True
                        last_status = response.status
                        if response.status == 200:
                            diagnostics: dict[str, str] = {}
                            try:
                                body = response.json()
                            except Exception as exc:
                                parse_reason = "响应 JSON 解析失败：" + type(exc).__name__
                                return
                            parsed = parse_detail_response(body, page.url, diagnostics)
                            if parsed:
                                parsed["observed_at"] = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
                                captured.update(parsed)
                            else:
                                parse_reason = diagnostics.get("reason", "详情响应无法解析")

                page.route("**/*", guard_navigation)
                page.on("response", on_response)
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                for _ in range(24):
                    if captured:
                        break
                    page.wait_for_timeout(500)
                if not captured:
                    try:
                        text = page.locator("body").inner_text(timeout=2000)
                    except Exception:
                        text = ""
                    if any(word in text for word in ("验证码", "安全验证", "异常访问", "请完成验证")):
                        raise RuntimeError("小红书要求人工安全验证，后台采集已停止，未尝试绕过验证")
                    logger.warning(
                        "Product detail capture failed: detail_seen=%s status=%s parse_reason=%s",
                        detail_seen,
                        last_status,
                        parse_reason or ("未收到目标详情接口响应" if not detail_seen else "无"),
                    )
                    if last_status and last_status != 200:
                        raise RuntimeError(f"商品详情接口返回 HTTP {last_status}")
                    raise RuntimeError("未捕获到商品详情数据，可能是链接失效、网络波动或页面接口发生变化")
                captured.update(_collect_shop_details(page, str(captured.get("shop_id") or "")))
                return dict(captured)
            finally:
                context.close()
