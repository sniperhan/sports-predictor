"""
Sports Betting Prediction System - FastAPI Backend

Serves frontend and provides analysis API endpoint.
Uses multi-dimensional analysis: league position, form, H2H, home/away,
injuries, match fitness, and data consistency scoring.
"""

import asyncio
import concurrent.futures
import traceback
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from predictor import PredictionEngine, TeamData
from data_fetcher import DataFetcher

# Thread pool for sync data fetching
executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)

app = FastAPI(title="Sports Prediction System", version="1.0.0")

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")


class MatchRequest(BaseModel):
    home_team: str
    away_team: str
    league: str
    match_date: Optional[str] = None
    handicap: Optional[str] = ""
    home_league_pos: Optional[int] = None
    away_league_pos: Optional[int] = None
    home_points: Optional[int] = None
    away_points: Optional[int] = None
    home_form: Optional[str] = None  # e.g. "W,D,L,W,W"
    away_form: Optional[str] = None
    home_home_form: Optional[str] = None
    away_away_form: Optional[str] = None
    home_goals_for: Optional[float] = None
    home_goals_against: Optional[float] = None
    away_goals_for: Optional[float] = None
    away_goals_against: Optional[float] = None
    h2h_wins_home: Optional[int] = 0
    h2h_draws: Optional[int] = 0
    h2h_wins_away: Optional[int] = 0
    home_injuries: Optional[str] = ""  # comma-separated
    away_injuries: Optional[str] = ""
    home_suspensions: Optional[str] = ""
    away_suspensions: Optional[str] = ""
    home_in_season: Optional[bool] = True
    away_in_season: Optional[bool] = True
    total_teams: Optional[int] = None
    home_market_value: Optional[float] = None
    away_market_value: Optional[float] = None
    home_uefa_coefficient: Optional[float] = None
    away_uefa_coefficient: Optional[float] = None
    home_odds_win: Optional[float] = None
    away_odds_win: Optional[float] = None
    odds_draw: Optional[float] = None


class PredictionResponse(BaseModel):
    home_team: str
    away_team: str
    win_prob: float
    draw_prob: float
    loss_prob: float
    recommended_bet: str
    recommended_bet_cn: str
    handicap_bet: str
    predicted_score: str
    confidence: int
    confidence_label: str
    key_factors: list[str]
    risk_factors: list[str]
    dimension_scores: dict
    data_consistency: str
    search_data_quality: str


@app.get("/")
async def root():
    return FileResponse("static/index.html")


@app.get("/api/debug")
async def debug_wikipedia():
    """Test Wikipedia connectivity from Render server."""
    import requests as req
    results = {}
    session = req.Session()
    session.headers["User-Agent"] = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    )

    # Test 1: Wikipedia API
    try:
        r = session.get("https://en.wikipedia.org/w/api.php", params={
            "action": "query", "list": "search",
            "srsearch": "Arsenal F.C.", "format": "json", "srlimit": 1
        }, timeout=15)
        results["wikipedia_api"] = f"HTTP {r.status_code}, {len(r.text)} bytes"
        if r.status_code == 200:
            data = r.json()
            results["wikipedia_api_parsed"] = str(data.get("query", {}).get("search", [[]])[0:1])[:150]
    except Exception as e:
        results["wikipedia_api"] = f"ERROR: {e}"

    # Test 2: Wikipedia main page
    try:
        r = session.get("https://en.wikipedia.org/wiki/Arsenal_F.C.", timeout=15)
        results["wikipedia_page"] = f"HTTP {r.status_code}, {len(r.text)} bytes"
    except Exception as e:
        results["wikipedia_page"] = f"ERROR: {e}"

    # Test 3: League table page
    try:
        r = session.get("https://en.wikipedia.org/wiki/2025%E2%80%9326_Premier_League", timeout=15)
        results["league_table"] = f"HTTP {r.status_code}, {len(r.text)} bytes"
    except Exception as e:
        results["league_table"] = f"ERROR: {e}"

    # Test 4: DNS resolution
    import socket
    try:
        ip = socket.gethostbyname("en.wikipedia.org")
        results["dns"] = f"en.wikipedia.org -> {ip}"
    except Exception as e:
        results["dns"] = f"ERROR: {e}"

    # Test 5: Try with urllib
    try:
        import urllib.request
        r2 = urllib.request.urlopen("https://en.wikipedia.org/wiki/Arsenal_F.C.", timeout=15)
        results["urllib_wikipedia"] = f"HTTP {r2.status}, {len(r2.read())} bytes"
    except Exception as e:
        results["urllib_wikipedia"] = f"ERROR: {e}"

    session.close()
    return results


def _format_steps(steps: dict) -> str:
    """Format diagnostic steps into a short string."""
    parts = []
    for k, v in steps.items():
        if v and v != 'none' and v != 'no_result' and v != 'empty' and v != 'all_zero':
            parts.append(f"{k}={v}")
    if not parts:
        # Show failed steps
        failed = [k for k, v in steps.items() if v in ('no_result', 'empty', 'all_zero', 'none') or str(v).startswith('error')]
        if failed:
            return f"failed: {','.join(failed)}"
        return f"steps: {len(steps)}"
    return '; '.join(parts[:4])


@app.post("/api/predict", response_model=PredictionResponse)
async def predict(req: MatchRequest):
    try:
        engine = PredictionEngine()

        # Build TeamData from user input
        home = TeamData(
            name=req.home_team,
            league_position=req.home_league_pos,
            league_points=req.home_points,
            total_teams=req.total_teams,
            goals_for=req.home_goals_for,
            goals_against=req.home_goals_against,
            key_injuries=[s.strip() for s in req.home_injuries.split(",") if s.strip()],
            key_suspensions=[s.strip() for s in req.home_suspensions.split(",") if s.strip()],
            in_season=req.home_in_season,
            market_value=req.home_market_value,
            uefa_coefficient=req.home_uefa_coefficient,
            odds_win=req.home_odds_win,
            odds_draw=req.odds_draw,
        )

        away = TeamData(
            name=req.away_team,
            league_position=req.away_league_pos,
            league_points=req.away_points,
            total_teams=req.total_teams,
            goals_for=req.away_goals_for,
            goals_against=req.away_goals_against,
            key_injuries=[s.strip() for s in req.away_injuries.split(",") if s.strip()],
            key_suspensions=[s.strip() for s in req.away_suspensions.split(",") if s.strip()],
            in_season=req.away_in_season,
            market_value=req.away_market_value,
            uefa_coefficient=req.away_uefa_coefficient,
            odds_win=req.away_odds_win,
        )

        # Parse form strings
        if req.home_form:
            home.recent_form = [f.strip().upper() for f in req.home_form.split(",") if f.strip()]
        if req.away_form:
            away.recent_form = [f.strip().upper() for f in req.away_form.split(",") if f.strip()]
        if req.home_home_form:
            home.home_form = [f.strip().upper() for f in req.home_home_form.split(",") if f.strip()]
        if req.away_away_form:
            away.away_form = [f.strip().upper() for f in req.away_away_form.split(",") if f.strip()]

        # H2H
        home.h2h_wins = req.h2h_wins_home or 0
        home.h2h_draws = req.h2h_draws or 0
        home.h2h_losses = req.h2h_wins_away or 0

        # Auto-search for comprehensive data - ALWAYS run
        fetched_home_fields = []
        fetched_away_fields = []
        data_quality = "用户手动输入 (未联网)"

        try:
            fetcher = DataFetcher()
            loop = asyncio.get_running_loop()

            # Run both searches in parallel for speed
            home_data, away_data = await asyncio.gather(
                loop.run_in_executor(
                    executor,
                    fetcher.search_team_data,
                    req.home_team, req.away_team, req.league, True
                ),
                loop.run_in_executor(
                    executor,
                    fetcher.search_team_data,
                    req.away_team, req.home_team, req.league, False
                ),
            )
            # Collect diagnostic info from data fetching
            home_steps = getattr(home_data, '_steps', {})
            away_steps = getattr(away_data, '_steps', {})
            fetcher.close()

            # Merge fetched data for HOME team (don't override user-provided data)
            if home_data.league_position and not home.league_position:
                home.league_position = home_data.league_position
                fetched_home_fields.append("排名")
            if home_data.total_teams and not home.total_teams:
                home.total_teams = home_data.total_teams
            if home_data.league_points and not home.league_points:
                home.league_points = home_data.league_points
            if home_data.recent_form and not home.recent_form:
                home.recent_form = home_data.recent_form
                fetched_home_fields.append("近期战绩")
            if home_data.home_form and not home.home_form:
                home.home_form = home_data.home_form
                fetched_home_fields.append("主场战绩")
            if home_data.goals_for and not home.goals_for:
                home.goals_for = home_data.goals_for
                fetched_home_fields.append("进球")
            if home_data.goals_against and not home.goals_against:
                home.goals_against = home_data.goals_against
                fetched_home_fields.append("失球")
            if home_data.goals_for_home and not home.goals_for_home:
                home.goals_for_home = home_data.goals_for_home
            if home_data.goals_against_home and not home.goals_against_home:
                home.goals_against_home = home_data.goals_against_home
            if home_data.key_injuries and not home.key_injuries:
                home.key_injuries = home_data.key_injuries
                fetched_home_fields.append("伤停")
            if home_data.key_suspensions and not home.key_suspensions:
                home.key_suspensions = home_data.key_suspensions
            if home_data.market_value and not home.market_value:
                home.market_value = home_data.market_value
                fetched_home_fields.append("身价")
            if home_data.uefa_coefficient and not home.uefa_coefficient:
                home.uefa_coefficient = home_data.uefa_coefficient
                fetched_home_fields.append("欧战系数")
            if (home_data.h2h_wins > 0 or home_data.h2h_losses > 0) and home.h2h_wins == 0 and home.h2h_losses == 0:
                home.h2h_wins = home_data.h2h_wins
                home.h2h_draws = home_data.h2h_draws
                home.h2h_losses = home_data.h2h_losses
                fetched_home_fields.append("交锋记录")

            # Merge fetched data for AWAY team
            if away_data.league_position and not away.league_position:
                away.league_position = away_data.league_position
                fetched_away_fields.append("排名")
            if away_data.total_teams and not away.total_teams:
                away.total_teams = away_data.total_teams
            if away_data.league_points and not away.league_points:
                away.league_points = away_data.league_points
            if away_data.recent_form and not away.recent_form:
                away.recent_form = away_data.recent_form
                fetched_away_fields.append("近期战绩")
            if away_data.away_form and not away.away_form:
                away.away_form = away_data.away_form
                fetched_away_fields.append("客场战绩")
            if away_data.goals_for and not away.goals_for:
                away.goals_for = away_data.goals_for
                fetched_away_fields.append("进球")
            if away_data.goals_against and not away.goals_against:
                away.goals_against = away_data.goals_against
                fetched_away_fields.append("失球")
            if away_data.goals_for_away and not away.goals_for_away:
                away.goals_for_away = away_data.goals_for_away
            if away_data.goals_against_away and not away.goals_against_away:
                away.goals_against_away = away_data.goals_against_away
            if away_data.key_injuries and not away.key_injuries:
                away.key_injuries = away_data.key_injuries
                fetched_away_fields.append("伤停")
            if away_data.key_suspensions and not away.key_suspensions:
                away.key_suspensions = away_data.key_suspensions
            if away_data.market_value and not away.market_value:
                away.market_value = away_data.market_value
                fetched_away_fields.append("身价")
            if away_data.uefa_coefficient and not away.uefa_coefficient:
                away.uefa_coefficient = away_data.uefa_coefficient
                fetched_away_fields.append("欧战系数")

            # Build data quality summary
            home_count = len(fetched_home_fields)
            away_count = len(fetched_away_fields)
            total_fields = home_count + away_count

            if total_fields >= 10:
                data_quality = f"联网获取 {total_fields} 项数据 (主队: {', '.join(fetched_home_fields)} | 客队: {', '.join(fetched_away_fields)})"
            elif total_fields >= 5:
                data_quality = f"联网获取 {total_fields} 项数据 (主: {', '.join(fetched_home_fields[:3])}... | 客: {', '.join(fetched_away_fields[:3])}...)"
            elif total_fields > 0:
                data_quality = f"联网获取 {total_fields} 项数据"
            else:
                # Show diagnostic info
                diag_parts = []
                if home_steps:
                    diag_parts.append(f"主队: {_format_steps(home_steps)}")
                if away_steps:
                    diag_parts.append(f"客队: {_format_steps(away_steps)}")
                if diag_parts:
                    data_quality = f"搜索诊断: {' | '.join(diag_parts)}"
                else:
                    data_quality = "联网搜索未获取到有效数据，使用用户手动输入"

        except Exception as e:
            data_quality = f"联网搜索失败，使用手动数据 (错误: {str(e)[:80]})"

        # Run prediction
        result = engine.analyze(home, away, req.league, req.handicap or "")

        # Translate bet
        bet_cn = {"home": "主胜", "draw": "平局", "away": "客胜"}

        # Confidence label
        conf_labels = {
            5: "★★★★★ 极高信心",
            4: "★★★★ 高信心",
            3: "★★★ 中等信心",
            2: "★★ 低信心",
            1: "★ 数据矛盾，谨慎参考",
        }

        return PredictionResponse(
            home_team=req.home_team,
            away_team=req.away_team,
            win_prob=result.win_prob,
            draw_prob=result.draw_prob,
            loss_prob=result.loss_prob,
            recommended_bet=result.recommended_bet,
            recommended_bet_cn=bet_cn.get(result.recommended_bet, result.recommended_bet),
            handicap_bet=result.handicap_bet,
            predicted_score=result.predicted_score,
            confidence=result.confidence,
            confidence_label=conf_labels.get(result.confidence, f"{result.confidence}星"),
            key_factors=result.key_factors,
            risk_factors=result.risk_factors,
            dimension_scores=result.dimension_scores,
            data_consistency=result.data_consistency,
            search_data_quality=data_quality,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"预测出错: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
