import re
import time
import json
from typing import Optional

import requests
from bs4 import BeautifulSoup

SUPPORTED_PLATFORMS = ['amazon', 'lazada']

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options as ChromeOptions
except Exception:
    webdriver = None
    ChromeOptions = None

class Product:
    def __init__(self, platform, id, name, seller, price, url):
        self.platform = platform
        self.platform_product_id = id
        self.name = name
        self.seller = seller
        self.price = price
        self.url = url

    def __repr__(self):
        return f"<Product(platform={self.platform}, id={self.platform_product_id}, name={self.name}, price={self.price})>"
    
    def pretty_print(self):
        return self.__dict__
    
    def set_price(self, price):
        self.price = price

class LazadaProduct(Product):
    def __init__(self, id, name, seller, price, url):
        super().__init__('lazada', id, name, seller, price, url)

class AmazonProduct(Product):
    def __init__(self, id, name, seller, price, url):
        super().__init__('amazon', id, name, seller, price, url)


def identify_platform(url: str):
    u = (url or '').lower()
    if 'amazon' in u:
        return 'amazon'
    if 'lazada' in u:
        return 'lazada'
    return None


def _requests_get(url: str):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36'
    }
    try:
        resp = requests.get(url, headers=headers, timeout=25)
        if resp.status_code == 200:
            return resp.text
    except Exception:
        return None
    return None


def _selenium_get(url: str):
    if webdriver is None or ChromeOptions is None:
        return None
    try:
        options = ChromeOptions()
        options.add_argument('--headless=new')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        driver = webdriver.Chrome(options=options)
        try:
            driver.get(url)
            time.sleep(4)
            return driver.page_source
        finally:
            driver.quit()
    except Exception:
        return None


def _parse_platform_product_id(url: str, platform: str):
    if platform == 'amazon':
        m = re.search(r'i\.(\d+)\.(\d+)', url or '')
        return f"{m.group(1)}_{m.group(2)}" if m else (url or '')
    if platform == 'lazada':
        m = re.search(r'-i(\d+)\.html', url or '')
        return m.group(1) if m else (url or '')
    return url


def _extract_price(text: Optional[str]) -> float:
    if not text:
        return 0.0
    # Keep digits, dots and commas
    cleaned = re.sub(r'[^\d\.,]', '', text)
    if not cleaned:
        return 0.0

    # - If there's exactly one dot, treat dot as decimal separator and remove commas.
    # - If there's no dot and exactly one comma, treat comma as decimal separator.
    # - Otherwise remove commas (thousands separators) and keep dots.
    if cleaned.count('.') == 1:
        cleaned = cleaned.replace(',', '')
    elif cleaned.count('.') == 0 and cleaned.count(',') == 1:
        cleaned = cleaned.replace(',', '.')
    else:
        cleaned = cleaned.replace(',', '')

    try:
        return float(cleaned)
    except Exception:
        # Fallback: extract first numeric group with optional decimal
        m = re.search(r'(\d+(?:\.\d+)?)', cleaned)
        if m:
            try:
                return float(m.group(1))
            except Exception:
                return 0.0
    return 0.0


def _scrape_amazon(url: str, soup: BeautifulSoup):
    amazon_product = AmazonProduct(
        id=_parse_platform_product_id(url, 'amazon'),
        name='',
        seller='',
        price=0.0,
        url=url
    )
    # normalize title
    title = soup.find('title')
    if title:
        amazon_product.name = title.get_text(strip=True)

    # price extraction (primitive)
    price_el = soup.select_one('span.a-price > span.a-offscreen') or soup.select_one('#priceblock_ourprice')
    if price_el:
        amazon_product.set_price(_extract_price(price_el.get_text(strip=True)))

    # seller extraction (primitive)
    seller_el = soup.select_one('#sellerProfileTriggerId') or soup.select_one('#bylineInfo') or soup.select_one('#merchant-info')
    if seller_el:
        amazon_product.seller = seller_el.get_text(strip=True)
        amazon_product.seller_scraped = True
    else:
        amazon_product.seller_scraped = False

    return amazon_product.pretty_print()


def _scrape_lazada(url: str, soup: BeautifulSoup):
    lazada_product = LazadaProduct(
        id=_parse_platform_product_id(url, 'lazada'),
        name='',
        seller='',
        price=0.0,
        url=url
    )

    for sc in soup.find_all('script', type=re.compile('application/(ld\\+json|json)')):
        try:
            data = json.loads(sc.get_text(strip=True))
        except Exception:
            continue
        if isinstance(data, dict) and ((data.get('@type') and str(data.get('@type')).lower() == 'product') or data.get('name')):
            lazada_product.name = data.get('name') or lazada_product.name
            offers = data.get('offers')
            if isinstance(offers, dict):
                seller_info = offers.get('seller')
                if isinstance(seller_info, dict):
                    lazada_product.seller = lazada_product.seller or seller_info.get('name')
                price_from_ld = offers.get('price')
                if price_from_ld:
                    lazada_product.set_price(lazada_product.price or _extract_price(str(price_from_ld)))
                    
    # 1) DOM Price Selectors
    if lazada_product.price == 0.0:
        primary = soup.select_one('span.pdp-v2-product-price-content-salePrice-amount')
        if primary:
            txt = ''.join(primary.stripped_strings)
            lazada_product.set_price(_extract_price(txt) or lazada_product.price)
    
    
    # 2) Price from JS var `pdpTrackingData`
    js_price_str = None
    for sc in soup.find_all('script'):
        txt = sc.get_text() or ''
        if 'pdpTrackingData' not in txt:
            continue
        m = re.search(
            r'var\s+pdpTrackingData\s*=\s*(?P<val>"(?:\\.|[^"])*"|\{.*?\})\s*;',
            txt, re.S
        )
        if not m:
            continue
        val = m.group('val').strip()
        try:
            # quoted JS-string containing JSON: first json.loads to unquote/unescape, then parse
            if val.startswith('"') and val.endswith('"'):
                inner = json.loads(val)    # unescape the JS quoted string -> returns JSON text
                obj = json.loads(inner)   # parse JSON text
            else:
                obj = json.loads(val)     # parse raw JSON object
        except Exception:
            continue
        # example key is "pdt_price" containing a currency-formatted string like "₱305.00"
        pdt_price = obj.get('pdt_price') or obj.get('price') or obj.get('product_price')
        if pdt_price:
            js_price_str = pdt_price
            break

    if js_price_str:
        lazada_product.set_price(_extract_price(js_price_str) or lazada_product.price)
        # pdpTrackingData often contains brand_name and pdt_price; extract seller from brand_name if present
        try:
            # obj was parsed above; reuse the last parsed obj variable if available
            if 'obj' in locals() and isinstance(obj, dict):
                brand = obj.get('brand_name') or obj.get('brand')
                if brand:
                    # ensure primitive string
                    lazada_product.seller = str(brand).strip()
        except Exception:
            pass

    return lazada_product.pretty_print()

def scrape_product(url: str, platform: str):
    html = _requests_get(url)
    if not html:
        html = _selenium_get(url)
    if not html:
        raise RuntimeError('Product page cannot be retrieved!')
    soup = BeautifulSoup(html, 'lxml')
    if platform == 'amazon':
        return _scrape_amazon(url, soup)
    if platform == 'lazada':
        return _scrape_lazada(url, soup)
    raise ValueError('Platform not supported! Please try a Lazada or Amazon product URL.')