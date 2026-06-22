import os
import re
import json
from contextlib import asynccontextmanager
from difflib import SequenceMatcher
import requests

from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

try:
    import mysql.connector
except ImportError:
    mysql = None


DB_NAME = "fashion_compare"
DB_HOST = os.getenv("MYSQL_HOST", "localhost")
DB_USER = os.getenv("MYSQL_USER", "root")
DB_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")

import hashlib


# ---------------------------------------------------------------------------
# Lifespan (replaces deprecated @app.on_event("startup"))
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    prepare_database()
    yield


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def get_connection():
    if mysql is None:
        return None
    return mysql.connector.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
    )


def get_logged_in_user(request: Request):
    email = request.cookies.get("user_email")
    if not email:
        return None
    try:
        connection = get_connection()
        if connection is None:
            return None
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            "SELECT id, email, name, DATE_FORMAT(created_at, '%Y-%m-%d') AS join_date FROM users WHERE email = %s",
            (email,),
        )
        user = cursor.fetchone()
        cursor.close()
        connection.close()
        return user
    except Exception as e:
        print("Error getting logged in user:", e)
        return None


def prepare_database():
    try:
        connection = get_connection()
        if connection is None:
            return
        cursor = connection.cursor()
        add_column_if_missing(cursor, "store_results", "match_score", "INT DEFAULT 0")
        add_column_if_missing(cursor, "store_results", "price_value", "DECIMAL(10,2)")
        # stable product identity
        add_column_if_missing(cursor, "wishlist", "product_key", "VARCHAR(255) NOT NULL DEFAULT ''")
        add_column_if_missing(cursor, "price_history", "product_key", "VARCHAR(255) NOT NULL DEFAULT ''")

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
                product_key VARCHAR(255) NOT NULL,
                image_url TEXT,
                checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_price_history_product_key (product_key)
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
        # Wishlist is the single product-tracking table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS wishlist (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                store_name VARCHAR(80) NOT NULL,
                product_title VARCHAR(500) NOT NULL,
                price_text VARCHAR(80),
                price_value DECIMAL(10,2),
                product_url TEXT,
                image_url TEXT,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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
    if cursor.fetchone()[0] == 0:
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")


def save_search(query, request):
    try:
        connection = get_connection()
        if connection is None:
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
            url = product["url"]
            pkey = get_product_key(url)

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
                    url,
                    product["image"],
                    product["match_score"],
                    product["price_value"],
                ),
            )
            cursor.execute(
                """
                INSERT INTO price_history
                    (search_log_id, store_name, product_title, price_text,
                     price_value, product_url, product_key, image_url)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    search_id,
                    product["store"],
                    product["name"],
                    product["price"],
                    product["price_value"],
                    url,
                    pkey,
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
                "SELECT COUNT(*) FROM price_history WHERE product_url = %s OR product_key = %s",
                (product["url"], product.get("product_key")),
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


def get_wishlist(user_id):

    try:
        connection = get_connection()
        if connection is None:
            return []
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id, store_name, product_title, price_text, price_value, product_url, product_key, image_url,
                   DATE_FORMAT(added_at, '%Y-%m-%d') AS added_date
            FROM wishlist

            WHERE user_id = %s
            ORDER BY added_at DESC
            """,
            (user_id,),
        )
        items = cursor.fetchall()
        cursor.close()
        connection.close()
        return items
    except Exception as e:
        print("Error getting wishlist:", e)
        return []


# ---------------------------------------------------------------------------
# Price history stats + AI advisor (rule-based)
# ---------------------------------------------------------------------------

def compute_price_stats(history: list) -> dict:
    """Compute min, max, avg and trend from price_history rows."""
    values = [r["price_value"] for r in history if r.get("price_value") is not None]
    if not values:
        return {}

    low = min(values)
    high = max(values)
    avg = sum(values) / len(values)
    current = values[0]  # most recent first

    pct_from_avg = ((current - avg) / avg * 100) if avg else 0

    # Trend: compare first half vs second half average
    mid = len(values) // 2
    if mid > 0:
        recent_avg = sum(values[:mid]) / mid
        older_avg = sum(values[mid:]) / (len(values) - mid)
        if recent_avg < older_avg * 0.97:
            trend = "falling"
        elif recent_avg > older_avg * 1.03:
            trend = "rising"
        else:
            trend = "stable"
    else:
        trend = "stable"

    return {
        "current": current,
        "low": low,
        "high": high,
        "avg": round(avg, 2),
        "pct_from_avg": round(pct_from_avg, 1),
        "trend": trend,
        "data_points": len(values),
    }


def get_shopping_advice(stats: dict) -> dict:
    """
    Rule-based shopping advisor. Returns recommendation, confidence, and reason.
    """
    if not stats:
        return {
            "recommendation": "MONITOR",
            "confidence": 30,
            "label": "Monitor",
            "color": "amber",
            "icon": "👀",
            "reason": "Not enough price data to advise. Check back after more price records are collected.",
            "factors": [],
        }

    current = stats["current"]
    low = stats["low"]
    high = stats["high"]
    avg = stats["avg"]
    pct_from_avg = stats["pct_from_avg"]
    trend = stats["trend"]
    data_points = stats["data_points"]

    score = 0  # positive = buy, negative = wait
    factors = []

    # Factor 1: How close to all-time low?
    price_range = high - low
    if price_range > 0:
        pct_above_low = ((current - low) / price_range) * 100
    else:
        pct_above_low = 50

    if pct_above_low <= 10:
        score += 40
        factors.append(("✅", "Price is at or near its all-time low"))
    elif pct_above_low <= 30:
        score += 20
        factors.append(("✅", "Price is in the lower 30% of its historical range"))
    elif pct_above_low >= 80:
        score -= 35
        factors.append(("❌", "Price is near its all-time high — likely to drop"))
    else:
        factors.append(("ℹ️", f"Price is at {round(pct_above_low)}% of its historical range"))

    # Factor 2: Below average?
    if pct_from_avg <= -10:
        score += 30
        factors.append(("✅", f"Price is {abs(pct_from_avg)}% below the historical average"))
    elif pct_from_avg <= 0:
        score += 10
        factors.append(("✅", "Price is slightly below the average"))
    elif pct_from_avg >= 15:
        score -= 25
        factors.append(("❌", f"Price is {pct_from_avg}% above average — not a great time"))
    else:
        factors.append(("ℹ️", f"Price is {pct_from_avg}% above average"))

    # Factor 3: Trend direction
    if trend == "falling":
        score -= 15
        factors.append(("⏳", "Prices are falling — waiting may get you a better deal"))
    elif trend == "rising":
        score += 15
        factors.append(("⬆️", "Prices are rising — buying now locks in a lower price"))
    else:
        factors.append(("➡️", "Price has been stable recently"))

    # Factor 4: Data confidence
    if data_points < 3:
        score = int(score * 0.6)
        factors.append(("⚠️", "Limited data — recommendation confidence is lower"))

    # Map score to recommendation
    if score >= 40:
        rec = "BUY NOW"
        label = "Buy Now"
        color = "green"
        icon = "🛒"
        confidence = min(95, 60 + score)
    elif score >= 10:
        rec = "BUY NOW"
        label = "Buy Now"
        color = "green"
        icon = "🛒"
        confidence = min(75, 50 + score)
    elif score >= -10:
        rec = "MONITOR"
        label = "Monitor"
        color = "amber"
        icon = "👀"
        confidence = max(40, 55 + score)
    else:
        rec = "WAIT"
        label = "Wait"
        color = "red"
        icon = "⏳"
        confidence = min(85, 55 + abs(score))

    confidence = max(20, min(95, confidence))

    # Build a short natural-language reason
    if rec == "BUY NOW":
        reason = f"At ₹{current:.0f}, this is a good time to buy. The price is {abs(pct_from_avg)}% {'below' if pct_from_avg < 0 else 'near'} the average and the trend is {trend}."
    elif rec == "WAIT":
        reason = f"At ₹{current:.0f}, the price is elevated ({pct_from_avg}% above average). With a {trend} trend, waiting may save you money."
    else:
        reason = f"At ₹{current:.0f}, the price is close to the average (₹{avg:.0f}). Monitor for a dip before buying."

    return {
        "recommendation": rec,
        "confidence": confidence,
        "label": label,
        "color": color,
        "icon": icon,
        "reason": reason,
        "factors": factors,
    }


# ---------------------------------------------------------------------------
# Product fetching helpers
# ---------------------------------------------------------------------------

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


def normalize_product_url(url: str) -> str:
    """Normalize a product URL into a canonical-ish representation.

    Goal: make product identity stable across SERP API URL variants.
    """
    if not url:
        return ""
    url = str(url).strip()
    # Lowercase scheme+host, strip fragment, and remove common tracking query params.
    # Keep path so different products don't collide.
    try:
        from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

        parts = urlsplit(url)
        query_pairs = parse_qsl(parts.query, keep_blank_values=True)

        # Drop common tracking params
        drop_keys = {
            "utm_source",
            "utm_medium",
            "utm_campaign",
            "utm_term",
            "utm_content",
            "gclid",
            "fbclid",
            "mc_cid",
            "mc_eid",
            "ga",
            "ref",
        }
        filtered = [(k, v) for (k, v) in query_pairs if k.lower() not in drop_keys]

        # Sort for stability
        filtered.sort(key=lambda kv: kv[0].lower())

        normalized_query = urlencode(filtered, doseq=True)
        normalized = urlunsplit(
            (parts.scheme.lower(), parts.netloc.lower(), parts.path, normalized_query, "")
        )
        return normalized
    except Exception:
        # Fallback: strip fragment and lowercase whole string
        return url.split("#", 1)[0].strip().lower()


def get_product_key(url: str) -> str:
    """Stable product identity key derived from normalized URL."""
    normalized = normalize_product_url(url)
    if not normalized:
        return ""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def get_price_value(price_text):
    if not price_text:
        return None
    price_numbers = re.sub(r"[^0-9.]", "", str(price_text))
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
        key=lambda p: (p["match_score"], -(p["price_value"] or 999999)),
        reverse=True,
    )
    return products


def get_serpapi_products(query):
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
            for item in data.get("shopping_results", []):
                name = item.get("title", "")
                price = item.get("price", "")
                store = item.get("source", "Google Shopping")
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
                products.append({"store": store, "name": name, "price": price, "url": url, "image": image})
                if len(products) == 20:
                    break
            return products, ""
        except requests.exceptions.RequestException as error:
            last_error = str(error)
            print(f"SerpAPI attempt {attempt}/{max_attempts} error:", last_error)
            if attempt < max_attempts:
                import time
                time.sleep(min(5.0 * (2 ** (attempt - 1)), 20.0))
        except Exception as error:
            last_error = str(error)
            print("SerpAPI error:", last_error)
            break

    return [], last_error


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


# ---------------------------------------------------------------------------
# Dashboard stats helper — uses wishlist only
# ---------------------------------------------------------------------------

def get_dashboard_stats(user_id):
    stats = {
        "total_wishlist": 0,
        "total_searches": 0,
        "avg_wishlist_price": None,
        "cheapest_wishlist": None,
        "most_expensive_wishlist": None,
    }
    try:
        connection = get_connection()
        if connection is None:
            return stats
        cursor = connection.cursor(dictionary=True)

        cursor.execute("SELECT COUNT(*) AS cnt FROM wishlist WHERE user_id = %s", (user_id,))
        stats["total_wishlist"] = cursor.fetchone()["cnt"]

        cursor.execute("SELECT COUNT(*) AS cnt FROM search_logs")
        stats["total_searches"] = cursor.fetchone()["cnt"]

        cursor.execute(
            """
            SELECT AVG(price_value) AS avg_price,
                   MIN(price_value) AS min_p,
                   MAX(price_value) AS max_p
            FROM wishlist
            WHERE user_id = %s AND price_value IS NOT NULL
            """,
            (user_id,),
        )
        row = cursor.fetchone()
        if row and row["avg_price"]:
            stats["avg_wishlist_price"] = round(float(row["avg_price"]), 2)
            stats["cheapest_wishlist"] = round(float(row["min_p"]), 2)
            stats["most_expensive_wishlist"] = round(float(row["max_p"]), 2)

        cursor.close()
        connection.close()
    except Exception as e:
        print("Dashboard stats error:", e)
    return stats


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/")
async def home(request: Request):
    user = get_logged_in_user(request)
    return templates.TemplateResponse(request, "index.html", {"user": user})


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
            return templates.TemplateResponse(request, "signup.html", {"error": "Database not connected."})
        cursor = connection.cursor()
        cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
        if cursor.fetchone():
            cursor.close()
            connection.close()
            return templates.TemplateResponse(request, "signup.html", {"error": "Email is already registered."})
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
        return templates.TemplateResponse(request, "signup.html", {"error": "An error occurred during signup."})


@app.post("/account")
async def account_post(request: Request, email: str = Form(...), password: str = Form(...)):
    email = email.strip().lower()
    hashed = hash_password(password)
    try:
        connection = get_connection()
        if connection is None:
            return templates.TemplateResponse(request, "signin.html", {"error": "Database not connected."})
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            "SELECT id, email, name, password_hash, DATE_FORMAT(created_at, '%Y-%m-%d') AS join_date FROM users WHERE email = %s",
            (email,),
        )
        user = cursor.fetchone()
        cursor.close()
        connection.close()
        if user and user["password_hash"] == hashed:
            user_data = {"id": user["id"], "email": user["email"], "name": user["name"], "join_date": user["join_date"]}
            response = templates.TemplateResponse(
                request,
                "account.html",
                {
                    "user": user_data,
                    "history": get_recent_searches(),
                    "wishlist": get_wishlist(user["id"]),
                    "dash_stats": get_dashboard_stats(user["id"]),
                },
            )
            response.set_cookie(key="user_email", value=email)
            return response
        return templates.TemplateResponse(request, "signin.html", {"error": "Invalid email or password."})
    except Exception as e:
        print("Login error:", e)
        return templates.TemplateResponse(request, "signin.html", {"error": "An error occurred during signin."})


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
            "wishlist": get_wishlist(user["id"]),
            "dash_stats": get_dashboard_stats(user["id"]),
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
                {"url": url, "title": title, "history": [], "stats": {}, "advice": {}, "chart_data": "[]", "error": "Database not connected", "user": user},
            )
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT price_text, price_value,
                   DATE_FORMAT(checked_at, '%Y-%m-%d %H:%i') AS checked_date,
                   store_name
            FROM price_history
            WHERE product_key = %s
            ORDER BY checked_at DESC
            """,
            (get_product_key(url),),
        )

        history = cursor.fetchall()
        cursor.close()
        connection.close()

        stats = compute_price_stats(history)
        advice = get_shopping_advice(stats)

        # Chart data: chronological order (oldest first) for the line chart
        chart_entries = [
            {"date": r["checked_date"], "price": float(r["price_value"])}
            for r in reversed(history)
            if r.get("price_value") is not None
        ]
        chart_data = json.dumps(chart_entries)

        return templates.TemplateResponse(
            request,
            "history.html",
            {
                "url": url,
                "title": title,
                "history": history,
                "stats": stats,
                "advice": advice,
                "chart_data": chart_data,
                "user": user,
            },
        )
    except Exception as e:
        print("Error getting price history:", e)
        return templates.TemplateResponse(
            request,
            "history.html",
            {"url": url, "title": title, "history": [], "stats": {}, "advice": {}, "chart_data": "[]", "error": str(e), "user": user},
        )


# ---------------------------------------------------------------------------
# Wishlist routes — single product-tracking system
# ---------------------------------------------------------------------------

@app.post("/wishlist/add")
async def wishlist_add(
    request: Request,
    store: str = Form(None),
    title: str = Form(None),
    price_text: str = Form(None),
    url: str = Form(None),
    image: str = Form(None),
):
    user = get_logged_in_user(request)
    if not user:
        return RedirectResponse("/signin", status_code=303)
    if not url or not title:
        return RedirectResponse("/account", status_code=303)

    parsed_price = get_price_value(price_text)
    try:
        connection = get_connection()
        if connection is None:
            return RedirectResponse("/account", status_code=303)
        cursor = connection.cursor()
        pkey = get_product_key(url)

        cursor.execute(

            "SELECT id FROM wishlist WHERE user_id = %s AND product_key = %s",
            (user["id"], pkey),
        )
        if not cursor.fetchone():
            cursor.execute(
                """
                INSERT INTO wishlist
                    (user_id, store_name, product_title, price_text, price_value, product_url, product_key, image_url)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (user["id"], store, title, price_text, parsed_price, url, pkey, image),
            )
            connection.commit()

        cursor.close()
        connection.close()
    except Exception as e:
        print("Error adding to wishlist:", e)
    return RedirectResponse("/account", status_code=303)


@app.post("/wishlist/remove")
async def wishlist_remove(request: Request, id: int = Form(...)):
    user = get_logged_in_user(request)
    if not user:
        return RedirectResponse("/signin", status_code=303)
    try:
        connection = get_connection()
        if connection is not None:
            cursor = connection.cursor()
            cursor.execute(
                "DELETE FROM wishlist WHERE id = %s AND user_id = %s", (id, user["id"])
            )
            connection.commit()
            cursor.close()
            connection.close()
    except Exception as e:
        print("Error removing from wishlist:", e)
    return RedirectResponse("/account", status_code=303)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)