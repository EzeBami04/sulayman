import re
import sys
import time
from datetime import datetime, timezone
from bs4 import BeautifulSoup
from driver import Driver
from selenium.webdriver.common.by import By     
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

import gspread
from google.oauth2.service_account import Credentials
import os
# from dotenv import load_dotenv
import logging
#==================== config ======================
# load_dotenv()
logging.basicConfig(level=logging.INFO)
NCX_URL = "https://ncx.com.ng/"

TICKER_ITEM_SELECTOR = "li.ticker-inner .ticker-elem-inner h3"

SERVICE_ACCOUNT_FILE = os.getenv("eomo_json_key")
SHEET_ID = os.getenv("afri_ex")    

LATEST_TAB_NAME = "ncx Latest Prices"
HISTORY_TAB_NAME = "ncx_price_history"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive",]


#======= parse ============ticker
def parse_h3(h3_inner_html: str):
    """
    Parse a ticker h3's innerHTML into (code, name, price, change).
    Handles mixed text-node + tag content, e.g.:
        'Cocoa (COCOND) <b>N3,500.00</b><span class="red">30%</span>'
    """
    soup = BeautifulSoup(h3_inner_html, "html.parser")

    b_tag = soup.find("b")
    span_tag = soup.find("span")

    price = b_tag.get_text(strip=True) if b_tag else ""
    change = span_tag.get_text(strip=True) if span_tag else ""
    direction = "down" if span_tag and "red" in span_tag.get("class", []) else (
        "up" if span_tag and "green" in span_tag.get("class", []) else "")

    for tag in soup.find_all(["b", "span"]):
        tag.decompose()
    name = soup.get_text(strip=True)

    code_match = re.search(r"\(([A-Z0-9]+)\)", name)
    code = code_match.group(1) if code_match else name

    return code, name, price, change, direction


def scrape_ticker():
    rows = []
    driver = Driver()
    driver = driver.web_driver()

    try:
        driver.set_page_load_timeout(60)
        try:
            driver.get(NCX_URL)
            
        except TimeoutException:
            logging.warning("Page load timed out, stopping further loading and continuing")
            driver.execute_script("window.stop();")
        
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, TICKER_ITEM_SELECTOR)))
        
        time.sleep(2) 

        elements = driver.find_elements(By.CSS_SELECTOR, TICKER_ITEM_SELECTOR)
        for el in elements:
            try:
                inner_html = el.get_attribute("innerHTML")
                code, name, price, change, direction = parse_h3(inner_html)
                if not name:
                    continue
                rows.append({
                    "code": code,
                    "name": name,
                    "price": price,
                    "change": change,
                    "direction": direction,
                    })
            except Exception as e:
                print(f"Skipped one ticker item due to: {e}", file=sys.stderr)
    finally:
        driver.quit()

    # Dedupe by code (ticker is duplicated for the scroll loop)
    deduped = {}
    for r in rows:
        deduped[r["code"]] = r
    return list(deduped.values())


def push_to_sheets(rows):
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(SHEET_ID)

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
        value_input_option="USER_ENTERED",)


def main():
    logging.info("Scraping NCX ticker with Selenium...")
    rows = scrape_ticker()

    if not rows:
        logging.info(
            "No ticker items found - the DOM may have changed, or the page "
            "didn't finish loading in time. Try increasing the WebDriverWait "
            "timeout or re-check TICKER_ITEM_SELECTOR.",
            file=sys.stderr,)
        sys.exit(1)

    logging.info(f"Found {len(rows)} commodities:")
    for r in rows:
        logging.info(f"  {r['code']}: {r['price']} ({r['change']} {r['direction']})")

    logging.info("Pushing to Google Sheets...")

    push_to_sheets(rows)
    logging.info("Done.")


if __name__ == "__main__":
    main()