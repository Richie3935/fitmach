from fastapi import FastAPI, Query, Request, Form
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
import requests
from bs4 import BeautifulSoup
import time
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from datetime import datetime

app = FastAPI()

# Serve static files and setup templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

def fetch_asos_products(query):
    try:
        url = "https://asos2.p.rapidapi.com/products/v2/list"
        headers = {
            "X-RapidAPI-Key": "d471f710e0msh7297125fd67a5ddp1e624bjsna08928b44335",
            "X-RapidAPI-Host": "asos2.p.rapidapi.com",
        }
        params = {"store": "US", "limit": "5", "q": query}
        response = session.get(url, headers=headers, params=params, timeout=15)
        response.raise_for_status()
        
        products = []
        for product in response.json().get("products", []):
            price_data = product.get("price", {})
            current_price = price_data.get("current", {}).get("text", "Price not available")
            
            products.append({
                "name": product.get("name", "No name"),
                "price": current_price,
                "url": f"https://www.asos.com/us/{product.get('url', '')}",
                "image": product.get("imageUrl", "")
            })
        return products
    except Exception as e:
        print(f"ASOS Error: {str(e)}")
        return []

def fetch_hm_products(query):
    try:
        url = f"https://www.hm.com/us/en/search?q={query}"
        headers = {
            # Existing headers
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
            
            # ADD THESE NEW HEADERS TO BYPASS 403
            "Accept": "text/html,application/xhtml+xml",
            "Referer": "https://www.hm.com/",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1"
        }
        
        print(f"\nFetching H&M URL: {url}")  # Debug
        response = session.get(url, headers=headers, timeout=15)
        print(f"HTTP Status: {response.status_code}")  # Debug
        
        # Save the HTML for inspection
        with open("hm_debug.html", "w", encoding="utf-8") as f:
            f.write(response.text)
        print("Saved H&M HTML to 'hm_debug.html'")  # Debug
        
        soup = BeautifulSoup(response.text, "html.parser")
        
        # NEW: Print raw HTML chunks containing products (debug)
        product_chunks = soup.select('[data-productid], .hm-product-item, .product-item')
        print(f"Found {len(product_chunks)} potential product containers")
        
        products = []
        for item in product_chunks:
            try:
                name = item.select_one('[data-productname], .item-heading, .product-item-heading, .product-title')
                price = item.select_one('.item-price, .product-item-price, .price-value, .price')
                link = item.select_one('a[href]')
                
                if not all([name, price, link]):
                    print("Skipping item - missing data")  # Debug
                    continue
                    
                product_data = {
                    "name": name.text.strip(),
                    "price": price.text.strip(),
                    "url": "https://www.hm.com" + link["href"]
                }
                print(f"Found product: {product_data}")  # Debug
                products.append(product_data)
                
            except Exception as e:
                print(f"Skipping product - Error: {str(e)}")  # Debug
                continue
                
        return products[:5]
    
    except Exception as e:
        print(f"H&M CRITICAL ERROR: {str(e)}")
        return []

def fetch_myntra_products(query):
    try:
        url = f"https://www.myntra.com/{query}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = session.get(url, headers=headers)
        soup = BeautifulSoup(response.text, 'html.parser')
        products = []
        for item in soup.select('.product-base'):
            try:
                name = item.select_one('.product-product').text.strip()
                price = item.select_one('.product-discountedPrice').text.strip()
                image = item.select_one('img')['src']
                url = 'https://www.myntra.com' + item.select_one('a')['href']
                products.append({'name': name, 'price': price, 'image': image, 'url': url})
            except:
                continue
        return products[:5]
    except Exception as e:
        print(f"Error fetching Myntra products: {e}")
        return []

def fetch_zara_products(query):
    try:
        url = f"https://www.zara.com/us/en/search?searchTerm={query}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = session.get(url, headers=headers)
        soup = BeautifulSoup(response.text, 'html.parser')
        products = []
        for item in soup.select('.product-grid-product'):
            try:
                name = item.select_one('.product-grid-product-info__name').text.strip()
                price = item.select_one('.money-amount__main').text.strip()
                image = item.select_one('img')['src']
                url = 'https://www.zara.com' + item.select_one('a')['href']
                products.append({'name': name, 'price': price, 'image': image, 'url': url})
            except:
                continue
        return products[:5]
    except Exception as e:
        print(f"Error fetching Zara products: {e}")
        return []

# Mock user database
users_db = {
    "user@example.com": {
        "name": "John Doe",
        "email": "user@example.com",
        "password": "password123",
        "join_date": "2023-01-15"
    }
}

# Mock comparison history
comparison_history = [
    {"query": "jeans", "date": "2023-11-01"},
    {"query": "t-shirt", "date": "2023-11-05"},
]

# Configure retry strategy
session = requests.Session()
retries = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=[500, 502, 503, 504]
)
session.mount('https://', HTTPAdapter(max_retries=retries))

# Your existing scraping functions (ASOS, H&M, Myntra, Zara) remain the same
# [Keep all the fetch_asos_products, fetch_hm_products, etc. functions exactly as they were]

@app.get("/")
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/shop")
async def shop(request: Request):
    return templates.TemplateResponse("shop.html", {"request": request})

@app.get("/signin")
async def signin(request: Request):
    return templates.TemplateResponse("signin.html", {"request": request})

@app.post("/account")
async def account(request: Request, email: str = Form(...), password: str = Form(...)):
    user = users_db.get(email)
    if user and user["password"] == password:
        return templates.TemplateResponse("account.html", {
            "request": request,
            "user": user,
            "history": comparison_history
        })
    return RedirectResponse("/signin")

@app.get("/account")
async def account_get(request: Request):
    # For demo purposes, show the first user
    user = list(users_db.values())[0]
    return templates.TemplateResponse("account.html", {
        "request": request,
        "user": user,
        "history": comparison_history
    })

@app.get("/compare")
async def compare_products(request: Request, query: str = Query(...)):
    results = {
        "ASOS": fetch_asos_products(query),
        "H&M": fetch_hm_products(query),
        "Myntra": fetch_myntra_products(query),
        "Zara": fetch_zara_products(query)
    }
    
    # Add to comparison history
    comparison_history.insert(0, {
        "query": query,
        "date": datetime.now().strftime("%Y-%m-%d")
    })
    
    return templates.TemplateResponse("results.html", {
        "request": request,
        "query": query,
        "results": results
    })

if __name__ == "__main__":
    import uvicorn
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        query = input("Enter product to search (e.g., shirt, jeans): ").strip()
        print(f"\nTesting with query: '{query}'")
        
        print("\nTesting ASOS:")
        asos_results = fetch_asos_products(query)
        print(f"Found {len(asos_results)} products")
        if asos_results:
            print("First product:", asos_results[0])
        
        print("\nTesting H&M:")
        hm_results = fetch_hm_products(query)
        print(f"Found {len(hm_results)} products")
        if hm_results:
            print("First product:", hm_results[0])
        
        print("\nTesting Myntra:")
        myntra_results = fetch_myntra_products(query)
        print(f"Found {len(myntra_results)} products")
        if myntra_results:
            print("First product:", myntra_results[0])
        
        print("\nTesting Zara:")
        zara_results = fetch_zara_products(query)
        print(f"Found {len(zara_results)} products")
        if zara_results:
            print("First product:", zara_results[0])
    else:
        uvicorn.run(app, host="0.0.0.0", port=8000)
