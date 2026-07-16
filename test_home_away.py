"""Check if Wikipedia league pages have home/away split tables."""
import requests
from bs4 import BeautifulSoup

session = requests.Session()
session.headers["User-Agent"] = "Mozilla/5.0 Chrome/126.0.0.0 Safari/537.36"

url = "https://en.wikipedia.org/wiki/2025%E2%80%9326_Premier_League"
resp = session.get(url, timeout=10)
soup = BeautifulSoup(resp.text, "html.parser")

# Look for home/away tables
for tag in soup.select("h2, h3, h4"):
    text = tag.get_text(strip=True).lower()
    if any(kw in text for kw in ['home', 'away', 'result', 'table']):
        print(f"Section: {tag.get_text(strip=True)}")
        tbl = tag.find_next("table", class_="wikitable")
        if tbl:
            rows = tbl.select("tr")
            if rows:
                header = rows[0].select("th")
                header_text = " | ".join([h.get_text(strip=True)[:15] for h in header[:12]])
                print(f"  Headers: {header_text[:200]}")
                if len(rows) > 2:
                    row2 = rows[2].select("th, td")
                    print(f"  Row 2: {' | '.join([c.get_text(strip=True)[:15] for c in row2[:12]])}")
                if len(rows) > 3:
                    # Find Arsenal row
                    for row in rows:
                        if "Arsenal" in row.get_text():
                            cells = row.select("th, td")
                            print(f"  Arsenal: {' | '.join([c.get_text(strip=True)[:12] for c in cells[:12]])}")
                            break
        print()

# Also check: does the German Bundesliga page have different format?
print("\n" + "="*60)
print("Bundesliga page structure:")
url2 = "https://en.wikipedia.org/wiki/2025%E2%80%9326_Bundesliga"
resp2 = session.get(url2, timeout=10)
soup2 = BeautifulSoup(resp2.text, "html.parser")
for tag in soup2.select("h2, h3, h4"):
    text = tag.get_text(strip=True).lower()
    if any(kw in text for kw in ['league table', 'standing', 'home', 'away', 'result']):
        print(f"  Section: {tag.get_text(strip=True)}")
        tbl = tag.find_next("table", class_="wikitable")
        if tbl:
            rows = tbl.select("tr")
            if rows:
                header = rows[0].select("th")
                header_text = " | ".join([h.get_text(strip=True)[:15] for h in header[:12]])
                print(f"    Headers: {header_text[:200]}")

session.close()
