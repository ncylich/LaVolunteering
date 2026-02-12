"""Playwright-based scraper for volunteer.laworks.com opportunities."""

import asyncio
import logging
import re

from playwright.async_api import async_playwright, Page, Browser

from config import (
    SEARCH_URL,
    BASE_URL,
    SELECTORS,
    OPP_TYPE_CLASSES,
    PAGE_LOAD_TIMEOUT_MS,
    LOAD_MORE_WAIT_MS,
    BETWEEN_REQUESTS_DELAY_S,
    MAX_LOAD_MORE_CLICKS,
)
from models import Opportunity

logger = logging.getLogger(__name__)


def _extract_id_from_href(href: str | None) -> str | None:
    """Extract Salesforce ID from a URL like /opportunity/a0CQg00009Z8TdkMAF."""
    if not href:
        return None
    match = re.search(r"/opportunity/([a-zA-Z0-9]+)", href)
    return match.group(1) if match else None


class VolunteerScraper:
    def __init__(self, headless: bool = True):
        self.headless = headless
        self._playwright = None
        self._browser: Browser | None = None
        self._page: Page | None = None

    async def start(self):
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self.headless)
        context = await self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 720},
        )
        self._page = await context.new_page()

    async def stop(self):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def scrape_search_results(self) -> list[Opportunity]:
        """Navigate to the search page and extract all volunteer opportunities."""
        page = self._page
        logger.info("Navigating to %s", SEARCH_URL)
        await page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT_MS)

        # Wait for the results table to be populated
        logger.info("Waiting for results table to render...")
        await page.wait_for_selector(
            SELECTORS["result_row"], state="attached", timeout=PAGE_LOAD_TIMEOUT_MS
        )
        # Extra wait for full render
        await asyncio.sleep(3)

        # Click "Load more" until all results are loaded
        await self._load_all_results()

        # Extract data from all rows
        return await self._extract_all_rows()

    async def _load_all_results(self):
        """Click 'Load more opportunities' until all results are visible."""
        page = self._page

        for click_num in range(1, MAX_LOAD_MORE_CLICKS + 1):
            count_before = await page.locator(SELECTORS["result_row"]).count()

            load_more = page.locator(SELECTORS["load_more"])
            if await load_more.count() == 0 or not await load_more.is_visible():
                logger.info("No more 'Load more' button. All results loaded.")
                break

            logger.info(
                "Click #%d: %d rows loaded, clicking 'Load more'...",
                click_num, count_before,
            )
            await load_more.scroll_into_view_if_needed()
            await load_more.click()

            # Wait for new rows to appear
            try:
                await page.wait_for_function(
                    f"document.querySelectorAll('{SELECTORS['result_row']}').length > {count_before}",
                    timeout=LOAD_MORE_WAIT_MS,
                )
            except Exception:
                logger.info("No new rows after click #%d. Assuming all loaded.", click_num)
                break

            await asyncio.sleep(BETWEEN_REQUESTS_DELAY_S)

        final_count = await page.locator(SELECTORS["result_row"]).count()
        logger.info("Total rows loaded: %d", final_count)

    async def _extract_all_rows(self) -> list[Opportunity]:
        """Extract Opportunity objects from all table rows."""
        page = self._page
        rows = page.locator(SELECTORS["result_row"])
        count = await rows.count()
        logger.info("Extracting data from %d rows...", count)

        opportunities = []
        for i in range(count):
            row = rows.nth(i)
            try:
                opp = await self._extract_row(row)
                if opp:
                    opportunities.append(opp)
            except Exception as e:
                logger.warning("Failed to extract row %d: %s", i, e)

        logger.info("Successfully extracted %d opportunities.", len(opportunities))
        return opportunities

    async def _extract_row(self, row) -> Opportunity | None:
        """Extract an Opportunity from a single table row."""
        # Opportunity title and link
        opp_cell = row.locator(SELECTORS["cell_opportunity"])
        opp_link = opp_cell.locator(SELECTORS["opp_link"]).first
        title = await opp_link.inner_text()
        href = await opp_link.get_attribute("href")
        opp_url = f"{BASE_URL}{href}" if href and href.startswith("/") else href
        opp_id = _extract_id_from_href(href)

        # Opportunity type from link class
        link_class = await opp_link.get_attribute("class") or ""
        opp_type = "Volunteer Opportunity"
        for cls, type_name in OPP_TYPE_CLASSES.items():
            if cls in link_class:
                opp_type = type_name
                break

        # Organization
        org_cell = row.locator(SELECTORS["cell_organization"])
        org_link = org_cell.locator(SELECTORS["org_link"]).first
        organization = await org_link.inner_text()
        org_href = await org_link.get_attribute("href")
        org_url = f"{BASE_URL}{org_href}" if org_href and org_href.startswith("/") else org_href

        # Location
        where_cell = row.locator(SELECTORS["cell_where"])
        location = (await where_cell.inner_text()).strip()

        # Date/Time
        time_cell = row.locator(SELECTORS["cell_time"])
        datetime_iso = await time_cell.get_attribute("data-order")

        date_el = time_cell.locator(SELECTORS["date_row"])
        date_str = (await date_el.inner_text()).strip() if await date_el.count() > 0 else None

        time_el = time_cell.locator(SELECTORS["time_row"])
        time_str = (await time_el.inner_text()).strip() if await time_el.count() > 0 else None

        dur_el = time_cell.locator(SELECTORS["duration"])
        duration = (await dur_el.inner_text()).strip() if await dur_el.count() > 0 else None

        # If no date/time spans, it might be "Ongoing"
        if not date_str:
            raw_time = (await time_cell.inner_text()).strip()
            if "ongoing" in raw_time.lower():
                date_str = "Ongoing"

        # Distance
        dist_cell = row.locator(SELECTORS["cell_distance"])
        distance = (await dist_cell.inner_text()).strip()

        return Opportunity(
            title=title.strip(),
            organization=organization.strip(),
            location=location,
            date=date_str,
            time=time_str,
            duration=duration,
            datetime_iso=datetime_iso,
            distance=distance,
            opportunity_type=opp_type,
            opportunity_url=opp_url,
            opportunity_id=opp_id,
            organization_url=org_url,
        )
