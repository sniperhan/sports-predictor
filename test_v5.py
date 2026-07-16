"""Test data_fetcher with season page results by round."""
from data_fetcher import DataFetcher
import time

fetcher = DataFetcher()

tests = [
    ("Arsenal", "Chelsea", "Premier League"),
    ("Manchester City", "Liverpool", "Premier League"),
    ("Bayern Munich", "Borussia Dortmund", "Bundesliga"),
    ("Real Madrid", "Barcelona", "La Liga"),
]

for home, away, league in tests:
    print(f"\n{'='*60}")
    print(f"{home} vs {away} ({league})")
    t0 = time.time()
    data = fetcher.search_team_data(home, away, league, True)
    elapsed = time.time() - t0
    print(f"  Time: {elapsed:.1f}s")
    print(f"  Position: {data.league_position}/{data.total_teams}")
    print(f"  Points: {data.league_points}")
    print(f"  GF/GA: {data.goals_for}/{data.goals_against}")
    print(f"  Recent Form (actual): {data.recent_form}")
    print(f"  Home Form: {data.home_form}")
    print(f"  Away Form: {data.away_form}")

fetcher.close()
