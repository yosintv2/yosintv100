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
    "Al Nassr", "inter miami cf", "Bayern München", "dortmund", "leverkusen", 
    "paris-saint-germain", "juventus", "atletico-madrid", "barcelona", "real madrid", 
    "arsenal", "chelsea", "manchester city", "manchester united", "liverpool",
    "portugal", "argentina", "brazil", "spain", "england", "france", "inter", "milan", "roma"
]

# Keywords that demote a match from the top (checked against Team names AND Category)
EXCLUSION_KEYWORDS = [
    "next gen", " u20", "castilla", " b ", " c ", " u21", " u23", " u19", " u18", 
    " youth", " women", "(w)", "gaúcho", "serie c", "femminile", "liga f", "moeve", "academy", "under-", "primera f"
]

API_BASE = "https://api.sofascore.com/api/v1"
FILE_PATH = 'api/highlights.json'

# Regex to extract 11-char YouTube ID and standardize the link
YT_REGEX = re.compile(r"(?:v=|\/|vi\/|embed\/)([A-Za-z0-9_-]{11})")

# --- UTILITIES ---

def generate_custom_id():
    """Generates a unique 10-character ID (4 letters + 6 digits)."""
    return ''.join(random.choices(string.ascii_lowercase, k=4)) + ''.join(random.choices(string.digits, k=6))

def clean_team_name(name):
    """Removes dashes and 'FC' fluff for a cleaner UI."""
    return name.replace('-', ' ').replace('FC', '').replace('fc', '').strip()

def is_priority_match(item):
    """
    Logic: 
    1. If ANY exclusion keyword is in Team1, Team2, or Category -> NOT Priority.
    2. If it passes exclusions AND one team is in FEATURED_TEAMS -> IS Priority.
    """
    t1 = item.get('team1', '').lower()
    t2 = item.get('team2', '').lower()
    cat = item.get('category', '').lower()
    
    # Check for exclusions first (Women, Youth, B-Teams, etc.)
    for word in EXCLUSION_KEYWORDS:
        if word in t1 or word in t2 or word in cat:
            return False
            
    # Check if a high-profile team is playing
    is_featured = any(team in t1 for team in FEATURED_TEAMS) or \
                  any(team in t2 for team in FEATURED_TEAMS)
    
    return is_featured

# --- SCRAPER LOGIC ---

async def get_matches(session, date_str):
    url = f"{API_BASE}/sport/football/scheduled-events/{date_str}"
    try:
        res = await session.get(url, impersonate="chrome120", timeout=15)
        if res.status_code == 200: 
            return res.json().get('events', [])
    except Exception:
        pass
    return []

async def get_highlight_data(session, event_id):
    url = f"{API_BASE}/event/{event_id}/highlights"
    try:
        res = await session.get(url, impersonate="chrome120", timeout=10)
        if res.status_code == 200: 
            return res.json().get('highlights', [])
    except Exception:
        pass
    return []

async def process_match(session, match):
    match_id = match.get('id')
    highlights = await get_highlight_data(session, match_id)
    if not highlights: 
        return None

    for h in highlights:
        subtitle = h.get('subtitle', '').lower()
        
        # 1. Relevance: Only full highlights or extended versions
        is_relevant = "highlights" in subtitle or "extended" in subtitle
        
        # 2. Global Check: Skip videos restricted to specific countries
        for_countries = h.get('forCountries', [])
        is_global = not for_countries or len(for_countries) == 0

        if is_relevant and is_global:
            url = h.get('url', '') or h.get('sourceUrl', '')
            
            # 3. YouTube Normalization
            yt_match = YT_REGEX.search(url)
            if yt_match:
                video_id = yt_match.group(1)
                return {
                    "id": generate_custom_id(),
                    "team1": clean_team_name(match['homeTeam']['name']),
                    "team2": clean_team_name(match['awayTeam']['name']),
                    "category": match.get('tournament', {}).get('name', 'Football'),
                    "date": datetime.fromtimestamp(match['startTimestamp']).strftime('%Y-%m-%d'),
                    "link": f"https://www.youtube.com/watch?v={video_id}"
                }
    return None

# --- MAIN ENGINE ---

async def main():
    # 1. Load Existing Data
    existing_data = []
    if os.path.exists(FILE_PATH):
        try:
            with open(FILE_PATH, 'r', encoding='utf-8') as f:
                existing_data = json.load(f)
                if not isinstance(existing_data, list): existing_data = []
        except Exception:
            existing_data = []

    async with AsyncSession() as session:
        # Check Yesterday and Today to catch late-night games
        now = datetime.now()
        dates = [(now - timedelta(days=1)).strftime('%Y-%m-%d'), now.strftime('%Y-%m-%d')]
        
        all_events = []
        for d in dates: 
            all_events.extend(await get_matches(session, d))
        
        # Process only finished matches
        finished = [e for e in all_events if e.get('status', {}).get('type') in ['finished', 'ended']]
        
        # 2. Fetch Highlights (Batching to prevent IP bans)
        new_highlights = []
        batch_size = 10
        for i in range(0, len(finished), batch_size):
            tasks = [process_match(session, m) for m in finished[i:i+batch_size]]
            batch_res = await asyncio.gather(*tasks)
            new_highlights.extend([r for r in batch_res if r])
            await asyncio.sleep(1)

        # 3. Merge and Deduplicate
        combined = new_highlights + existing_data
        unique_list = []
        seen_links = set()
        
        for item in combined:
            link = item.get('link')
            if link and link not in seen_links:
                # Cleanup legacy keys if present
                if 'isPriority' in item: 
                    del item['isPriority']
                unique_list.append(item)
                seen_links.add(link)

        # 4. Final Advanced Sorting
        def sort_key(x):
            # First criteria: Is it a main priority match? (Boolean 1/0)
            # Second criteria: Date (Newest first)
            priority = is_priority_match(x)
            return (priority, x.get('date', '1970-01-01'))

        unique_list.sort(key=sort_key, reverse=True)

        # 5. Save to File
        os.makedirs('api', exist_ok=True)
        with open(FILE_PATH, 'w', encoding='utf-8') as f:
            json.dump(unique_list, f, indent=2, ensure_ascii=False)

        print(f"🏁 Success! API updated with {len(unique_list)} items.")
        print(f"🚫 Strict Filter: Categories like 'Femminile' or 'Liga F' are demoted.")
        print(f"🌍 Link Check: All videos are global/unrestricted.")

if __name__ == "__main__":
    asyncio.run(main())
