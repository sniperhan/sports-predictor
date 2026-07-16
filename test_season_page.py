"""Scrape Wikipedia season page for team match results."""
import requests
from bs4 import BeautifulSoup
import re

session = requests.Session()
session.headers["User-Agent"] = "Mozilla/5.0 Chrome/126.0.0.0 Safari/537.36"

# Try Arsenal's season page
urls = [
    "https://en.wikipedia.org/wiki/2025%E2%80%9326_Arsenal_F.C._season",
    "https://en.wikipedia.org/wiki/2025%E2%80%9326_Manchester_City_F.C._season",
]

for url in urls:
    print(f"\n{'='*60}")
    print(f"URL: {url}")
    resp = session.get(url, timeout=10)
    print(f"Status: {resp.status_code}, Size: {len(resp.text)}")

    if resp.status_code != 200:
        continue

    soup = BeautifulSoup(resp.text, "html.parser")

    # Look for "Premier League" section with match results
    in_pl_section = False
    results = []
    for tag in soup.select("h2, h3, h4, table.wikitable"):
        if tag.name in ("h2", "h3", "h4"):
            text = tag.get_text(strip=True)
            # Check if this section is about Premier League
            if any(kw in text.lower() for kw in ['premier league', 'league', 'matches', 'results', 'fixtures']):
                in_pl_section = True
            elif in_pl_section and text and not any(kw in text.lower() for kw in ['premier league', 'league', 'match', 'result', 'fixture', 'statistic', 'score', 'goal']):
                in_pl_section = False

        if tag.name == "table" and "wikitable" in tag.get("class", []) and in_pl_section:
            rows = tag.select("tr")
            header = rows[0].select("th")
            header_text = " | ".join([h.get_text(strip=True)[:15] for h in header[:12]])

            # Check if this is a match results table (has Date, Opponent, Venue, Result etc.)
            if any(kw in header_text.lower() for kw in ['date', 'opponent', 'venue', 'result', 'score', 'round', 'match']):
                print(f"\n  Match table found: {header_text[:150]}")
                for row in rows[1:8]:  # First few matches
                    cells = row.select("th, td")
                    cell_text = " | ".join([c.get_text(strip=True)[:20] for c in cells[:10]])
                    print(f"    {cell_text[:200]}")

                    # Try to determine H/A and result
                    row_text = row.get_text(" ", strip=True)
                    score_m = re.search(r'(\d+)[–\-–—](\d+)', row_text)
                    if score_m:
                        gf = int(score_m.group(1))
                        ga = int(score_m.group(2))
                        is_home = 'h' in row_text.lower() or 'home' in row_text.lower()
                        if gf > ga:
                            result = 'W'
                        elif gf == ga:
                            result = 'D'
                        else:
                            result = 'L'
                        venue = 'H' if is_home else 'A'
                        results.append((result, venue))
                break  # Only process first match table

    if results:
        print(f"\n  Parsed results: {results}")

session.close()
