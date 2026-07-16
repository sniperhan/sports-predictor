"""
Data Fetcher - Wikipedia-based data extraction for sports prediction.

Data sources (all Wikipedia, all free, no API keys):
1. Team page infobox -> league position, total teams (~1s)
2. League season page -> league table: Pts, GF, GA, W/D/L for all teams (~2s)
3. Team season page -> "Results by round" table: Ground(H/A) + Result(W/D/L) (~2s)

Covers 7 of 9 dimensions: home_away, recent_form, league_position, goals_data,
match_fitness, team_strength (partial via points). Missing: h2h, injuries, odds.
"""

import re
import concurrent.futures
from datetime import datetime
from typing import Optional
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

from predictor import TeamData


# Wikipedia league season page names (2025-26 season)
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
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=3)
        self._league_table_cache = {}
        self._season_page_cache = {}

    def close(self):
        self._executor.shutdown(wait=False)

    def _make_session(self):
        s = requests.Session()
        s.headers["User-Agent"] = self.USER_AGENT
        return s

    # ─── Main Entry Point ───────────────────────────────────

    def search_team_data(
        self, team_name: str, opponent: str, league: str, is_home: bool
    ) -> TeamData:
        """Fetch comprehensive team data from Wikipedia in parallel."""
        data = TeamData(name=team_name)
        futures = {}

        # Task 1: Team infobox -> position, total teams, season page URL
        f1 = self._executor.submit(self._fetch_team_page, team_name, league)
        futures[f1] = "team_page"

        # Task 2: League table -> points, GF, GA, W, D, L
        if league in LEAGUE_TABLES:
            f2 = self._executor.submit(self._fetch_league_table_data, team_name, league)
            futures[f2] = "league_table"

        # Collect results
        season_url = None
        for future in concurrent.futures.as_completed(futures):
            task = futures[future]
            try:
                result = future.result()
                if task == "team_page" and result:
                    pos, total, s_url = result
                    if pos:
                        data.league_position = pos
                    if total:
                        data.total_teams = total
                    if s_url:
                        season_url = s_url
                elif task == "league_table" and result:
                    pts, gf, ga, matches, wins, draws, losses = result
                    if pts:
                        data.league_points = pts
                    if gf is not None and ga is not None and matches > 0:
                        data.goals_for = round(gf / matches, 1)
                        data.goals_against = round(ga / matches, 1)
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

        # Task 3: Team season page -> actual recent results with H/A split
        if season_url and not data.home_form:
            season_html = self._fetch_season_page(season_url, team_name)
            if season_html:
                home_form, away_form, recent_form = self._parse_results_by_round(season_html)
                if home_form:
                    data.home_form = home_form
                if away_form:
                    data.away_form = away_form
                if recent_form:
                    data.recent_form = recent_form  # Override estimated form with actual

        data.in_season = True
        return data

    # ─── Task 1: Team Page + Infobox ─────────────────────────

    def _fetch_team_page(self, team_name: str, user_league: str) -> tuple:
        """Fetch team Wikipedia page and extract infobox data.
        Returns (position, total_teams, team_season_page_url).
        """
        html = self._fetch_wikipedia_page(team_name)
        if not html:
            return None, None, None
        pos, total, _ = self._parse_wikipedia_infobox(html, user_league)
        season_url = self._find_season_page_link(html, team_name)
        return pos, total, season_url

    def _fetch_wikipedia_page(self, team_name: str) -> Optional[str]:
        """Search Wikipedia for a team page and return its HTML."""
        try:
            s = self._make_session()
            params = {
                "action": "query",
                "list": "search",
                "srsearch": f"{team_name} football club",
                "format": "json",
                "srlimit": 3,
            }
            resp = s.get(self.WIKI_API, params=params, timeout=10)
            if resp.status_code != 200:
                return None
            results = resp.json().get("query", {}).get("search", [])
            if not results:
                return None
            page_title = results[0]["title"]
            page_url = f"{self.WIKI_BASE}{quote_plus(page_title.replace(' ', '_'))}"
            resp = s.get(page_url, timeout=10)
            if resp.status_code == 200:
                return resp.text
        except Exception:
            pass
        return None

    def _parse_wikipedia_infobox(self, html: str, user_league: str) -> tuple:
        """Extract position, total teams, and team season page URL from infobox.

        Infobox rows:
          [League]: Premier League
          [2025-26]: Premier League, 2nd of 20  (<a> links to team season page)
        Returns (position, total_teams, team_season_url).
        """
        try:
            soup = BeautifulSoup(html, "html.parser")
            infobox = soup.select_one(".infobox")
            if not infobox:
                return None, None, None

            position = None
            total_teams = None
            season_url = None

            for row in infobox.select("tr"):
                th = row.select_one("th")
                td = row.select_one("td")
                if not th or not td:
                    continue

                label = th.get_text(strip=True)
                value = td.get_text(" ", strip=True)

                # Season year row: "2025-26" or "2025–26" or "2025"
                if re.match(r"^(20\d{2}[–\-–—]\d{2,4}|20\d{2})$", label):
                    pos_match = re.search(
                        r"(\d+)(?:st|nd|rd|th)\s+(?:of|in|place)?\s*(\d+)",
                        value, re.IGNORECASE
                    )
                    if pos_match:
                        position = int(pos_match.group(1))
                        total = int(pos_match.group(2))
                        if total <= 50:
                            total_teams = total
                    else:
                        pos_only = re.search(r"(\d+)(?:st|nd|rd|th)", value)
                        if pos_only:
                            position = int(pos_only.group(1))

                    # Get the TEAM season page link (e.g. /wiki/2025-26_Arsenal_F.C._season)
                    for link in td.select("a[href*='20']"):
                        href = link.get("href", "")
                        if "/wiki/" in href:
                            # Check if it's a team season page or league season page
                            link_text = link.get_text(strip=True).lower()
                            if any(kw in href.lower() for kw in ['season', '_f.c.', '_fc', 'cf_', 'united', 'city', 'madrid', 'munich', 'milan']):
                                season_url = href
                                break
                            elif not season_url:
                                season_url = href  # Fallback

                # League row (fallback)
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

    def _find_season_page_link(self, html: str, team_name: str) -> Optional[str]:
        """Find the team's 2025-26 season page URL from Wikipedia page links.

        Looks for links like '/wiki/2025%E2%80%9326_Arsenal_F.C._season'.
        Filters out league season pages (e.g. '2025-26_Premier_League').
        """
        try:
            soup = BeautifulSoup(html, "html.parser")
            # Build search tokens from team name
            name_parts = team_name.lower().replace(" ", "_").split("_")
            # Remove common suffixes for matching
            league_keywords = {"premier", "la_liga", "bundesliga", "serie_a", "ligue_1",
                               "champions", "europa", "major_league", "eliteserien", "campeonato"}

            for link in soup.select("a[href*='2025']"):
                href = link.get("href", "")
                href_lower = href.lower()

                # Must contain "season"
                if "season" not in href_lower:
                    continue

                # Must NOT be a league season page
                if any(lk in href_lower for lk in league_keywords):
                    continue

                # Check if team name appears in the URL
                matches = sum(1 for part in name_parts if len(part) > 2 and part in href_lower)
                if matches >= 1:  # At least 1 name part matches
                    return href

            return None
        except Exception:
            return None

    # ─── Task 2: League Table ────────────────────────────────

    def _fetch_league_table_data(self, team_name: str, league: str) -> tuple:
        """Scrape the Wikipedia league season page for team stats.
        Returns (points, goals_for, goals_against, matches_played, wins, draws, losses).
        """
        if league not in LEAGUE_TABLES:
            return None, None, None, 0, 0, 0, 0

        if league in self._league_table_cache:
            table_html = self._league_table_cache[league]
        else:
            page_name = LEAGUE_TABLES[league]
            url = f"{self.WIKI_BASE}{page_name}"
            try:
                s = self._make_session()
                resp = s.get(url, timeout=10)
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

            data_rows = league_table.select("tr")[1:]
            for row in data_rows:
                cells = row.select("th, td")
                if len(cells) < 3:
                    continue

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

                def get_val(col_name):
                    idx = col_map.get(col_name)
                    if idx is not None and idx < len(cells):
                        raw = cells[idx].get_text(strip=True)
                        raw = re.sub(r'\[.*?\]', '', raw)
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

    # ─── Task 3: Season Page -> Results by Round ─────────────

    def _fetch_season_page(self, season_url: str, team_name: str) -> Optional[str]:
        """Fetch the team's season page from Wikipedia."""
        if season_url in self._season_page_cache:
            return self._season_page_cache[season_url]

        try:
            if season_url.startswith("/wiki/"):
                url = f"https://en.wikipedia.org{season_url}"
            elif season_url.startswith("//"):
                url = f"https:{season_url}"
            elif season_url.startswith("http"):
                url = season_url
            else:
                url = f"{self.WIKI_BASE}{season_url}"

            s = self._make_session()
            resp = s.get(url, timeout=10)
            if resp.status_code == 200:
                self._season_page_cache[season_url] = resp.text
                return resp.text
        except Exception:
            pass
        return None

    def _parse_results_by_round(self, html: str) -> tuple:
        """Parse the 'Results by round' table from a team season page.

        Table format:
          Round | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9
          Ground | H | A | H | A | H | H | A | H | A
          Result | W | W | L | W | D | W | W | W | W

        Returns (home_form, away_form, recent_form) - each is list of W/D/L.
        """
        try:
            soup = BeautifulSoup(html, "html.parser")

            for table in soup.select("table.wikitable"):
                rows = table.select("tr")
                ground_row = None
                result_row = None

                for row in rows:
                    cells = row.select("th, td")
                    if not cells:
                        continue
                    first_cell = cells[0].get_text(strip=True).lower()

                    if first_cell in ('ground', 'venue', 'h/a', 'home/away'):
                        ground_row = [c.get_text(strip=True).upper() for c in cells[1:]]
                    elif first_cell == 'result':
                        result_row = [c.get_text(strip=True).upper() for c in cells[1:]]
                    # else: skip 'round' and other rows

                if not ground_row or not result_row:
                    continue

                # Ensure same length
                n = min(len(ground_row), len(result_row))
                ground_row = ground_row[:n]
                result_row = result_row[:n]

                if n < 3:
                    continue

                # Split by home/away and get last 5 of each
                home_results = []
                away_results = []
                all_results = []

                for g, r in zip(ground_row, result_row):
                    if r in ('W', 'D', 'L'):
                        all_results.append(r)
                        if g == 'H':
                            home_results.append(r)
                        elif g == 'A':
                            away_results.append(r)

                if all_results:
                    return (
                        home_results[-5:] if home_results else [],
                        away_results[-5:] if away_results else [],
                        all_results[-5:] if all_results else [],
                    )
        except Exception:
            pass
        return [], [], []
