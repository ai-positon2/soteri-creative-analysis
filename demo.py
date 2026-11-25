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


def make(days=90, n_ads=46, seed=7):
    rnd = random.Random(seed)
    today = date.today()
    ads, rows = {}, []
    for i in range(n_ads):
        ad_id = str(120210000000000 + i)
        fmt = rnd.choice(FORMATS)
        hook = rnd.choice(HOOKS)
        angle = rnd.choice(ANGLES)
        camp = rnd.choice(["Prospecting | ASC+", "Prospecting | Broad", "Retargeting | 30d"])
        ads[ad_id] = {"name": "%s_%s_%s_v%d" % (angle, fmt.split()[0].upper(), "Eczema" if i % 2 else "Barrier", i % 4 + 1),
                      "status": "ACTIVE" if rnd.random() < .7 else "PAUSED", "created": (today - timedelta(days=rnd.randint(5, 120))).isoformat(),
                      "campaign": camp, "adset": camp.split("|")[1].strip() + " - US", "format": fmt, "partnership": rnd.random() < .35, "partnership_ids": "Facebook + Instagram", "cta": rnd.choice(["Shop now", "Shop now", "Get offer", "Learn more"]), "hook": hook,
                      "body": hook + "\n\nSoteri's ceramide cream calms flare-ups without steroids.", "headline": "Calm skin in 7 days",
                      "thumb": "", "video_id": "1" if "Video" in fmt else "", "creative_id": "", "post_url": ""}
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
            rows.append({"date": (today - timedelta(days=days - 1 - d)).isoformat(), "ad_id": ad_id, "ad_name": ads[ad_id]["name"],
                         "adset": ads[ad_id]["adset"], "campaign": camp, "spend": spend, "impressions": impr, "clicks": clicks,
                         "purchases": purch, "revenue": round(purch * rnd.uniform(38, 72), 2), "atc": purch * 3 + rnd.randint(0, 3),
                         "v3": int(impr * hook_rate) if ads[ad_id]["video_id"] else 0,
                         "thru": int(impr * hook_rate * rnd.uniform(.2, .45)) if ads[ad_id]["video_id"] else 0})
    return {"account": {"id": "act_demo", "name": "Soteri Skin (demo data)", "currency": "USD", "timezone": ""},
            "rows": rows, "ads": ads, "since": (today - timedelta(days=days - 1)).isoformat(), "until": today.isoformat(),
            "purchase_types": ["demo"], "demo": True}
