"""Meta creative analysis dashboards: Soteri Skin and CABA Design, served by one web server.

A small web server (standard library only) that reads each client's Meta ad accounts every REFRESH_HOURS, keeps the
daily ad-level rows on disk (the Railway volume when there is one), and serves one page per client that works out,
for any date range, which creatives to scale, keep or cut against the account's average ROAS, and which hooks and
formats work.

The clients and their ad accounts are written below (CLIENTS). Each has its own link: Soteri at / (and /soteri),
CABA Design at /caba. A client with several ad accounts gets an Account filter on its page.

Environment:
  META_ADS_ACCESS_TOKEN   System User token with ads_read on every client's ad accounts (required unless DEMO=1)
  DASH_PASSWORD           when set, the pages ask for it (any user name)
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
import threading
import time
import traceback
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import demo
import meta

# The clients: link slug -> name on the page and Meta ad account IDs (in the order the Account filter lists them).
# The first one is also what the bare link (/) shows. To add a client, add a line here.
CLIENTS = {
    "soteri": {"name": "Soteri Skin", "accounts": ["261215873024315"]},
    "caba": {"name": "CABA Design", "accounts": ["6928133667255774", "1135846647331525", "990238779748852"]},   # CABA Design, Design 2, Design 3
}
DEFAULT = next(iter(CLIENTS))

ROOT = Path(__file__).resolve().parent
PORT = int(os.environ.get("PORT", "8000"))
PASSWORD = os.environ.get("DASH_PASSWORD", "")
LOOKBACK = int(os.environ.get("LOOKBACK_DAYS", "90"))
REFRESH_HOURS = float(os.environ.get("REFRESH_HOURS", "24"))
DEMO = os.environ.get("DEMO", "").strip().lower() in ("1", "true", "yes", "on")
_vol = os.environ.get("RAILWAY_VOLUME_MOUNT_PATH")
CACHE_DIR = Path(_vol) if _vol else ROOT / "cache"


class State:
    """One client's last good pull, its page payload, its last error and whether it is being read now."""

    def __init__(self, slug):
        self.slug, self.client = slug, CLIENTS[slug]
        self.data = self.payload = None
        self.error = ""
        self.refreshing = False
        self.progress = ""                       # the last step of the read in progress, for the loading screen
        self.started = None
        self.lock = threading.Lock()
        self.cache = CACHE_DIR / ("%s_meta.json" % slug)


STATES = {slug: State(slug) for slug in CLIENTS}


def log(*a):
    print(datetime.now().strftime("%H:%M:%S"), *a, flush=True)


def compact(st, data):
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
    out.update({"ads": [dict(ads[k], id=k) for k in ids], "rows": rows, "builtAt": data.get("builtAt"), "error": st.error, "refreshHours": REFRESH_HOURS,
                "client": st.client["name"], "slug": st.slug, "clients": [{"slug": k, "name": v["name"]} for k, v in CLIENTS.items()]})
    return out


def publish(st, data):
    with st.lock:
        st.data = data
        st.payload = gzip.compress(json.dumps(compact(st, data), separators=(",", ":")).encode())


def refresh(st):
    if st.refreshing:
        return
    st.refreshing = True
    st.started, st.progress = datetime.now(timezone.utc).isoformat(timespec="seconds"), "Starting"

    def note(*a):
        log("[%s]" % st.slug, *a)
        st.progress = " ".join(str(x) for x in a).strip()
    try:
        if DEMO:
            data = demo.make(LOOKBACK, accounts=len(st.client["accounts"]), client=st.client["name"], seed=7 + len(st.slug))
        else:
            data = meta.pull(st.data, st.client["accounts"], LOOKBACK, log=note)
        data["builtAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        st.error = ""
        if not DEMO:
            st.cache.parent.mkdir(parents=True, exist_ok=True)
            tmp = st.cache.with_suffix(".tmp")
            tmp.write_text(json.dumps(data))
            tmp.replace(st.cache)
        publish(st, data)
    except Exception as e:
        traceback.print_exc()
        st.error = str(e)
        if st.data:
            publish(st, st.data)
    finally:
        st.refreshing = False
        st.progress = ""


def refresh_loop():
    while True:
        # one client after the other, so Meta is never asked twice at once; a client with nothing to show yet goes first
        for st in sorted(STATES.values(), key=lambda s: s.data is not None):
            refresh(st)
        time.sleep(max(0.25, REFRESH_HOURS) * 3600)


def load_cache():
    for st in STATES.values():                   # soteri_meta.json is the name Soteri's cache already had, so it carries over
        if DEMO or not st.cache.exists():
            continue
        try:
            publish(st, json.loads(st.cache.read_text()))
            log("Loaded cache from", st.cache)
        except Exception as e:
            log("Cache unreadable, starting fresh:", st.cache, e)


def client_of(path, query=""):
    """The client a request is for: ?client=caba, or the link /caba, else the first client."""
    for part in query.split("&"):
        k, _, v = part.partition("=")
        if k == "client" and v in CLIENTS:
            return v
    slug = path.strip("/").split("/")[0].lower()
    return slug if slug in CLIENTS else DEFAULT


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path, _, query = self.path.partition("?")
        if path == "/healthz":
            return self._send(200, b"ok", "text/plain")
        if not self._authorized():
            return self._ask_password()
        if path in ("/", "/index.html") or path.strip("/").lower() in CLIENTS:
            return self._send(200, (ROOT / "static" / "index.html").read_bytes(), "text/html; charset=utf-8")
        if path == "/api/data":
            st = STATES[client_of(path, query)]
            if st.payload is None:
                body = json.dumps({"loading": True, "error": st.error, "client": st.client["name"], "progress": st.progress, "started": st.started,
                                   "waiting": not st.refreshing and not st.error}).encode()
                return self._send(200, body, "application/json")
            if "gzip" in self.headers.get("Accept-Encoding", ""):
                return self._send(200, st.payload, "application/json", gz=True)
            return self._send(200, gzip.decompress(st.payload), "application/json")
        self._send(404, b"not found", "text/plain")

    def do_POST(self):
        if not self._authorized():
            return self._ask_password()
        path, _, query = self.path.partition("?")
        if path == "/api/refresh":
            st = STATES[client_of(path, query)]
            started = not st.refreshing
            if started:
                threading.Thread(target=refresh, args=(st,), daemon=True).start()
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
        self.send_header("WWW-Authenticate", 'Basic realm="Meta creative analysis"')
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
        for st in STATES.values():
            st.error = "META_ADS_ACCESS_TOKEN is not set on the server."
    load_cache()
    if DEMO or meta.token():
        threading.Thread(target=refresh_loop, daemon=True).start()
    log("Serving on port", PORT)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
