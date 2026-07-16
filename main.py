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

        # Auto-search for data if minimal input provided
        data_quality = "用户手动输入"

        if not req.home_league_pos or not req.away_league_pos:
            try:
                data_quality = "正在联网搜索补充数据..."
                fetcher = DataFetcher()

                loop = asyncio.get_running_loop()
                home_data = await loop.run_in_executor(
                    executor,
                    fetcher.search_team_data,
                    req.home_team, req.away_team, req.league, True
                )
                away_data = await loop.run_in_executor(
                    executor,
                    fetcher.search_team_data,
                    req.away_team, req.home_team, req.league, False
                )

                # Merge fetched data (don't override user-provided data)
                if not home.league_position:
                    home.league_position = home_data.league_position
                if not home.league_points:
                    home.league_points = home_data.league_points
                if not home.recent_form:
                    home.recent_form = home_data.recent_form
                if not home.home_form:
                    home.home_form = home_data.home_form
                if not home.goals_for:
                    home.goals_for = home_data.goals_for
                if not home.goals_against:
                    home.goals_against = home_data.goals_against
                if not home.key_injuries:
                    home.key_injuries = home_data.key_injuries
                if not home.key_suspensions:
                    home.key_suspensions = home_data.key_suspensions
                if not home.market_value:
                    home.market_value = home_data.market_value
                if not home.uefa_coefficient:
                    home.uefa_coefficient = home_data.uefa_coefficient
                if home.h2h_wins == 0 and home.h2h_losses == 0:
                    home.h2h_wins = home_data.h2h_wins
                    home.h2h_draws = home_data.h2h_draws
                    home.h2h_losses = home_data.h2h_losses

                if not away.league_position:
                    away.league_position = away_data.league_position
                if not away.league_points:
                    away.league_points = away_data.league_points
                if not away.recent_form:
                    away.recent_form = away_data.recent_form
                if not away.away_form:
                    away.away_form = away_data.away_form
                if not away.goals_for:
                    away.goals_for = away_data.goals_for
                if not away.goals_against:
                    away.goals_against = away_data.goals_against
                if not away.key_injuries:
                    away.key_injuries = away_data.key_injuries
                if not away.key_suspensions:
                    away.key_suspensions = away_data.key_suspensions
                if not away.market_value:
                    away.market_value = away_data.market_value
                if not away.uefa_coefficient:
                    away.uefa_coefficient = away_data.uefa_coefficient

                fetcher.close()
                data_quality = "联网搜索完成"
            except Exception as e:
                data_quality = f"联网搜索失败，使用用户提供的数据 ({str(e)[:50]})"

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
