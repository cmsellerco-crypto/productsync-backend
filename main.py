from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import httpx
import json
import csv
import io
import asyncio
import re

app = FastAPI(title="ProductSync API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
}

# ─── Walmart Scraper ─────────────────────────────────────────────────────────

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

    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=30) as client:
        while len(products) < max_items:
            url = (
                f"https://www.walmart.com/search?q={brand}"
                f"&sort={sort_param}&page={page}&affinityOverride=default"
            )

            try:
                resp = await client.get(url)
                html = resp.text

                # Extract __NEXT_DATA__ JSON from Walmart's page
                match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.DOTALL)
                if not match:
                    break

                data = json.loads(match.group(1))
                items = (
                    data.get("props", {})
                    .get("pageProps", {})
                    .get("initialData", {})
                    .get("searchResult", {})
                    .get("itemStacks", [{}])[0]
                    .get("items", [])
                )

                if not items:
                    break

                for item in items:
                    if len(products) >= max_items:
                        break

                    name = item.get("name", "")
                    if not name:
                        continue

                    price_info = item.get("priceInfo", {})
                    price = price_info.get("currentPrice", {}).get("price", "")
                    price_str = f"${price:.2f}" if isinstance(price, (int, float)) else ""

                    products.append({
                        "name": name,
                        "brand": item.get("brand", brand),
                        "sku": item.get("usItemId", ""),
                        "item_id": item.get("itemId", ""),
                        "upc": item.get("upc", ""),
                        "price": price_str,
                        "category": item.get("category", {}).get("name", ""),
                        "image": item.get("imageInfo", {}).get("thumbnailUrl", ""),
                        "url": f"https://www.walmart.com{item.get('canonicalUrl', '')}",
                        "rating": item.get("averageRating", ""),
                        "source": "Walmart",
                        "asin": "",
                    })

                page += 1
                await asyncio.sleep(0.5)

            except Exception as e:
                print(f"Walmart error page {page}: {e}")
                break

    return products


# ─── Endpoints ───────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {"status": "ok", "message": "ProductSync API is running"}


@app.get("/scrape/walmart")
async def walmart_endpoint(
    brand: str = Query(..., description="Brand name to search"),
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
    return {"status": "healthy"}
