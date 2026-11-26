# Creative analysis: Meta and Google Ads (Soteri Skin, CABA Design)

One service serves every client, each at its own link: Soteri Skin at `/` (and `/soteri`), CABA Design at `/caba`
(three ad accounts, with an **Account** filter on the page). The clients and their ad account IDs are written in
`app.py` (`CLIENTS`); a switch in the page header moves between them. Adding a client is one line there.

A client with Google Ads also has a **Google** page (`/soteri/google`), reached from the Meta / Google switch next to
the page title. It judges Google ads with the same rules; see *Google Ads* below.

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
| Too early | spend below 1.5 × the account's average CPA, not judged yet |

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

## Google Ads

`gads.py` reads the Google Ads API (read only, `googleAds:search`) through Position2's manager account with the same
sign-in as the Intelligence Platform. A client's Google accounts are given in `CLIENTS` as `"google": {"ids": [...]}`,
or found by name under the manager account (`"find": "Soteri"`).

- Each ad (search, YouTube, Demand Gen, display, shopping) is one creative, and so is each **Performance Max asset
  group**, since Performance Max has no ads of its own.
- Purchases = Google's *Conversions*, purchase value = *Conv. value*, so ROAS matches the Google Ads interface.
- Running = ad, ad group and campaign all enabled.
- Videos: *view rate* (views ÷ impressions) and *watched to end* stand in for Meta's hook and hold rate.
- Hooks: ads grouped by the headline that shows first (pinned to position 1, else the first written).
- The whole lookback is re-read on every refresh (a handful of requests), since Google keeps adding late conversions.

## Railway

| Variable | |
|---|---|
| `META_ADS_ACCESS_TOKEN` | System User token with `ads_read` on every client's ad accounts (required) |
| `DASH_PASSWORD` | optional; the page asks for it |
| `LOOKBACK_DAYS` | default 90 |
| `REFRESH_HOURS` | default 24 (once a day); the Refresh button reads Meta any time |
| `PURCHASE_ACTION` | override the purchase action types, comma-separated |
| `GOOGLE_ADS_CLIENT_ID`, `GOOGLE_ADS_CLIENT_SECRET`, `GOOGLE_ADS_DEVELOPER_TOKEN`, `GOOGLE_ADS_REFRESH_TOKEN` | the Google Ads sign-in (copy from the Intelligence Platform service); without them the Google page says it isn't connected |
| `GOOGLE_ADS_LOGIN_CUSTOMER_ID` | optional, the manager account, default 9923720096 |

An ad account the token cannot read is left out and named in a banner; the client's other accounts still show.

Attach a volume (any mount path) so the cache survives redeploys. Start command and health check are in
`railway.json`. No dependencies beyond Python 3.12's standard library.

## Local

```
DEMO=1 python app.py        # made-up data, http://localhost:8000
META_ADS_ACCESS_TOKEN=... python app.py
```
