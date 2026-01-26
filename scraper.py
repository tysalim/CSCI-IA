import re
import time
import json
import os
from typing import Optional

import requests
from bs4 import BeautifulSoup

# Debug flag (set SCRAPER_DEBUG=1 to enable)
DEBUG = os.environ.get("SCRAPER_DEBUG", "").lower() in ("1", "true", "yes")

# Optional dependencies
try:
    from playwright.sync_api import sync_playwright
except Exception:
    sync_playwright = None

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options as ChromeOptions
except Exception:
    webdriver = ChromeOptions = None


# ----------------------------
# Models
# ----------------------------

class Product:
    def __init__(self, platform, product_id, name, seller, price, url):
        self.platform = platform
        self.platform_product_id = product_id
        self.name = name
        self.seller = seller
        self.price = price
        self.url = url

    def set_price(self, price: float):
        if price and self.price == 0.0:
            self.price = price

    def __repr__(self):
        return (
            f"<Product(platform={self.platform}, "
            f"id={self.platform_product_id}, "
            f"name={self.name}, price={self.price})>"
        )


class LazadaProduct(Product):
    def __init__(self, product_id, name, seller, price, url):
        super().__init__("lazada", product_id, name, seller, price, url)


# ----------------------------
# Helpers
# ----------------------------

def identify_platform(url: str) -> Optional[str]:
    return "lazada" if "lazada" in (url or "").lower() else None


def _requests_get(url: str) -> Optional[str]:
    try:
        resp = requests.get(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
                )
            },
            timeout=25,
        )
        return resp.text if resp.status_code == 200 else None
    except Exception:
        return None


def _selenium_get(url: str) -> Optional[str]:
    if not webdriver or not ChromeOptions:
        return None

    try:
        options = ChromeOptions()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")

        driver = webdriver.Chrome(options=options)
        try:
            driver.get(url)
            time.sleep(4)
            return driver.page_source
        finally:
            driver.quit()
    except Exception:
        return None


def _parse_lazada_product_id(url: str) -> str:
    m = re.search(r"-i(\d+)\.html", url or "")
    return m.group(1) if m else url


def _extract_price(text: Optional[str]) -> float:
    if not text:
        return 0.0

    cleaned = re.sub(r"[^\d.,]", "", text)
    if not cleaned:
        return 0.0

    if cleaned.count(".") == 1:
        cleaned = cleaned.replace(",", "")
    elif cleaned.count(".") == 0 and cleaned.count(",") == 1:
        cleaned = cleaned.replace(",", ".")
    else:
        cleaned = cleaned.replace(",", "")

    try:
        return float(cleaned)
    except ValueError:
        m = re.search(r"(\d+(?:\.\d+)?)", cleaned)
        return float(m.group(1)) if m else 0.0


# ----------------------------
# Lazada UI Scraper
# ----------------------------

def _scrape_lazada_ui_price(url: str) -> Optional[float]:
    if not sync_playwright:
        return None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="networkidle", timeout=30000)

            page.mouse.wheel(0, 800)
            page.wait_for_timeout(1500)

            page.wait_for_function(
                """() => [...document.querySelectorAll("span,div")]
                .some(e => e.innerText?.includes("₱"))""",
                timeout=20000,
            )

            text = page.inner_text("body")
            browser.close()

        m = re.search(r"₱\s*([\d,]+(?:\.\d+)?)", text or "")
        return float(m.group(1).replace(",", "")) if m else None
    except Exception:
        if DEBUG:
            import traceback
            print(traceback.format_exc())
        return None


# ----------------------------
# Lazada Scraper
# ----------------------------

def _scrape_lazada(url: str, soup: BeautifulSoup) -> dict:
    product = LazadaProduct(
        product_id=_parse_lazada_product_id(url),
        name="",
        seller="",
        price=0.0,
        url=url,
    )

    # 1) UI price (highest priority)
    product.set_price(_scrape_lazada_ui_price(url))

    # 2) DOM price fallback
    if product.price == 0.0:
        for selector in (
            "span.pdp-v2-product-price-content-salePrice-amount",
            "span.pdp-v2-product-price-content-originalPrice-amount",
        ):
            el = soup.select_one(selector)
            if el:
                product.set_price(_extract_price("".join(el.stripped_strings)))
                break

    # 3) JSON-LD
    for sc in soup.find_all("script", type=re.compile("application/(ld\\+json|json)")):
        try:
            data = json.loads(sc.get_text(strip=True))
        except Exception:
            continue

        if not isinstance(data, dict):
            continue

        product.name = product.name or data.get("name", "")

        offers = data.get("offers")
        if product.price == 0.0 and isinstance(offers, dict):
            product.set_price(_extract_price(str(offers.get("price"))))

    # 4) pdpTrackingData
    for sc in soup.find_all("script"):
        txt = sc.get_text() or ""
        if "pdpTrackingData" not in txt:
            continue

        m = re.search(
            r"var\s+pdpTrackingData\s*=\s*(\".*?\"|\{.*?\});",
            txt,
            re.S,
        )
        if not m:
            continue

        try:
            raw = m.group(1)
            data = json.loads(json.loads(raw)) if raw.startswith('"') else json.loads(raw)
        except Exception:
            continue

        product.set_price(_extract_price(
            data.get("pdt_price")
            or data.get("price")
            or data.get("product_price")
        ))

        product.seller = product.seller or str(
            data.get("brand_name") or data.get("brand") or ""
        ).strip()
        break

    return vars(product)


# ----------------------------
# Public API
# ----------------------------

def scrape_product(url: str, platform: str) -> dict:
    html = _requests_get(url) or _selenium_get(url)
    if not html:
        raise RuntimeError("Product page cannot be retrieved!")

    soup = BeautifulSoup(html, "lxml")

    if platform == "lazada":
        return _scrape_lazada(url, soup)

    raise ValueError("Platform not supported! Please try a Lazada product URL.")