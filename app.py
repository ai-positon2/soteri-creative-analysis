"""Meta creative analysis dashboard (Soteri Skin, CABA Design: one service per client, the same code).

A small web server (standard library only) that reads the Meta ad account every REFRESH_HOURS, keeps the daily
ad-level rows on disk (the Railway volume when there is one), and serves one page that works out, for any date
range, which creatives to scale, keep or cut against the account's average ROAS, and which hooks and formats work.

Environment:
  META_ADS_ACCESS_TOKEN   System User token with ads_read on the account (required unless DEMO=1)
  CLIENT_NAME             the client's name on the page, default "Soteri Skin"
  META_AD_ACCOUNT_IDS     the ad accounts read, comma separated (CABA Design has three); the page gets an Account filter when there are several
  META_AD_ACCOUNT_ID      one ad account, when META_AD_ACCOUNT_IDS is not set: default 261215873024315 (Soteri Skin)
  DASH_PASSWORD           when set, the page asks for it (any user name)
  LOOKBACK_DAYS           days of history kept, default 90
  REFRESH_HOURS           how often Meta is re-read, default 24 (once a day; the Refresh button reads it any time)
  PURCHASE_ACTION         purchase action types tried in order, default omni_purchase,offsite_conversion.fb_pixel_purchase,purchase
  DEMO=1                  made-up data, no Meta calls
"""
import base64
import gzip
import hmac
import json
import os
import re
import threading
import time
import traceback
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import demo
import meta

ROOT = Path(__file__).resolve().parent
PORT = int(os.environ.get("PORT", "8000"))
PASSWORD = os.environ.get("DASH_PASSWORD", "")
LOOKBACK = int(os.environ.get("LOOKBACK_DAYS", "90"))
REFRESH_HOURS = float(os.environ.get("REFRESH_HOURS", "24"))
DEMO = os.environ.get("DEMO", "").strip().lower() in ("1", "true", "yes", "on")
CLIENT = os.environ.get("CLIENT_NAME", "").strip() or "Soteri Skin"
SLUG = re.sub(r"[^a-z0-9]+", "-", CLIENT.lower()).strip("-") or "client"
_vol = os.environ.get("RAILWAY_VOLUME_MOUNT_PATH")
CACHE = Path(os.environ.get("CACHE_FILE") or (Path(_vol) if _vol else ROOT / "cache") / ("soteri_meta.json" if SLUG == "soteri-skin" else SLUG + "_meta.json"))


class State:
    data = None          # the last good pull
    payload = None       # its gzipped JSON for the page
    error = ""           # the last refresh's failure, shown on the page
    refreshing = False
    lock = threading.Lock()


def log(*a):
    print(datetime.now().strftime("%H:%M:%S"), *a, flush=True)


def compact(data):
    """What the page needs, small: ads keyed by id, and one array per daily row."""
    ads = dict(data["ads"])
    for r in data["rows"]:                       # ads Meta no longer returns (deleted) keep their names from the rows
        if r["ad_id"] not in ads:
            ads[r["ad_id"]] = {"name": r["ad_name"], "status": "DELETED", "campaign": r["campaign"], "adset": r["adset"], "account": r.get("account", ""),
                               "format": "Unknown", "cta": "Unknown", "partnership": None, "partnership_ids": "", "hook": "", "body": "", "headline": "", "thumb": "", "video_id": "",
                               "creative_id": "", "post_url": "", "created": ""}
    ids = sorted(ads)
    idx = {k: i for i, k in enumerate(ids)}
    rows = [[r["date"], idx[r["ad_id"]], round(r["spend"], 2), r["impressions"], r["clicks"], r["purchases"],
             round(r["revenue"], 2), r["atc"], r["v3"], r["thru"]] for r in data["rows"]]
    rows.sort()
    first = (data.get("account") or {}).get("id", "")
    for a in ads.values():                       # a cache from before several accounts were read: everything is the one account's
        a.setdefault("account", first)
    out = {k: v for k, v in data.items() if k not in ("rows", "ads")}
    out.setdefault("accounts", [data["account"]] if data.get("account") else [])
    out.update({"ads": [dict(ads[k], id=k) for k in ids], "rows": rows,
                "builtAt": data.get("builtAt"), "error": State.error, "refreshHours": REFRESH_HOURS, "client": CLIENT, "slug": SLUG})
    return out


def publish(data):
    with State.lock:
        State.data = data
        State.payload = gzip.compress(json.dumps(compact(data), separators=(",", ":")).encode())


def refresh():
    if State.refreshing:
        return
    State.refreshing = True
    try:
        if DEMO:
            data = demo.make(LOOKBACK, accounts=int(os.environ.get("DEMO_ACCOUNTS", "1") or 1), client=CLIENT)
        else:
            data = meta.pull(State.data, LOOKBACK, log=log)
        data["builtAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        State.error = ""
        if not DEMO:
            CACHE.parent.mkdir(parents=True, exist_ok=True)
            tmp = CACHE.with_suffix(".tmp")
            tmp.write_text(json.dumps(data))
            tmp.replace(CACHE)
        publish(data)
    except Exception as e:
        traceback.print_exc()
        State.error = str(e)
        if State.data:
            publish(State.data)
    finally:
        State.refreshing = False


def refresh_loop():
    while True:
        refresh()
        time.sleep(max(0.25, REFRESH_HOURS) * 3600)


def load_cache():
    if DEMO or not CACHE.exists():
        return
    try:
        publish(json.loads(CACHE.read_text()))
        log("Loaded cache from", CACHE)
    except Exception as e:
        log("Cache unreadable, starting fresh:", e)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/healthz":
            return self._send(200, b"ok", "text/plain")
        if not self._authorized():
            return self._ask_password()
        if path in ("/", "/index.html"):
            return self._send(200, (ROOT / "static" / "index.html").read_bytes(), "text/html; charset=utf-8")
        if path == "/api/data":
            if State.payload is None:
                body = json.dumps({"loading": True, "error": State.error}).encode()
                return self._send(200, body, "application/json")
            if "gzip" in self.headers.get("Accept-Encoding", ""):
                return self._send(200, State.payload, "application/json", gz=True)
            return self._send(200, gzip.decompress(State.payload), "application/json")
        self._send(404, b"not found", "text/plain")

    def do_POST(self):
        if not self._authorized():
            return self._ask_password()
        if self.path.split("?")[0] == "/api/refresh":
            started = not State.refreshing
            if started:
                threading.Thread(target=refresh, daemon=True).start()
            return self._send(202, json.dumps({"started": started}).encode(), "application/json")
        self._send(404, b"not found", "text/plain")

    def _authorized(self):
        if not PASSWORD:
            return True
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Basic "):
            return False
        try:
            _, _, pw = base64.b64decode(auth[6:]).decode().partition(":")
        except Exception:
            return False
        return hmac.compare_digest(pw, PASSWORD)

    def _ask_password(self):
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="%s creative analysis"' % CLIENT.replace('"', ""))
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send(self, code, body, ctype, gz=False):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-cache")
        if gz:
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    if not DEMO and not meta.token():
        log("META_ADS_ACCESS_TOKEN is not set: the page will say so. Set DEMO=1 to try it with made-up data.")
        State.error = "META_ADS_ACCESS_TOKEN is not set on the server."
    load_cache()
    if DEMO or meta.token():
        threading.Thread(target=refresh_loop, daemon=True).start()
    log("Serving on port", PORT)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
