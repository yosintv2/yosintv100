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
    "al-nassr", "inter miami cf", "fc-bayern-munchen", "dortmund", "leverkusen", 
    "paris-saint-germain", "juventus", "atletico-madrid", "barcelona", "real madrid", 
    "arsenal", "chelsea", "manchester city", "manchester united", "liverpool",
    "portugal", "argentina", "brazil", "spain", "england", "france", "inter", "milan", "roma"
]

# Keywords that disqualify a team from being "Main Team" priority
EXCLUSION_KEYWORDS = [
    "next gen"," u20", "castilla", " b", " c", " u21", " u23", " u19", " u18", 
    " youth", " women", "(w)"," Femminile", " Femminile" " Liga F Moeve"
]

API_BASE = "https://api.sofascore.com/api/v1"
FILE_PATH = 'api/highlights.json'

# Regex to extract 11-char YouTube ID from various URL formats
YT_REGEX = re.compile(r"(?:v=|\/|vi\/|embed\/)([A-Za-z0-9_-]{11})")

# --- UTILITIES ---

def generate_custom_id():
    """Generates a unique 10-character ID (4 letters + 6 digits)."""
    return ''.join(random.choices(string.ascii_lowercase, k=4)) + ''.join(random.choices(string.digits, k=6))

def clean_team_name(name):
    """Removes dashes and 'FC' fluff for a cleaner UI."""
    return name.replace('-', ' ').replace('FC', '').replace('fc', '').strip()

def is_main_priority_team(team_name):
    """Checks if a team is featured and NOT a youth/women/B team."""
    name_lower = team_name.lower()
    is_featured = any(team in name_lower for team in FEATURED_TEAMS)
    has_exclusion = any(word in name_lower for word in EXCLUSION_KEYWORDS)
    return is_featured and not has_exclusion

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
        
        # 1. Check if the video is relevant (Highlights/Extended)
        is_relevant = "highlights" in subtitle or "extended" in subtitle
        
        # 2. GLOBAL CHECK: Ensure no country restrictions
        # If 'forCountries' is missing or empty, it's a global video
        for_countries = h.get('forCountries', [])
        is_global = not for_countries or len(for_countries) == 0

        if is_relevant and is_global:
            url = h.get('url', '') or h.get('sourceUrl', '')
            
            # 3. YOUTUBE NORMALIZATION: Extract ID and rebuild link
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

# --- MAIN EXECUTION ---

async def main():
    # 1. Load Existing Data for merging
    existing_data = []
    if os.path.exists(FILE_PATH):
        try:
            with open(FILE_PATH, 'r', encoding='utf-8') as f:
                existing_data = json.load(f)
                if not isinstance(existing_data, list): existing_data = []
        except Exception: 
            existing_data = []

    async with AsyncSession() as session:
        # Check Yesterday and Today
        now = datetime.now()
        dates = [(now - timedelta(days=1)).strftime('%Y-%m-%d'), now.strftime('%Y-%m-%d')]
        
        all_events = []
        for d in dates: 
            all_events.extend(await get_matches(session, d))
        
        # Filter for completed matches
        finished = [e for e in all_events if e.get('status', {}).get('type') in ['finished', 'ended']]
        
        # 2. Fetch New Highlights in Batches
        new_highlights = []
        batch_size = 10
        for i in range(0, len(finished), batch_size):
            tasks = [process_match(session, m) for m in finished[i:i+batch_size]]
            batch_res = await asyncio.gather(*tasks)
            new_highlights.extend([r for r in batch_res if r])
            await asyncio.sleep(1) # Polite delay

        # 3. Merge and Deduplicate by Link
        combined = new_highlights + existing_data
        unique_list = []
        seen_links = set()
        
        for item in combined:
            link = item.get('link')
            if link and link not in seen_links:
                # Remove legacy priority tags if they exist
                if 'isPriority' in item: 
                    del item['isPriority']
                unique_list.append(item)
                seen_links.add(link)

        # 4. ADVANCED SORTING
        def sort_key(x):
            # Prioritize featured teams + latest date
            t1_priority = is_main_priority_team(x.get('team1', ''))
            t2_priority = is_main_priority_team(x.get('team2', ''))
            is_featured_match = t1_priority or t2_priority
            return (is_featured_match, x.get('date', '1970-01-01'))

        unique_list.sort(key=sort_key, reverse=True)

        # 5. Save Final JSON
        os.makedirs('api', exist_ok=True)
        with open(FILE_PATH, 'w', encoding='utf-8') as f:
            json.dump(unique_list, f, indent=2, ensure_ascii=False)

        print(f"🏁 Success! Clean API generated with {len(unique_list)} items.")
        print(f"🌍 Global-only videos: Verified.")
        print(f"🔝 Priority: Featured senior teams moved to top.")

if __name__ == "__main__":
    asyncio.run(main())
