import re
from typing import Optional

from playwright.sync_api import sync_playwright


def _extract_price(text: str) -> Optional[float]:
    if not text:
        return None
    # keep digits and dots only
    cleaned = re.sub(r"[^\d.]", "", text)
    try:
        return float(cleaned)
    except ValueError:
        return None


def _scrape_lazada_ui_price(url: str) -> Optional[float]:
    """
    Option C fallback: scrape displayed UI price via Playwright.
    This works even when Lazada does not expose JSON or DOM price fields.
    """
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="networkidle", timeout=30000)

            # Sometimes price is lazy-loaded; scroll a bit to force render
            page.mouse.wheel(0, 800)
            page.wait_for_timeout(1500)

            # Wait for any visible price text containing "₱"
            page.wait_for_function(
                """() => {
                    return Array.from(document.querySelectorAll("span, div"))
                        .some(el => el.innerText && el.innerText.includes("₱"));
                }""",
                timeout=20000
            )

            # Grab all visible text on the page
            text = page.inner_text("body")
            browser.close()

        # Extract first peso price
        match = re.search(r"₱\s*([\d,]+(?:\.\d+)?)", text)
        if not match:
            return None

        return float(match.group(1).replace(",", ""))

    except Exception as e:
        print("Playwright UI scrape failed:", e)
        return None


# Example usage (can replace your existing UI fallback call)
if __name__ == "__main__":
    url = "https://www.lazada.com.ph/products/4681012-person-large-camping-tent-automatic-waterproof-family-tents-for-outdoor-double-layers-sun-proof-camping-tent-outdoor-heavy-duty-tent-i3959393460-s21394130883.html"
    price = _scrape_lazada_ui_price(url)
    print("Displayed price:", price)
