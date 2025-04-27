from fastapi import FastAPI, Query, Request, Form
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from datetime import datetime

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

users_db = {
    "user@example.com": {
        "name": "John Doe",
        "email": "user@example.com",
        "password": "password123",
        "join_date": "2023-01-15"
    }
}

session = requests.Session()
retries = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
session.mount('https://', HTTPAdapter(max_retries=retries))

comparison_history = [
    {"query": "jeans", "date": "2025-04-18"},
    {"query": "t-shirt", "date": "2025-04-19"},
]

def fetch_asos_products(query):
    try:
        url = f"https://www.asos.com/search/?q={query}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = session.get(url, headers=headers)
        soup = BeautifulSoup(response.text, 'html.parser')
        products = []
        for item in soup.select('article[data-auto-id="productTile"]'):
            try:
                name = item.select_one('[data-auto-id="productTileDescription"]').text.strip()
                price = item.select_one('[data-auto-id="productTilePrice"]').text.strip()
                image = item.select_one('img')['src']
                url = 'https://www.asos.com' + item.select_one('a[data-auto-id="productTileLink"]')['href']
                products.append({'name': name, 'price': price, 'image': image, 'url': url})
            except:
                continue
        return products[:5]
    except Exception as e:
        print(f"Error fetching ASOS products: {e}")
        return []

def fetch_hm_products(query):
    try:
        url = f"https://www2.hm.com/en_us/search-results.html?q={query}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = session.get(url, headers=headers)
        soup = BeautifulSoup(response.text, 'html.parser')
        products = []
        for item in soup.select('.product-item'):
            try:
                name = item.select_one('.item-heading a').text.strip()
                price = item.select_one('.item-price').text.strip()
                image = item.select_one('img')['data-src']
                url = 'https://www2.hm.com' + item.select_one('.item-heading a')['href']
                products.append({'name': name, 'price': price, 'image': image, 'url': url})
            except:
                continue
        return products[:5]
    except Exception as e:
        print(f"Error fetching H&M products: {e}")
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
async def account_post(request: Request, email: str = Form(...), password: str = Form(...)):
    user = users_db.get(email)
    if user and user["password"] == password:
        return templates.TemplateResponse("account.html", {"request": request, "user": user, "history": comparison_history})
    return RedirectResponse("/signin", status_code=303)

@app.get("/account")
async def account_get(request: Request):
    user = list(users_db.values())[0]
    return templates.TemplateResponse("account.html", {"request": request, "user": user, "history": comparison_history})

@app.get("/compare")
async def compare_products(request: Request, query: str = Query(...)):
    results = {
        "ASOS": fetch_asos_products(query),
        "H&M": fetch_hm_products(query),
        "Myntra": fetch_myntra_products(query),
        "Zara": fetch_zara_products(query)
    }
    comparison_history.insert(0, {"query": query, "date": datetime.now().strftime("%Y-%m-%d")})
    return templates.TemplateResponse("results.html", {"request": request, "query": query, "results": results})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
