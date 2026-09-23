import asyncio
import ipaddress
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


class ProductTerminalError(RuntimeError):
    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status


class BatchCollectionError(RuntimeError):
    def __init__(self, reason: str, message: str, *, requires_manual: bool = False):
        super().__init__(message)
        self.reason = reason
        self.requires_manual = requires_manual


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


def _pick_shop_logo(*sources: dict[str, Any]) -> str:
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in ("logo", "logo_url", "logoUrl", "avatar", "avatar_url", "avatarUrl"):
            value = source.get(key)
            if isinstance(value, dict):
                value = next((value.get(name) for name in ("url", "url_default", "imageUrl", "image_url") if value.get(name)), "")
            url = str(value or "").strip()
            if url.startswith("//"):
                url = "https:" + url
            try:
                parts = urlsplit(url)
                if len(url) > 2048 or parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
                    continue
                host = parts.hostname.lower()
                try:
                    if not ipaddress.ip_address(host).is_global:
                        continue
                except ValueError:
                    if "." not in host or host == "localhost" or host.endswith(".localhost"):
                        continue
                return url
            except ValueError:
                continue
    return ""


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
            "shop_logo_url": _pick_shop_logo(seller),
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


async def _collect_shop_details(page, shop_id: str) -> dict[str, Any]:
    if not shop_id:
        return {}
    try:
        payload = await page.evaluate("""
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
            "shop_logo_url": _pick_shop_logo(data.get("shop") or {}, popup, brand, data.get("user_info") or {}, data),
            "shop_brand_name": str(brand.get("name") or "").strip(),
            "shop_fans_count": brand.get("fans_num"),
            "shop_notes_count": brand.get("notes_num"),
            "shop_user_id": str((data.get("user_info") or {}).get("user_id") or brand.get("id") or "").strip(),
            "shop_status": str(popup.get("status") or "").strip(),
        }
    except Exception:
        return {}


async def _collect_page(context, key: int, url: str, timeout_ms: int) -> tuple[int, dict[str, Any] | Exception]:
    page = await context.new_page()
    captured: dict[str, Any] = {}
    captured_event = asyncio.Event()
    last_status = None
    detail_seen = False
    parse_reason = ""

    async def on_response(response):
        nonlocal detail_seen, last_status, parse_reason
        try:
            validate_url(response.url)
        except ValueError:
            return
        if DETAIL_API not in response.url or "/variant" in response.url:
            return
        detail_seen = True
        last_status = response.status
        if response.status != 200:
            return
        diagnostics: dict[str, str] = {}
        try:
            body = await response.json()
        except Exception as exc:
            parse_reason = "响应 JSON 解析失败：" + type(exc).__name__
            return
        parsed = parse_detail_response(body, page.url, diagnostics)
        if parsed:
            parsed["observed_at"] = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
            captured.update(parsed)
            captured_event.set()
        else:
            parse_reason = diagnostics.get("reason", "详情响应无法解析")

    page.on("response", on_response)
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        try:
            await asyncio.wait_for(captured_event.wait(), timeout=12)
        except TimeoutError:
            pass
        if not captured:
            try:
                text = await page.locator("body").inner_text(timeout=2000)
            except Exception:
                text = ""
            if any(word in text for word in ("验证码", "安全验证", "异常访问", "请完成验证")):
                raise BatchCollectionError(
                    "需要人工验证",
                    "小红书要求人工安全验证，后台采集已停止，未尝试绕过验证",
                    requires_manual=True,
                )
            if any(word in text for word in ("商品已下架", "该商品已下架")):
                raise ProductTerminalError("delisted", "商品已下架，已停止后续自动采集")
            if any(word in text for word in ("商品不存在", "页面不存在", "链接已失效")):
                raise ProductTerminalError("invalid_link", "商品链接失效，已停止后续自动采集")
            logger.warning(
                "Product detail capture failed: detail_seen=%s status=%s parse_reason=%s",
                detail_seen,
                last_status,
                parse_reason or ("未收到目标详情接口响应" if not detail_seen else "无"),
            )
            if last_status and last_status != 200:
                if last_status in {404, 410}:
                    raise ProductTerminalError("invalid_link", f"商品详情接口返回 HTTP {last_status}，链接已失效")
                raise RuntimeError(f"商品详情接口返回 HTTP {last_status}")
            raise RuntimeError("未捕获到商品详情数据，可能是链接失效、网络波动或页面接口发生变化")
        shop_details = await _collect_shop_details(page, str(captured.get("shop_id") or ""))
        if not shop_details.get("shop_logo_url"):
            shop_details.pop("shop_logo_url", None)
        captured.update(shop_details)
        return key, dict(captured)
    except Exception as exc:
        return key, exc
    finally:
        await page.close()


async def _collect_products_async(
    requests: list[tuple[int, str]],
    timeout_ms: int,
    max_pages: int,
    should_continue,
    deadline: datetime | None,
) -> dict[int, dict[str, Any] | Exception]:
    from playwright.async_api import async_playwright

    results: dict[int, dict[str, Any] | Exception] = {}
    try:
        async with async_playwright() as playwright:
            context = await playwright.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR),
                channel="chrome",
                headless=True,
                locale="zh-CN",
                viewport={"width": 1365, "height": 900},
            )
            try:
                async def route_request(route):
                    request = route.request
                    if request.is_navigation_request():
                        try:
                            validate_url(request.url)
                        except ValueError:
                            await route.abort()
                            return
                    if request.resource_type in {"image", "media", "font"}:
                        await route.abort()
                        return
                    await route.continue_()

                await context.route("**/*", route_request)
                for page in list(context.pages):
                    await page.close()
                for offset in range(0, len(requests), max_pages):
                    if should_continue is not None and not should_continue():
                        break
                    remaining = (deadline - datetime.now()).total_seconds() if deadline else None
                    if remaining is not None and remaining <= 0:
                        break
                    wave = requests[offset:offset + max_pages]
                    pending = asyncio.gather(
                        *(_collect_page(context, key, url, timeout_ms) for key, url in wave)
                    )
                    try:
                        completed = await asyncio.wait_for(pending, timeout=remaining) if remaining is not None else await pending
                    except TimeoutError:
                        break
                    results.update(completed)
                    batch_error = next(
                        (value for _, value in completed if isinstance(value, BatchCollectionError)),
                        None,
                    )
                    if batch_error:
                        raise batch_error
                    errors = [value for _, value in completed if isinstance(value, Exception)]
                    if len(errors) == len(completed) and len(errors) > 1 and all(
                        any(term in str(error) for term in ("ERR_INTERNET_DISCONNECTED", "ERR_NAME_NOT_RESOLVED", "ERR_CONNECTION"))
                        for error in errors
                    ):
                        raise BatchCollectionError("网络连接异常", "整批商品均因网络连接异常采集失败，任务已停止")
            finally:
                await context.close()
    except BatchCollectionError:
        raise
    except Exception as exc:
        raise BatchCollectionError("浏览器运行异常", f"Chrome 采集进程异常：{type(exc).__name__}") from exc
    return results


def collect_products(
    requests: list[tuple[int, str]],
    timeout_ms: int = 30000,
    max_pages: int = 4,
    should_continue=None,
    deadline: datetime | None = None,
) -> dict[int, dict[str, Any] | Exception]:
    if not requests:
        return {}
    validated = [(int(key), validate_url(url)) for key, url in requests]
    try:
        import playwright.async_api  # noqa: F401
    except ImportError as exc:
        raise RuntimeError("Playwright 尚未安装") from exc
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    with COLLECT_LOCK:
        return asyncio.run(
            _collect_products_async(validated, timeout_ms, max(1, max_pages), should_continue, deadline)
        )


def collect_product(url: str, timeout_ms: int = 30000) -> dict[str, Any]:
    result = collect_products([(0, url)], timeout_ms=timeout_ms, max_pages=1)[0]
    if isinstance(result, Exception):
        raise result
    return result
