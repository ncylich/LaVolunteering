"""Configuration constants for the LA Works volunteer scraper."""

BASE_URL = "https://volunteer.laworks.com"
SEARCH_URL = f"{BASE_URL}/search"

# CSS Selectors (discovered from live DOM)
SELECTORS = {
    # Search results table
    "results_table": "table#datatable-search-opportunities-block",
    "result_row": "table#datatable-search-opportunities-block tbody tr",
    # Per-row cells (use data-th attribute)
    "cell_opportunity": 'td[data-th="Opportunity"]',
    "cell_organization": 'td[data-th="Organization"]',
    "cell_where": 'td[data-th="Where"]',
    "cell_time": 'td[data-th="Time"]',
    "cell_distance": 'td[data-th="Distance"]',
    # Links within cells
    "opp_link": "a",
    "org_link": "a",
    # Date/time sub-elements
    "date_row": ".date-row",
    "time_row": ".time-row",
    "duration": ".duration",
    # Pagination
    "load_more": "a.view-more-link",
    # Result count
    "result_count": ".results-count",
}

# Opportunity type CSS classes on the <a> tag
OPP_TYPE_CLASSES = {
    "blue-key": "Volunteer Opportunity",
    "green-key": "Special Event",
    "light-gray-key": "Already Filled",
    "yellow-key": "Training",
}

# Timing
PAGE_LOAD_TIMEOUT_MS = 60000
LOAD_MORE_WAIT_MS = 5000
BETWEEN_REQUESTS_DELAY_S = 1.5
MAX_LOAD_MORE_CLICKS = 20

# Output
OUTPUT_DIR = "output"
