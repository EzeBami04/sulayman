from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from driver import Driver, get_env
import gspread
from google.oauth2.service_account import Credentials
import re
import sys
import time
from datetime import datetime, timezone

import logging
# ========= Config ===========================
logging.basicConfig(level=logging.INFO)

SERVICE_ACCOUNT_FILE = get_env("eomo_json_key")   
SHEET_ID = get_env("afri_ex")
LATEST_TAB_NAME = "AFCEX Latest Prices"
HISTORY_TAB_NAME = "AFCEX Price History"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

URL = "https://africaexchange.com/"

# CSS classes must be dot-chained, not space-separated (space = descendant selector)
TICKER_ITEM_SELECTOR = "li.flex.gap-3.font-light.text-white"


def parse_ticker_li(li_inner_html: str):
    """
    Parse one ticker <li>'s innerHTML into (code, name, price, change).
    Expected shape:
        <span>Sorghum (SGM)</span>
        <span>N321.63</span>
        <span class="text-crayola">1.88%</span>
    """
    soup = BeautifulSoup(li_inner_html, "html.parser")
    spans = soup.find_all("span")

    if len(spans) < 3:
        return None

    name = spans[0].get_text(strip=True)
    price = spans[1].get_text(strip=True)
    change = spans[2].get_text(strip=True)

    # todo direction (up/down) isn't determinable from color class alone here
    # (unlike NCX's red/green). Inspect for an arrow icon or extra class
    # inside the li if you need this, then extend this function.
    direction = ""

    code_match = re.search(r"\(([A-Za-z0-9]+)\)", name)
    code = code_match.group(1) if code_match else name

    return {
        "code": code,
        "name": name,
        "price": price,
        "change": change,
        "direction": direction,
    }


def scrape_afcex(url):
    rows = []
    driver = Driver()
    page = driver.web_driver()
    try:
        page.get(url)
        page.set_page_load_timeout(45)
        WebDriverWait(page, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, TICKER_ITEM_SELECTOR))
        )
        time.sleep(2)

        elements = page.find_elements(By.CSS_SELECTOR, TICKER_ITEM_SELECTOR)
        for el in elements:
            try:
                inner_html = el.get_attribute("innerHTML")
                row = parse_ticker_li(inner_html)
                if row:
                    rows.append(row)
            except Exception as e:
                logging.info(f"Skipped one ticker item due to: {e}")

    except Exception as e:
        logging.info(f"error scraping data: {e}")
    finally:
        page.quit()

    # Dedupe by code, in case the ticker duplicates items for a scroll loop
    deduped = {}
    for r in rows:
        deduped[r["code"]] = r
    return list(deduped.values())


def push_to_sheets(rows):
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(SHEET_ID)
    logging.info(f"Writing to spreadsheet: '{sh.title}' -> {sh.url}")

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    header = ["Code", "Commodity", "Price", "Change", "Direction", "Scraped At (UTC)"]

    try:
        ws_latest = sh.worksheet(LATEST_TAB_NAME)
    except gspread.WorksheetNotFound:
        ws_latest = sh.add_worksheet(title=LATEST_TAB_NAME, rows=200, cols=6)
    ws_latest.clear()
    ws_latest.update(range_name="A1", values=[header] + [
        [r["code"], r["name"], r["price"], r["change"], r["direction"], timestamp]
        for r in rows
    ])

    try:
        ws_history = sh.worksheet(HISTORY_TAB_NAME)
    except gspread.WorksheetNotFound:
        ws_history = sh.add_worksheet(title=HISTORY_TAB_NAME, rows=1, cols=6)
        ws_history.update(range_name="A1", values=[header])
    ws_history.append_rows(
        [[r["code"], r["name"], r["price"], r["change"], r["direction"], timestamp]
         for r in rows],
        value_input_option="USER_ENTERED",
    )


def main():
    logging.info("Scraping africaexchange.com ticker...")
    rows = scrape_afcex(URL)

    if not rows:
        logging.info(
            "No ticker items found - check TICKER_ITEM_SELECTOR against the "
            "live DOM (classes may have changed)."
        )
        sys.exit(1)

    logging.info(f"Found {len(rows)} commodities:")
    for r in rows:
        print(f"  {r['code']}: {r['price']} ({r['change']})")

    logging.info("Pushing to Google Sheets...")
    push_to_sheets(rows)
    logging.info("Done.")


if __name__ == "__main__":
    main()