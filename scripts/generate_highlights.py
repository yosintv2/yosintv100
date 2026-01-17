import asyncio 
import json
import os
import random
import string
from datetime import datetime, timedelta
from curl_cffi.requests import AsyncSession

# --- CONFIGURATION ---
FEATURED_TEAMS = [
    "al-nassr", "inter miami cf", "fc-bayern-munchen", "dortmund", "leverkusen", 
    "paris-saint-germain", "juventus", "atletico-madrid", "barcelona", "real madrid", 
    "arsenal", "chelsea", "manchester city", "manchester united", "liverpool",
    "portugal", "argentina", "brazil", "spain", "england", "france", "inter", "milan", "roma"
]

# Keywords that disqualify a team from being "Main Team" priority
EXCLUSION_KEYWORDS = [
    "next gen", "castilla", " b", " c", " u21", " u23", " u19", " u18", 
    " youth", " women", "(w)", " academy"
]

API_BASE = "https://api.sofascore.com/api/v1"
FILE_PATH = 'api/highlights.json'

def generate_custom_id():
    return ''.join(random.choices(string.ascii_lowercase, k=4)) + ''.join(random.choices(string.digits, k=6))

def clean_team_name(name):
    return name.replace('-', ' ').replace('FC', '').replace('fc', '').strip()

def is_main_priority_team(team_name):
    """
    Checks if a team is a priority team AND ensures it is the main senior team.
    """
    name_lower = team_name.lower()
    
    # 1. Check if the team is in our featured list
    is_featured = any(team in name_lower for team in FEATURED_TEAMS)
    if not is_featured:
        return False
        
    # 2. Check if the name contains any exclusion keywords (B teams, Youth, Women, etc.)
    has_exclusion = any(word in name_lower for word in EXCLUSION_KEYWORDS)
    
    # It is only a priority if it is featured AND NOT excluded
    return is_featured and not has_exclusion

async def get_matches(session, date_str):
    url = f"{API_BASE}/sport/football/scheduled-events/{date_str}"
    try:
        res = await session.get(url, impersonate="chrome120", timeout=15)
        if res.status_code == 200: return res.json().get('events', [])
    except: pass
    return []

async def get_highlight_data(session, event_id):
    url = f"{API_BASE}/event/{event_id}/highlights"
    try:
        res = await session.get(url, impersonate="chrome120", timeout=10)
        if res.status_code == 200: return res.json().get('highlights', [])
    except: pass
    return []

async def process_match(session, match):
    match_id = match.get('id')
    highlights = await get_highlight_data(session, match_id)
    if not highlights: return None

    yt_link = None
    for h in highlights:
        subtitle = h.get('subtitle', '').lower()
        if "highlights" in subtitle or "extended" in subtitle:
            url = h.get('url', '') or h.get('sourceUrl', '')
            if 'youtube.com' in url or 'youtu.be' in url:
                yt_link = url
                break
    
    if yt_link:
        return {
            "id": generate_custom_id(),
            "team1": clean_team_name(match['homeTeam']['name']),
            "team2": clean_team_name(match['awayTeam']['name']),
            "category": match.get('tournament', {}).get('name', 'Football'),
            "date": datetime.fromtimestamp(match['startTimestamp']).strftime('%Y-%m-%d'),
            "link": yt_link
        }
    return None

async def main():
    # 1. Load Existing Data
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
        for d in dates: all_events.extend(await get_matches(session, d))
        finished = [e for e in all_events if e.get('status', {}).get('type') in ['finished', 'ended']]
        
        # 2. Fetch New Highlights
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
                # Remove legacy priority tags from JSON
                if 'isPriority' in item: del item['isPriority']
                unique_list.append(item)
                seen_links.add(link)

        # 4. ADVANCED SORTING LOGIC
        def sort_key(x):
            # Check Home and Away team for "Main Team" priority
            t1_priority = is_main_priority_team(x.get('team1', ''))
            t2_priority = is_main_priority_team(x.get('team2', ''))
            
            is_featured_match = t1_priority or t2_priority
            return (is_featured_match, x.get('date', '1970-01-01'))

        unique_list.sort(key=sort_key, reverse=True)

        # 5. Save Everything (No isPriority key in output)
        os.makedirs('api', exist_ok=True)
        with open(FILE_PATH, 'w', encoding='utf-8') as f:
            json.dump(unique_list, f, indent=2, ensure_ascii=False)

        print(f"🏁 Success! Clean API generated with {len(unique_list)} items.")
        print(f"✅ Filtered out B-teams, Youth, and Women's teams from priority list.")

if __name__ == "__main__":
    asyncio.run(main())
