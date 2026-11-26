"""Google Ads API reader for the creative analysis: daily ad-level results plus what each ad shows, in the same shape
meta.pull returns, so the page judges Google ads with the same rules.

Read only (googleAds:search and nothing else). One shared sign-in reads every client through Position2's manager
account, the same one the Intelligence Platform uses:

  GOOGLE_ADS_CLIENT_ID / GOOGLE_ADS_CLIENT_SECRET   the OAuth client
  GOOGLE_ADS_DEVELOPER_TOKEN                        the API developer token
  GOOGLE_ADS_REFRESH_TOKEN                          a sign-in that can see the manager account
  GOOGLE_ADS_LOGIN_CUSTOMER_ID                      the manager account, default 9923720096
  GOOGLE_ADS_API_VERSION                            default v24

What counts as one "creative":
  * every ad (search, YouTube, Demand Gen, display, shopping) with its daily cost, impressions, clicks, conversions,
    conversion value and video views;
  * every Performance Max asset group, since Performance Max has no ads of its own.
Purchases are Google's "Conversions" column (the account's primary conversion actions) and purchase value is its
"Conv. value", so ROAS matches the Google Ads interface.
"""
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

VERSION = os.environ.get("GOOGLE_ADS_API_VERSION", "v24").strip() or "v24"
API = "https://googleads.googleapis.com/" + VERSION
TOKEN_URL = "https://oauth2.googleapis.com/token"
DEFAULT_LOGIN = "9923720096"
NEEDED = ("GOOGLE_ADS_CLIENT_ID", "GOOGLE_ADS_CLIENT_SECRET", "GOOGLE_ADS_DEVELOPER_TOKEN", "GOOGLE_ADS_REFRESH_TOKEN")

FORMATS = {
    "RESPONSIVE_SEARCH_AD": "Search (responsive)", "EXPANDED_TEXT_AD": "Search (text)", "TEXT_AD": "Search (text)",
    "CALL_AD": "Call", "SHOPPING_PRODUCT_AD": "Shopping", "SHOPPING_SMART_AD": "Shopping",
    "VIDEO_AD": "YouTube video", "VIDEO_RESPONSIVE_AD": "YouTube video", "IN_FEED_VIDEO_AD": "YouTube video",
    "VIDEO_BUMPER_AD": "YouTube video", "VIDEO_NON_SKIPPABLE_IN_STREAM_AD": "YouTube video", "VIDEO_TRUEVIEW_IN_STREAM_AD": "YouTube video",
    "DEMAND_GEN_VIDEO_RESPONSIVE_AD": "Demand Gen video", "DEMAND_GEN_MULTI_ASSET_AD": "Demand Gen image",
    "DEMAND_GEN_CAROUSEL_AD": "Demand Gen carousel", "DEMAND_GEN_PRODUCT_AD": "Demand Gen product",
    "DISCOVERY_MULTI_ASSET_AD": "Demand Gen image", "DISCOVERY_CAROUSEL_AD": "Demand Gen carousel",
    "DISCOVERY_VIDEO_RESPONSIVE_AD": "Demand Gen video",
    "RESPONSIVE_DISPLAY_AD": "Display (responsive)", "IMAGE_AD": "Display image", "APP_AD": "App",
}

# What an ad shows. Any of these Google refuses (a field renamed in a newer API version) is dropped and the read goes on.
AD_FIELDS = [
    "ad_group_ad.ad.final_urls",
    "ad_group_ad.ad.responsive_search_ad.headlines", "ad_group_ad.ad.responsive_search_ad.descriptions",
    "ad_group_ad.ad.video_ad.video.asset",
    "ad_group_ad.ad.video_responsive_ad.videos", "ad_group_ad.ad.video_responsive_ad.headlines",
    "ad_group_ad.ad.video_responsive_ad.long_headlines", "ad_group_ad.ad.video_responsive_ad.descriptions",
    "ad_group_ad.ad.demand_gen_multi_asset_ad.marketing_images", "ad_group_ad.ad.demand_gen_multi_asset_ad.square_marketing_images",
    "ad_group_ad.ad.demand_gen_multi_asset_ad.portrait_marketing_images",
    "ad_group_ad.ad.demand_gen_multi_asset_ad.headlines", "ad_group_ad.ad.demand_gen_multi_asset_ad.descriptions",
    "ad_group_ad.ad.demand_gen_video_responsive_ad.videos", "ad_group_ad.ad.demand_gen_video_responsive_ad.headlines",
    "ad_group_ad.ad.demand_gen_video_responsive_ad.long_headlines", "ad_group_ad.ad.demand_gen_video_responsive_ad.descriptions",
    "ad_group_ad.ad.demand_gen_carousel_ad.headline", "ad_group_ad.ad.demand_gen_carousel_ad.description",
    "ad_group_ad.ad.responsive_display_ad.marketing_images", "ad_group_ad.ad.responsive_display_ad.square_marketing_images",
    "ad_group_ad.ad.responsive_display_ad.headlines", "ad_group_ad.ad.responsive_display_ad.long_headline",
    "ad_group_ad.ad.responsive_display_ad.descriptions",
    "ad_group_ad.ad.image_ad.image_url",
]
VIDEO_METRICS = ["metrics.video_trueview_views", "metrics.video_quartile_p100_rate"]


def _env(name, default=""):
    return (os.environ.get(name) or default).strip().strip("\"'")


def configured():
    """None when Google Ads can be read, else what is missing (for the page)."""
    missing = [n for n in NEEDED if not _env(n)]
    return ("Google Ads is not connected yet: %s not set on the server." % ", ".join(missing)) if missing else None


def cid(x):
    return re.sub(r"\D", "", str(x))


class Api:
    """googleAds:search calls with the access token refreshed as needed. Errors carry Google's message, never a secret."""

    def __init__(self):
        problem = configured()
        if problem:
            raise RuntimeError(problem)
        self.login = cid(_env("GOOGLE_ADS_LOGIN_CUSTOMER_ID", DEFAULT_LOGIN)) or DEFAULT_LOGIN
        self.tok, self.exp, self.requests = None, 0.0, 0

    def _token(self):
        if self.tok and self.exp > time.time() + 60:
            return self.tok
        body = urllib.parse.urlencode({"client_id": _env("GOOGLE_ADS_CLIENT_ID"), "client_secret": _env("GOOGLE_ADS_CLIENT_SECRET"),
                                       "refresh_token": _env("GOOGLE_ADS_REFRESH_TOKEN"), "grant_type": "refresh_token"}).encode()
        try:
            with urllib.request.urlopen(urllib.request.Request(TOKEN_URL, data=body), timeout=30) as r:
                d = json.load(r)
        except urllib.error.HTTPError as e:
            try:
                err = json.loads(e.read().decode("utf-8", "replace")).get("error", "")
            except ValueError:
                err = ""
            raise RuntimeError("Google would not sign in (%s%s). The GOOGLE_ADS_* sign-in may need refreshing."
                               % (e.code, ", " + err if err else "")) from None
        except urllib.error.URLError as e:
            raise RuntimeError("Google could not be reached to sign in (%s)" % e.reason) from None
        self.tok, self.exp = d["access_token"], time.time() + float(d.get("expires_in", 3000))
        return self.tok

    def _post(self, customer, query, page_token=None):
        body = {"query": query}
        if page_token:
            body["pageToken"] = page_token
        for attempt in range(4):
            self.requests += 1
            req = urllib.request.Request(
                "%s/customers/%s/googleAds:search" % (API, customer), data=json.dumps(body).encode(), method="POST",
                headers={"Authorization": "Bearer " + self._token(), "developer-token": _env("GOOGLE_ADS_DEVELOPER_TOKEN"),
                         "login-customer-id": self.login, "Content-Type": "application/json", "User-Agent": "creative-analysis-dashboard"})
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    return json.load(r)
            except urllib.error.HTTPError as e:
                raw = e.read().decode("utf-8", "replace")
                if e.code == 401 and attempt == 0:
                    self.tok = None
                    continue
                if e.code in (429, 500, 503) and attempt < 3:
                    time.sleep(10 * (attempt + 1))
                    continue
                raise GoogleError(e.code, _message(raw), raw) from None
            except urllib.error.URLError as e:
                if attempt == 3:
                    raise RuntimeError("Google Ads could not be reached (%s)" % e.reason) from None
                time.sleep(3 * (attempt + 1))
        raise RuntimeError("Google Ads kept refusing the request")

    def search(self, customer, query):
        rows, tok = [], None
        while True:
            d = self._post(customer, query, tok)
            rows += d.get("results") or []
            tok = d.get("nextPageToken")
            if not tok:
                return rows

    def search_pruned(self, customer, build, optional, log=print):
        """build(fields) with as many of the optional fields as Google accepts: a 400 naming some drops those and asks again."""
        fields = list(optional)
        for _ in range(8):
            try:
                return self.search(customer, build(fields))
            except GoogleError as e:
                named = [f for f in fields if re.search(r"(?<![a-z_.])%s(?![a-z_])" % re.escape(f), e.raw)]
                if e.code != 400 or not fields:
                    raise
                if not named:                                   # Google named no field: try once with none of the optional ones
                    log("Google refused the detail fields (%s); reading without them" % str(e)[:160])
                    fields = []
                    continue
                log("Google does not know %s; reading without %s" % (", ".join(named), "it" if len(named) == 1 else "them"))
                fields = [f for f in fields if f not in named]
        raise RuntimeError("Google Ads refused the field list")


class GoogleError(RuntimeError):
    def __init__(self, code, message, raw):
        super().__init__("Google Ads answered %s: %s" % (code, message or "no reason given"))
        self.code, self.raw = code, raw


def _message(raw):
    try:
        e = json.loads(raw)
        e = e[0] if isinstance(e, list) and e else e
        err = (e or {}).get("error", {})
        for d in err.get("details") or []:
            for x in d.get("errors") or []:
                if x.get("message"):
                    return x["message"][:300]
        return (err.get("message") or "")[:300]
    except ValueError:
        return raw[:200]


# ── accounts ────────────────────────────────────────────────────────────────

def find_accounts(api, name_part):
    """Client accounts under the manager whose name contains name_part (any case), enabled and not managers."""
    rows = api.search(api.login, "SELECT customer_client.id, customer_client.descriptive_name, customer_client.currency_code, "
                                 "customer_client.time_zone, customer_client.manager, customer_client.status FROM customer_client "
                                 "WHERE customer_client.manager = FALSE AND customer_client.status = 'ENABLED'")
    out = []
    for r in rows:
        c = r.get("customerClient") or {}
        if name_part.lower() in (c.get("descriptiveName") or "").lower():
            out.append(str(c.get("id")))
    return sorted(set(out))


def fetch_account(api, customer):
    r = api.search(customer, "SELECT customer.id, customer.descriptive_name, customer.currency_code, customer.time_zone FROM customer")
    c = (r[0] if r else {}).get("customer") or {}
    return {"id": customer, "name": c.get("descriptiveName") or customer, "currency": c.get("currencyCode") or "USD",
            "timezone": c.get("timeZone") or "", "platform": "google"}


# ── rows ────────────────────────────────────────────────────────────────────

def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _row(r, ad_id, customer, name, adset, campaign):
    m = r.get("metrics") or {}
    impr = int(_f(m.get("impressions")))
    views = _f(m.get("videoTrueviewViews"))
    return {"date": (r.get("segments") or {}).get("date"), "ad_id": ad_id, "ad_name": name, "adset": adset, "campaign": campaign, "account": customer,
            "spend": _f(m.get("costMicros")) / 1e6, "impressions": impr, "clicks": int(_f(m.get("clicks"))),
            "purchases": _f(m.get("conversions")), "revenue": _f(m.get("conversionsValue")), "atc": 0,
            "v3": views, "thru": round(_f(m.get("videoQuartileP100Rate")) * impr) if views else 0}


def _status(*parts):
    """ACTIVE when the ad, its ad group and its campaign are all enabled (what the page calls running)."""
    if any(p == "REMOVED" for p in parts):
        return "REMOVED"
    return "ACTIVE" if all(p == "ENABLED" for p in parts) else "PAUSED"


def _texts(lst):
    return [" ".join(str((x or {}).get("text") or "").split()) for x in (lst or []) if (x or {}).get("text")]


def _first_headline(lst):
    """The headline that shows first: one pinned to position 1, else the first written."""
    lst = lst or []
    pinned = [x for x in lst if (x or {}).get("pinnedField") == "HEADLINE_1" and x.get("text")]
    t = _texts(pinned or lst)
    return t[0] if t else ""


def _assets(lst):
    return [(x or {}).get("asset") for x in (lst or []) if (x or {}).get("asset")]


def describe_ad(ad, ad_type):
    """Format, opening headline, copy and the assets to look up for a picture, from one ad_group_ad.ad."""
    fmt = FORMATS.get(ad_type, (ad_type or "Other").replace("_", " ").capitalize())
    rsa = ad.get("responsiveSearchAd") or {}
    vra = ad.get("videoResponsiveAd") or {}
    dgm = ad.get("demandGenMultiAssetAd") or {}
    dgv = ad.get("demandGenVideoResponsiveAd") or {}
    dgc = ad.get("demandGenCarouselAd") or {}
    rda = ad.get("responsiveDisplayAd") or {}
    heads = rsa.get("headlines") or vra.get("headlines") or dgm.get("headlines") or dgv.get("headlines") or rda.get("headlines") or []
    longs = _texts(vra.get("longHeadlines") or dgv.get("longHeadlines"))
    if not heads and dgc.get("headline"):
        heads = [{"text": dgc["headline"]}]
    if not heads and (rda.get("longHeadline") or {}).get("text"):
        heads = [rda["longHeadline"]]
    descs = _texts(rsa.get("descriptions") or vra.get("descriptions") or dgm.get("descriptions") or dgv.get("descriptions") or rda.get("descriptions"))
    if not descs and dgc.get("description"):
        descs = [dgc["description"]]
    videos = _assets(vra.get("videos") or dgv.get("videos")) + ([ad["videoAd"]["video"]["asset"]] if ((ad.get("videoAd") or {}).get("video") or {}).get("asset") else [])
    images = _assets(dgm.get("marketingImages") or dgm.get("squareMarketingImages") or dgm.get("portraitMarketingImages")
                     or rda.get("marketingImages") or rda.get("squareMarketingImages"))
    hook = _first_headline(heads) or (longs[0] if longs else "")
    return {"format": fmt, "hook": hook, "headline": " | ".join(_texts(heads)[:15]), "body": "\n".join(descs),
            "cta": "", "partnership": None, "partnership_ids": "", "creative_id": "",
            "landing": (ad.get("finalUrls") or [""])[0], "_video": videos[0] if videos else "", "_image": images[0] if images else "",
            "thumb": (ad.get("imageAd") or {}).get("imageUrl") or "", "video_id": "", "post_url": ""}


def fetch_ads(api, customer, since, until, log=print):
    """Daily rows of every ad that cost money in the range, and what each ad shows."""
    def build(fields):
        return ("SELECT segments.date, campaign.id, campaign.name, campaign.status, ad_group.id, ad_group.name, ad_group.status, "
                "ad_group_ad.status, ad_group_ad.ad.id, ad_group_ad.ad.name, ad_group_ad.ad.type, "
                "metrics.cost_micros, metrics.impressions, metrics.clicks, metrics.conversions, metrics.conversions_value%s "
                "FROM ad_group_ad WHERE segments.date BETWEEN '%s' AND '%s' AND metrics.cost_micros > 0"
                % ("".join(", " + f for f in fields), since, until))
    got = api.search_pruned(customer, build, VIDEO_METRICS + AD_FIELDS, log)
    rows, ads = [], {}
    for r in got:
        aga = r.get("adGroupAd") or {}
        ad = aga.get("ad") or {}
        ad_id = str(ad.get("id") or "")
        if not ad_id:
            continue
        camp, grp = r.get("campaign") or {}, r.get("adGroup") or {}
        if ad_id not in ads:
            info = describe_ad(ad, ad.get("type"))
            name = (ad.get("name") or "").strip() or "%s · %s" % (grp.get("name") or "Ad group", info["format"])
            info.update({"name": name, "status": _status(aga.get("status"), grp.get("status"), camp.get("status")),
                         "campaign_status": "ACTIVE" if camp.get("status") == "ENABLED" else camp.get("status") or "",
                         "campaign": camp.get("name") or "", "adset": grp.get("name") or "", "account": customer, "created": "",
                         "gid": "%s~%s" % (grp.get("id") or "", ad_id), "campaign_id": str(camp.get("id") or "")})
            ads[ad_id] = info
        a = ads[ad_id]
        rows.append(_row(r, ad_id, customer, a["name"], a["adset"], a["campaign"]))
    log("%d ads read" % len(ads))
    return rows, ads


def fetch_asset_groups(api, customer, since, until, log=print):
    """Performance Max: one 'creative' per asset group, with its daily rows, first headline and a picture."""
    got = api.search(customer, "SELECT segments.date, campaign.id, campaign.name, campaign.status, asset_group.id, asset_group.name, "
                               "asset_group.status, metrics.cost_micros, metrics.impressions, metrics.clicks, metrics.conversions, "
                               "metrics.conversions_value FROM asset_group WHERE segments.date BETWEEN '%s' AND '%s' "
                               "AND metrics.cost_micros > 0" % (since, until))
    rows, ads = [], {}
    for r in got:
        g, camp = r.get("assetGroup") or {}, r.get("campaign") or {}
        key = "pmax-%s" % g.get("id")
        if key not in ads:
            ads[key] = {"name": g.get("name") or "Asset group", "format": "Performance Max", "status": _status(g.get("status"), camp.get("status")),
                        "campaign_status": "ACTIVE" if camp.get("status") == "ENABLED" else camp.get("status") or "",
                        "campaign": camp.get("name") or "", "adset": "Asset group", "account": customer, "created": "",
                        "hook": "", "headline": "", "body": "", "cta": "", "partnership": None, "partnership_ids": "", "creative_id": "",
                        "landing": "", "thumb": "", "video_id": "", "post_url": "", "_video": "", "_image": "",
                        "campaign_id": str(camp.get("id") or ""), "asset_group_id": str(g.get("id") or "")}
        rows.append(_row(r, key, customer, ads[key]["name"], "Asset group", ads[key]["campaign"]))
    if ads:
        try:
            ag = api.search(customer, "SELECT asset_group.id, asset_group_asset.field_type, asset.text_asset.text, asset.resource_name "
                                      "FROM asset_group_asset WHERE asset_group_asset.status != 'REMOVED' "
                                      "AND asset_group_asset.field_type IN ('HEADLINE', 'DESCRIPTION', 'MARKETING_IMAGE', "
                                      "'SQUARE_MARKETING_IMAGE', 'YOUTUBE_VIDEO')")
        except RuntimeError as e:
            log("Asset group assets could not be read:", e)
            ag = []
        heads, descs = {}, {}
        for r in ag:
            key = "pmax-%s" % (r.get("assetGroup") or {}).get("id")
            a = ads.get(key)
            if not a:
                continue
            ft = (r.get("assetGroupAsset") or {}).get("fieldType")
            asset = r.get("asset") or {}
            text = " ".join(str((asset.get("textAsset") or {}).get("text") or "").split())
            if ft == "HEADLINE" and text:
                heads.setdefault(key, []).append(text)
            elif ft == "DESCRIPTION" and text:
                descs.setdefault(key, []).append(text)
            elif ft == "YOUTUBE_VIDEO" and not a["_video"]:
                a["_video"] = asset.get("resourceName") or ""
            elif ft in ("MARKETING_IMAGE", "SQUARE_MARKETING_IMAGE") and not a["_image"]:
                a["_image"] = asset.get("resourceName") or ""
        for key, a in ads.items():
            a["hook"] = (heads.get(key) or [""])[0]
            a["headline"] = " | ".join((heads.get(key) or [])[:15])
            a["body"] = "\n".join(descs.get(key) or [])
    log("%d Performance Max asset groups read" % len(ads))
    return rows, ads


def fill_pictures(api, customer, ads, log=print):
    """Image URLs and YouTube ids of the assets the ads point at, a few hundred per request."""
    names = sorted({a[k] for a in ads.values() for k in ("_video", "_image") if a.get(k)})
    found = {}
    for i in range(0, len(names), 300):
        ids = ", ".join(n.rsplit("/", 1)[-1] for n in names[i:i + 300])
        try:
            for r in api.search(customer, "SELECT asset.resource_name, asset.type, asset.image_asset.full_size.url, "
                                          "asset.youtube_video_asset.youtube_video_id FROM asset WHERE asset.id IN (%s)" % ids):
                a = r.get("asset") or {}
                found[a.get("resourceName")] = a
        except RuntimeError as e:
            log("Pictures could not be read:", e)
            break
    for a in ads.values():
        v = found.get(a.pop("_video", ""), {})
        yt = (v.get("youtubeVideoAsset") or {}).get("youtubeVideoId")
        if yt:
            a["video_id"] = yt
            a["post_url"] = "https://www.youtube.com/watch?v=" + yt
            a["thumb"] = a["thumb"] or "https://i.ytimg.com/vi/%s/mqdefault.jpg" % yt
        img = found.get(a.pop("_image", ""), {})
        a["thumb"] = a["thumb"] or ((img.get("imageAsset") or {}).get("fullSize") or {}).get("url") or ""


def day(d):
    return "%d %s" % (d.day, d.strftime("%b"))


def pull(cache, customer_ids=(), find="", lookback_days=90, log=print):
    """A fresh copy of every Google account's ads for the last lookback_days. Google keeps adding late conversions for weeks,
    so the whole range is read each time (one request for the ads, one for Performance Max, one for pictures)."""
    api = Api()
    today = date.today()
    first = today - timedelta(days=lookback_days - 1)
    ids = [cid(x) for x in customer_ids if cid(x)]
    if not ids and find:
        log("finding the %s account under the manager account" % find)
        ids = find_accounts(api, find)
        if not ids:
            raise RuntimeError("No Google Ads account with \"%s\" in its name was found under the manager account %s." % (find, api.login))
    accounts, rows, ads, warnings = [], [], {}, []
    for i, c in enumerate(ids, 1):
        try:
            acct = fetch_account(api, c)
            tag = acct["name"] + (" (account %d of %d)" % (i, len(ids)) if len(ids) > 1 else "")
            note = (lambda t: lambda *a: log(t + ":", *a))(tag)
            note("reading ads %s to %s" % (day(first), day(today)))
            r1, a1 = fetch_ads(api, c, first.isoformat(), today.isoformat(), note)
            note("reading Performance Max asset groups")
            try:
                r2, a2 = fetch_asset_groups(api, c, first.isoformat(), today.isoformat(), note)
            except RuntimeError as e:
                note("Performance Max could not be read:", e)
                r2, a2 = [], {}
                warnings.append("%s: Performance Max could not be read: %s" % (acct["name"], e))
            a1.update(a2)
            note("reading pictures")
            fill_pictures(api, c, a1, note)
        except RuntimeError as e:
            log("Account %s failed: %s" % (c, e))
            if len(ids) == 1:
                raise
            warnings.append("Google account %s could not be read: %s" % (c, e))
            continue
        accounts.append(acct)
        rows += r1 + r2
        ads.update(a1)
    if not accounts:
        raise RuntimeError("; ".join(warnings) or "No Google Ads account could be read")
    log("Done: %d accounts, %d rows, %d ads, %d requests" % (len(accounts), len(rows), len(ads), api.requests))
    return {"account": accounts[0], "accounts": accounts, "rows": rows, "ads": ads, "platform": "google",
            "since": first.isoformat(), "until": today.isoformat(), "purchase_types": ["Google Ads conversions"], "warning": " · ".join(warnings)}
