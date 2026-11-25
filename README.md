# Soteri Skin: Meta creative analysis

A dashboard that says which Meta creatives to **scale**, **keep running** or **cut**, judged against the
account's average ROAS for the date range you pick, and shows which **hooks** and **ad formats** are working.

## How creatives are judged

Totals and the benchmark (average ROAS = purchase value ÷ spend) count everything the active campaigns spent in the
chosen dates, ads paused since included, so they match Ads Manager's campaign rows. Only ads Meta reports as ACTIVE
(the ad, its ad set and its campaign all on) are listed and judged.

| Verdict | Rule (all adjustable on the page) |
|---|---|
| Scale | ROAS ≥ 1.2 × average **and** at least 2 purchases |
| Keep running | ROAS ≥ 0.8 × average |
| Cut | ROAS below 0.8 × average (or spent without a purchase) |
| Too early | spend below one average CPA, not judged yet |

"Judge by" can merge ads that share a name (the same creative duplicated across ad sets) into one row.

## Tabs

- **Creatives**: spend vs ROAS chart with the scale/cut lines, a sortable table with thumbnails, the verdict and
  why, links to Ads Manager and the post, CSV download.
- **Hooks**: for videos, hook rate (3-second plays ÷ impressions) and hold rate (ThruPlays ÷ 3-second plays)
  against ROAS, read as *strong/weak hook × converts/doesn't*. For copy, ads grouped by the opening line of the
  primary text with their combined ROAS.
- **Formats & angles**: ROAS, CPA, CTR, conversion rate, 3-second views and hook rate by format (image, video,
  carousel, flexible, catalog), by partnership ad vs brand ad, by call-to-action button, and by any tag or part of the
  ad name (concept, hook, creator…).
- **3-second views** (video plays of at least 3 seconds) and their cost show on every creative, video and breakdown.

## Data

`meta.py` reads the Marketing API (read only): daily ad-level insights for the last `LOOKBACK_DAYS`, and each
ad's creative. The last 7 days are re-read on every refresh since Meta keeps attributing purchases to them.
Purchases use the first action type present of `omni_purchase`, `offsite_conversion.fb_pixel_purchase`,
`purchase` (never summed). Data is cached in a JSON file on the Railway volume.

## Railway

| Variable | |
|---|---|
| `META_ADS_ACCESS_TOKEN` | System User token with `ads_read` on the Soteri ad account (required) |
| `META_AD_ACCOUNT_ID` | defaults to `261215873024315` |
| `DASH_PASSWORD` | optional; the page asks for it |
| `LOOKBACK_DAYS` | default 90 |
| `REFRESH_HOURS` | default 24 (once a day); the Refresh button reads Meta any time |
| `PURCHASE_ACTION` | override the purchase action types, comma-separated |

Attach a volume (any mount path) so the cache survives redeploys. Start command and health check are in
`railway.json`. No dependencies beyond Python 3.12's standard library.

## Local

```
DEMO=1 python app.py        # made-up data, http://localhost:8000
META_ADS_ACCESS_TOKEN=... python app.py
```
