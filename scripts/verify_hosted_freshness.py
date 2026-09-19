"""Visit the public Streamlit session and fail visibly on a stale market row.

This runs outside ChatGPT and the teacher's PC. It never writes market data or
assumes that a successful HTTP health response means the Streamlit script ran.
"""

from __future__ import annotations

import os
import re
import time
from datetime import datetime, timezone


PUBLIC_URL = os.environ.get("CQE_PUBLIC_URL", "https://cqe-btc-eth-eleves.streamlit.app/")
STAMP = re.compile(r"dernier relevé\s+(\d{2})/(\d{2})/(\d{4})\s+\d{2}:\d{2}\s+Paris\s+\((\d{2}):(\d{2})\s+UTC\)")


def observed_age_minutes(text: str, now: datetime) -> float | None:
    match = STAMP.search(text)
    if not match:
        return None
    day, month, year, hour, minute = map(int, match.groups())
    observed = datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
    return (now - observed).total_seconds() / 60.0


def main() -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(PUBLIC_URL, wait_until="domcontentloaded", timeout=90_000)
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                text = page.locator("body").inner_text(timeout=15_000)
                wake = page.get_by_text("Yes, get this app back up!", exact=False)
                if wake.count() and wake.first.is_visible():
                    wake.first.click()
                age = observed_age_minutes(text, datetime.now(timezone.utc))
                if "FLUX HÉBERGÉ" in text and age is not None and -2 <= age <= 30:
                    print(f"Hosted feature observation age: {age:.1f} minutes")
                    if "SOURCES PARTIELLES" in text or "FLUX PARTIEL" in text:
                        print("WARNING: one or more hosted sources are degraded")
                    return
                page.wait_for_timeout(10_000)
            raise RuntimeError("No hosted market observation fresher than 30 minutes after three minutes")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
