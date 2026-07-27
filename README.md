# sulayman
webscrping solution for sulayman

"""
NCX (ncx.com.ng) commodity ticker scraper -> Google Sheets, using Selenium.

Based on the confirmed DOM structure:

    div.ticker-container
      div.ticker-title            "LIVE DATA"
      ul.ticker-text#ticker-text
        div.eocjs-newsticker-container
          div.eocjs-newsticker-one   <- one (or more) scrolling copies
            li.ticker-inner
              div.ticker-elem-inner
                h3
                  "Cocoa (COCOND) "        <- loose text node (name)
                  <b>N3,500.00</b>         <- price
                  <span class="red">30%</span>  <- change (red=down, green=up)

The ticker is duplicated (e.g. eocjs-newsticker-one / -two) to make the CSS
scroll loop seamless, so we dedupe by commodity code.

SETUP
-----
1. pip install selenium beautifulsoup4 gspread google-auth --break-system-packages
   (Selenium 4.6+ auto-manages the chromedriver binary - no separate download
   needed, as long as Chrome/Chromium is installed on the machine.)

2. Google Sheets auth: same as before -
   - Service account JSON key -> service_account.json next to this script.
   - Share the target sheet with the service account's email as Editor.
   - Put the sheet ID (from its URL) into SHEET_ID below.

Run manually:
    python ncx_ticker_selenium.py

Run on a schedule (prices move through the day): cron, GitHub Actions, or
your n8n instance (Execute Command node / schedule trigger).
"""
