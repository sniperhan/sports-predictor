"""
Data Fetcher - Web search and data extraction for sports match prediction.

Uses DuckDuckGo search + regex parsing to gather pre-match data.
Synchronous implementation with requests library for compatibility.
"""

import re
import time
from datetime import datetime
from typing import Optional

import requests
from bs4 import BeautifulSoup

from predictor import TeamData


class DataFetcher:
    """Fetch and parse sports data from the web."""

    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    )

    def __init__(self):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = self.USER_AGENT

    def close(self):
        self.session.close()

    def search_team_data(
        self, team_name: str, opponent: str, league: str, is_home: bool
    ) -> TeamData:
        """Search for team data using multiple queries."""
        data = TeamData(name=team_name)
        year = str(datetime.now().year)

        queries = [
            f"{team_name} {league} {year} 排名 积分 战绩",
            f"{team_name} 近期战绩 {league} {year}",
            f"{team_name} vs {opponent} 历史交锋",
            f"{team_name} 伤病 停赛 {league} {year}",
        ]

        all_text = ""
        for query in queries:
            try:
                text = self._ddg_search(query)
                if text:
                    all_text += text + "\n"
                time.sleep(0.3)  # Rate limiting
            except Exception:
                pass

        if not all_text:
            try:
                all_text = self._ddg_search(
                    f"{team_name} football {league} {year} season record form"
                )
            except Exception:
                pass

        if all_text:
            self._parse_team_data(all_text, data, is_home)

        return data

    def _ddg_search(self, query: str) -> str:
        """Search using DuckDuckGo and return concatenated text."""
        # Try DDGS library first
        try:
            from duckduckgo_search import DDGS
            results = list(DDGS().text(query, max_results=6))
            return " ".join(r.get("body", "") for r in results)
        except Exception:
            pass

        # Fallback: direct HTTP request to DuckDuckGo HTML
        try:
            url = f"https://html.duckduckgo.com/html/?q={query}"
            resp = self.session.get(url, timeout=15)
            soup = BeautifulSoup(resp.text, "html.parser")
            snippets = soup.select(".result__snippet")
            return " ".join(s.get_text() for s in snippets)
        except Exception:
            return ""

    def _parse_team_data(self, text: str, data: TeamData, is_home: bool):
        """Parse structured data from search result text."""
        # Parse league position
        data.league_position = self._extract_position(text)

        # Parse points
        data.league_points = self._extract_points(text)

        # Parse recent form
        data.recent_form = self._extract_form(text)
        if is_home:
            data.home_form = self._extract_home_form(text)
        else:
            data.away_form = self._extract_away_form(text)

        # Parse goals data
        gf, ga = self._extract_goals(text)
        data.goals_for = gf
        data.goals_against = ga

        # Parse H2H
        h2h_wins, h2h_draws, h2h_losses = self._extract_h2h(text)
        data.h2h_wins = h2h_wins
        data.h2h_draws = h2h_draws
        data.h2h_losses = h2h_losses

        # Parse injuries
        data.key_injuries = self._extract_injuries(text)
        data.key_suspensions = self._extract_suspensions(text)

        # Parse season status
        data.in_season = self._check_in_season(text)

        # Parse market value
        data.market_value = self._extract_market_value(text)

        # Parse UEFA coefficient
        data.uefa_coefficient = self._extract_uefa_coefficient(text)

    def _extract_position(self, text: str) -> Optional[int]:
        patterns = [
            r'排名(?:第)?\s*(\d+)',
            r'第\s*(\d+)\s*名',
            r'第\s*(\d+)\s*位',
            r'position\s*(\d+)',
            r'(\d+)(?:st|nd|rd|th)\s+place',
        ]
        for p in patterns:
            m = re.search(p, text, re.IGNORECASE)
            if m:
                pos = int(m.group(1))
                if pos <= 50:
                    return pos
        return None

    def _extract_points(self, text: str) -> Optional[int]:
        patterns = [r'(\d+)\s*分', r'(\d+)\s*points', r'(\d+)\s*pts']
        for p in patterns:
            m = re.search(p, text, re.IGNORECASE)
            if m:
                pts = int(m.group(1))
                if pts <= 120:
                    return pts
        return None

    def _extract_form(self, text: str) -> list[str]:
        form = []
        cn_pattern = r'(\d+)\s*胜\s*(\d+)\s*平\s*(\d+)\s*负'
        m = re.search(cn_pattern, text)
        if m:
            wins, draws, losses = int(m.group(1)), int(m.group(2)), int(m.group(3))
            form = ['W'] * wins + ['D'] * draws + ['L'] * losses
            return form[:10]

        eng_matches = re.findall(r'\b([WDL])\b', text[:500])
        if len(eng_matches) >= 3:
            return eng_matches[:10]

        cn_single = re.findall(r'[胜平负]', text[:300])
        mapping = {'胜': 'W', '平': 'D', '负': 'L'}
        return [mapping.get(r, r) for r in cn_single[:10]]

    def _extract_home_form(self, text: str) -> list[str]:
        # Try to find home-specific form
        patterns = [
            r'主场[：:]\s*(\d+)\s*胜\s*(\d+)\s*平\s*(\d+)\s*负',
            r'主场\s*(\d+)\s*胜\s*(\d+)\s*平\s*(\d+)\s*负',
            r'home\s*(\d+)\s*W\s*(\d+)\s*D\s*(\d+)\s*L',
        ]
        for p in patterns:
            m = re.search(p, text, re.IGNORECASE)
            if m:
                w, d, l = int(m.group(1)), int(m.group(2)), int(m.group(3))
                return ['W'] * w + ['D'] * d + ['L'] * l
        return []

    def _extract_away_form(self, text: str) -> list[str]:
        patterns = [
            r'客场[：:]\s*(\d+)\s*胜\s*(\d+)\s*平\s*(\d+)\s*负',
            r'客场\s*(\d+)\s*胜\s*(\d+)\s*平\s*(\d+)\s*负',
            r'away\s*(\d+)\s*W\s*(\d+)\s*D\s*(\d+)\s*L',
        ]
        for p in patterns:
            m = re.search(p, text, re.IGNORECASE)
            if m:
                w, d, l = int(m.group(1)), int(m.group(2)), int(m.group(3))
                return ['W'] * w + ['D'] * d + ['L'] * l
        return []

    def _extract_goals(self, text: str) -> tuple:
        gf, ga = None, None
        gf_m = re.search(r'场均进[球]?\s*(\d+\.?\d*)', text)
        ga_m = re.search(r'场均(?:失|丢)[球]?\s*(\d+\.?\d*)', text)
        if gf_m:
            gf = float(gf_m.group(1))
        if ga_m:
            ga = float(ga_m.group(1))

        if not gf:
            m = re.search(r'(?:进|打入|攻入)\s*(\d+)\s*球.*?(\d+)\s*场', text)
            if m:
                gf = float(m.group(1)) / float(m.group(2))
        if not ga:
            m = re.search(r'(?:失|丢)\s*(\d+)\s*球.*?(\d+)\s*场', text)
            if m:
                ga = float(m.group(1)) / float(m.group(2))
        return gf, ga

    def _extract_h2h(self, text: str) -> tuple:
        wins = draws = losses = 0
        m = re.search(r'(\d+)\s*胜\s*(\d+)\s*平\s*(\d+)\s*负', text)
        if m:
            wins, draws, losses = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return wins, draws, losses

    def _extract_injuries(self, text: str) -> list[str]:
        injuries = []
        keywords = ['受伤', '伤病', '缺阵', '缺席', 'injury', 'injured']
        for kw in keywords:
            idx = text.lower().find(kw.lower())
            if idx >= 0:
                snippet = text[max(0, idx - 50):idx + 100]
                names = re.findall(r'[一-鿿]{2,4}(?:·[一-鿿]{1,4})?', snippet)
                for name in names[:3]:
                    if name not in ['因为', '由于', '目前', '已经', '球队', '赛季']:
                        injuries.append(name)
        return injuries[:3]

    def _extract_suspensions(self, text: str) -> list[str]:
        suspensions = []
        keywords = ['停赛', '红牌', '黄牌累积', 'suspended', 'suspension']
        for kw in keywords:
            idx = text.lower().find(kw.lower())
            if idx >= 0:
                snippet = text[max(0, idx - 50):idx + 100]
                names = re.findall(r'[一-鿿]{2,4}(?:·[一-鿿]{1,4})?', snippet)
                for name in names[:2]:
                    if name not in ['因为', '由于', '目前']:
                        suspensions.append(name)
        return suspensions[:2]

    def _extract_uefa_coefficient(self, text: str) -> Optional[float]:
        m = re.search(
            r'(?:欧(?:战|足联)|UEFA)\s*(?:系数|coefficient|排名|rank)[:\s]*(\d+\.?\d*)',
            text, re.IGNORECASE
        )
        if m:
            return float(m.group(1))
        return None

    def _check_in_season(self, text: str) -> bool:
        off_season = ['休赛期', '赛季结束', '联赛结束', 'offseason', 'season ended']
        for kw in off_season:
            if kw.lower() in text.lower():
                return False
        return True

    def _extract_market_value(self, text: str) -> Optional[float]:
        m = re.search(
            r'(?:身价|市值|market value)[:\s]*(\d+\.?\d*)\s*(?:亿|亿欧|€|M)',
            text, re.IGNORECASE
        )
        if m:
            val = float(m.group(1))
            if '亿' in text[m.start():m.end()]:
                return val * 100
            return val
        return None
