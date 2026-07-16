"""
Sports Match Prediction Engine

Encodes the analysis methodology developed through real-world prediction testing:
- Multi-dimensional scoring (league position, form, H2H, home/away, injuries, fitness, odds)
- Directional signal detection (how many dimensions point same way?)
- Confidence calibration (data contradiction → lower confidence)
- Key lesson: "must win" != "can win"; domestic data != continental data
"""

from dataclasses import dataclass, field
from typing import Optional
import math


@dataclass
class TeamData:
    name: str
    league_position: Optional[int] = None
    league_points: Optional[int] = None
    total_teams: Optional[int] = None
    recent_form: list[str] = field(default_factory=list)  # ['W','D','L','W','L']
    home_form: list[str] = field(default_factory=list)
    away_form: list[str] = field(default_factory=list)
    goals_for: Optional[float] = None
    goals_against: Optional[float] = None
    goals_for_home: Optional[float] = None
    goals_against_home: Optional[float] = None
    goals_for_away: Optional[float] = None
    goals_against_away: Optional[float] = None
    h2h_wins: int = 0
    h2h_draws: int = 0
    h2h_losses: int = 0
    h2h_goals_for: int = 0
    h2h_goals_against: int = 0
    key_injuries: list[str] = field(default_factory=list)
    key_suspensions: list[str] = field(default_factory=list)
    in_season: bool = True
    market_value: Optional[float] = None
    uefa_coefficient: Optional[float] = None
    odds_win: Optional[float] = None
    odds_draw: Optional[float] = None


@dataclass
class PredictionResult:
    win_prob: float
    draw_prob: float
    loss_prob: float
    recommended_bet: str  # 'home', 'draw', 'away'
    handicap_bet: str
    predicted_score: str
    confidence: int  # 1-5 stars
    key_factors: list[str]
    risk_factors: list[str]
    dimension_scores: dict
    data_consistency: str  # 'high', 'medium', 'low', 'contradictory'


class PredictionEngine:
    """Core prediction engine using weighted multi-dimensional analysis."""

    # Weights calibrated from real prediction results
    WEIGHTS = {
        "home_away": 0.22,      # Home/away performance split
        "recent_form": 0.20,    # Last 5-10 matches
        "h2h": 0.15,            # Head-to-head record
        "league_position": 0.13, # League standing
        "goals_data": 0.10,     # GF/GA differential
        "injuries": 0.12,       # Key absences
        "match_fitness": 0.08,  # In-season vs off-season
    }

    def analyze(self, home: TeamData, away: TeamData, league: str, handicap: str = "") -> PredictionResult:
        scores = {}
        factors = []
        risks = []

        # 1. Home/Away Performance (22%)
        ha_score = self._score_home_away(home, away)
        scores["home_away"] = ha_score
        if home.home_form:
            home_wins = home.home_form.count('W')
            home_total = len(home.home_form)
            factors.append(f"主队主场: {home_wins}胜/{home_total}场")
        if away.away_form:
            away_losses = away.away_form.count('L')
            away_total = len(away.away_form)
            factors.append(f"客队客场: {away_losses}负/{away_total}场")

        # 2. Recent Form (20%)
        rf_score = self._score_recent_form(home, away)
        scores["recent_form"] = rf_score
        if home.recent_form:
            last5_home = sum(1 for r in home.recent_form[:5] if r == 'W')
            factors.append(f"主队近5场: {last5_home}胜")
        if away.recent_form:
            last5_away = sum(1 for r in away.recent_form[:5] if r == 'W')
            factors.append(f"客队近5场: {last5_away}胜")

        # 3. Head-to-Head (15%)
        h2h_score = self._score_h2h(home, away)
        scores["h2h"] = h2h_score
        total_h2h = home.h2h_wins + home.h2h_draws + home.h2h_losses
        if total_h2h > 0:
            factors.append(f"历史交锋: 主队{home.h2h_wins}胜{home.h2h_draws}平{home.h2h_losses}负")

        # 4. League Position (13%)
        lp_score = self._score_league_position(home, away)
        scores["league_position"] = lp_score
        if home.league_position and away.league_position:
            factors.append(f"联赛排名: 主#{home.league_position} vs 客#{away.league_position}")

        # 5. Goals Data (10%)
        gd_score = self._score_goals(home, away)
        scores["goals_data"] = gd_score
        if home.goals_for and away.goals_against:
            factors.append(f"主队场均进{home.goals_for:.1f}球 | 客队场均失{away.goals_against:.1f}球")

        # 6. Injuries/Suspensions (12%)
        inj_score = self._score_injuries(home, away)
        scores["injuries"] = inj_score
        if home.key_injuries or home.key_suspensions:
            risks.append(f"主队缺阵: {', '.join(home.key_injuries + home.key_suspensions)}")
        if away.key_injuries or away.key_suspensions:
            factors.append(f"客队缺阵: {', '.join(away.key_injuries + away.key_suspensions)}")

        # 7. Match Fitness (8%)
        mf_score = self._score_match_fitness(home, away)
        scores["match_fitness"] = mf_score
        if not home.in_season:
            risks.append("⚠️ 主队处于休赛期，比赛状态存疑")
        if not away.in_season:
            factors.append("客队处于休赛期，状态不足")

        # Calculate weighted total
        total_home = 0.0
        for dim, score in scores.items():
            total_home += score * self.WEIGHTS[dim]

        # Convert to probabilities (sigmoid-like transformation)
        # total_home > 0 favors home team, < 0 favors away
        home_adv = total_home  # already weighted and centered

        if home_adv > 0.3:
            win_prob = 0.40 + home_adv * 0.5
            draw_prob = 0.30 - home_adv * 0.2
            loss_prob = 1.0 - win_prob - draw_prob
        elif home_adv < -0.3:
            loss_prob = 0.40 + abs(home_adv) * 0.5
            draw_prob = 0.30 - abs(home_adv) * 0.2
            win_prob = 1.0 - loss_prob - draw_prob
        else:
            win_prob = 0.30 + home_adv * 0.4
            draw_prob = 0.35 - abs(home_adv) * 0.15
            loss_prob = 1.0 - win_prob - draw_prob

        # Clamp
        win_prob = max(0.08, min(0.85, win_prob))
        draw_prob = max(0.10, min(0.45, draw_prob))
        loss_prob = max(0.08, min(0.85, loss_prob))
        total = win_prob + draw_prob + loss_prob
        win_prob /= total
        draw_prob /= total
        loss_prob /= total

        # Determine recommended bet
        probs = {"home": win_prob, "draw": draw_prob, "away": loss_prob}
        recommended = max(probs, key=probs.get)

        # Confidence: data consistency + probability margin
        consistency = self._check_consistency(scores)
        margin = probs[recommended] - sorted(probs.values())[-2]
        confidence = self._calc_confidence(consistency, margin)

        # Handicap bet
        handicap_bet = self._generate_handicap_bet(recommended, margin, handicap)

        # Predicted score
        predicted_score = self._generate_score(home, away, home_adv)

        return PredictionResult(
            win_prob=round(win_prob, 3),
            draw_prob=round(draw_prob, 3),
            loss_prob=round(loss_prob, 3),
            recommended_bet=recommended,
            handicap_bet=handicap_bet,
            predicted_score=predicted_score,
            confidence=confidence,
            key_factors=factors[:5],
            risk_factors=risks[:3],
            dimension_scores={k: round(v, 2) for k, v in scores.items()},
            data_consistency=consistency,
        )

    def _score_home_away(self, home: TeamData, away: TeamData) -> float:
        """Score home/away performance. Returns -1 to 1, positive favors home."""
        score = 0.0

        # Home team home form
        if home.home_form:
            home_pts = sum(3 if r == 'W' else 1 if r == 'D' else 0 for r in home.home_form)
            home_max = len(home.home_form) * 3
            if home_max > 0:
                score += (home_pts / home_max - 0.45) * 0.6

        # Away team away form
        if away.away_form:
            away_pts = sum(3 if r == 'W' else 1 if r == 'D' else 0 for r in away.away_form)
            away_max = len(away.away_form) * 3
            if away_max > 0:
                score -= (away_pts / away_max - 0.35) * 0.6

        # Home goals vs away goals defense
        if home.goals_for_home and away.goals_against_away:
            diff = home.goals_for_home - away.goals_against_away
            score += diff * 0.1

        return max(-1.0, min(1.0, score))

    def _score_recent_form(self, home: TeamData, away: TeamData) -> float:
        """Score recent form (last 5-10 matches)."""
        score = 0.0

        if home.recent_form:
            recent = home.recent_form[:5]
            home_pts = sum(3 if r == 'W' else 1 if r == 'D' else 0 for r in recent)
            score += (home_pts / (len(recent) * 3) - 0.45) * 0.7

        if away.recent_form:
            recent = away.recent_form[:5]
            away_pts = sum(3 if r == 'W' else 1 if r == 'D' else 0 for r in recent)
            score -= (away_pts / (len(recent) * 3) - 0.40) * 0.7

        return max(-1.0, min(1.0, score))

    def _score_h2h(self, home: TeamData, away: TeamData) -> float:
        """Score head-to-head record."""
        total = home.h2h_wins + home.h2h_draws + home.h2h_losses
        if total == 0:
            return 0.0

        home_pts = home.h2h_wins * 3 + home.h2h_draws
        max_pts = total * 3
        win_rate = home_pts / max_pts
        return (win_rate - 0.4) * 0.8

    def _score_league_position(self, home: TeamData, away: TeamData) -> float:
        """Score based on league position difference."""
        if not home.league_position or not away.league_position:
            return 0.0
        if not home.total_teams or not away.total_teams:
            return 0.0

        # Normalize position to 0-1 (0=top, 1=bottom)
        home_norm = (home.league_position - 1) / max(1, home.total_teams - 1)
        away_norm = (away.league_position - 1) / max(1, away.total_teams - 1)

        diff = away_norm - home_norm  # positive = home better
        return max(-1.0, min(1.0, diff * 1.5))

    def _score_goals(self, home: TeamData, away: TeamData) -> float:
        """Score goal differential and offensive/defensive quality."""
        score = 0.0

        if home.goals_for and away.goals_against:
            score += (home.goals_for - away.goals_against) * 0.08

        if away.goals_for and home.goals_against:
            score -= (away.goals_for - home.goals_against) * 0.08

        return max(-1.0, min(1.0, score))

    def _score_injuries(self, home: TeamData, away: TeamData) -> float:
        """Score impact of injuries and suspensions."""
        score = 0.0
        home_missing = len(home.key_injuries) + len(home.key_suspensions)
        away_missing = len(away.key_injuries) + len(away.key_suspensions)

        # Each key absence shifts score by 0.15 toward opponent
        score += away_missing * 0.15
        score -= home_missing * 0.15

        return max(-1.0, min(1.0, score))

    def _score_match_fitness(self, home: TeamData, away: TeamData) -> float:
        """Score match fitness (in-season advantage)."""
        score = 0.0
        if home.in_season and not away.in_season:
            score = 0.5
        elif not home.in_season and away.in_season:
            score = -0.5
        return score

    def _check_consistency(self, scores: dict) -> str:
        """Check how many dimensions point in the same direction."""
        positive = sum(1 for v in scores.values() if v > 0.05)
        negative = sum(1 for v in scores.values() if v < -0.05)
        neutral = sum(1 for v in scores.values() if -0.05 <= v <= 0.05)
        total = len(scores)

        if positive >= total * 0.7:
            return "high"
        elif negative >= total * 0.7:
            return "high"
        elif abs(positive - negative) <= 1:
            return "contradictory"
        elif abs(positive - negative) <= 2:
            return "low"
        else:
            return "medium"

    def _calc_confidence(self, consistency: str, margin: float) -> int:
        """Calculate confidence stars (1-5)."""
        base = {"high": 4, "medium": 3, "low": 2, "contradictory": 1}
        stars = base.get(consistency, 2)

        if margin > 0.20:
            stars += 1
        elif margin < 0.08:
            stars = max(1, stars - 1)

        return min(5, max(1, stars))

    def _generate_handicap_bet(self, recommended: str, margin: float, handicap: str) -> str:
        """Generate handicap recommendation."""
        direction_cn = {"home": "主队", "draw": "平局", "away": "客队"}

        if margin > 0.25:
            return f"推荐{direction_cn[recommended]}方向（穿盘）"
        elif margin > 0.12:
            return f"推荐{direction_cn[recommended]}方向（赢半或全赢）"
        else:
            return f"推荐{direction_cn[recommended]}方向（谨慎）"

    def _generate_score(self, home: TeamData, away: TeamData, home_adv: float) -> str:
        """Generate predicted score consistent with recommended direction."""
        # Estimate total goals
        total_goals = 2.5

        if home.goals_for and away.goals_against:
            total_goals = (home.goals_for + away.goals_against) / 2
        if away.goals_for and home.goals_against:
            total_goals = (total_goals + (away.goals_for + home.goals_against) / 2) / 2

        total_goals = max(1.5, min(5.0, total_goals))
        total_goals = round(total_goals)

        # Split based on advantage, ensure consistency with direction
        if home_adv > 0.1:
            # Home advantage: home scores more
            home_goals = max(1, round(total_goals * 0.6))
            away_goals = total_goals - home_goals
            if home_goals <= away_goals:
                home_goals = away_goals + 1
        elif home_adv < -0.1:
            # Away advantage: away scores more
            away_goals = max(1, round(total_goals * 0.6))
            home_goals = total_goals - away_goals
            if away_goals <= home_goals:
                away_goals = home_goals + 1
        else:
            # Even match
            base = total_goals // 2
            home_goals = base
            away_goals = total_goals - base

        # Clamp
        home_goals = max(0, min(6, home_goals))
        away_goals = max(0, min(6, away_goals))

        return f"{home_goals}-{away_goals}"
