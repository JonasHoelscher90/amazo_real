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
    options.add_argument("--disable-dev-shm-usage")  # CI-friendly
    options.add_argument("--window-size=1920,1080")
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
        # Try main image
        try:
            img = driver.find_element(By.ID, "landingImage")
            image_url = img.get_attribute("src")
        except:
            # Fallback: first thumbnail
            try:
                thumb = driver.find_element(By.CSS_SELECTOR, "ul.a-unordered-list.a-nostyle.a-horizontal li img")
                image_url = thumb.get_attribute("src")
            except:
                pass
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

rake = Rake()
rake.sentence_tokenizer = lambda text: [text]

def rewrite_title(original_title, discount):
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
            cards = driver.find_elements(By.XPATH, "//div[contains(@class,'DealContent-module__grid')]//a[contains(@href,'/dp/')]")
            for card in cards:
                try:
                    badge = card.find_element(By.XPATH, ".//span[contains(text(), '%')]")
                    pct = int(re.search(r"(\d{1,3})%", badge.text).group(1))
                    if pct < MIN_DISCOUNT:
                        continue
                except:
                    continue
                link = card.get_attribute("href").split("?",1)[0]
                link = re.sub(r"https://www\\.amazon\\.[a-z.]+", "https://www.amazon.com", link)
                if link in seen:
                    continue
                seen.add(link)
                # Extract image
                img_url = None
                try:
                    img_elem = card.find_element(By.TAG_NAME, 'img')
                    img_url = img_elem.get_attribute('src')
                except:
                    pass
                temp_title = card.get_attribute('aria-label') or ''
                deals.append({
                    'temp_title': temp_title,
                    'link': link,
                    'discount': pct,
                    'image_url': img_url
                })
        return deals
    finally:
        driver.quit()

# ─── POST TO TELEGRAM ──────────────────────────────────────────────────────────
def post_to_telegram(deals):
    sent, used = 0, set()
    while sent < TELEGRAM_POST_COUNT and len(used) < len(deals):
        idx = random.randrange(len(deals))
        if idx in used:
            continue
        used.add(idx)
        d = deals[idx]
        title_raw, img_fallback = fetch_full_title_and_image(d['link'])
        if not title_raw:
            title_raw = d['temp_title']
        if not d.get('image_url') and img_fallback:
            d['image_url'] = img_fallback
        new_ad = rewrite_title(title_raw, d['discount'])
        link_short = shorten_link(d['link'])
        msg = (
            f"<b>{new_ad}</b>\n"
            f"<a href=\"{link_short}\">Buy Now</a>"
        )
        if d.get('image_url'):
            requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
                data={
                    'chat_id': CHANNEL_USERNAME,
                    'photo': d['image_url'],
                    'caption': msg,
                    'parse_mode': 'HTML'
                }
            )
        else:
            requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                data={
                    'chat_id': CHANNEL_USERNAME,
                    'text': msg,
                    'parse_mode': 'HTML',
                    'disable_web_page_preview': True
                }
            )
        sent += 1

# ─── MAIN ENTRY POINT ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    deals = get_amazon_deals()
    if not deals:
        print(f"No deals found with >= {MIN_DISCOUNT}% discount.")
    else:
        post_to_telegram(deals)
        print(f"Posted {TELEGRAM_POST_COUNT} of {len(deals)} deals.")
