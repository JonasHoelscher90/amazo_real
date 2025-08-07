import random
import time
import logging
import re
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# ─── CONFIG ───────────────────────────────────────────────────────────────────
BOT_TOKEN = "8460257816:AAH-RjlgE5l-qnb----01bp-PGNedzY0jug"
CHANNEL_USERNAME = "@amaz0n_deal5"
MIN_DISCOUNT = 30
DESIRED_DEALS = 50
TELEGRAM_POST_COUNT = 1
SCROLL_PAUSE = (2, 5)
MAX_SCROLLS = 40

# ─── LOCAL HEURISTIC CONFIG ─────────────────────────────────────────────────────
# We replace the AI API call with a simple free heuristic for ad headlines
# No external API calls needed

# ─── LOGGING SETUP ─────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# ─── UTILITIES ─────────────────────────────────────────────────────────────────
def shorten_link(long_url):
    try:
        resp = requests.get("http://tinyurl.com/api-create", params={"url": long_url}, timeout=5)
        resp.raise_for_status()
        return resp.text.strip()
    except Exception:
        return long_url

# ─── CHROME DRIVER SETUP ───────────────────────────────────────────────────────
def init_headless_driver(user_agent=None):
    options = Options()
    options.add_argument("--lang=en-US")
    if user_agent:
        options.add_argument(f"--user-agent={user_agent}")
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1920,1080")
    # Explicitly set binary location for GitHub Actions
    options.binary_location = "/usr/bin/chromium-browser"
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    try:
        driver.execute_cdp_cmd('Network.enable', {})
        driver.execute_cdp_cmd('Network.setExtraHTTPHeaders', {'headers': {'Accept-Language': 'en-US'}})
    except Exception:
        pass
    return driver

# ─── FETCH TITLE & IMAGE ──────────────────────────────────────────────────────
def fetch_full_title_and_image(url):
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/115.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/605.1.15",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/114.0.0.0 Safari/537.36",
    ]
    driver = init_headless_driver(random.choice(user_agents))
    try:
        url_with_lang = url + ("&language=en_US" if "?" in url else "?language=en_US")
        driver.get(url_with_lang)
        WebDriverWait(driver, 30).until(EC.visibility_of_element_located((By.ID, "productTitle")))
        title_elem = driver.find_element(By.ID, "productTitle")
        full_title = title_elem.text.strip()
        image_url = None
        try:
            image_elem = driver.find_element(By.ID, "landingImage")
            image_url = image_elem.get_attribute("src")
        except:
            logging.warning(f"No landingImage element found for URL: {url}")
        return full_title, image_url
    except Exception as e:
        logging.error(f"Error fetching title/image: {e}")
        return "", None
    finally:
        driver.quit()

# ─── GENERATE CLEANED AD COPY VIA RAKE ─────────────────────────────────────
import nltk
from rake_nltk import Rake

# Ensure NLTK stopwords and punkt tokenizer are downloaded
try:
    nltk.data.find('corpora/stopwords')
except LookupError:
    nltk.download('stopwords')
try:
    nltk.data.find('tokenizers/punkt')
except LookupError:
    nltk.download('punkt')

# Initialize RAKE once without using punkt tokenizer
rake = Rake()
# Override sentence tokenizer to avoid missing punkt_tab resource
rake.sentence_tokenizer = lambda text: [text]

def rewrite_title(original_title, discount):
    # Extract keywords/phrases
    rake.extract_keywords_from_text(original_title)
    phrases = rake.get_ranked_phrases()
    top = phrases[:3]
    if not top:
        short = original_title if len(original_title) <= 50 else original_title[:47] + "..."
        return f"Save {discount}% on {short} – Shop Now!"
    headline = " – ".join([p.title() for p in top])
    return f"{headline} – Save {discount}% Now!"

# ─── SCRAPE AMAZON DEALS ───────────────────────────────────────────────────────
def get_amazon_deals():
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/115.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/605.1.15",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/114.0.0.0 Safari/537.36",
    ]
    driver = init_headless_driver(random.choice(user_agents))
    try:
        driver.get("https://www.amazon.com/gp/goldbox?ie=UTF8&language=en_US")
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.XPATH, "//span[contains(text(), '%')]/.."))
        )
        deals, seen, scrolls = [], set(), 0
        while len(deals) < DESIRED_DEALS and scrolls < MAX_SCROLLS:
            driver.execute_script("window.scrollBy(0, window.innerHeight);")
            time.sleep(random.uniform(*SCROLL_PAUSE))
            scrolls += 1
            badges = driver.find_elements(By.XPATH, "//span[contains(text(), '%')]")
            for badge in badges:
                try:
                    pct = int(re.search(r"(\d{1,3})%", badge.text).group(1))
                except:
                    continue
                if pct < MIN_DISCOUNT:
                    continue
                try:
                    link_elem = badge.find_element(By.XPATH, ".//ancestor::a[contains(@href,'/dp/')]")
                    raw_link = link_elem.get_attribute("href").split("?", 1)[0]
                    link = re.sub(r"https://www\\.amazon\\.[a-z.]+", "https://www.amazon.com", raw_link)
