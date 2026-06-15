import os
import re
from difflib import SequenceMatcher
import requests

from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

try:
    import mysql.connector
except ImportError:
    mysql = None


app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

DB_NAME = "fashion_compare"
DB_HOST = os.getenv("MYSQL_HOST", "localhost")
DB_USER = os.getenv("MYSQL_USER", "root")
DB_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")

users_db = {
    "user@example.com": {
        "name": "John Doe",
        "email": "user@example.com",
        "password": "password123",
        "join_date": "2023-01-15",
    }
}

@app.on_event("startup")
async def startup_event():
    prepare_database()



import hashlib

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def get_logged_in_user(request: Request):
    email = request.cookies.get("user_email")
    if not email:
        return None
    try:
        connection = get_connection()
        if connection is None:
            return None
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT id, email, name, DATE_FORMAT(created_at, '%Y-%m-%d') AS join_date FROM users WHERE email = %s", (email,))
        user = cursor.fetchone()
        cursor.close()
        connection.close()
        return user
    except Exception as e:
        print("Error getting logged in user:", e)
        return None


def get_connection():
    if mysql is None:
        return None

    return mysql.connector.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
    )


def prepare_database():
    try:
        connection = get_connection()
        if connection is None:
            return

        cursor = connection.cursor()
        add_column_if_missing(cursor, "store_results", "match_score", "INT DEFAULT 0")
        add_column_if_missing(cursor, "store_results", "price_value", "DECIMAL(10,2)")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS price_history (
                id INT AUTO_INCREMENT PRIMARY KEY,
                search_log_id INT,
                store_name VARCHAR(80) NOT NULL,
                product_title VARCHAR(500) NOT NULL,
                price_text VARCHAR(80),
                price_value DECIMAL(10,2),
                product_url TEXT,
                image_url TEXT,
                checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INT AUTO_INCREMENT PRIMARY KEY,
                email VARCHAR(255) UNIQUE NOT NULL,
                name VARCHAR(255) NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS saved_products (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                store_name VARCHAR(80) NOT NULL,
                product_title VARCHAR(500) NOT NULL,
                price_text VARCHAR(80),
                price_value DECIMAL(10,2),
                product_url TEXT,
                image_url TEXT,
                saved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )
        connection.commit()
        cursor.close()
        connection.close()
    except Exception as error:
        print("Database update skipped:", error)


def add_column_if_missing(cursor, table_name, column_name, column_type):
    cursor.execute(
        """
        SELECT COUNT(*) AS total
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = %s
          AND TABLE_NAME = %s
          AND COLUMN_NAME = %s
        """,
        (DB_NAME, table_name, column_name),
    )
    column_exists = cursor.fetchone()[0] > 0

    if not column_exists:
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")


def save_search(query, request):
    try:
        connection = get_connection()
        if connection is None:
            print("MySQL connector is not installed.")
            return None

        cursor = connection.cursor()
        ip_address = request.client.host if request.client else ""

        cursor.execute(
            "INSERT INTO search_logs (query, ip_address) VALUES (%s, %s)",
            (query, ip_address),
        )
        connection.commit()

        search_id = cursor.lastrowid
        cursor.close()
        connection.close()
        return search_id
    except Exception as error:
        print("Search was not saved:", error)
        return None


def save_products(search_id, products):
    if search_id is None or not products:
        return

    try:
        connection = get_connection()
        if connection is None:
            return

        cursor = connection.cursor()

        for product in products:
            cursor.execute(
                """
                INSERT INTO store_results
                    (search_log_id, store_name, product_title, price_text,
                     product_url, image_url, match_score, price_value)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    search_id,
                    product["store"],
                    product["name"],
                    product["price"],
                    product["url"],
                    product["image"],
                    product["match_score"],
                    product["price_value"],
                ),
            )
            cursor.execute(
                """
                INSERT INTO price_history
                    (search_log_id, store_name, product_title, price_text,
                     price_value, product_url, image_url)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    search_id,
                    product["store"],
                    product["name"],
                    product["price"],
                    product["price_value"],
                    product["url"],
                    product["image"],
                ),
            )

        connection.commit()
        cursor.close()
        connection.close()
    except Exception as error:
        print("Products were not saved:", error)


def add_history_count(products):
    connection = get_connection()
    if connection is None:
        return products

    try:
        cursor = connection.cursor()
        for product in products:
            cursor.execute(
                "SELECT COUNT(*) FROM price_history WHERE product_url = %s",
                (product["url"],),
            )
            product["history_count"] = cursor.fetchone()[0]

        cursor.close()
        connection.close()
    except Exception as error:
        print("Could not read price history:", error)

    return products


def get_recent_searches():
    try:
        connection = get_connection()
        if connection is None:
            return []

        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT query, DATE_FORMAT(searched_at, '%Y-%m-%d %H:%i') AS date
            FROM search_logs
            ORDER BY searched_at DESC
            LIMIT 10
            """
        )

        searches = cursor.fetchall()
        cursor.close()
        connection.close()
        return searches
    except Exception as error:
        print("Could not read recent searches:", error)
        return []


def get_text(item, selector):
    tag = item.select_one(selector)
    if tag:
        return tag.get_text(" ", strip=True)
    return ""


def make_full_url(link, base_url):
    if not link:
        return base_url
    if link.startswith("http"):
        return link
    if link.startswith("/"):
        return base_url + link
    return base_url + "/" + link


def clean_words(text):
    text = text.lower()
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    return text.split()


def get_match_score(search_query, product_name):
    query_words = clean_words(search_query)
    product_words = clean_words(product_name)

    if not query_words or not product_words:
        return 0

    common_words = set(query_words).intersection(set(product_words))
    word_score = int((len(common_words) / len(query_words)) * 100)
    text_score = int(SequenceMatcher(None, search_query.lower(), product_name.lower()).ratio() * 100)
    return int((word_score + text_score) / 2)


def get_price_value(price_text):
    price_numbers = re.sub(r"[^0-9.]", "", price_text)
    if not price_numbers:
        return None

    try:
        return float(price_numbers)
    except ValueError:
        return None


def add_product_details(products, query):
    for product in products:
        product["match_score"] = get_match_score(query, product["name"])
        product["price_value"] = get_price_value(product["price"])
        product["history_count"] = 0

    products.sort(
        key=lambda product: (
            product["match_score"],
            -(product["price_value"] or 999999),
        ),
        reverse=True,
    )
    return products


def get_serpapi_products(query):
    """Fetch products from SerpAPI.

    Returns a tuple: (products, error_message).
    """
    if not SERPAPI_KEY:
        return [], "Missing SERPAPI_KEY"

    serpapi_timeout = float(os.getenv("SERPAPI_TIMEOUT_SECONDS", "25"))
    max_attempts = int(os.getenv("SERPAPI_MAX_ATTEMPTS", "3"))

    last_error = ""

    for attempt in range(1, max_attempts + 1):
        try:
            response = requests.get(
                "https://serpapi.com/search.json",
                params={
                    "engine": "google_shopping",
                    "q": query,
                    "api_key": SERPAPI_KEY,
                    "gl": "in",
                    "hl": "en",
                },
                timeout=serpapi_timeout,
            )
            data = response.json()

            products = []
            for idx, item in enumerate(data.get("shopping_results", [])):
                # One-time debug to identify the actual URL field coming from SerpAPI.
                if idx == 0:
                    print("SERPAPI first item keys:", list(item.keys()))
                    for k in [
                        "link",
                        "url",
                        "product_link",
                        "product_url",
                        "redirect_link",
                        "buy_link",
                    ]:
                        if k in item:
                            print(f"SERPAPI {k}:", item.get(k))

                name = item.get("title", "")
                price = item.get("price", "")
                store = item.get("source", "Google Shopping")

                # SerpAPI field names can vary; try multiple known options.
                url = (
                    item.get("link")
                    or item.get("url")
                    or item.get("product_link")
                    or item.get("product_url")
                    or item.get("redirect_link")
                    or item.get("buy_link")
                    or ""
                )

                image = item.get("thumbnail", "")

                if not name or not price:
                    continue

                products.append(
                    {
                        "store": store,
                        "name": name,
                        "price": price,
                        "url": url,
                        "image": image,
                    }
                )

                if len(products) == 20:
                    break

            return products, ""

        except requests.exceptions.RequestException as error:
            last_error = str(error)
            print(f"SerpAPI attempt {attempt}/{max_attempts} error:", last_error)

            if attempt < max_attempts:
                backoff_seconds = min(5.0 * (2 ** (attempt - 1)), 20.0)
                try:
                    import time

                    time.sleep(backoff_seconds)
                except Exception:
                    pass

        except Exception as error:
            last_error = str(error)
            print("SerpAPI error:", last_error)
            break


    return [], last_error





def get_saved_products(user_id):
    try:
        connection = get_connection()
        if connection is None:
            return []
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id, store_name, product_title, price_text, price_value, product_url, image_url
            FROM saved_products
            WHERE user_id = %s
            ORDER BY saved_at DESC
            """,
            (user_id,),
        )
        saved = cursor.fetchall()
        cursor.close()
        connection.close()
        return saved
    except Exception as e:
        print("Error getting saved products:", e)
        return []


def get_all_products(query):
    serpapi_products, serpapi_error = get_serpapi_products(query)
    if serpapi_products:
        return add_product_details(serpapi_products, query), ""
    return [], serpapi_error



def group_by_store(products):
    grouped = {}
    for product in products:
        store = product["store"]
        if store not in grouped:
            grouped[store] = []
        grouped[store].append(product)
    return grouped


@app.get("/")
async def home(request: Request):
    user = get_logged_in_user(request)
    return templates.TemplateResponse(request, "index.html", {"user": user})


@app.get("/shop")
async def shop(request: Request):
    user = get_logged_in_user(request)
    return templates.TemplateResponse(request, "shop.html", {"user": user})


@app.get("/signin")
async def signin(request: Request, error: str = ""):
    user = get_logged_in_user(request)
    if user:
        return RedirectResponse("/account", status_code=303)
    return templates.TemplateResponse(request, "signin.html", {"error": error})


@app.get("/signup")
async def signup_get(request: Request, error: str = ""):
    user = get_logged_in_user(request)
    if user:
        return RedirectResponse("/account", status_code=303)
    return templates.TemplateResponse(request, "signup.html", {"error": error})


@app.post("/signup")
async def signup_post(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
):
    email = email.strip().lower()
    hashed = hash_password(password)
    try:
        connection = get_connection()
        if connection is None:
            return templates.TemplateResponse(
                request, "signup.html", {"error": "Database not connected."}
            )

        cursor = connection.cursor()
        cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
        if cursor.fetchone():
            cursor.close()
            connection.close()
            return templates.TemplateResponse(
                request, "signup.html", {"error": "Email is already registered."}
            )

        cursor.execute(
            "INSERT INTO users (email, name, password_hash) VALUES (%s, %s, %s)",
            (email, name, hashed),
        )
        connection.commit()
        cursor.close()
        connection.close()

        response = RedirectResponse("/account", status_code=303)
        response.set_cookie(key="user_email", value=email)
        return response
    except Exception as e:
        print("Signup error:", e)
        return templates.TemplateResponse(
            request, "signup.html", {"error": "An error occurred during signup."}
        )


@app.post("/account")
async def account_post(request: Request, email: str = Form(...), password: str = Form(...)):
    email = email.strip().lower()
    hashed = hash_password(password)
    try:
        connection = get_connection()
        if connection is None:
            return templates.TemplateResponse(
                request, "signin.html", {"error": "Database not connected."}
            )

        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            "SELECT id, email, name, password_hash, DATE_FORMAT(created_at, '%Y-%m-%d') AS join_date FROM users WHERE email = %s",
            (email,),
        )
        user = cursor.fetchone()
        cursor.close()
        connection.close()

        if user and user["password_hash"] == hashed:
            user_data = {
                "id": user["id"],
                "email": user["email"],
                "name": user["name"],
                "join_date": user["join_date"],
            }
            response = templates.TemplateResponse(
                request,
                "account.html",
                {
                    "user": user_data,
                    "history": get_recent_searches(),
                    "saved_products": get_saved_products(user["id"]),
                },
            )
            response.set_cookie(key="user_email", value=email)
            return response

        return templates.TemplateResponse(
            request, "signin.html", {"error": "Invalid email or password."}
        )
    except Exception as e:
        print("Login error:", e)
        return templates.TemplateResponse(
            request, "signin.html", {"error": "An error occurred during signin."}
        )


@app.get("/account")
async def account_get(request: Request):
    user = get_logged_in_user(request)
    if not user:
        return RedirectResponse("/signin", status_code=303)

    return templates.TemplateResponse(
        request,
        "account.html",
        {
            "user": user,
            "history": get_recent_searches(),
            "saved_products": get_saved_products(user["id"]),
        },
    )


@app.get("/logout")
async def logout(request: Request):
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie("user_email")
    return response


@app.get("/compare")
async def compare_products(request: Request, query: str = Query(..., min_length=2)):
    query = query.strip()
    search_id = save_search(query, request)

    products, serpapi_error = get_all_products(query)
    save_products(search_id, products)
    products = add_history_count(products)
    user = get_logged_in_user(request)

    return templates.TemplateResponse(
        request,
        "results.html",
        {
            "query": query,
            "results": group_by_store(products),
            "search_id": search_id,
            "user": user,
            "serpapi_error": serpapi_error,
        },
    )



@app.get("/history")
async def price_history_page(request: Request, url: str = Query(...), title: str = Query("")):
    user = get_logged_in_user(request)
    try:
        connection = get_connection()
        if connection is None:
            return templates.TemplateResponse(
                request,
                "history.html",
                {
                    "url": url,
                    "title": title,
                    "history": [],
                    "error": "Database not connected",
                    "user": user,
                },
            )
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT price_text, price_value, DATE_FORMAT(checked_at, '%Y-%m-%d %H:%i') AS checked_date
            FROM price_history
            WHERE product_url = %s
            ORDER BY checked_at DESC
            """,
            (url,),
        )
        history = cursor.fetchall()
        cursor.close()
        connection.close()
        return templates.TemplateResponse(
            request, "history.html", {"url": url, "title": title, "history": history, "user": user}
        )
    except Exception as e:
        print("Error getting price history:", e)
        return templates.TemplateResponse(
            request,
            "history.html",
            {"url": url, "title": title, "history": [], "error": str(e), "user": user},
        )


@app.post("/save-product")
async def save_product(
    request: Request,
    store: str = Form(None),
    title: str = Form(None),
    price_text: str = Form(None),
    price_value: str = Form(None),
    url: str = Form(None),
    image: str = Form(None),
):
    user = get_logged_in_user(request)
    if not user:
        return RedirectResponse("/signin", status_code=303)

    if not url or not title:
        print("Missing required fields for saving product:", f"url={url}", f"title={title}")
        return RedirectResponse("/account", status_code=303)

    parsed_price = get_price_value(price_text)

    # Store debug info so we can confirm the POST payload is correct.
    # Log request payload for debugging (avoid None-url inserts).
    print(
        "SAVE_PRODUCT payload:",
        {
            "user_id": user.get("id"),
            "store": store,
            "title": title,
            "price_text": price_text,
            "parsed_price": parsed_price,
            "url": url,
            "image_present": bool(image),
        },
    )

    # Extra safety: if form is missing URL, do not attempt DB write.
    if not url:
        print("SAVE_PRODUCT: missing url in payload; skipping save")
        return RedirectResponse("/account", status_code=303)


    try:
        connection = get_connection()
        if connection is None:
            print("SAVE_PRODUCT: DB connection is None")
            return RedirectResponse("/account", status_code=303)

        cursor = connection.cursor()
        cursor.execute(
            "SELECT id FROM saved_products WHERE user_id = %s AND product_url = %s",
            (user["id"], url),
        )
        existing = cursor.fetchone()

        if not existing:
            cursor.execute(
                """
                INSERT INTO saved_products
                    (user_id, store_name, product_title, price_text, price_value, product_url, image_url)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (user["id"], store, title, price_text, parsed_price, url, image),
            )
            connection.commit()
            print("SAVE_PRODUCT: inserted")
        else:
            print("SAVE_PRODUCT: already saved, skipping insert")

        cursor.close()
        connection.close()
    except Exception as e:
        print("Error saving product:", e)

    return RedirectResponse("/account", status_code=303)



@app.post("/delete-product")
async def delete_product(request: Request, id: int = Form(...)):
    user = get_logged_in_user(request)
    if not user:
        return RedirectResponse("/signin", status_code=303)

    try:
        connection = get_connection()
        if connection is not None:
            cursor = connection.cursor()
            cursor.execute(
                "DELETE FROM saved_products WHERE id = %s AND user_id = %s", (id, user["id"])
            )
            connection.commit()
            cursor.close()
            connection.close()
    except Exception as e:
        print("Error deleting product:", e)

    return RedirectResponse("/account", status_code=303)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
