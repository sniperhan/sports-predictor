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


# Chinese → English team name mapping for Wikipedia search
TEAM_NAME_MAP = {
    # 挪超 (Eliteserien)
    "瓦勒伦加": "Vålerenga", "瓦勒伦加足球俱乐部": "Vålerenga",
    "奥勒松": "Aalesund", "奥勒松足球俱乐部": "Aalesund",
    "博德闪耀": "Bodø/Glimt", "博多格林特": "Bodø/Glimt",
    "罗森博格": "Rosenborg", "罗森博格足球俱乐部": "Rosenborg",
    "莫尔德": "Molde", "莫尔德足球俱乐部": "Molde",
    "维京": "Viking FK", "维京足球俱乐部": "Viking FK",
    "布兰": "SK Brann", "布兰足球俱乐部": "SK Brann",
    "利勒斯特伦": "Lillestrøm", "利勒斯特罗姆": "Lillestrøm",
    "奥德": "Odds BK", "奥德足球俱乐部": "Odds BK",
    "桑德菲杰": "Sandefjord", "桑讷菲尤尔": "Sandefjord",
    "斯托姆加斯特": "Strømsgodset", "斯特罗姆加斯特": "Strømsgodset",
    "萨普斯堡": "Sarpsborg 08", "萨普斯堡08": "Sarpsborg 08",
    "特罗姆瑟": "Tromsø", "特罗姆瑟足球俱乐部": "Tromsø",
    "克里斯蒂安松": "Kristiansund", "克里斯蒂安松BK": "Kristiansund",
    "海于格松": "Haugesund", "海于格松足球俱乐部": "Haugesund",
    "腓特烈斯塔": "Fredrikstad", "腓特烈斯塔FK": "Fredrikstad",
    "KFUM奥斯陆": "KFUM Oslo", "奥斯陆KFUM": "KFUM Oslo",

    # 英超 (Premier League)
    "阿森纳": "Arsenal", "阿仙奴": "Arsenal",
    "切尔西": "Chelsea", "车路士": "Chelsea",
    "曼联": "Manchester United", "曼彻斯特联": "Manchester United",
    "利物浦": "Liverpool",
    "曼城": "Manchester City", "曼彻斯特城": "Manchester City",
    "热刺": "Tottenham Hotspur", "托特纳姆热刺": "Tottenham Hotspur",
    "纽卡斯尔": "Newcastle United", "纽卡斯尔联": "Newcastle United",
    "布莱顿": "Brighton & Hove Albion",
    "阿斯顿维拉": "Aston Villa", "维拉": "Aston Villa",
    "西汉姆联": "West Ham United", "西汉姆": "West Ham United",
    "埃弗顿": "Everton",
    "狼队": "Wolverhampton Wanderers", "狼": "Wolverhampton Wanderers",
    "水晶宫": "Crystal Palace",
    "富勒姆": "Fulham",
    "伯恩茅斯": "AFC Bournemouth", "伯恩茅斯足球俱乐部": "AFC Bournemouth",
    "诺丁汉森林": "Nottingham Forest",
    "布伦特福德": "Brentford",
    "南安普敦": "Southampton", "南安普顿": "Southampton",
    "莱斯特城": "Leicester City", "莱切斯特": "Leicester City",
    "伊普斯维奇": "Ipswich Town",
    "利兹联": "Leeds United",

    # 西甲 (La Liga)
    "巴塞罗那": "FC Barcelona", "巴萨": "FC Barcelona",
    "皇家马德里": "Real Madrid", "皇马": "Real Madrid",
    "马德里竞技": "Atlético Madrid", "马竞": "Atlético Madrid",
    "塞维利亚": "Sevilla",
    "瓦伦西亚": "Valencia", "巴伦西亚": "Valencia",
    "比利亚雷亚尔": "Villarreal",
    "皇家社会": "Real Sociedad",
    "毕尔巴鄂竞技": "Athletic Bilbao", "毕尔巴鄂": "Athletic Bilbao",
    "皇家贝蒂斯": "Real Betis", "贝蒂斯": "Real Betis",
    "赫罗纳": "Girona",
    "奥萨苏纳": "Osasuna",
    "塞尔塔": "Celta de Vigo",
    "西班牙人": "RCD Espanyol",
    "赫塔费": "Getafe", "赫塔菲": "Getafe",
    "马略卡": "RCD Mallorca", "马洛卡": "RCD Mallorca",
    "阿拉维斯": "Alavés",
    "拉斯帕尔马斯": "UD Las Palmas",
    "莱加内斯": "CD Leganés",
    "巴列卡诺": "Rayo Vallecano",

    # 意甲 (Serie A)
    "尤文图斯": "Juventus",
    "AC米兰": "AC Milan", "米兰": "AC Milan",
    "国际米兰": "Inter Milan", "国米": "Inter Milan",
    "那不勒斯": "Napoli", "拿坡里": "Napoli",
    "罗马": "AS Roma",
    "拉齐奥": "Lazio",
    "亚特兰大": "Atalanta",
    "佛罗伦萨": "Fiorentina",
    "都灵": "Torino",
    "博洛尼亚": "Bologna",
    "热那亚": "Genoa",
    "乌迪内斯": "Udinese",
    "帕尔马": "Parma",
    "科莫": "Como",
    "蒙扎": "Monza",
    "维罗纳": "Hellas Verona",
    "莱切": "US Lecce",
    "卡利亚里": "Cagliari",
    "恩波利": "Empoli",
    "威尼斯": "Venezia",

    # 德甲 (Bundesliga)
    "拜仁慕尼黑": "Bayern Munich", "拜仁": "Bayern Munich",
    "多特蒙德": "Borussia Dortmund",
    "莱比锡": "RB Leipzig", "RB莱比锡": "RB Leipzig",
    "勒沃库森": "Bayer Leverkusen",
    "法兰克福": "Eintracht Frankfurt",
    "斯图加特": "VfB Stuttgart",
    "沃尔夫斯堡": "VfL Wolfsburg",
    "门兴格拉德巴赫": "Borussia Mönchengladbach", "门兴": "Borussia Mönchengladbach",
    "弗赖堡": "SC Freiburg",
    "霍芬海姆": "TSG Hoffenheim",
    "柏林联合": "Union Berlin",
    "奥格斯堡": "FC Augsburg",
    "云达不来梅": "Werder Bremen", "不来梅": "Werder Bremen",
    "海登海姆": "1. FC Heidenheim",
    "美因茨": "Mainz 05",
    "圣保利": "FC St. Pauli",
    "基尔": "Holstein Kiel",
    "波鸿": "VfL Bochum",

    # 法甲 (Ligue 1)
    "巴黎圣日耳曼": "Paris Saint-Germain", "巴黎": "Paris Saint-Germain",
    "马赛": "Olympique de Marseille",
    "里昂": "Olympique Lyonnais",
    "摩纳哥": "AS Monaco",
    "里尔": "Lille OSC",
    "尼斯": "OGC Nice",
    "朗斯": "RC Lens",
    "雷恩": "Stade Rennais",
    "斯特拉斯堡": "RC Strasbourg",
    "南特": "FC Nantes",
    "蒙彼利埃": "Montpellier HSC",
    "图卢兹": "Toulouse FC",
    "兰斯": "Stade de Reims",
    "布雷斯特": "Stade Brestois",
    "勒阿弗尔": "Le Havre",
    "欧塞尔": "AJ Auxerre",
    "圣埃蒂安": "AS Saint-Étienne",
    "昂热": "Angers SCO",

    # 巴甲 (Campeonato Brasileiro)
    "弗拉门戈": "Flamengo",
    "帕尔梅拉斯": "Palmeiras",
    "桑托斯": "Santos FC",
    "科林蒂安": "Corinthians",
    "圣保罗": "São Paulo FC",
    "格雷米奥": "Grêmio",
    "巴西国际": "Internacional",
    "米内罗竞技": "Atlético Mineiro",
    "弗鲁米嫩塞": "Fluminense",
    "克鲁塞罗": "Cruzeiro",
    "博塔弗戈": "Botafogo",
    "布拉甘蒂诺红牛": "Red Bull Bragantino", "红牛布拉甘蒂诺": "Red Bull Bragantino",
    "巴伊亚": "Bahia",
    "福塔莱萨": "Fortaleza",
    "塞阿拉": "Ceará",
    "瓦斯科达伽马": "Vasco da Gama",
    "库亚巴": "Cuiabá",
    "戈亚尼恩斯竞技": "Atlético Goianiense",
    "米内罗美洲": "América Mineiro",

    # 美职联 (MLS)
    "洛杉矶银河": "LA Galaxy",
    "洛杉矶FC": "Los Angeles FC",
    "迈阿密国际": "Inter Miami",
    "纽约城FC": "New York City FC", "纽约城": "New York City FC",
    "亚特兰大联": "Atlanta United",
    "西雅图海湾人": "Seattle Sounders FC",
    "哥伦布机员": "Columbus Crew",
    "辛辛那提": "FC Cincinnati",
    "波特兰伐木者": "Portland Timbers",
    "纳什维尔": "Nashville SC",
    "奥兰多城": "Orlando City SC",
    "费城联合": "Philadelphia Union",
    "新英格兰革命": "New England Revolution",
    "多伦多FC": "Toronto FC",
    "芝加哥火焰": "Chicago Fire FC",
    "休斯顿迪纳摩": "Houston Dynamo FC",
    "达拉斯FC": "FC Dallas",
    "皇家盐湖城": "Real Salt Lake",
    "温哥华白帽": "Vancouver Whitecaps FC",
    "奥斯汀FC": "Austin FC",
    "夏洛特FC": "Charlotte FC",
    "圣路易斯城": "St. Louis City SC",

    # 日职 (J League)
    "横滨水手": "Yokohama F. Marinos",
    "川崎前锋": "Kawasaki Frontale",
    "浦和红钻": "Urawa Red Diamonds",
    "鹿岛鹿角": "Kashima Antlers",
    "大阪钢巴": "Gamba Osaka",
    "广岛三箭": "Sanfrecce Hiroshima",
    "名古屋鲸八": "Nagoya Grampus",
    "东京FC": "FC Tokyo",
    "柏太阳神": "Kashiwa Reysol",
    "神户胜利船": "Vissel Kobe",
    "清水心跳": "Shimizu S-Pulse",
    "大阪樱花": "Cerezo Osaka",
    "札幌冈萨多": "Hokkaido Consadole Sapporo",
    "横滨FC": "Yokohama FC",
    "湘南比马": "Shonan Bellmare",
    "磐田喜悦": "Júbilo Iwata",
    "京都不死鸟": "Kyoto Sanga FC",
    "新潟天鹅": "Albirex Niigata",
    "福冈黄蜂": "Avispa Fukuoka",
    "鸟栖砂岩": "Sagan Tosu",

    # 韩K联 (K League)
    "全北现代": "Jeonbuk Hyundai Motors",
    "蔚山现代": "Ulsan Hyundai",
    "首尔FC": "FC Seoul",
    "浦项制铁": "Pohang Steelers",
    "水原三星": "Suwon Samsung Bluewings",
    "大邱FC": "Daegu FC",
    "仁川联": "Incheon United",
    "光州FC": "Gwangju FC",
    "江原FC": "Gangwon FC",
    "济州联": "Jeju United",
    "大田市民": "Daejeon Hana Citizen",
    "水原FC": "Suwon FC",

    # 欧冠/欧联 常用
    "阿贾克斯": "AFC Ajax",
    "埃因霍温": "PSV Eindhoven",
    "费耶诺德": "Feyenoord",
    "本菲卡": "Benfica",
    "波尔图": "FC Porto",
    "葡萄牙体育": "Sporting CP",
    "加拉塔萨雷": "Galatasaray",
    "费内巴切": "Fenerbahçe",
    "贝西克塔斯": "Beşiktaş",
    "顿涅茨克矿工": "Shakhtar Donetsk",
    "凯尔特人": "Celtic",
    "格拉斯哥流浪者": "Rangers",
    "萨尔茨堡红牛": "Red Bull Salzburg",
    "布鲁日": "Club Brugge",
    "安德莱赫特": "Anderlecht",
    "哥本哈根": "FC Copenhagen",
    "奥林匹亚科斯": "Olympiacos",
    "帕纳辛纳科斯": "Panathinaikos",
    "费伦茨瓦罗斯": "Ferencváros",
    "贝尔格莱德红星": "Red Star Belgrade",
    "萨格勒布迪纳摩": "Dinamo Zagreb",
    "布拉格斯拉维亚": "Slavia Prague",
    "巴塞尔": "FC Basel",
    "年轻人": "Young Boys",
    "马尔默": "Malmö FF",
    "罗森博格": "Rosenborg",
    "莫尔德": "Molde",
}

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
        self._league_table_cache = {}
        self._season_page_cache = {}

    def close(self):
        pass

    def _make_session(self):
        s = requests.Session()
        s.headers["User-Agent"] = self.USER_AGENT
        return s

    # ─── Main Entry Point ───────────────────────────────────

    def _translate_name(self, name: str) -> str:
        """Translate Chinese team name to English for Wikipedia search."""
        # Direct mapping lookup
        if name in TEAM_NAME_MAP:
            return TEAM_NAME_MAP[name]
        # Try case-insensitive
        name_lower = name.lower()
        for cn, en in TEAM_NAME_MAP.items():
            if cn.lower() == name_lower:
                return en
        return name  # Return as-is if no mapping found

    def search_team_data(
        self, team_name: str, opponent: str, league: str, is_home: bool
    ) -> TeamData:
        """Fetch comprehensive team data from Wikipedia."""
        # Translate Chinese names to English for Wikipedia search
        search_name = self._translate_name(team_name)
        search_opponent = self._translate_name(opponent)

        data = TeamData(name=team_name)
        steps = {}  # Track success/failure of each step
        if search_name != team_name:
            steps['translated'] = f'{team_name}->{search_name}'
        season_url = None

        # Task 1: Team infobox
        try:
            result = self._fetch_team_page_raw(search_name, league)
            if result and any(v is not None for v in result):
                pos, total, s_url = result
                if pos:
                    data.league_position = pos
                    steps['pos'] = str(pos)
                if total:
                    data.total_teams = total
                    steps['total'] = str(total)
                if s_url:
                    season_url = s_url
                    steps['season_url'] = 'found'
                else:
                    steps['season_url'] = 'none'
            else:
                steps['team_page'] = 'no_result'
        except Exception as e:
            steps['team_page'] = f'error: {str(e)[:50]}'

        # Task 2: League table
        if league in LEAGUE_TABLES:
            try:
                result = self._fetch_league_table_data_raw(search_name, league)
                if result:
                    pts, gf, ga, matches, wins, draws, losses = result
                    if pts:
                        data.league_points = pts
                        steps['pts'] = str(pts)
                    if gf is not None and ga is not None and matches > 0:
                        data.goals_for = round(gf / matches, 1)
                        data.goals_against = round(ga / matches, 1)
                        steps['goals'] = f'{data.goals_for}/{data.goals_against}'
                    if wins or draws or losses:
                        total_games = wins + draws + losses
                        if total_games >= 5:
                            steps['wlr'] = f'{wins}W{draws}D{losses}L'
                            n = 5
                            w5 = max(0, min(n, round(wins / total_games * n)))
                            d5 = max(0, min(n - w5, round(draws / total_games * n)))
                            l5 = n - w5 - d5
                            data.recent_form = ['W'] * w5 + ['D'] * d5 + ['L'] * l5
                else:
                    steps['league_table'] = 'no_result'
            except Exception as e:
                steps['league_table'] = f'error: {e}'
        else:
            steps['league_table'] = f'no_mapping for {league}'

        # Task 3: H2H data
        if is_home:
            try:
                result = self._fetch_h2h_data(search_name, search_opponent)
                if result:
                    w, d, l = result
                    if w > 0 or d > 0 or l > 0:
                        data.h2h_wins = w
                        data.h2h_draws = d
                        data.h2h_losses = l
                        steps['h2h'] = f'{w}W{d}D{l}L'
                    else:
                        steps['h2h'] = 'all_zero'
                else:
                    steps['h2h'] = 'no_result'
            except Exception as e:
                steps['h2h'] = f'error: {e}'

        # Task 4: Season page for home/away form
        if season_url and not data.home_form:
            try:
                season_html = self._fetch_season_page(season_url, team_name)
                if season_html:
                    home_form, away_form, recent_form = self._parse_results_by_round(season_html)
                    if home_form:
                        data.home_form = home_form
                        steps['home_form'] = ','.join(home_form[-5:])
                    if away_form:
                        data.away_form = away_form
                        steps['away_form'] = ','.join(away_form[-5:])
                    if recent_form:
                        data.recent_form = recent_form
                        steps['recent_form'] = ','.join(recent_form[-5:])
                else:
                    steps['season_html'] = 'empty'
            except Exception as e:
                steps['season_page'] = f'error: {e}'

        data.in_season = True
        data._steps = steps
        return data

    def _fetch_team_page_raw(self, team_name: str, user_league: str) -> tuple:
        """Fetch team page - raises exceptions instead of swallowing them."""
        html = self._fetch_wikipedia_page(team_name)
        if not html:
            return None
        return self._parse_wikipedia_infobox(html, user_league)

    def _fetch_league_table_data_raw(self, team_name: str, league: str) -> tuple:
        """Fetch league table - raises exceptions instead of swallowing them."""
        if league not in LEAGUE_TABLES:
            return None
        if league in self._league_table_cache:
            table_html = self._league_table_cache[league]
        else:
            page_name = LEAGUE_TABLES[league]
            url = f"{self.WIKI_BASE}{page_name}"
            s = self._make_session()
            resp = s.get(url, timeout=25)
            if resp.status_code != 200:
                return None
            table_html = resp.text
            self._league_table_cache[league] = table_html
        return self._parse_league_table(table_html, team_name)

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
        """Search Wikipedia for a team page and return its HTML.
        Returns None if page not found, raises on network errors."""
        s = self._make_session()
        params = {
            "action": "query",
            "list": "search",
            "srsearch": f"{team_name} football club",
            "format": "json",
            "srlimit": 3,
        }
        resp = s.get(self.WIKI_API, params=params, timeout=20)
        if resp.status_code != 200:
            return None
        results = resp.json().get("query", {}).get("search", [])
        if not results:
            return None
        page_title = results[0]["title"]
        page_url = f"{self.WIKI_BASE}{quote_plus(page_title.replace(' ', '_'))}"
        resp = s.get(page_url, timeout=25)
        if resp.status_code == 200:
            return resp.text
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
                resp = s.get(url, timeout=25)
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
            resp = s.get(url, timeout=25)
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

    # ─── Task 4: H2H from Rivalry Pages ─────────────────────

    def _fetch_h2h_data(self, team1: str, team2: str) -> tuple:
        """Fetch head-to-head data from Wikipedia rivalry pages.
        Returns (h2h_wins, h2h_draws, h2h_losses) from team1's perspective.
        """
        try:
            html = self._search_rivalry_page(team1, team2)
            if not html:
                html = self._search_rivalry_page(team2, team1)
            if not html:
                return 0, 0, 0
            return self._parse_rivalry_page(html, team1, team2)
        except Exception:
            return 0, 0, 0

    def _search_rivalry_page(self, team1: str, team2: str) -> Optional[str]:
        """Search Wikipedia for a rivalry page between two teams."""
        try:
            s = self._make_session()
            search_terms = [
                f"{team1} {team2} rivalry",
                f"{team1} F.C. {team2} F.C. rivalry",
            ]

            def is_good_match(title_lower, t1_parts, t2_parts):
                """Check if a Wikipedia page title matches our rivalry criteria."""
                t1_match = any(p in title_lower for p in t1_parts if len(p) > 2)
                t2_match = any(p in title_lower for p in t2_parts if len(p) > 2)
                is_rivalry = any(kw in title_lower for kw in [
                    "rivalry", "rival", "derby", "head-to-head", "h2h",
                    "head to head", "klassiker", "clásico", "clasico", "derby"
                ])
                is_football = any(kw in title_lower for kw in [
                    "f.c.", "fc ", "football", "soccer", "premier league",
                    "klassiker", "clásico", "clasico", "derby", "madrid",
                    "barcelona", "bayern", "dortmund", "borussia", "munich"
                ])
                return t1_match and t2_match and is_rivalry and is_football

            t1_parts_all = [p for p in team1.lower().split() if len(p) > 2]
            t2_parts_all = [p for p in team2.lower().split() if len(p) > 2]

            for term in search_terms:
                params = {
                    "action": "query", "list": "search",
                    "srsearch": term, "format": "json", "srlimit": 5,
                }
                resp = s.get(self.WIKI_API, params=params, timeout=25)
                if resp.status_code != 200:
                    continue
                results = resp.json().get("query", {}).get("search", [])

                # Pass 1: strict match
                for r in results:
                    title = r.get("title", "")
                    if is_good_match(title.lower(), t1_parts_all, t2_parts_all):
                        page_url = self._wiki_url(title)
                        resp2 = s.get(page_url, timeout=25)
                        if resp2.status_code == 200:
                            return resp2.text

                # Pass 2: lenient - take first result that is rivalry/football
                for r in results:
                    title_lower = r.get("title", "").lower()
                    is_rivalry = any(kw in title_lower for kw in [
                        "rivalry", "rival", "derby", "head-to-head",
                        "klassiker", "clásico", "clasico"
                    ])
                    if is_rivalry:
                        page_url = self._wiki_url(r["title"])
                        resp2 = s.get(page_url, timeout=25)
                        if resp2.status_code == 200:
                            return resp2.text

            return None
        except Exception:
            return None

    def _wiki_url(self, title: str) -> str:
        return f"{self.WIKI_BASE}{quote_plus(title.replace(' ', '_'))}"

    def _parse_rivalry_page(self, html: str, team1: str, team2: str) -> tuple:
        """Parse a Wikipedia rivalry page for H2H statistics.

        Uses match results tables with color-coded scores:
        - Red background (#FF0000) = home team won
        - Blue background = away team won
        - Silver/gray background = draw

        Tables are split by venue, so we can determine W/D/L from team1's perspective.
        Returns (h2h_wins, h2h_draws, h2h_losses) from team1's perspective.
        """
        try:
            soup = BeautifulSoup(html, "html.parser")
            t1_lower = team1.lower()

            # Strategy 1: Parse the "Head-to-head" stats table's Total row
            # The table headers tell us which column is which team's wins
            for table in soup.select("table.wikitable"):
                headers = []
                header_row = table.select_one("tr")
                if header_row:
                    headers = [h.get_text(strip=True).lower() for h in header_row.select("th, td")]

                # Check if this looks like a H2H stats table (has competition + win/draw columns)
                has_wins_col = any("win" in h for h in headers)
                has_draws_col = any("draw" in h for h in headers)
                if not (has_wins_col or has_draws_col):
                    continue

                # Find the Total row
                for row in table.select("tr"):
                    cells = row.select("th, td")
                    if not cells:
                        continue
                    first_cell = cells[0].get_text(strip=True).lower()
                    if "total" not in first_cell:
                        continue

                    # Map columns to values
                    vals = []
                    for c in cells:
                        try:
                            vals.append(int(re.sub(r'[^\d]', '', c.get_text(strip=True))))
                        except ValueError:
                            vals.append(0)

                    t1_win_idx = None
                    t2_win_idx = None
                    draw_idx = None

                    for i, h in enumerate(headers):
                        if i >= len(vals):
                            break
                        h_clean = re.sub(r'[^a-z\s]', '', h).strip()
                        if "win" in h_clean:
                            t1_parts = [p for p in team1.lower().split() if len(p) > 2]
                            t2_parts = [p for p in team2.lower().split() if len(p) > 2]
                            if any(p in h_clean for p in t1_parts):
                                t1_win_idx = i
                            elif any(p in h_clean for p in t2_parts):
                                t2_win_idx = i
                        elif "draw" in h_clean:
                            draw_idx = i

                    if t1_win_idx is not None and t2_win_idx is not None:
                        w = vals[t1_win_idx] if t1_win_idx < len(vals) else 0
                        d = vals[draw_idx] if draw_idx is not None and draw_idx < len(vals) else 0
                        l = vals[t2_win_idx] if t2_win_idx < len(vals) else 0
                        if w > 0 or l > 0:
                            return w, d, l

                    break  # Only check first matching table

            # Strategy 2: Parse match results from color-coded score cells
            all_matches = self._parse_rivalry_matches(soup, team1, team2)
            if len(all_matches) >= 3:
                recent = all_matches[-10:]
                w = sum(1 for m in recent if m["result"] == "W")
                d = sum(1 for m in recent if m["result"] == "D")
                l = sum(1 for m in recent if m["result"] == "L")
                if w > 0 or l > 0:
                    return w, d, l

            return 0, 0, 0
        except Exception:
            return 0, 0, 0

    def _parse_rivalry_matches(self, soup, team1: str, team2: str) -> list:
        """Parse match results from rivalry page match tables.

        Tables are split by venue. Score cells use color coding:
        - #FF0000 (red) = home team won
        - blue = away team won
        - silver/gray = draw

        Returns list of dicts with 'result' key ('W', 'D', 'L') from team1's perspective.
        """
        matches = []
        t1_lower = team1.lower()
        t2_lower = team2.lower()

        for table in soup.select("table.wikitable"):
            caption = table.select_one("caption")
            caption_text = caption.get_text(strip=True).lower() if caption else ""

            # Determine which team is "home" for this table
            t1_is_home = any(p in caption_text for p in t1_lower.split() if len(p) > 2)
            t2_is_home = any(p in caption_text for p in t2_lower.split() if len(p) > 2)

            if not t1_is_home and not t2_is_home:
                continue

            for row in table.select("tr"):
                cells = row.select("th, td")
                if len(cells) < 2:
                    continue

                first_text = cells[0].get_text(strip=True)
                # Skip header rows and empty rows
                if first_text.lower() in ("date", "score", "competition", ""):
                    continue
                if not re.search(r'\d{4}', first_text):  # Must contain a year
                    continue

                # Get the score cell
                score_cell = cells[1] if len(cells) > 1 else None
                if not score_cell:
                    continue

                score_text = score_cell.get_text(strip=True)
                if not re.search(r'\d+[–\-]\d+', score_text):
                    continue

                # Determine result from cell color
                style = score_cell.get("style", "") if score_cell.name == "td" else ""
                style_lower = style.lower()

                if "#ff0000" in style_lower or "red" in style_lower or "background:red" in style_lower:
                    # Home team won
                    result = "W" if t1_is_home else "L"
                elif "blue" in style_lower:
                    # Away team won
                    result = "L" if t1_is_home else "W"
                elif "silver" in style_lower or "gray" in style_lower or "grey" in style_lower:
                    result = "D"
                else:
                    # Fallback: parse score directly
                    score_match = re.search(r'(\d+)[–\-](\d+)', score_text)
                    if score_match:
                        home_goals = int(score_match.group(1))
                        away_goals = int(score_match.group(2))
                        if t1_is_home:
                            result = "W" if home_goals > away_goals else ("D" if home_goals == away_goals else "L")
                        else:
                            result = "L" if home_goals > away_goals else ("D" if home_goals == away_goals else "W")
                    else:
                        continue

                matches.append({"result": result})

        # Sort by recency (tables are in chronological order, last matches are at the bottom)
        return matches
