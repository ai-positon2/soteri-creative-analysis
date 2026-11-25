"""Meta Marketing API reader for the creative analysis: daily ad-level results plus each ad's creative.

Read only. The ad account is META_AD_ACCOUNT_ID (Soteri Skin: 261215873024315), the token is
META_ADS_ACCESS_TOKEN (a System User token with ads_read on that account).

What is read:
  * the account's name, currency and time zone;
  * /insights at ad level, one row per ad per day, for every ad that spent: spend, impressions, link clicks,
    purchases and purchase value, add-to-carts, 3-second video plays and ThruPlays;
  * for every ad in those rows: its name, status, campaign, ad set and creative (format, primary text,
    headline, thumbnail, link to the post).
"""
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

GRAPH = "https://graph.facebook.com/" + os.environ.get("META_API_VERSION", "v23.0").strip()
CHUNK_DAYS = 10            # insights are read ten days at a time so one request never gets too large
# the purchase action counted, first one present wins (never summed: Meta reports the same purchase under several of these)
PURCHASE_TYPES = [t.strip() for t in os.environ.get(
    "PURCHASE_ACTION", "omni_purchase,offsite_conversion.fb_pixel_purchase,purchase,onsite_web_purchase").split(",") if t.strip()]
# every status an ad that spent can be in now, archived included (the ads edge leaves archived ones out unless asked)
ALL_STATUSES = ["ACTIVE", "PAUSED", "CAMPAIGN_PAUSED", "ADSET_PAUSED", "ARCHIVED", "PENDING_REVIEW", "IN_PROCESS",
                "WITH_ISSUES", "DISAPPROVED", "PREAPPROVED", "PENDING_BILLING_INFO"]
CTA = {"LEARN_MORE": "Learn more", "SHOP_NOW": "Shop now", "SIGN_UP": "Sign up", "BOOK_NOW": "Book now", "CONTACT_US": "Contact us",
       "GET_OFFER": "Get offer", "SUBSCRIBE": "Subscribe", "ORDER_NOW": "Order now", "BUY_NOW": "Buy now", "GET_STARTED": "Get started",
       "SEE_MORE": "See more", "SEE_DETAILS": "See details", "WATCH_MORE": "Watch more", "APPLY_NOW": "Apply now", "DOWNLOAD": "Download",
       "GET_QUOTE": "Get quote", "SEND_MESSAGE": "Send message", "MESSAGE_PAGE": "Send message", "CALL_NOW": "Call now", "NO_BUTTON": "No button"}
ATC_TYPES = ["omni_add_to_cart", "offsite_conversion.fb_pixel_add_to_cart", "add_to_cart"]
INSIGHT_FIELDS = "ad_id,ad_name,adset_name,campaign_name,spend,impressions,inline_link_clicks,actions,action_values,video_thruplay_watched_actions"
AD_FIELDS = ("name,effective_status,created_time,campaign{id,name,effective_status},adset{id,name,effective_status},"
             "creative{id,object_type,title,body,image_url,thumbnail_url,video_id,call_to_action_type,object_story_spec,asset_feed_spec,"
             "instagram_permalink_url,effective_object_story_id,product_set_id}")


def token():
    return os.environ.get("META_ADS_ACCESS_TOKEN", "").strip().strip("\"'")


def account_id():
    d = re.sub(r"\D", "", os.environ.get("META_AD_ACCOUNT_ID", "261215873024315"))
    return "act_" + d


class Api:
    """Graph API GETs with paging and a retry on Meta's rate limits. Errors carry Meta's message, never the token."""

    def __init__(self):
        self.tok = token()
        if not self.tok:
            raise RuntimeError("META_ADS_ACCESS_TOKEN is not set")
        self.requests, self.lock = 0, threading.Lock()

    def get(self, path, params=None):
        q = dict(params or {}, access_token=self.tok)
        url = path if path.startswith("https://") else "%s/%s?%s" % (GRAPH, path.lstrip("/"), urllib.parse.urlencode(q))
        for attempt in range(5):
            with self.lock:
                self.requests += 1
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "creative-analysis-dashboard"})
                with urllib.request.urlopen(req, timeout=90) as r:
                    return json.load(r)
            except urllib.error.HTTPError as e:
                try:
                    err = json.loads(e.read().decode("utf-8", "replace")).get("error") or {}
                except ValueError:
                    err = {}
                if err.get("code") in (1, 2, 4, 17, 32, 613, 80000, 80004) and attempt < 4:   # rate limits and "try again later"
                    time.sleep(15 * (attempt + 1))
                    continue
                raise RuntimeError("Meta answered %s: %s" % (e.code, err.get("message") or "no reason given")) from None
            except urllib.error.URLError as e:
                if attempt == 4:
                    raise RuntimeError("Meta could not be reached (%s)" % e.reason) from None
                time.sleep(3 * (attempt + 1))
        raise RuntimeError("Meta kept refusing the request (rate limit)")

    def pages(self, path, params):
        out, got = [], self.get(path, params)
        while True:
            out += got.get("data") or []
            nxt = (got.get("paging") or {}).get("next")
            if not nxt:
                return out
            got = self.get(nxt)


# ── one insights row ────────────────────────────────────────────────────────

def _action(lst, types):
    """The value of the first action type present (lists of {action_type, value})."""
    vals = {a.get("action_type"): a.get("value") for a in (lst or [])}
    for t in types:
        if t in vals:
            return float(vals[t] or 0), t
    return 0.0, None


def parse_row(r):
    purchases, ptype = _action(r.get("actions"), PURCHASE_TYPES)
    revenue = _action(r.get("action_values"), [ptype])[0] if ptype else 0.0
    return {
        "date": r["date_start"],
        "ad_id": r["ad_id"],
        "ad_name": r.get("ad_name") or "",
        "adset": r.get("adset_name") or "",
        "campaign": r.get("campaign_name") or "",
        "spend": float(r.get("spend") or 0),
        "impressions": int(float(r.get("impressions") or 0)),
        "clicks": int(float(r.get("inline_link_clicks") or 0)),
        "purchases": purchases,
        "revenue": revenue,
        "atc": _action(r.get("actions"), ATC_TYPES)[0],
        "v3": _action(r.get("actions"), ["video_view"])[0],            # 3-second video plays
        "thru": _action(r.get("video_thruplay_watched_actions"), ["video_view"])[0],
    }


# ── one creative ────────────────────────────────────────────────────────────

def _first_line(text):
    """The hook of the primary text: its first non-empty line, or its first sentence when that line runs long."""
    for line in str(text or "").splitlines():
        line = " ".join(line.split())
        if line:
            if len(line) > 110:
                m = re.match(r"(.{20,110}?[.!?])(\s|$)", line)
                line = m.group(1) if m else line[:107].rstrip() + "…"
            return line
    return ""


def describe_creative(c):
    """Format, primary text, headline and picture of one creative, wherever Meta keeps them."""
    c = c or {}
    oss = c.get("object_story_spec") or {}
    afs = c.get("asset_feed_spec") or {}
    link, video, photo = oss.get("link_data") or {}, oss.get("video_data") or {}, oss.get("photo_data") or {}
    tmpl = oss.get("template_data") or {}
    body = c.get("body") or link.get("message") or video.get("message") or photo.get("caption") or tmpl.get("message") or ""
    title = c.get("title") or link.get("name") or video.get("title") or tmpl.get("name") or ""
    if afs:
        body = body or next((b.get("text") for b in afs.get("bodies") or [] if b.get("text")), "")
        title = title or next((t.get("text") for t in afs.get("titles") or [] if t.get("text")), "")

    if c.get("product_set_id") or tmpl or "product_set" in json.dumps(afs.get("ad_formats") or []).lower():
        fmt = "Catalog"
    elif afs and len(afs.get("videos") or []) + len(afs.get("images") or []) + bool(c.get("video_id") or video) > 0:
        # Advantage+ creatives often keep their one video on the creative itself, not in the asset feed
        n_vid, n_img = len(afs.get("videos") or []), len(afs.get("images") or [])
        if not n_vid and (c.get("video_id") or video):
            n_vid = 1
        if "CAROUSEL" in (afs.get("ad_formats") or []):
            fmt = "Carousel"
        elif n_vid and n_img:
            fmt = "Flexible (mixed)"
        elif n_vid:
            fmt = "Video" if n_vid == 1 else "Flexible (videos)"
        else:
            fmt = "Image" if n_img <= 1 else "Flexible (images)"
    elif link.get("child_attachments"):
        fmt = "Carousel"
    elif video or c.get("video_id") or c.get("object_type") == "VIDEO":
        fmt = "Video"
    elif link or photo or c.get("object_type") in ("SHARE", "PHOTO", "STATUS"):
        fmt = "Image"
    else:
        fmt = "Other"

    afs_cta = afs.get("call_to_action_types") or [x.get("type") for x in afs.get("call_to_actions") or [] if isinstance(x, dict)]
    cta = (c.get("call_to_action_type") or (link.get("call_to_action") or {}).get("type") or (video.get("call_to_action") or {}).get("type")
           or (tmpl.get("call_to_action") or {}).get("type") or (afs_cta[0] if afs_cta else "") or "")
    story = c.get("effective_object_story_id") or ""
    return {
        "format": fmt,
        "cta": CTA.get(cta, cta.replace("_", " ").capitalize()) if cta else "No button",
        "body": body.strip(),
        "hook": _first_line(body),
        "headline": " ".join(str(title).split()),
        "thumb": c.get("image_url") or video.get("image_url") or c.get("thumbnail_url") or "",
        "video_id": c.get("video_id") or video.get("video_id") or "",
        "creative_id": c.get("id") or "",
        "post_url": c.get("instagram_permalink_url") or ("https://www.facebook.com/" + story if story else ""),
    }


# ── the whole pull ──────────────────────────────────────────────────────────

def fetch_account(api):
    a = api.get(account_id(), {"fields": "name,currency,timezone_name"})
    return {"id": a.get("id", account_id()), "name": a.get("name", ""), "currency": a.get("currency", "USD"),
            "timezone": a.get("timezone_name", "")}


def fetch_insights(api, since, until, log=print):
    """Daily ad-level rows for every ad that spent between since and until (dates, inclusive)."""
    rows, d = [], since
    while d <= until:
        end = min(d + timedelta(days=CHUNK_DAYS - 1), until)
        got = api.pages(account_id() + "/insights", {
            "level": "ad", "time_increment": 1, "fields": INSIGHT_FIELDS, "limit": 500,
            "time_range": json.dumps({"since": d.isoformat(), "until": end.isoformat()}),
            "filtering": json.dumps([{"field": "spend", "operator": "GREATER_THAN", "value": 0}]),
            "action_breakdowns": "action_type",
        })
        rows += [parse_row(r) for r in got]
        log("  insights %s → %s: %d rows" % (d, end, len(got)))
        d = end + timedelta(days=1)
    return rows


def _picked(d):
    """Any id-like value under a branded-content field: Meta doesn't document the names a partnership ad is read back under."""
    d = d if isinstance(d, dict) else {}
    return next((str(v) for v in d.values() if isinstance(v, (str, int)) and str(v)), "")


def _extras(api, creative_id):
    """A 400px thumbnail and the Partnership-ad (branded content) settings of one creative. Some accounts refuse the
    branded-content fields: then the thumbnail is read alone and partnership is None (unknown), never a failed pull."""
    q = {"thumbnail_width": 400, "thumbnail_height": 400}
    try:
        c = api.get(creative_id, dict(q, fields="thumbnail_url,facebook_branded_content,instagram_branded_content"))
        fb, ig = _picked(c.get("facebook_branded_content")), _picked(c.get("instagram_branded_content"))
        return creative_id, c.get("thumbnail_url"), {"on": bool(fb or ig), "fb": bool(fb), "ig": bool(ig)}
    except RuntimeError:
        try:
            return creative_id, api.get(creative_id, dict(q, fields="thumbnail_url")).get("thumbnail_url"), None
        except RuntimeError:
            return creative_id, None, None


def fetch_ads(api, ad_ids):
    """Name, status, campaign, ad set and creative of each ad (read from the account's ads edge, filtered to these
    ids, a hundred at a time: Graph v26 dropped the ?ids= lookup), plus larger thumbnails."""
    ads, ids = {}, sorted(set(ad_ids))
    for i in range(0, len(ids), 100):
        got = api.pages(account_id() + "/ads", {
            "fields": "id," + AD_FIELDS, "limit": 100,
            "filtering": json.dumps([{"field": "id", "operator": "IN", "value": ids[i:i + 100]},
                                     {"field": "effective_status", "operator": "IN", "value": ALL_STATUSES}]),
        })
        for a in got:
            info = describe_creative(a.get("creative"))
            info.update({"name": a.get("name", ""), "status": a.get("effective_status", ""),
                         "created": (a.get("created_time") or "")[:10],
                         "campaign": (a.get("campaign") or {}).get("name", ""),
                         "adset": (a.get("adset") or {}).get("name", ""),
                         "campaign_status": (a.get("campaign") or {}).get("effective_status", ""),
                         "adset_status": (a.get("adset") or {}).get("effective_status", "")})
            ads[a["id"]] = info
    # thumbnail_url is 64px unless asked for bigger, and partnership settings; one read per creative, eight at a time
    need = sorted({a["creative_id"] for a in ads.values() if a["creative_id"]})
    with ThreadPoolExecutor(8) as pool:
        got = list(pool.map(lambda c: _extras(api, c), need))
    big = {k: t for k, t, _ in got if t}
    branded = {k: b for k, _, b in got}
    for a in ads.values():
        b = branded.get(a["creative_id"])
        a["partnership"] = None if b is None else b["on"]
        a["partnership_ids"] = "" if not b or not b["on"] else ("Facebook + Instagram" if b["fb"] and b["ig"] else "Facebook" if b["fb"] else "Instagram")
        if a["format"] in ("Video", "Flexible (videos)", "Flexible (mixed)", "Carousel", "Catalog") or not a["thumb"]:
            a["thumb"] = big.get(a["creative_id"]) or a["thumb"]
    return ads


def pull(cache, lookback_days=90, refetch_days=7, log=print):
    """A fresh copy of the data: rows older than refetch_days are kept from the cache, the rest re-read
    (Meta keeps attributing purchases to recent days for a week)."""
    api = Api()
    today = date.today()
    first = today - timedelta(days=lookback_days - 1)
    old_rows = [r for r in (cache or {}).get("rows", []) if r["date"] >= first.isoformat()]
    have = {r["date"] for r in old_rows}
    cut = today - timedelta(days=refetch_days)
    keep = [r for r in old_rows if r["date"] < cut.isoformat()]
    since = cut if have and min(have) <= first.isoformat() else first
    log("Reading Meta %s: %s → %s" % (account_id(), since, today))
    rows = keep + [r for r in fetch_insights(api, since, today, log) if r["date"] >= since.isoformat()]
    warning = ""
    try:
        ads = fetch_ads(api, [r["ad_id"] for r in rows])
    except RuntimeError as e:          # the results still show, named from the insights rows, without pictures or formats
        log("Creative details failed:", e)
        ads, warning = (cache or {}).get("ads", {}), "Creative details (thumbnails, formats, copy) could not be read: %s" % e
    log("Done: %d rows, %d ads, %d requests" % (len(rows), len(ads), api.requests))
    return {"account": fetch_account(api), "rows": rows, "ads": ads, "since": first.isoformat(), "until": today.isoformat(),
            "purchase_types": PURCHASE_TYPES, "warning": warning}
