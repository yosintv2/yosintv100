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

EXCLUSION_KEYWORDS = [
    "next gen", " u20", "castilla", " b ", " c ", " u21", " u23", " u19", " u18", 
    " youth", " women", "(w)", "gaúcho", "serie c", "femminile", "liga f", "moeve", "academy", "under-", "primera f"
]

API_BASE = "https://api.sofascore.com/api/v1"
FILE_PATH = 'api/highlights.json'

YT_REGEX = re.compile(r"(?:v=|\/|vi\/|embed\/)([A-Za-z0-9_-]{11})")

# --- UTILITIES ---

def generate_custom_id():
    return ''.join(random.choices(string.ascii_lowercase, k=4)) + ''.join(random.choices(string.digits, k=6))

def clean_team_name(name):
    return name.replace('-', ' ').replace('FC', '').replace('fc', '').strip()

def get_yt_id(url):
    match = YT_REGEX.search(url)
    return match.group(1) if match else None

def is_priority_match(item):
    t1 = item.get('team1', '').lower()
    t2 = item.get('team2', '').lower()
    cat = item.get('category', '').lower()
    
    for word in EXCLUSION_KEYWORDS:
        if word in t1 or word in t2 or word in cat:
            return False
            
    is_featured = any(team.lower() in t1 for team in FEATURED_TEAMS) or \
                  any(team.lower() in t2 for team in FEATURED_TEAMS)
    
    return is_featured

# --- SCRAPER LOGIC ---

async def get_matches(session, date_str):
    url = f"{API_BASE}/sport/football/scheduled-events/{date_str}"
    try:
        res = await session.get(url, impersonate="chrome120", timeout=15)
        if res.status_code == 200: 
            return res.json().get('events', [])
    except: pass
    return []

async def get_highlight_data(session, event_id):
    url = f"{API_BASE}/event/{event_id}/highlights"
    try:
        res = await session.get(url, impersonate="chrome120", timeout=10)
        if res.status_code == 200: 
            return res.json().get('highlights', [])
    except: pass
    return []

async def process_match(session, match):
    """
    Returns (ValidHighlightDict, SetOfRestrictedYoutubeIDs)
    """
    match_id = match.get('id')
    highlights = await get_highlight_data(session, match_id)
    if not highlights: 
        return None, set()

    valid_highlight = None
    restricted_ids = set()

    for h in highlights:
        subtitle = h.get('subtitle', '').lower()
        url = h.get('url', '') or h.get('sourceUrl', '')
        v_id = get_yt_id(url)
        
        if not v_id: continue

        # Check restrictions
        for_countries = h.get('forCountries')
        is_restricted = isinstance(for_countries, list) and len(for_countries) > 0
        
        if is_restricted:
            # Add to purge list if it has country limits
            restricted_ids.add(v_id)
            continue

        # If it's global, check if it's a relevant highlight
        if not valid_highlight:
            is_relevant = "highlights" in subtitle or "extended" in subtitle
            if is_relevant:
                valid_highlight = {
                    "id": generate_custom_id(),
                    "team1": clean_team_name(match['homeTeam']['name']),
                    "team2": clean_team_name(match['awayTeam']['name']),
                    "category": match.get('tournament', {}).get('name', 'Football'),
                    "date": datetime.fromtimestamp(match['startTimestamp']).strftime('%Y-%m-%d'),
                    "link": f"https://www.youtube.com/watch?v={v_id}"
                }
    
    return valid_highlight, restricted_ids

# --- MAIN ENGINE ---

async def main():
    existing_data = []
    if os.path.exists(FILE_PATH):
        try:
            with open(FILE_PATH, 'r', encoding='utf-8') as f:
                existing_data = json.load(f)
                if not isinstance(existing_data, list): existing_data = []
        except: existing_data = []

    async with AsyncSession() as session:
        now = datetime.now()
        dates = [(now - timedelta(days=1)).strftime('%Y-%m-%d'), now.strftime('%Y-%m-%d')]
        
        all_events = []
        for d in dates: 
            all_events.extend(await get_matches(session, d))
        
        finished = [e for e in all_events if e.get('status', {}).get('type') in ['finished', 'ended']]
        
        new_highlights = []
        restricted_purge_list = set()
        
        batch_size = 10
        for i in range(0, len(finished), batch_size):
            tasks = [process_match(session, m) for m in finished[i:i+batch_size]]
            results = await asyncio.gather(*tasks)
            
            for item, purged_ids in results:
                if item: new_highlights.append(item)
                if purged_ids: restricted_purge_list.update(purged_ids)
            
            await asyncio.sleep(1)

        # Merge and Filter
        combined = new_highlights + existing_data
        unique_list = []
        seen_links = set()
        
        removed_count = 0
        for item in combined:
            link = item.get('link')
            v_id = get_yt_id(link) if link else None
            
            # AUTO-REMOVE logic: 
            # 1. Skip if the link is in the restricted purge list
            if v_id in restricted_purge_list:
                removed_count += 1
                continue
            
            # 2. Standard Deduplication
            if link and link not in seen_links:
                if 'isPriority' in item: del item['isPriority']
                unique_list.append(item)
                seen_links.add(link)

        # Final Advanced Sorting
        def sort_key(x):
            priority = is_priority_match(x)
            return (priority, x.get('date', '1970-01-01'))

        unique_list.sort(key=sort_key, reverse=True)

        os.makedirs('api', exist_ok=True)
        with open(FILE_PATH, 'w', encoding='utf-8') as f:
            json.dump(unique_list, f, indent=2, ensure_ascii=False)

        print(f"🏁 Success! API updated with {len(unique_list)} items.")
        print(f"🔥 Auto-Removed {removed_count} restricted/existing links from API.")
        print(f"🚫 Geo-Restriction: Global-only policy enforced.")

if __name__ == "__main__":
    asyncio.run(main())
