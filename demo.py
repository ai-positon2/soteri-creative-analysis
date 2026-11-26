"""Made-up data in the shape meta.pull returns, for running the dashboard without a Meta token (DEMO=1).
The page shows a "demo data" banner whenever this is what it is drawing."""
import random
from datetime import date, timedelta

HOOKS = ["Your eczema isn't the problem. Your moisturizer is.", "I tried 14 creams before this one.",
         "Dermatologists don't tell you this about ceramides.", "POV: the itch finally stops at 2am.",
         "Stop putting steroids on your baby's skin.", "This is what 7 days of Soteri looks like.",
         "The 3-ingredient rule for sensitive skin.", "Flare-ups after every shower? Read this."]
FORMATS = ["Video", "Video", "Video", "Image", "Image", "Carousel", "Flexible (mixed)", "Catalog"]
ANGLES = ["UGC", "Founder", "Derm", "BeforeAfter", "Static", "Testimonial"]
G_FORMATS = ["Search (responsive)", "Search (responsive)", "Search (responsive)", "Performance Max", "Performance Max",
             "YouTube video", "Demand Gen video", "Demand Gen image", "Shopping"]
G_HEADS = ["Steroid-Free Eczema Cream", "Calm Flare-Ups in 7 Days", "Dermatologist Tested Relief", "Soteri Skin Official Site",
           "Ceramide Cream for Babies", "Free Shipping Over $50", "Stop the Itch Tonight", "Gentle Enough for Daily Use"]
G_CAMPS = {"Search": ["Search | Brand", "Search | Eczema Generic"], "Performance Max": ["PMax | All Products"],
           "YouTube": ["YouTube | Prospecting"], "Demand Gen": ["Demand Gen | Prospecting"], "Shopping": ["Shopping | Catalog"]}


def make(days=90, n_ads=46, seed=7, accounts=1, client="Soteri Skin", platform="meta"):
    rnd = random.Random(seed)
    accts = [{"id": "act_demo%d" % (i + 1), "name": client + (" %d" % (i + 1) if accounts > 1 else "") + " (demo data)", "currency": "USD", "timezone": ""}
             for i in range(max(1, accounts))]
    today = date.today()
    ads, rows = {}, []
    for i in range(n_ads):
        ad_id = str(120210000000000 + i)
        google = platform == "google"
        fmt = rnd.choice(G_FORMATS if google else FORMATS)
        hook = rnd.choice(G_HEADS if google else HOOKS)
        angle = rnd.choice(ANGLES)
        camp = rnd.choice(next(v for k, v in G_CAMPS.items() if fmt.startswith(k)) if google else ["Prospecting | ASC+", "Prospecting | Broad", "Retargeting | 30d"])
        acct = accts[i % len(accts)]["id"]
        ads[ad_id] = {"account": acct, "name": "%s_%s_%s_v%d" % (angle, fmt.split()[0].upper(), "Eczema" if i % 2 else "Barrier", i % 4 + 1),
                      "status": "ACTIVE" if rnd.random() < .7 else "PAUSED", "created": (today - timedelta(days=rnd.randint(5, 120))).isoformat(),
                      "campaign": camp, "adset": camp.split("|")[1].strip() + " - US", "format": fmt, "partnership": rnd.random() < .35, "partnership_ids": "Facebook + Instagram", "cta": rnd.choice(["Shop now", "Shop now", "Get offer", "Learn more"]), "hook": hook,
                      "body": hook + "\n\nSoteri's ceramide cream calms flare-ups without steroids.", "headline": "Calm skin in 7 days",
                      "thumb": "", "video_id": "1" if "Video" in fmt else "", "creative_id": "", "post_url": ""}
        if google:
            ads[ad_id].update({"name": "%s · %s" % (camp.split("|")[1].strip(), fmt) if fmt != "Performance Max" else "Asset group %d" % (i % 5 + 1),
                               "adset": "Asset group" if fmt == "Performance Max" else camp.split("|")[1].strip() + " - Core",
                               "partnership": None, "partnership_ids": "", "cta": "", "body": "Steroid-free ceramide cream. Calms flare-ups fast.",
                               "headline": hook + " | Shop Soteri Skin", "video_id": "1" if "video" in fmt else "", "landing": "https://soteriskin.com/"})
        quality = rnd.lognormvariate(0, .55) * (1.25 if angle in ("UGC", "Derm") else 1) * (1.2 if fmt == "Video" else 1)
        hook_rate = min(.6, max(.08, rnd.gauss(.28, .08) * (1.3 if "eczema" in hook.lower() else 1)))
        budget = rnd.lognormvariate(3.4, .9)
        start = rnd.randint(0, days - 5)
        for d in range(start, days):
            if rnd.random() < .12:
                continue
            spend = round(budget * rnd.uniform(.5, 1.5), 2)
            impr = int(spend / rnd.uniform(.012, .022))
            clicks = int(impr * rnd.uniform(.006, .016) * quality ** .5)
            purch = sum(1 for _ in range(clicks) if rnd.random() < .022 * quality)
            rows.append({"date": (today - timedelta(days=days - 1 - d)).isoformat(), "ad_id": ad_id, "ad_name": ads[ad_id]["name"], "account": acct,
                         "adset": ads[ad_id]["adset"], "campaign": camp, "spend": spend, "impressions": impr, "clicks": clicks,
                         "purchases": purch, "revenue": round(purch * rnd.uniform(38, 72), 2), "atc": purch * 3 + rnd.randint(0, 3),
                         "v3": int(impr * hook_rate * (.6 if google else 1)) if ads[ad_id]["video_id"] else 0,
                         "thru": int(impr * hook_rate * rnd.uniform(.2, .45)) if ads[ad_id]["video_id"] else 0})
    return {"account": accts[0], "accounts": accts,
            "rows": rows, "ads": ads, "since": (today - timedelta(days=days - 1)).isoformat(), "until": today.isoformat(),
            "purchase_types": ["demo"], "demo": True, "platform": platform}
