const fs = require('fs');
const path = require('path');

const fetch = (...args) => import('node-fetch').then(({default: fetch}) => fetch(...args));

// --- CONFIGURATION ---
const featuredTeamsList = [
    "al-nassr", "inter miami cf", "fc-bayern-munchen", "dortmund", "leverkusen", 
    "paris-saint-germain", "juventus", "atletico-madrid", "barcelona", "real madrid", 
    "arsenal", "chelsea", "manchester city", "manchester united", "liverpool",
    "portugal", "argentina", "brazil", "spain", "england", "france", "inter", "milan"
];

const API_BASE = "https://www.sofascore.com/api/v1";
const API_HIGHLIGHTS = "https://api.sofascore.com/api/v1";

// We use a real-looking browser header to avoid being blocked
const headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
};

function generateCustomID() {
    return Math.random().toString(36).substring(2, 6) + Math.floor(100000 + Math.random() * 900000);
}

function cleanTeamName(name) {
    return name.replace(/-/g, ' ').replace(/\bFC\b/gi, '').trim();
}

async function getMatchesForDate(dateStr) {
    console.log(`🔍 Fetching matches for: ${dateStr}`);
    try {
        const response = await fetch(`${API_BASE}/sport/football/scheduled-events/${dateStr}`, { headers });
        const data = await response.json();
        return data.events || [];
    } catch (err) {
        console.error(`Error fetching date ${dateStr}:`, err.message);
        return [];
    }
}

async function startExtraction() {
    // Get dates for Yesterday and Today to ensure no match is missed
    const today = new Date();
    const yesterday = new Date();
    yesterday.setDate(today.getDate() - 1);

    const dateToday = today.toISOString().split('T')[0];
    const dateYesterday = yesterday.toISOString().split('T')[0];

    try {
        const eventsYesterday = await getMatchesForDate(dateYesterday);
        const eventsToday = await getMatchesForDate(dateToday);
        
        const allEvents = [...eventsYesterday, ...eventsToday];

        if (allEvents.length === 0) {
            console.log("❌ No events found in the API response.");
            return;
        }

        // Filter for finished/ended matches
        const finishedMatches = allEvents.filter(m => {
            const status = m.status.type.toLowerCase();
            return status === 'finished' || status === 'ended';
        });

        console.log(`✅ Total finished matches found: ${finishedMatches.length}`);

        let priorityQueue = [];
        let standardQueue = [];
        let seenIds = new Set(); // Prevent duplicates between yesterday and today

        for (const match of finishedMatches) {
            if (seenIds.has(match.id)) continue;
            seenIds.add(match.id);

            const hName = match.homeTeam.name.toLowerCase();
            const aName = match.awayTeam.name.toLowerCase();
            const isTopTeam = featuredTeamsList.some(team => hName.includes(team) || aName.includes(team));

            try {
                const hRes = await fetch(`${API_HIGHLIGHTS}/event/${match.id}/highlights`, { headers });
                const hData = await hRes.json();

                if (hData.highlights && hData.highlights.length > 0) {
                    let ytLink = null;
                    for (const h of hData.highlights) {
                        const subtitle = (h.subtitle || "").toLowerCase();
                        if (subtitle.includes("highlights") || subtitle.includes("extended")) {
                            const url = h.url || h.sourceUrl || '';
                            const ytMatch = url.match(/(?:v=|\/|vi\/|embed\/)([A-Za-z0-9_-]{11})/);
                            if (ytMatch) {
                                ytLink = `https://www.youtube.com/watch?v=${ytMatch[1]}`;
                                break; 
                            }
                        }
                    }

                    if (ytLink) {
                        const highlightObj = {
                            id: generateCustomID(),
                            team1: cleanTeamName(match.homeTeam.name),
                            team2: cleanTeamName(match.awayTeam.name),
                            category: match.tournament.name,
                            date: new Date(match.startTimestamp * 1000).toISOString().split('T')[0],
                            link: ytLink,
                            isPriority: isTopTeam
                        };

                        if (isTopTeam) priorityQueue.push(highlightObj);
                        else standardQueue.push(highlightObj);
                    }
                }
            } catch (err) {
                // Silent error for individual highlights
            }
        }

        // Merge Priority First
        const finalHighlights = [...priorityQueue, ...standardQueue];

        const apiDir = path.join(__dirname, '../api');
        if (!fs.existsSync(apiDir)) fs.mkdirSync(apiDir, { recursive: true });

        fs.writeFileSync(
            path.join(apiDir, 'highlights.json'),
            JSON.stringify(finalHighlights, null, 2)
        );

        console.log(`🏁 Success! Generated highlights.json with ${finalHighlights.length} items.`);
        console.log(`🔥 Top Team Matches: ${priorityQueue.length}`);

    } catch (globalError) {
        console.error("Fatal Script Error:", globalError);
        process.exit(1);
    }
}

startExtraction();
