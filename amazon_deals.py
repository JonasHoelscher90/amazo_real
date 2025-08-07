import os
import random
import time
import logging
import re
import requests
import nltk
from rake_nltk import Rake
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import InvalidSessionIdException, WebDriverException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# ─── CONFIG ───────────────────────────────────────────────────────────────────
BOT_TOKEN            = os.getenv("TELEGRAM_BOT_TOKEN", "8460257816:AAH-RjlgE5l-qnb----01bp-PGNedzY0jug")
CHANNEL_USERNAME     = os.getenv("TELEGRAM_CHANNEL_USERNAME", "@amaz0n_deal5")
MIN_DISCOUNT         = 30
DESIRED_DEALS        = 50
TELEGRAM_POST_COUNT  = 1
SCROLL_PAUSE         = (2, 5)
MAX_SCROLLS          = 40
SELENIUM_RETRY_DELAY = 3  # seconds

# ─── LOGGING ───────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# ─── UTILITIES ─────────────────────────────────────────────────────────────────
def shorten_link(long_url):
    try:
        r = requests.get("http://tinyurl.com/api-create", params={"url": long_url}, timeout=5)
        r.raise_for_status()
        return r.text.strip()
    except Exception:
        return long_url

# ─── SELENIUM DRIVER SETUP ─────────────────────────────────────────────────────
def init_headless_driver():
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--disable-software-rasterizer")
    opts.add_argument("--single-process")
    opts.add_argument("--remote-debugging-port=9222")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--lang=en-US")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=opts)
    # keep the connection alive so we can detect dead sessions
    driver.command_executor._conn_keep_alive = True
    driver.set_page_load_timeout(60)
    return driver

# ─── NLTK / RAKE SETUP ─────────────────────────────────────────────────────────
for pkg in ("stopwords", "punkt"):
    try:
        nltk.data.find(f"corpora/{pkg}" if pkg=="stopwords" else f"tokenizers/{pkg}")
    except LookupError:
        nltk.download(pkg)

rake = Rake()
rake.sentence_tokenizer = lambda text: [text]

def rewrite_title(text, discount):
    rake.extract_keywords_from_text(text)
    phrases = rake.get_ranked_phrases()[:3]
    if not phrases:
        short = text if len(text) <= 50 else text[:47] + "..."
        return f"Save {discount}% on {short} – Shop Now!"
    headline = " – ".join(p.title() for p in phrases)
    return f"{headline} – Save {discount}% Now!"

# ─── FETCH TITLE & IMAGE WITH RETRY ────────────────────────────────────────────
def fetch_full_title_and_image(url):
    """
    Uses Selenium to fetch the Amazon title + image.
    If the session dies mid-flight, restart the driver and retry once.
    """
    def _inner(driver):
        driver.get(url + ("&language=en_US" if "?" in url else "?language=en_US"))
        WebDriverWait(driver, 30).until(
            EC.any_of(
                EC.visibility_of_element_located((By.ID, "productTitle")),
                EC.visibility_of_element_located((By.CSS_SELECTOR, "img#landingImage"))
            )
        )
        # title
        title = ""
        try:
            title = driver.find_element(By.ID, "productTitle").text.strip()
        except:
            pass
        # image
        img_url = None
        try:
            img_url = driver.find_element(By.CSS_SELECTOR, "img#landingImage").get_attribute("src")
        except:
            # fallback scan
            for img in driver.find_elements(By.TAG_NAME, "img"):
                src = img.get_attribute("src") or ""
                if "media-amazon" in src and len(src) > 100:
                    img_url = src
                    break
        return title, img_url

    # attempt + one retry on InvalidSessionIdException
    driver = init_headless_driver()
    try:
        return _inner(driver)
    except (InvalidSessionIdException, WebDriverException) as e:
        logging.warning(f"Driver died fetching {url!r}, retrying: {e}")
        try:
            driver.quit()
        except:
            pass
        time.sleep(SELENIUM_RETRY_DELAY)
        driver = init_headless_driver()
        try:
            return _inner(driver)
        finally:
            driver.quit()
    finally:
        try:
            driver.quit()
        except:
            pass

# ─── SCRAPE AMAZON DEALS ───────────────────────────────────────────────────────
def get_amazon_deals():
    driver = init_headless_driver()
    try:
        driver.get("https://www.amazon.com/gp/goldbox?ie=UTF8&language=en_US")
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.XPATH, "//span[contains(text(), '%')]"))
        )
        deals, seen, scrolls = [], set(), 0
        while len(deals) < DESIRED_DEALS and scrolls < MAX_SCROLLS:
            driver.execute_script("window.scrollBy(0, window.innerHeight);")
            time.sleep(random.uniform(*SCROLL_PAUSE))
            scrolls += 1
            for badge in driver.find_elements(By.XPATH, "//span[contains(text(), '%')]"):
                try:
                    pct = int(re.search(r"(\d{1,3})%", badge.text).group(1))
                    if pct < MIN_DISCOUNT:
                        continue
                except:
                    continue
                try:
                    anc = badge.find_element(By.XPATH, ".//ancestor::a[contains(@href,'/dp/')]")
                    raw = anc.get_attribute("href").split("?",1)[0]
                    link = re.sub(r"https://www\.amazon\.[a-z.]+", "https://www.amazon.com", raw)
                except:
                    continue
                if link in seen:
                    continue
                seen.add(link)
                deals.append({
                    "temp_title": anc.get_attribute("aria-label") or "",
                    "link": link,
                    "discount": pct,
                })
        return deals
    finally:
        driver.quit()

# ─── POST TO TELEGRAM ──────────────────────────────────────────────────────────
def post_to_telegram(deals):
    if not BOT_TOKEN or not CHANNEL_USERNAME:
        logging.error("Missing Telegram credentials.")
        return

    sent, used = 0, set()
    while sent < TELEGRAM_POST_COUNT and len(used) < len(deals):
        idx = random.randrange(len(deals))
        if idx in used:
            continue
        used.add(idx)
        d = deals[idx]

        title, img = fetch_full_title_and_image(d["link"])
        if not title or not img:
            logging.warning(f"Skipping (no title/img): {d['link']}")
            continue

        ad      = rewrite_title(title, d["discount"])
        short   = shorten_link(d["link"])
        caption = f"<b>{ad}</b>\n<u><a href=\"{short}\">Buy Now</a></u>"

        try:
            requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
                data={
                    "chat_id": CHANNEL_USERNAME,
                    "photo": img,
                    "caption": caption,
                    "parse_mode": "HTML"
                },
                timeout=15
            )
            sent += 1
        except Exception as e:
            logging.error(f"Telegram send failed: {e}")

# ─── MAIN ENTRY POINT ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    deals = get_amazon_deals()
    if not deals:
        print(f"No deals found with ≥{MIN_DISCOUNT}% discount.")
    else:
        post_to_telegram(deals)
        print(f"Posted {min(TELEGRAM_POST_COUNT, len(deals))} of {len(deals)} deals.")
