#!/usr/bin/env python3
"""
BoozeNewz Scraper
Fetches beer, spirits, and wine deals from Morrisons, Tesco, and Asda.
Output: deals.json

Requirements:
    pip3 install playwright curl_cffi beautifulsoup4 requests
    python3 -m playwright install chromium
"""

import json
import re
import sys
import time
import logging
import requests as std_requests
from datetime import datetime, timezone
from collections import Counter

try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False
    print("Warning: playwright not installed — Morrisons will be skipped")

try:
    from curl_cffi import requests as cffi_requests
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False
    print("Warning: curl_cffi not installed — Tesco will be skipped")

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False
    print("Warning: beautifulsoup4 not installed — Tesco will be skipped")

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)


# ── Helpers ────────────────────────────────────────────────────────────────────

def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")

def parse_price(val) -> float:
    if isinstance(val, (int, float)):
        return float(val)
    m = re.search(r"[\d.]+", str(val))
    return float(m.group()) if m else 0.0

def calc_saving(price: float, promo: str) -> float:
    """Estimate per-unit saving from a UK supermarket promo description."""
    if not promo or price <= 0:
        return 0.0

    # "Any N for £X" / "Buy N for £X"
    m = re.search(r"(?:any|buy)\s+(\d+)\s+for\s+[£$]?([\d.]+)", promo, re.I)
    if m:
        qty = int(m.group(1))
        offer_total = float(m.group(2))
        return round(max((qty * price - offer_total) / qty, 0), 2)

    # "Any N for M" (pay for M items, get N) — e.g. "Any 4 for 3"
    m = re.search(r"(?:any|buy)\s+(\d+)\s+for\s+(\d+)$", promo.strip(), re.I)
    if m:
        buy_qty = int(m.group(1))
        pay_qty = int(m.group(2))
        free = buy_qty - pay_qty
        return round(price * free / buy_qty, 2)

    # "£X.XX - More Card Price" / "More Card Price £X"
    m = re.search(r"[£$]([\d.]+)\s*[-–]\s*more\s+card", promo, re.I)
    if not m:
        m = re.search(r"more\s+card\s+price\s+[£$]?([\d.]+)", promo, re.I)
    if m:
        card_price = float(m.group(1))
        return round(max(price - card_price, 0), 2)

    # "Save £X"
    m = re.search(r"save\s+[£$]([\d.]+)", promo, re.I)
    if m:
        return round(float(m.group(1)), 2)

    # "Save X%" / "Buy N Save X%"
    m = re.search(r"save\s+([\d.]+)%", promo, re.I)
    if m:
        return round(price * float(m.group(1)) / 100, 2)

    # "Now £X, Was £Y" / "Was £X, Now £Y"
    m = re.search(r"now\s+[£$]([\d.]+)[,\s]+was\s+[£$]([\d.]+)", promo, re.I)
    if not m:
        m = re.search(r"was\s+[£$]([\d.]+)[,\s]+now\s+[£$]([\d.]+)", promo, re.I)
        if m:
            m = type("m", (), {"group": lambda self, n: [None, m.group(2), m.group(1)][n]})()
    if m:
        now_p = float(m.group(1))
        was_p = float(m.group(2))
        return round(max(was_p - now_p, 0), 2)

    # "Was £X"
    m = re.search(r"was\s+[£$]([\d.]+)", promo, re.I)
    if m:
        was = float(m.group(1))
        return round(max(was - price, 0), 2)

    # "Half price"
    if re.search(r"half.?price|50%\s+off", promo, re.I):
        return round(price / 2, 2)

    return 0.0

def is_beverage(name: str) -> bool:
    """Return True if the product name looks like an actual drink."""
    nl = name.lower()
    # Volume measurements (330ml, 70cl, 1.5l, etc.)
    if re.search(r"\d+\s*(?:ml|cl|l\b|litre|liter)", nl):
        return True
    # Pack formats (15x440ml, 4 pack, etc.)
    if re.search(r"\d+\s*(?:x\s*\d+|pack|cans|bottles|pints|keg)", nl, re.I):
        return True
    # ABV (5%, 40% vol, etc.)
    if re.search(r"\d+(?:\.\d+)?\s*%", nl):
        return True
    return False


def detect_category(name: str) -> str:
    nl = name.lower()
    # Check spirits first — spirit names can contain beer words (e.g. "Stout Edition Whiskey")
    spirits_kws = ["whisky", "whiskey", "vodka", "gin ", "rum ", " rum", "rum,",
                   "brandy", "tequila", "bourbon", "liqueur", "cognac", "armagnac",
                   "mezcal", "schnapps", "absinthe", "sambuca", "baileys",
                   "kahlua", "cointreau", "triple sec", "vermouth", "aperol",
                   "campari", "amaretto", "bitters", "calvados", "grappa",
                   "pisco", "eau de vie", "disaronno", "malibu", "midori",
                   "jagermeister", "jägermeister", "fireball", "drambuie",
                   "frangelico", "chartreuse", "benedictine", "advocaat"]
    beer_kws = ["beer", "lager", "stout", "cider", "ipa", "bitter",
                "porter", "pilsner", "pale ale", "saison", "wheat beer", "sour beer",
                "shandy", "craft brew", "pils", " pint", "draught"]
    wine_kws = ["wine", "prosecco", "champagne", "cava", "rosé", "rose",
                "chardonnay", "merlot", "cabernet", "pinot", "sauvignon",
                "shiraz", "malbec", "rioja", "bordeaux", "burgundy",
                "port wine", "port ", "moscato", "vinho", "claret", "riesling",
                "gewurztraminer", "viognier", "albariño"]
    for kw in spirits_kws:
        if kw in nl:
            return "spirits"
    for kw in beer_kws:
        if kw in nl:
            return "beer"
    # word-boundary check for "ale" to avoid matching "originale", "pale", etc.
    if re.search(r'\bale\b', nl):
        return "beer"
    for kw in wine_kws:
        if kw in nl:
            return "wine"
    return "other"


# ── Morrisons ──────────────────────────────────────────────────────────────────

MORRISONS_BASE = "https://groceries.morrisons.com"
MORRISONS_BWS_CAT = "b182dd9d-bdfe-487e-b583-74007e5b1e69"
MORRISONS_API = f"{MORRISONS_BASE}/api/webproductpagews/v6/product-pages/promotions"


def scrape_morrisons(page) -> list:
    log.info("  Loading Morrisons…")
    page.goto(MORRISONS_BASE, timeout=30_000)
    page.wait_for_load_state("networkidle", timeout=20_000)

    try:
        page.click("#onetrust-accept-btn-handler", timeout=5_000)
        page.wait_for_timeout(500)
    except Exception:
        pass

    deals = []
    page_token = None
    page_num = 1

    while True:
        params = (
            "includeAdditionalPageInfo=true"
            "&maxPageSize=100&maxProductsToDecorate=100"
            "&tag=web"
            f"&categoryId={MORRISONS_BWS_CAT}"
        )
        if page_token:
            params += f"&pageToken={page_token}"

        resp = page.request.get(f"{MORRISONS_API}?{params}")
        if resp.status != 200:
            log.warning(f"    Morrisons API {resp.status} on page {page_num}")
            break

        data = resp.json()
        groups = data.get("productGroups", [])
        page_count = 0

        for g in groups:
            for prod in g.get("decoratedProducts", []):
                price = parse_price(prod.get("price", {}).get("amount", 0))
                promos = prod.get("promotions", [])
                promo_text = promos[0].get("description", "") if promos else ""
                saving = calc_saving(price, promo_text)

                name = prod.get("name", "")
                rid = prod.get("retailerProductId", "")
                link = f"{MORRISONS_BASE}/products/{slugify(name)}/{rid}" if rid else MORRISONS_BASE

                deals.append({
                    "store": "Morrisons",
                    "category": detect_category(name),
                    "title": name,
                    "price": f"£{price:.2f}" if price else "",
                    "promotion": promo_text,
                    "saving": saving,
                    "link": link,
                })
                page_count += 1

        log.info(f"    Page {page_num}: {page_count} products")

        page_token = data.get("metadata", {}).get("nextPageToken")
        if not page_token or page_count == 0:
            break
        page_num += 1
        time.sleep(0.3)

    return deals


# ── Tesco ──────────────────────────────────────────────────────────────────────

TESCO_BASE = "https://www.tesco.com/groceries/en-GB"
# Broad queries covering all BWS categories; duplicates are deduped by URL
TESCO_QUERIES = [
    "beer", "cider",
    "spirits", "gin", "vodka", "rum", "whisky",
]


def parse_tesco_tile(tile) -> dict:
    title_link = tile.find("a", class_=re.compile("titleLink"))
    if not title_link:
        return None

    name = title_link.get_text(strip=True)
    # Skip non-drink items (e.g. "Beer Pong Table", accessories, glassware)
    if not is_beverage(name):
        return None

    link = title_link.get("href", "")
    if link and not link.startswith("http"):
        link = f"https://www.tesco.com{link}"

    # All price strings in this tile
    all_prices = [str(p).strip() for p in tile.find_all(string=re.compile(r"£[\d.]+"))]

    # Clubcard/deal price text
    clubcard_text = next((p for p in all_prices if "Clubcard" in p), "")

    # Regular shelf price: plain "£X.XX" with no per-unit slash
    regular_text = next(
        (p for p in all_prices if "Clubcard" not in p and "/" not in p and re.match(r"^£[\d.]+$", p)),
        "",
    )

    price = parse_price(regular_text) if regular_text else 0.0

    if clubcard_text and price:
        # Try simple clubcard price (e.g. "£13.00 Clubcard Price")
        cc_match = re.match(r"^£([\d.]+)", clubcard_text)
        if cc_match:
            cc_price = float(cc_match.group(1))
            saving = round(max(price - cc_price, 0), 2)
        else:
            saving = calc_saving(price, clubcard_text)
    else:
        saving = 0.0

    return {
        "store": "Tesco",
        "category": detect_category(name),
        "title": name,
        "price": f"£{price:.2f}" if price else "",
        "promotion": clubcard_text,
        "saving": saving,
        "link": link,
    }


def scrape_tesco() -> list:
    if not HAS_CURL_CFFI or not HAS_BS4:
        log.warning("  Skipping Tesco: requires curl_cffi and beautifulsoup4")
        return []

    deals = {}  # link → deal  (dedup across queries)

    for query in TESCO_QUERIES:
        log.info(f"  Searching '{query}'…")
        page_num = 1
        query_count = 0

        while True:
            url = (
                f"{TESCO_BASE}/search?query={query}"
                f"&sortBy=relevance&facetsArgs=offer%3Atrue&count=48&page={page_num}"
            )
            r = cffi_requests.get(url, impersonate="chrome")
            if r.status_code != 200:
                log.warning(f"    Tesco HTTP {r.status_code} on page {page_num}")
                break

            soup = BeautifulSoup(r.text, "html.parser")
            tiles = soup.find_all("div", class_=re.compile("verticalTile"))
            if not tiles:
                break

            for tile in tiles:
                deal = parse_tesco_tile(tile)
                if deal and deal["link"] and deal["link"] not in deals:
                    deals[deal["link"]] = deal
                    query_count += 1

            # Next page link exists?
            if not soup.find("a", href=re.compile(rf"page={page_num + 1}")):
                break
            page_num += 1
            time.sleep(0.5)

        log.info(f"    '{query}': {query_count} new deals")

    return list(deals.values())


# ── Asda ───────────────────────────────────────────────────────────────────────

ASDA_ALGOLIA_APP = "8I6WSKCCNV"
ASDA_ALGOLIA_KEY = "03e4272048dd17f771da37b57ff8a75e"
ASDA_ALGOLIA_INDEX = "ASDA_PRODUCTS"
ASDA_PRODUCT_BASE = "https://www.asda.com/groceries/product/x/x"


def _algolia_query(payload: dict) -> dict:
    url = (
        f"https://{ASDA_ALGOLIA_APP}-dsn.algolia.net"
        f"/1/indexes/{ASDA_ALGOLIA_INDEX}/query"
    )
    headers = {
        "X-Algolia-Application-Id": ASDA_ALGOLIA_APP,
        "X-Algolia-API-Key": ASDA_ALGOLIA_KEY,
        "Content-Type": "application/json",
    }
    r = std_requests.post(url, headers=headers, json=payload, timeout=15)
    r.raise_for_status()
    return r.json()


def parse_asda_hit(hit: dict) -> dict:
    name = hit.get("NAME", "")
    if not name:
        return None

    brand = hit.get("BRAND", "")
    if brand and not name.lower().startswith(brand.lower()):
        name = f"{brand} {name}"

    cin = hit.get("CIN", "")
    image_id = hit.get("IMAGE_ID", "")
    prices_en = hit.get("PRICES", {}).get("EN", {})
    promos_en = hit.get("PROMOS", {}).get("EN") or []

    price = float(prices_en.get("PRICE", 0))
    was_price = float(prices_en.get("WASPRICE", 0))
    offer_type = prices_en.get("OFFER", "List")
    promo_name = promos_en[0].get("NAME", "") if promos_en else ""

    if offer_type in ("Rollback", "Dropped") and was_price:
        promo = f"Now £{price:.2f}, Was £{was_price:.2f}"
        saving = round(max(was_price - price, 0), 2)
    elif promo_name:
        promo = promo_name
        saving = calc_saving(price, promo_name)
    else:
        promo = offer_type if offer_type != "List" else ""
        saving = 0.0

    return {
        "store": "Asda",
        "category": detect_category(name),
        "title": name,
        "price": f"£{price:.2f}" if price else "",
        "promotion": promo,
        "saving": saving,
        "link": f"{ASDA_PRODUCT_BASE}/{cin}" if cin else "https://www.asda.com/groceries",
    }


def scrape_asda() -> list:
    # Discover current deal types for BWS products
    facet_resp = _algolia_query({
        "query": "",
        "hitsPerPage": 0,
        "facets": ["PRICES.EN.OFFER", "PROMOS.EN.NAME"],
        "facetFilters": [["IS_BWS:true"]],
    })

    offer_facets = facet_resp.get("facets", {}).get("PRICES.EN.OFFER", {})
    promo_facets = facet_resp.get("facets", {}).get("PROMOS.EN.NAME", {})

    deal_filters = (
        [f"PRICES.EN.OFFER:{t}" for t in offer_facets if t != "List"]
        + [f"PROMOS.EN.NAME:{n}" for n in promo_facets]
    )

    if not deal_filters:
        log.warning("  Asda: no active deals found")
        return []

    deals = []
    page = 0

    while True:
        data = _algolia_query({
            "query": "",
            "hitsPerPage": 1000,
            "page": page,
            "facetFilters": [deal_filters, ["IS_BWS:true"]],
        })

        hits = data.get("hits", [])
        for hit in hits:
            deal = parse_asda_hit(hit)
            if deal:
                deals.append(deal)

        log.info(f"    Page {page}: {len(hits)} products")

        if page >= data.get("nbPages", 1) - 1:
            break
        page += 1
        time.sleep(0.2)

    return deals


# ── Main ───────────────────────────────────────────────────────────────────────

_AF_RE = re.compile(
    r'alcohol[\s-]?free|non[\s-]?alcoholic|\b0\.0\s*%|\b0\s*%\s*(?:abv|vol)\b',
    re.I,
)


def _is_valid_deal(d: dict) -> bool:
    name = d.get("title", "")
    promo = d.get("promotion", "")

    # Malformed / empty name (e.g. "75cl" with no product text)
    if len(name.strip()) < 8:
        return False

    # Alcohol-free products
    if _AF_RE.search(name):
        return False

    # "Was £X, Now £Y" where Y >= X — phantom deal, no actual saving
    m = re.search(r'was\s+[£$]([\d.]+),?\s+now\s+[£$]([\d.]+)', promo, re.I)
    if m and float(m.group(2)) >= float(m.group(1)):
        return False

    # No saving calculated — promo text exists but we couldn't parse a value
    if d.get("saving", 0) == 0:
        return False

    return True


def main():
    log.info("🍺  BoozeNewz Scraper")
    log.info("=" * 42)

    all_deals = []

    # ── Tesco (curl_cffi + HTML scraping) ──
    log.info("\nScraping Tesco…")
    try:
        tesco_deals = scrape_tesco()
        all_deals.extend(tesco_deals)
        log.info(f"  ✓ {len(tesco_deals)} deals from Tesco")
    except Exception as exc:
        log.error(f"  ✗ Tesco failed: {exc}")

    # ── Asda (Algolia API) ──
    log.info("\nScraping Asda…")
    try:
        asda_deals = scrape_asda()
        all_deals.extend(asda_deals)
        log.info(f"  ✓ {len(asda_deals)} deals from Asda")
    except Exception as exc:
        log.error(f"  ✗ Asda failed: {exc}")

    # ── Morrisons (Playwright — needs real browser cookies) ──
    if HAS_PLAYWRIGHT:
        log.info("\nScraping Morrisons…")
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--no-sandbox",                # required in Linux CI
                        "--disable-dev-shm-usage",     # prevents crashes in low-memory CI
                        "--disable-gpu",
                    ],
                )
                ctx = browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (X11; Linux x86_64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/121.0.0.0 Safari/537.36"
                    ),
                    locale="en-GB",
                    timezone_id="Europe/London",
                )
                ctx.add_init_script(
                    'Object.defineProperty(navigator, "webdriver", {get: () => undefined})'
                )
                page = ctx.new_page()
                morrisons_deals = scrape_morrisons(page)
                browser.close()

            all_deals.extend(morrisons_deals)
            log.info(f"  ✓ {len(morrisons_deals)} deals from Morrisons")
        except Exception as exc:
            log.error(f"  ✗ Morrisons failed: {exc}")
    else:
        log.warning("\nSkipping Morrisons: playwright not installed")
        log.warning("  Run: pip3 install playwright && python3 -m playwright install chromium")

    # Remove wine — beer and spirits only
    all_deals = [d for d in all_deals if d.get("category") != "wine"]

    # Remove junk deals
    all_deals = [d for d in all_deals if _is_valid_deal(d)]

    # Sort: highest saving first, then alphabetically
    all_deals.sort(key=lambda d: (-d.get("saving", 0), d.get("title", "").lower()))

    output = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "total": len(all_deals),
        "deals": all_deals,
    }

    with open("deals.json", "w", encoding="utf-8") as fh:
        json.dump(output, fh, indent=2, ensure_ascii=False)

    store_counts = Counter(d["store"] for d in all_deals)
    cat_counts = Counter(d["category"] for d in all_deals)
    log.info(f"\n✅  {len(all_deals)} deals → deals.json")
    log.info(f"    By store:    {dict(store_counts)}")
    log.info(f"    By category: {dict(cat_counts)}")
    log.info(f"    Updated:     {output['updated']}")


if __name__ == "__main__":
    main()
