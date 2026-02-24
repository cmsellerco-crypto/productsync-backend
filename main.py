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

SCRAPER_API_KEY = os.environ.get("SCRAPER_API_KEY", "0a600af29843b12ea0ae1c13f89f1800")

# ─── Extract items from Walmart HTML ─────────────────────────────────────────

def extract_items_from_html(html: str) -> list:
    items = []

    # Find __NEXT_DATA__ script tag
    start_marker = '<script id="__NEXT_DATA__" type="application/json">'
    end_marker = '</script>'

    start_idx = html.find(start_marker)
    if start_idx == -1:
        print("__NEXT_DATA__ not found")
        return []

    start_idx += len(start_marker)
    end_idx = html.find(end_marker, start_idx)
    if end_idx == -1:
        print("Closing script tag not found")
        return []

    json_str = html[start_idx:end_idx]
    print(f"JSON string length: {len(json_str)}")

    try:
        data = json.loads(json_str)
    except Exception as e:
        print(f"JSON parse error: {e}")
        return []

    # Navigate to items
    try:
        search_result = (
            data["props"]["pageProps"]["initialData"]["searchResult"]
        )
        for stack in search_result.get("itemStacks", []):
            for item in stack.get("items", []):
                if item.get("name"):
                    items.append(item)
        print(f"Found {len(items)} items via itemStacks")
    except KeyError as e:
        print(f"Key error navigating JSON: {e}")

    return items


def parse_item(item: dict, brand: str) -> dict:
    # Price
    price = ""
    try:
        raw = item["priceInfo"]["currentPrice"]["price"]
        price = f"${float(raw):.2f}"
    except:
        pass

    # UPC
    upc = str(
        item.get("upc") or
        item.get("upcCode") or
        item.get("GTIN") or
        item.get("gtin") or
        ""
    )

    # Category
    cat = item.get("category", "")
    if isinstance(cat, dict):
        cat = cat.get("name", "")

    # Image
    img = item.get("imageInfo", "")
    if isinstance(img, dict):
        img = img.get("thumbnailUrl", "")

    # URL
    canonical = item.get("canonicalUrl", "")
    url = f"https://www.walmart.com{canonical}" if canonical else ""

    return {
        "name": item.get("name", ""),
        "brand": item.get("brand", brand) or brand,
        "sku": str(item.get("usItemId", "")),
        "item_id": str(item.get("itemId", "")),
        "upc": upc,
        "price": price,
        "category": str(cat),
        "image": str(img),
        "url": url,
        "rating": str(item.get("averageRating", "")),
        "source": "Walmart",
        "asin": "",
    }


# ─── Walmart Scraper ──────────────────────────────────────────────────────────

async def scrape_walmart(brand: str, max_items: int, sort: str = "best_match"):
    products = []
    sort_map = {
        "best_match": "best_match",
        "price_low": "price_low",
        "price_high": "price_high",
        "rating": "best_seller",
    }
    sort_param = sort_map.get(sort, "best_match")
    page = 1

    async with httpx.AsyncClient(timeout=120) as client:
        while len(products) < max_items:
            walmart_url = f"https://www.walmart.com/search?q={brand}&sort={sort_param}&page={page}"
            scraper_url = (
                f"https://api.scraperapi.com/"
                f"?api_key={SCRAPER_API_KEY}"
                f"&url={walmart_url}"
                f"&country_code=us"
                f"&device_type=desktop"
            )

            try:
                print(f"[Page {page}] Fetching Walmart for: {brand}")
                resp = await client.get(scraper_url)
                html = resp.text
                print(f"[Page {page}] Status: {resp.status_code} | Size: {len(html)}")

                items = extract_items_from_html(html)

                if not items:
                    print(f"[Page {page}] No items extracted, stopping")
                    break

                for item in items:
                    if len(products) >= max_items:
                        break
                    parsed = parse_item(item, brand)
                    if parsed["name"]:
                        products.append(parsed)

                print(f"[Page {page}] Total so far: {len(products)}")
                page += 1
                await asyncio.sleep(1.5)

            except Exception as e:
                print(f"[Page {page}] Exception: {e}")
                break

    print(f"Final total: {len(products)} products")
    return products


# ─── Endpoints ───────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {"status": "ok", "message": "ProductSync API v3.0"}


@app.get("/scrape/walmart")
async def walmart_endpoint(
    brand: str = Query(...),
    max_items: int = Query(40, ge=1, le=200),
    sort: str = Query("best_match"),
):
    products = await scrape_walmart(brand, max_items, sort)
    return {"brand": brand, "source": "walmart", "count": len(products), "products": products}


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
    return {"status": "healthy", "version": "3.0"}
