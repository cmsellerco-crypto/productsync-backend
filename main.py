from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import httpx
import json
import csv
import io
import asyncio
import re
import os

app = FastAPI(title="ProductSync API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── ScraperAPI config ────────────────────────────────────────────────────────
SCRAPER_API_KEY = os.environ.get("SCRAPER_API_KEY", "0a600af29843b12ea0ae1c13f89f1800")
SCRAPER_API_URL = "https://api.scraperapi.com"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

# ─── Walmart Scraper via ScraperAPI ──────────────────────────────────────────

async def scrape_walmart(brand: str, max_items: int, sort: str = "best_match"):
    products = []
    page = 1

    sort_map = {
        "best_match": "best_match",
        "price_low": "price_low",
        "price_high": "price_high",
        "rating": "best_seller",
    }
    sort_param = sort_map.get(sort, "best_match")

    async with httpx.AsyncClient(timeout=60) as client:
        while len(products) < max_items:
            walmart_url = (
                f"https://www.walmart.com/search?q={brand}"
                f"&sort={sort_param}&page={page}&affinityOverride=default"
            )

            # Route through ScraperAPI to bypass Walmart's bot detection
            scraper_url = (
                f"{SCRAPER_API_URL}/?api_key={SCRAPER_API_KEY}"
                f"&url={walmart_url}"
                f"&render=true"
                f"&country_code=us"
            )

            try:
                print(f"Fetching Walmart page {page} for brand: {brand}")
                resp = await client.get(scraper_url, headers=HEADERS)
                html = resp.text

                print(f"Response status: {resp.status_code}, length: {len(html)}")

                # Extract __NEXT_DATA__ JSON from Walmart's page
                match = re.search(
                    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
                    html, re.DOTALL
                )

                if not match:
                    print(f"No __NEXT_DATA__ found on page {page}")
                    break

                data = json.loads(match.group(1))

                item_stacks = (
                    data.get("props", {})
                    .get("pageProps", {})
                    .get("initialData", {})
                    .get("searchResult", {})
                    .get("itemStacks", [])
                )

                items = []
                for stack in item_stacks:
                    items.extend(stack.get("items", []))

                if not items:
                    print(f"No items found on page {page}")
                    break

                print(f"Found {len(items)} items on page {page}")

                for item in items:
                    if len(products) >= max_items:
                        break

                    name = item.get("name", "")
                    if not name:
                        continue

                    price_info = item.get("priceInfo", {})
                    price = price_info.get("currentPrice", {}).get("price", "")
                    price_str = f"${price:.2f}" if isinstance(price, (int, float)) else ""

                    upc = (
                        item.get("upc") or
                        item.get("upcCode") or
                        item.get("GTIN") or
                        ""
                    )

                    products.append({
                        "name": name,
                        "brand": item.get("brand", brand),
                        "sku": item.get("usItemId", ""),
                        "item_id": item.get("itemId", ""),
                        "upc": upc,
                        "price": price_str,
                        "category": item.get("category", {}).get("name", "") if isinstance(item.get("category"), dict) else "",
                        "image": item.get("imageInfo", {}).get("thumbnailUrl", "") if isinstance(item.get("imageInfo"), dict) else "",
                        "url": f"https://www.walmart.com{item.get('canonicalUrl', '')}",
                        "rating": str(item.get("averageRating", "")),
                        "source": "Walmart",
                        "asin": "",
                    })

                page += 1
                await asyncio.sleep(1)

            except Exception as e:
                print(f"Walmart scrape error page {page}: {e}")
                break

    print(f"Total products scraped: {len(products)}")
    return products


# ─── Endpoints ───────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {"status": "ok", "message": "ProductSync API is running", "scraper": "ScraperAPI active"}


@app.get("/scrape/walmart")
async def walmart_endpoint(
    brand: str = Query(..., description="Brand name to search"),
    max_items: int = Query(40, ge=1, le=200),
    sort: str = Query("best_match"),
):
    products = await scrape_walmart(brand, max_items, sort)
    return {
        "brand": brand,
        "source": "walmart",
        "count": len(products),
        "products": products
    }


@app.get("/export/csv")
async def export_csv(
    brand: str = Query(...),
    max_items: int = Query(40),
    sort: str = Query("best_match"),
):
    products = await scrape_walmart(brand, max_items, sort)

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=[
        "name", "brand", "sku", "item_id", "upc", "price",
        "category", "url", "rating", "source", "asin"
    ])
    writer.writeheader()
    for p in products:
        writer.writerow({k: p.get(k, "") for k in writer.fieldnames})

    output.seek(0)
    filename = f"{brand.replace(' ', '_')}_products.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "scraper_key_set": bool(SCRAPER_API_KEY),
    }
