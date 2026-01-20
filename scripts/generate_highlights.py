import asyncio
import json
import os
import random
import string
import re
from datetime import datetime, timedelta
from curl_cffi.requests import AsyncSession

# --- CONFIGURATION ---

FEATURED_TEAMS = [
    "al nassr", "inter miami", "bayern", "dortmund", "leverkusen",
    "psg", "juventus", "atletico", "barcelona", "real madrid",
    "arsenal", "chelsea", "manchester city", "manchester united",
    "liverpool", "portugal", "argentina", "brazil", "spain",
    "england", "france", "inter", "milan", "roma"
]

EXCLUSION_KEYWORDS = [
    "u20", "u21", "u23", "u19", "u18", "women", "youth",
    "academy", "castilla", "femminile", "liga f", "serie c"
]

API_BASE = "https://api.sofascore.com/api/v1"
FILE_PATH = "api/highlights.json"

YT_REGEX = re.compile(r"(?:v=|\/|vi\/|embed\/)([A-Za-z0-9_-]{11})")

# --- UTILITIES ---

def generate_custom_id():
    return ''.join(random.choices(string.ascii_lowercase, k=4)) + ''.join(random.choices(string.digits, k=6))

def clean_team_name(name):
    return name.replace('-', ' ').replace('FC', '').replace('fc', '').strip()

def get_yt_id(url):
    m = YT_REGEX.search(url)
    return m.group(1) if m else None

def is_priority_match(item):
    t1 = item.get("team1", "").lower()
    t2 = item.get("team2", "").lower()
    cat = item.get("category", "").lower()

    if any(x in t1 or x in t2 or x in cat for x in EXCLUSION_KEYWORDS):
        return False

    return any(t in t1 or t in t2 for t in FEATURED_TEAMS)

# --- INCIDENTS (GOALS ONLY) ---

async def get_goals(session, match_id):
    url = f"{API_BASE}/event/{match_id}/incidents"
    try:
        res = await session.get(url, impersonate="chrome120", timeout=10)
        if res.status_code != 200:
            return None
        data = res.json()
    except:
        return None

    home, away = [], []

    for inc in data.get("incidents", []):
        if inc.get("incidentType") != "goal":
            continue

        goal = {
            "name": inc.get("player", {}).get("name", "Unknown"),
            "time": f"{inc.get('time', '')}'"
        }

        if inc.get("isHome"):
            home.append(goal)
        else:
            away.append(goal)

    return {
        "match_id": match_id,
        "home_score": len(home),
        "away_score": len(away),
        "home_scorers": home,
        "away_scorers": away
    }

# --- SCRAPER LOGIC ---

async def get_matches(session, date_str):
    url = f"{API_BASE}/sport/football/scheduled-events/{date_str}"
    try:
        r = await session.get(url, impersonate="chrome120", timeout=15)
        if r.status_code == 200:
            return r.json().get("events", [])
    except:
        pass
    return []

async def get_highlights(session, match_id):
    url = f"{API_BASE}/event/{match_id}/highlights"
    try:
        r = await session.get(url, impersonate="chrome120", timeout=10)
        if r.status_code == 200:
            return r.json().get("highlights", [])
    except:
        pass
    return []

async def process_match(session, match):
    match_id = match["id"]
    highlights = await get_highlights(session, match_id)
    if not highlights:
        return None, set()

    goals = await get_goals(session, match_id)
    if not goals:
        return None, set()

    restricted_ids = set()
    valid_item = None

    for h in highlights:
        url = h.get("url") or h.get("sourceUrl", "")
        vid = get_yt_id(url)
        if not vid:
            continue

        if h.get("forCountries"):
            restricted_ids.add(vid)
            continue

        subtitle = h.get("subtitle", "").lower()
        if not valid_item and ("highlights" in subtitle or "extended" in subtitle):
            valid_item = {
                "id": generate_custom_id(),
                "match_id": match_id,
                "team1": clean_team_name(match["homeTeam"]["name"]),
                "team2": clean_team_name(match["awayTeam"]["name"]),
                "category": match.get("tournament", {}).get("name", "Football"),
                "date": datetime.fromtimestamp(match["startTimestamp"]).strftime("%Y-%m-%d"),
                **goals,
                "link": f"https://www.youtube.com/watch?v={vid}"
            }

    return valid_item, restricted_ids

# --- MAIN ENGINE ---

async def main():
    os.makedirs("api", exist_ok=True)

    existing = []
    if os.path.exists(FILE_PATH):
        with open(FILE_PATH, "r", encoding="utf-8") as f:
            existing = json.load(f)

    async with AsyncSession() as session:
        today = datetime.now()
        dates = [
            (today - timedelta(days=1)).strftime("%Y-%m-%d"),
            today.strftime("%Y-%m-%d")
        ]

        events = []
        for d in dates:
            events.extend(await get_matches(session, d))

        finished = [e for e in events if e.get("status", {}).get("type") in ("finished", "ended")]

        new_items = []
        purge_ids = set()

        for i in range(0, len(finished), 8):
            batch = finished[i:i+8]
            results = await asyncio.gather(*[process_match(session, m) for m in batch])

            for item, restricted in results:
                if item:
                    new_items.append(item)
                purge_ids.update(restricted)

            await asyncio.sleep(1)

        merged = new_items + existing
        final = []
        seen = set()

        for it in merged:
            vid = get_yt_id(it.get("link", ""))
            if vid in purge_ids:
                continue
            if it["link"] not in seen:
                final.append(it)
                seen.add(it["link"])

        final.sort(key=lambda x: (is_priority_match(x), x["date"]), reverse=True)

        with open(FILE_PATH, "w", encoding="utf-8") as f:
            json.dump(final, f, indent=2, ensure_ascii=False)

        print(f"✅ Highlights API updated → {len(final)} items")

if __name__ == "__main__":
    asyncio.run(main())
