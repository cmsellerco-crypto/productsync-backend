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

            # Try ScraperAPI without render first (faster, cheaper)
            scraper_url = (
                f"https://api.scraperapi.com/"
                f"?api_key={SCRAPER_API_KEY}"
                f"&url={walmart_url}"
                f"&country_code=us"
                f"&device_type=desktop"
            )

            try:
                print(f"[Page {page}] Fetching: {walmart_url}")
                resp = await client.get(scraper_url)
                html = resp.text
                print(f"[Page {page}] Status: {resp.status_code} | Length: {len(html)}")

                # Try multiple JSON extraction patterns
                items = []

                # Pattern 1: __NEXT_DATA__
                match = re.search(
                    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
                    html, re.DOTALL
                )
                if match:
                    try:
                        data = json.loads(match.group(1))
                        # Try different paths in the JSON
                        search_result = (
                            data.get("props", {})
                            .get("pageProps", {})
                            .get("initialData", {})
                            .get("searchResult", {})
                        )
                        for stack in search_result.get("itemStacks", []):
                            items.extend(stack.get("items", []))
                        print(f"[Page {page}] __NEXT_DATA__ items: {len(items)}")
                    except Exception as e:
                        print(f"[Page {page}] __NEXT_DATA__ parse error: {e}")

                # Pattern 2: Look for JSON in script tags with product data
                if not items:
                    patterns = [
                        r'"searchResult"\s*:\s*(\{.*?"itemStacks".*?\})\s*[,}]',
                        r'window\.__WML_REDUX_INITIAL_STATE__\s*=\s*(\{.*?\});',
                    ]
                    for pattern in patterns:
                        m = re.search(pattern, html, re.DOTALL)
                        if m:
                            try:
                                chunk = json.loads(m.group(1))
                                for stack in chunk.get("itemStacks", []):
                                    items.extend(stack.get("items", []))
                                if items:
                                    print(f"[Page {page}] Alt pattern items: {len(items)}")
                                    break
                            except:
                                pass

                # Pattern 3: Walmart's structured data / JSON-LD
                if not items:
                    ld_matches = re.findall(
                        r'<script type="application/ld\+json">(.*?)</script>',
                        html, re.DOTALL
                    )
                    for ld in ld_matches:
                        try:
                            ld_data = json.loads(ld)
                            if isinstance(ld_data, list):
                                for entry in ld_data:
                                    if entry.get("@type") == "Product":
                                        items.append({
                                            "name": entry.get("name", ""),
                                            "brand": entry.get("brand", {}).get("name", brand) if isinstance(entry.get("brand"), dict) else brand,
                                            "usItemId": "",
                                            "upc": entry.get("gtin12", entry.get("gtin13", "")),
                                            "priceInfo": {"currentPrice": {"price": entry.get("offers", {}).get("price", "")}},
                                            "canonicalUrl": entry.get("url", "").replace("https://www.walmart.com", ""),
                                        })
                        except:
                            pass
                    if items:
                        print(f"[Page {page}] JSON-LD items: {len(items)}")

                if not items:
                    print(f"[Page {page}] No items found. HTML snippet: {html[:500]}")
                    break

                for item in items:
                    if len(products) >= max_items:
                        break

                    name = item.get("name", "")
                    if not name:
                        continue

                    price_info = item.get("priceInfo", {})
                    price = ""
                    if isinstance(price_info, dict):
                        p = price_info.get("currentPrice", {})
                        if isinstance(p, dict):
                            raw = p.get("price", "")
                            price = f"${float(raw):.2f}" if raw else ""

                    upc = str(item.get("upc") or item.get("upcCode") or item.get("GTIN") or "")
                    category = item.get("category", "")
                    if isinstance(category, dict):
                        category = category.get("name", "")

                    image = item.get("imageInfo", "")
                    if isinstance(image, dict):
                        image = image.get("thumbnailUrl", "")

                    canonical = item.get("canonicalUrl", "")
                    url = f"https://www.walmart.com{canonical}" if canonical.startswith("/") else canonical

                    products.append({
                        "name": name,
                        "brand": item.get("brand", brand) or brand,
                        "sku": str(item.get("usItemId", "")),
                        "item_id": str(item.get("itemId", "")),
                        "upc": upc,
                        "price": price,
                        "category": str(category),
                        "image": str(image),
                        "url": url,
                        "rating": str(item.get("averageRating", "")),
                        "source": "Walmart",
                        "asin": "",
                    })

                print(f"[Page {page}] Collected so far: {len(products)}")
                page += 1
                await asyncio.sleep(1.5)

            except Exception as e:
                print(f"[Page {page}] Error: {e}")
                break

    print(f"Total: {len(products)} products")
    return products


# ─── Endpoints ───────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {"status": "ok", "message": "ProductSync API running", "version": "2.0"}


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


@app.get("/debug")
async def debug_walmart(brand: str = Query("elf")):
    """Returns raw HTML snippet to debug scraping issues"""
    walmart_url = f"https://www.walmart.com/search?q={brand}&sort=best_match&page=1"
    scraper_url = f"https://api.scraperapi.com/?api_key={SCRAPER_API_KEY}&url={walmart_url}&country_code=us"
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(scraper_url)
        html = resp.text
        has_next_data = "__NEXT_DATA__" in html
        has_items = "itemStacks" in html
        return {
            "status": resp.status_code,
            "html_length": len(html),
            "has_next_data": has_next_data,
            "has_item_stacks": has_items,
            "html_preview": html[:1000],
        }


@app.get("/health")
def health():
    return {"status": "healthy", "scraper_key_set": bool(SCRAPER_API_KEY)}
