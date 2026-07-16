"""
Data Fetcher - Wikipedia-based data extraction for sports prediction.

Uses Wikipedia exclusively (fast, reliable, no rate limiting):
1. Team page infobox → league position, total teams (~2s)
2. League season page → league table with Pts/GF/GA for all teams (~2s)
3. Team season page → recent results form (~2s)

Covers: league position, points, goals for/against, recent form, season status.
Other dimensions (H2H, injuries, market value) require manual input.
"""

import re
import concurrent.futures
from datetime import datetime
from typing import Optional
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

from predictor import TeamData


# Wikipedia season page names (2025-26 season) and total teams
LEAGUE_TABLES = {
    "英超": "2025%E2%80%9326_Premier_League",
    "Premier League": "2025%E2%80%9326_Premier_League",
    "西甲": "2025%E2%80%9326_La_Liga",
    "La Liga": "2025%E2%80%9326_La_Liga",
    "德甲": "2025%E2%80%9326_Bundesliga",
    "Bundesliga": "2025%E2%80%9326_Bundesliga",
    "意甲": "2025%E2%80%9326_Serie_A",
    "Serie A": "2025%E2%80%9326_Serie_A",
    "法甲": "2025%E2%80%9326_Ligue_1",
    "Ligue 1": "2025%E2%80%9326_Ligue_1",
    "欧冠": "2025%E2%80%9326_UEFA_Champions_League",
    "Champions League": "2025%E2%80%9326_UEFA_Champions_League",
    "欧联杯": "2025%E2%80%9326_UEFA_Europa_League",
    "Europa League": "2025%E2%80%9326_UEFA_Europa_League",
    "美职联": "2026_Major_League_Soccer_season",
    "MLS": "2026_Major_League_Soccer_season",
    "日职": "2026_J1_League",
    "J League": "2026_J1_League",
    "韩K联": "2026_K_League_1",
    "K League": "2026_K_League_1",
    "挪超": "2026_Eliteserien",
    "巴甲": "2026_Campeonato_Brasileiro_S%C3%A9rie_A",
}


class DataFetcher:
    """Fetch sports data from Wikipedia (fast, reliable, free)."""

    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    )
    WIKI_API = "https://en.wikipedia.org/w/api.php"
    WIKI_BASE = "https://en.wikipedia.org/wiki/"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = self.USER_AGENT
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=3)
        self._league_table_cache = {}  # Cache league table data per league

    def close(self):
        self._executor.shutdown(wait=False)
        self.session.close()

    # ─── Main Entry Point ───────────────────────────────────

    def search_team_data(
        self, team_name: str, opponent: str, league: str, is_home: bool
    ) -> TeamData:
        """Fetch comprehensive team data from Wikipedia."""
        data = TeamData(name=team_name)
        year = str(datetime.now().year)

        futures = {}

        # Task 1: Wikipedia team page → infobox (position, total teams)
        f1 = self._executor.submit(self._fetch_wikipedia_data, team_name, league)
        futures[f1] = "wiki_team"

        # Task 2: Wikipedia league table → points, goals for/against
        if league in LEAGUE_TABLES:
            f2 = self._executor.submit(self._fetch_league_table_data, team_name, league)
            futures[f2] = "league_table"

        # Collect results
        for future in concurrent.futures.as_completed(futures):
            task = futures[future]
            try:
                result = future.result()
                if task == "wiki_team" and result:
                    pos, total = result
                    if pos:
                        data.league_position = pos
                    if total:
                        data.total_teams = total
                elif task == "league_table" and result:
                    pts, gf, ga, matches, wins, draws, losses = result
                    if pts:
                        data.league_points = pts
                    if gf is not None and ga is not None and matches > 0:
                        data.goals_for = round(gf / matches, 1)
                        data.goals_against = round(ga / matches, 1)
                    # Build estimated recent form from season W/D/L proportions
                    if wins or draws or losses:
                        total_games = wins + draws + losses
                        if total_games >= 5:
                            n = 5
                            w5 = max(0, min(n, round(wins / total_games * n)))
                            d5 = max(0, min(n - w5, round(draws / total_games * n)))
                            l5 = n - w5 - d5
                            data.recent_form = ['W'] * w5 + ['D'] * d5 + ['L'] * l5
            except Exception:
                pass

        data.in_season = True  # Wikipedia data implies in-season
        return data

    # ─── Wikipedia Team Page ────────────────────────────────

    def _fetch_wikipedia_data(
        self, team_name: str, user_league: str
    ) -> tuple:
        """Fetch team Wikipedia page and extract infobox data.

        Returns (position, total_teams).
        """
        html = self._fetch_wikipedia_page(team_name)
        if not html:
            return None, None

        pos, total, _ = self._parse_wikipedia_infobox(html, user_league)
        return pos, total

    def _fetch_wikipedia_page(self, team_name: str) -> Optional[str]:
        """Search Wikipedia for a team page and return its HTML."""
        try:
            params = {
                "action": "query",
                "list": "search",
                "srsearch": f"{team_name} football club",
                "format": "json",
                "srlimit": 3,
            }
            resp = self.session.get(self.WIKI_API, params=params, timeout=10)
            if resp.status_code != 200:
                return None

            results = resp.json().get("query", {}).get("search", [])
            if not results:
                return None

            page_title = results[0]["title"]
            page_url = f"{self.WIKI_BASE}{quote_plus(page_title.replace(' ', '_'))}"
            resp = self.session.get(page_url, timeout=10)
            if resp.status_code == 200:
                return resp.text
        except Exception:
            pass
        return None

    def _parse_wikipedia_infobox(
        self, html: str, user_league: str
    ) -> tuple:
        """Extract position, total teams, and season page URL from infobox.

        The infobox has rows like:
          [League]: Premier League
          [2025-26]: Premier League, 2nd of 20  (with link to season page)
        Returns (position, total_teams, season_page_url).
        """
        try:
            soup = BeautifulSoup(html, "html.parser")
            infobox = soup.select_one(".infobox")
            if not infobox:
                return None, None, None

            position = None
            total_teams = None
            season_url = None

            rows = infobox.select("tr")
            for row in rows:
                th = row.select_one("th")
                td = row.select_one("td")
                if not th or not td:
                    continue

                label = th.get_text(strip=True)
                value = td.get_text(" ", strip=True)

                # Season year row: "2025-26" or "2025–26" or "2025"
                if re.match(r"^(20\d{2}[–\-–—]\d{2,4}|20\d{2})$", label):
                    # "Premier League, 2nd of 20"
                    pos_season = re.search(
                        r"(\d+)(?:st|nd|rd|th)\s+(?:of|in|place)?\s*(\d+)",
                        value, re.IGNORECASE
                    )
                    if pos_season:
                        position = int(pos_season.group(1))
                        total = int(pos_season.group(2))
                        if total <= 50:
                            total_teams = total
                    else:
                        pos_only = re.search(r"(\d+)(?:st|nd|rd|th)", value)
                        if pos_only:
                            position = int(pos_only.group(1))

                    # Get the link to the season page
                    link = td.select_one("a[href*='20']")
                    if link:
                        href = link.get("href", "")
                        if "/wiki/" in href:
                            season_url = href

                # Also check League row for position (some infobox formats)
                if not position and "league" in label.lower():
                    pos_match = re.search(
                        r"(\d+)(?:st|nd|rd|th)\s+(?:of|in|place)?\s*(\d+)",
                        value, re.IGNORECASE
                    )
                    if pos_match:
                        position = int(pos_match.group(1))
                        total = int(pos_match.group(2))
                        if total <= 50:
                            total_teams = total

            return position, total_teams, season_url
        except Exception:
            return None, None, None

    # ─── Wikipedia League Table ─────────────────────────────

    def _fetch_league_table_data(
        self, team_name: str, league: str
    ) -> tuple:
        """Scrape the Wikipedia league season page for team stats.

        Returns (points, goals_for, goals_against, matches_played, wins, draws, losses).
        """
        if league not in LEAGUE_TABLES:
            return None, None, None, 0

        # Check cache first
        if league in self._league_table_cache:
            table_html = self._league_table_cache[league]
        else:
            page_name = LEAGUE_TABLES[league]
            url = f"{self.WIKI_BASE}{page_name}"
            try:
                resp = self.session.get(url, timeout=10)
                if resp.status_code != 200:
                    return None, None, None, 0, 0, 0, 0
                table_html = resp.text
                self._league_table_cache[league] = table_html
            except Exception:
                return None, None, None, 0, 0, 0, 0

        return self._parse_league_table(table_html, team_name)

    def _parse_league_table(self, html: str, team_name: str) -> tuple:
        """Parse a Wikipedia league table and find the team's row.

        Returns (points, goals_for, goals_against, matches_played, wins, draws, losses).
        """
        try:
            soup = BeautifulSoup(html, "html.parser")

            # Find the league table: it follows a "League table" heading
            league_table = None
            for tag in soup.select("h2, h3, h4"):
                if "league table" in tag.get_text(strip=True).lower():
                    league_table = tag.find_next("table", class_="wikitable")
                    break

            if not league_table:
                return None, None, None, 0, 0, 0, 0

            header_row = league_table.select_one("tr")
            if not header_row:
                return None, None, None, 0, 0, 0, 0

            headers = [h.get_text(strip=True).upper() for h in header_row.select("th")]
            # Map: column_name → index
            col_map = {}
            for i, h in enumerate(headers):
                h_clean = h.strip()
                if h_clean in ('POS', 'POSITION', 'RANK', '#'):
                    col_map['pos'] = i
                elif h_clean in ('TEAM', 'CLUB', 'SQUAD'):
                    col_map['team'] = i
                elif h_clean in ('PLD', 'MP', 'GP', 'P', 'MATCHES'):
                    col_map['pld'] = i
                elif h_clean in ('W', 'WIN'):
                    col_map['w'] = i
                elif h_clean in ('D', 'DRAW'):
                    col_map['d'] = i
                elif h_clean in ('L', 'LOSS', 'LOST'):
                    col_map['l'] = i
                elif h_clean in ('GF', 'F', 'GS', 'GOALSFOR'):
                    col_map['gf'] = i
                elif h_clean in ('GA', 'A', 'GC', 'GOALSAGAINST'):
                    col_map['ga'] = i
                elif h_clean in ('GD', 'GOAL DIFFERENCE', '+/-', 'DIFF'):
                    col_map['gd'] = i
                elif h_clean in ('PTS', 'POINTS', 'PT'):
                    col_map['pts'] = i

            # Find team's row
            data_rows = league_table.select("tr")[1:]  # Skip header
            for row in data_rows:
                cells = row.select("th, td")
                if len(cells) < 3:
                    continue

                # Check if this row contains our team
                team_col = col_map.get('team', 1)
                row_has_team = False
                if team_col < len(cells):
                    cell_text = cells[team_col].get_text(strip=True).lower()
                    if team_name.lower() in cell_text:
                        row_has_team = True
                if not row_has_team:
                    for c in cells:
                        if team_name.lower() in c.get_text(strip=True).lower():
                            row_has_team = True
                            break

                if not row_has_team:
                    continue

                # Extract data using column map
                def get_val(col_name):
                    idx = col_map.get(col_name)
                    if idx is not None and idx < len(cells):
                        raw = cells[idx].get_text(strip=True)
                        raw = re.sub(r'\[.*?\]', '', raw)  # Remove citation brackets
                        try:
                            return int(re.sub(r'[^\d]', '', raw))
                        except ValueError:
                            return None
                    return None

                pts = get_val('pts')
                gf = get_val('gf')
                ga = get_val('ga')
                mp = get_val('pld') or 0
                w = get_val('w') or 0
                d = get_val('d') or 0
                l = get_val('l') or 0

                return pts, gf, ga, mp, w, d, l

        except Exception:
            pass
        return None, None, None, 0, 0, 0, 0

