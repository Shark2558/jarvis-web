# src/jarvis/helpers/sources.py
"""The outside services R11 reads, in one place (docs/plans/r11-free-helpers.md "External
sources", checked 11 Nov 2026). Constants only; the parts' clients use them with `httpx`, a
timeout of at most `OUTSIDE_TIMEOUT_S` and a response cap. No key, no secret, no new paid service.

- Open-Meteo forecast (B, D12): free for non-commercial use (personal home automation is), no
  key, 10,000 calls a day per IP; the data is CC BY 4.0, so the panel and the brief carry
  `OPEN_METEO_ATTRIBUTION`.
- NDMA SACHET CAP feeds (B, D13): RSS 2.0 per state (`rss_<state>.xml`, the national one
  `rss_india.xml`), each item linking a CAP 1.2 message; the channel says "public domain". Which
  state slugs exist beyond india / kerala / karnataka is for Part B to confirm.
- USDA FoodData Central (D, D15): CC0; used only when the bundled nutrition subset is built
  (`scripts/kitchen_fdc_subset.py`), never at run time.
- UPI (A, D7): the NPCI deep-link scheme JARVIS writes for the owner to open; it calls nothing.
  `MAX_UPI_AMOUNT_PAISE` is the CEILING of a prepared payment (R14 D13 (6)): the cap in force is
  the deploy-time setting `bill_pay_cap_inr`, which can only be lower
  (`helpers.today.models.pay_cap_paise`).
"""

from __future__ import annotations

OUTSIDE_TIMEOUT_S = 8.0

OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_ATTRIBUTION = "Weather data by Open-Meteo.com (CC BY 4.0)"
MAX_WEATHER_BYTES = 256 * 1024

SACHET_RSS_URL = "https://sachet.ndma.gov.in/cap_public_website/rss/rss_{feed}.xml"
SACHET_CAP_URL = "https://sachet.ndma.gov.in/cap_public_website/FetchXMLFile"
SACHET_NATIONAL_FEED = "india"
SACHET_ATTRIBUTION = "Warnings from NDMA SACHET (public domain)"
MAX_RSS_BYTES = 512 * 1024
MAX_CAP_BYTES = 256 * 1024

FDC_ATTRIBUTION = "USDA FoodData Central (public domain)"

UPI_PAY_SCHEME = "upi://pay"
MAX_UPI_AMOUNT_PAISE = 1_00_000 * 100  # D7: ₹1,00,000, the ceiling; `bill_pay_cap_inr` may lower it

__all__ = [
    "FDC_ATTRIBUTION",
    "MAX_CAP_BYTES",
    "MAX_RSS_BYTES",
    "MAX_UPI_AMOUNT_PAISE",
    "MAX_WEATHER_BYTES",
    "OPEN_METEO_ATTRIBUTION",
    "OPEN_METEO_FORECAST_URL",
    "OUTSIDE_TIMEOUT_S",
    "SACHET_ATTRIBUTION",
    "SACHET_CAP_URL",
    "SACHET_NATIONAL_FEED",
    "SACHET_RSS_URL",
    "UPI_PAY_SCHEME",
]
