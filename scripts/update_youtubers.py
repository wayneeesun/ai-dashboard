#!/usr/bin/env python3
"""
update_youtubers.py
每周末运行，通过 YouTube RSS feed 抓取最新视频，更新 data/youtubers.json
"""

import json, re, urllib.request, urllib.error, xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).parent.parent
DATA_FILE = ROOT / "data" / "youtubers.json"

# YouTube 频道 handle -> channel_id 映射（RSS 需要 channel ID）
CHANNEL_IDS = {
    "karpathy":      "UCbmNph6atAoGfqLoCL_duAg",
    "3b1b":          "UCYO_jab_esuFRV4b17AJtAg",
    "yannic":        "UCZHmQk67mSJgfCCTn7xBfew",
    "lex":           "UCSHZKyawb77ixDdsGog4iWA",
    "aiexplained":   "UCNJ1Ymd5yFuUPtn21xtRbbw",
    "twominutepapers": "UCbfYPyITQ-7l4upoX8nvctg",
    "davidshapiro":  "UCShkK7TJK85_lJjpTdU7Zdg",
    "mattwolfe":     "UCCDNbFPBFnPSYtGpBEp0Hgg",
    "fireship":      "UCsBjURrPoezykLs9EqgamOA",
    "matthewberman": "UCQ2UBhg0mTL29LnNR6Xn47w",
}

NS = "http://www.w3.org/2005/Atom"
YT_NS = "http://www.youtube.com/xml/schemas/2015"
MEDIA_NS = "http://search.yahoo.com/mrss/"

def fetch_rss(channel_id: str) -> list[dict]:
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read()
    except Exception as e:
        print(f"  RSS fetch failed ({channel_id}): {e}")
        return []

    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        print(f"  XML parse failed ({channel_id}): {e}")
        return []

    videos = []
    for entry in root.findall(f"{{{NS}}}entry"):
        title_el   = entry.find(f"{{{NS}}}title")
        link_el    = entry.find(f"{{{NS}}}link")
        pub_el     = entry.find(f"{{{NS}}}published")
        vid_id_el  = entry.find(f"{{{YT_NS}}}videoId")
        desc_el    = entry.find(f"{{{MEDIA_NS}}}group/{{{MEDIA_NS}}}description")

        title  = title_el.text if title_el is not None else ""
        url_   = link_el.get("href", "") if link_el is not None else ""
        pub    = pub_el.text if pub_el is not None else ""
        vid_id = vid_id_el.text if vid_id_el is not None else ""
        desc   = (desc_el.text or "")[:200] if desc_el is not None else ""

        # parse date
        try:
            dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
            date_str = dt.strftime("%Y-%m-%d")
        except Exception:
            date_str = pub[:10] if pub else ""

        videos.append({
            "title": title,
            "url": url_,
            "video_id": vid_id,
            "date": date_str,
            "summary": desc.strip(),
            "duration": "",
        })

    return videos


def is_this_week(date_str: str) -> bool:
    """判断日期是否在最近 7 天内"""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        return (now - dt) <= timedelta(days=7)
    except Exception:
        return False


def main():
    with open(DATA_FILE) as f:
        data = json.load(f)

    print(f"Updating {len(data['channels'])} channels...")

    for ch in data["channels"]:
        cid_key = ch["id"]
        channel_id = CHANNEL_IDS.get(cid_key)
        if not channel_id:
            print(f"  SKIP {ch['name']}: no channel_id mapped")
            continue

        print(f"  Fetching {ch['name']} ({channel_id})...")
        videos = fetch_rss(channel_id)

        this_week = [v for v in videos if is_this_week(v["date"])]
        # 最多保留 3 条
        ch["latest_videos"] = this_week[:3]
        print(f"    -> {len(this_week)} new video(s) this week")

    data["updated_at"] = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")

    with open(DATA_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\nDone. Data written to {DATA_FILE}")


if __name__ == "__main__":
    main()
