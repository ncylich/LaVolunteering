"""CLI entry point for the LA Works volunteer opportunity scraper."""

import asyncio
import argparse
import json
import logging
import os

import pandas as pd

from config import OUTPUT_DIR
from scraper import VolunteerScraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def save_results(opportunities: list[dict]):
    """Save scraped opportunities to CSV and JSON."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # JSON
    json_path = os.path.join(OUTPUT_DIR, "opportunities.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(opportunities, f, indent=2, ensure_ascii=False)
    logger.info("Saved JSON: %s (%d records)", json_path, len(opportunities))

    # CSV
    csv_path = os.path.join(OUTPUT_DIR, "opportunities.csv")
    df = pd.DataFrame(opportunities)
    df.to_csv(csv_path, index=False, encoding="utf-8")
    logger.info("Saved CSV: %s (%d records)", csv_path, len(opportunities))

    return json_path, csv_path


async def run(args):
    scraper = VolunteerScraper(headless=not args.visible)
    try:
        await scraper.start()
        opportunities = await scraper.scrape_search_results()

        if not opportunities:
            logger.warning("No opportunities found!")
            return

        records = [opp.to_dict() for opp in opportunities]
        json_path, csv_path = save_results(records)

        # Print summary
        print(f"\n{'='*60}")
        print(f"Scraped {len(opportunities)} volunteer opportunities")
        print(f"{'='*60}")
        print(f"  JSON: {json_path}")
        print(f"  CSV:  {csv_path}")

        # Quick stats
        types = {}
        for opp in opportunities:
            types[opp.opportunity_type] = types.get(opp.opportunity_type, 0) + 1
        print(f"\nBy type:")
        for t, c in sorted(types.items()):
            print(f"  {t}: {c}")

        orgs = set(opp.organization for opp in opportunities)
        print(f"\nUnique organizations: {len(orgs)}")
        print(f"{'='*60}")

    except KeyboardInterrupt:
        logger.info("Interrupted. Saving partial results...")
    finally:
        await scraper.stop()


def main():
    parser = argparse.ArgumentParser(
        description="Scrape volunteer opportunities from LA Works"
    )
    parser.add_argument(
        "--visible",
        action="store_true",
        help="Run browser in visible (non-headless) mode for debugging",
    )
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
