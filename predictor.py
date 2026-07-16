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
        "home_away": 0.19,       # Home/away performance split
        "recent_form": 0.17,     # Last 5-10 matches
        "h2h": 0.12,             # Head-to-head record
        "league_position": 0.11, # League standing
        "team_strength": 0.09,   # Market value + UEFA coefficient
        "odds": 0.08,            # Market odds (implied probability)
        "goals_data": 0.08,      # GF/GA differential
        "injuries": 0.10,        # Key absences
        "match_fitness": 0.06,   # In-season vs off-season
    }

    def analyze(self, home: TeamData, away: TeamData, league: str, handicap: str = "") -> PredictionResult:
        scores = {}
        factors = []
        risks = []

        # Auto-calculate fair odds from available data (no external API needed)
        if not home.odds_win or not away.odds_win or not home.odds_draw:
            calc_home, calc_draw, calc_away = self._calculate_fair_odds(home, away)
            if not home.odds_win:
                home.odds_win = calc_home
            if not away.odds_win:
                away.odds_win = calc_away
            if not home.odds_draw:
                home.odds_draw = calc_draw
            factors.append(f"公平赔率: 主{calc_home:.2f} / 平{calc_draw:.2f} / 客{calc_away:.2f}")

        # 1. Home/Away Performance (20%)
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

        # 2. Recent Form (18%)
        rf_score = self._score_recent_form(home, away)
        scores["recent_form"] = rf_score
        if home.recent_form:
            last5_home = sum(1 for r in home.recent_form[:5] if r == 'W')
            factors.append(f"主队近5场: {last5_home}胜")
        if away.recent_form:
            last5_away = sum(1 for r in away.recent_form[:5] if r == 'W')
            factors.append(f"客队近5场: {last5_away}胜")

        # 3. Head-to-Head (13%)
        h2h_score = self._score_h2h(home, away)
        scores["h2h"] = h2h_score
        total_h2h = home.h2h_wins + home.h2h_draws + home.h2h_losses
        if total_h2h > 0:
            factors.append(f"历史交锋: 主队{home.h2h_wins}胜{home.h2h_draws}平{home.h2h_losses}负")

        # 4. League Position (12%)
        lp_score = self._score_league_position(home, away)
        scores["league_position"] = lp_score
        if home.league_position and away.league_position:
            factors.append(f"联赛排名: 主#{home.league_position} vs 客#{away.league_position}")

        # 5. Team Strength - Market Value & UEFA Coefficient (10%)
        ts_score = self._score_team_strength(home, away)
        scores["team_strength"] = ts_score
        if home.market_value and away.market_value:
            factors.append(f"球队身价: 主{home.market_value:.0f}M vs 客{away.market_value:.0f}M")
        if home.uefa_coefficient and away.uefa_coefficient:
            factors.append(f"欧战系数: 主{home.uefa_coefficient:.1f} vs 客{away.uefa_coefficient:.1f}")

        # 6. Market Odds (8%)
        odds_score = self._score_odds(home, away)
        scores["odds"] = odds_score
        if home.odds_win and away.odds_win and home.odds_draw:
            home_implied = (1.0 / home.odds_win) * 100
            away_implied = (1.0 / away.odds_win) * 100
            factors.append(f"赔率隐含概率: 主{home_implied:.0f}% vs 客{away_implied:.0f}%")

        # 7. Goals Data (8%)
        gd_score = self._score_goals(home, away)
        scores["goals_data"] = gd_score
        if home.goals_for and away.goals_against:
            factors.append(f"主队场均进{home.goals_for:.1f}球 | 客队场均失{away.goals_against:.1f}球")

        # 8. Injuries/Suspensions (10%)
        inj_score = self._score_injuries(home, away)
        scores["injuries"] = inj_score
        if home.key_injuries or home.key_suspensions:
            risks.append(f"主队缺阵: {', '.join(home.key_injuries + home.key_suspensions)}")
        if away.key_injuries or away.key_suspensions:
            factors.append(f"客队缺阵: {', '.join(away.key_injuries + away.key_suspensions)}")

        # 9. Match Fitness (6%)
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

        # Predicted score (must be consistent with recommended bet)
        predicted_score = self._generate_score(home, away, home_adv, recommended)

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

    def _calculate_fair_odds(self, home: TeamData, away: TeamData) -> tuple:
        """Calculate fair decimal odds (1X2) from available team data.
        Uses Elo-style rating with league position, points, form, and home advantage.
        Returns (home_odds, draw_odds, away_odds).
        """
        # Build Elo-style rating from available data
        home_rating = 1500.0
        away_rating = 1500.0

        # League position factor (0-200 points swing)
        if home.league_position and away.league_position and home.total_teams:
            home_pct = (home.total_teams - home.league_position) / max(1, home.total_teams - 1)
            away_pct = (away.total_teams - away.league_position) / max(1, away.total_teams - 1)
            home_rating += (home_pct - away_pct) * 200

        # Points factor (each point ~= 5 Elo points)
        if home.league_points and away.league_points:
            pt_diff = home.league_points - away.league_points
            home_rating += pt_diff * 5

        # Recent form factor
        if home.recent_form:
            form_pts = sum(3 if r == 'W' else 1 if r == 'D' else 0 for r in home.recent_form[:5])
            home_rating += (form_pts / max(1, len(home.recent_form[:5]) * 3) - 0.45) * 100

        if away.recent_form:
            form_pts = sum(3 if r == 'W' else 1 if r == 'D' else 0 for r in away.recent_form[:5])
            away_rating += (form_pts / max(1, len(away.recent_form[:5]) * 3) - 0.45) * 100

        # Market value factor
        if home.market_value and away.market_value and home.market_value > 0 and away.market_value > 0:
            ratio = home.market_value / away.market_value
            import math
            home_rating += math.log2(ratio) * 50

        # Home advantage (~35 Elo points)
        home_rating += 35

        # Rating difference
        rating_diff = home_rating - away_rating

        # Convert to win probability using logistic function
        win_prob = 1.0 / (1.0 + 10 ** (-rating_diff / 400.0))

        # Draw probability: higher when teams are close
        rating_gap = abs(rating_diff)
        draw_prob = max(0.18, 0.32 - rating_gap / 1000.0)

        # Adjust win/loss around draw
        win_prob = win_prob * (1.0 - draw_prob)
        loss_prob = (1.0 - win_prob) * (1.0 - draw_prob)

        # Normalize
        total = win_prob + draw_prob + loss_prob
        win_prob /= total
        draw_prob /= total
        loss_prob /= total

        # Convert probabilities to decimal odds (with 8% margin)
        margin = 1.08
        home_odds = round(margin / max(0.05, win_prob), 2)
        draw_odds = round(margin / max(0.05, draw_prob), 2)
        away_odds = round(margin / max(0.05, loss_prob), 2)

        return home_odds, draw_odds, away_odds

    def _score_home_away(self, home: TeamData, away: TeamData) -> float:
        """Score home/away performance. Returns -1 to 1, positive favors home."""
        score = 0.0

        # Home team home form - fallback to overall form if home form unavailable
        home_form_data = home.home_form if home.home_form else home.recent_form
        if home_form_data:
            home_pts = sum(3 if r == 'W' else 1 if r == 'D' else 0 for r in home_form_data)
            home_max = len(home_form_data) * 3
            if home_max > 0:
                score += (home_pts / home_max - 0.45) * 0.6

        # Away team away form - fallback to overall form if away form unavailable
        away_form_data = away.away_form if away.away_form else away.recent_form
        if away_form_data:
            away_pts = sum(3 if r == 'W' else 1 if r == 'D' else 0 for r in away_form_data)
            away_max = len(away_form_data) * 3
            if away_max > 0:
                score -= (away_pts / away_max - 0.35) * 0.6

        # Home goals vs away goals defense (use overall as fallback)
        home_gf = home.goals_for_home if home.goals_for_home else home.goals_for
        away_ga = away.goals_against_away if away.goals_against_away else away.goals_against
        if home_gf and away_ga:
            diff = home_gf - away_ga
            score += diff * 0.1

        # Away goals vs home defense (additional factor)
        away_gf = away.goals_for_away if away.goals_for_away else away.goals_for
        home_ga = home.goals_against_home if home.goals_against_home else home.goals_against
        if away_gf and home_ga:
            diff = home_ga - away_gf
            score -= diff * 0.1

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

    def _score_team_strength(self, home: TeamData, away: TeamData) -> float:
        """Score team strength based on market value, UEFA coefficient, and league points."""
        score = 0.0
        components = 0

        # Market value comparison (log-scale to handle huge disparities)
        if home.market_value and away.market_value and home.market_value > 0 and away.market_value > 0:
            ratio = home.market_value / away.market_value
            log_ratio = math.log2(ratio)
            score += max(-1.0, min(1.0, log_ratio * 0.3))
            components += 1

        # UEFA coefficient comparison
        if home.uefa_coefficient and away.uefa_coefficient and home.uefa_coefficient > 0 and away.uefa_coefficient > 0:
            diff = home.uefa_coefficient - away.uefa_coefficient
            score += max(-1.0, min(1.0, diff / 20.0))
            components += 1

        # League points as fallback proxy for team strength
        if not components and home.league_points and away.league_points:
            if home.league_points > 0 and away.league_points > 0:
                diff = home.league_points - away.league_points
                # ~20 point gap in a season = significant strength difference
                score += max(-1.0, min(1.0, diff / 25.0))
                components += 1

        if components == 0:
            return 0.0
        return max(-1.0, min(1.0, score / components))

    def _score_odds(self, home: TeamData, away: TeamData) -> float:
        """Score based on market odds implied probabilities."""
        if not home.odds_win or not away.odds_win or not home.odds_draw:
            return 0.0
        if home.odds_win <= 0 or away.odds_win <= 0 or home.odds_draw <= 0:
            return 0.0

        # Convert odds to implied probabilities
        home_imp = 1.0 / home.odds_win
        away_imp = 1.0 / away.odds_win
        draw_imp = 1.0 / home.odds_draw

        # Remove overround (bookmaker margin), re-normalize
        overround = home_imp + away_imp + draw_imp
        home_prob = home_imp / overround
        away_prob = away_imp / overround
        draw_prob = draw_imp / overround

        # Score: how much does the market favor home? 0.5 diff = full 1.0
        diff = home_prob - away_prob
        return max(-1.0, min(1.0, diff * 2.0))

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
            return "高度一致"
        elif negative >= total * 0.7:
            return "高度一致"
        elif abs(positive - negative) <= 1:
            return "数据矛盾"
        elif abs(positive - negative) <= 2:
            return "一致性低"
        else:
            return "中等一致"

    def _calc_confidence(self, consistency: str, margin: float) -> int:
        """Calculate confidence stars (1-5)."""
        base = {"高度一致": 4, "中等一致": 3, "一致性低": 2, "数据矛盾": 1}
        stars = base.get(consistency, 2)

        if margin > 0.20:
            stars += 1
        elif margin < 0.08:
            stars = max(1, stars - 1)

        return min(5, max(1, stars))

    def _generate_handicap_bet(self, recommended: str, margin: float, handicap: str) -> str:
        """Generate handicap recommendation using actual handicap if available."""
        direction_cn = {"home": "主队", "draw": "平局", "away": "客队"}
        direction_en = {"home": "主队", "draw": "平局", "away": "客队"}

        # Parse handicap to give specific advice
        if handicap and handicap != "draw" and recommended != "draw":
            handicap_val = 0.0
            handicap_side = ""
            if handicap.startswith("home-"):
                handicap_val = float(handicap.replace("home-", ""))
                handicap_side = "home"
            elif handicap.startswith("away-"):
                handicap_val = float(handicap.replace("away-", ""))
                handicap_side = "away"

            if handicap_side == recommended:
                if margin > 0.20:
                    return f"推荐{direction_cn[recommended]}方向（让{handicap_val}球，穿盘可期）"
                elif margin > 0.10:
                    return f"推荐{direction_cn[recommended]}方向（让{handicap_val}球，赢半博全赢）"
                else:
                    return f"推荐{direction_cn[recommended]}方向（让{handicap_val}球，谨慎博穿盘）"
            elif handicap_side and handicap_side != recommended:
                return f"{direction_cn[recommended]}方向有优势，对手让{handicap_val}球，{direction_cn[recommended]}不败可期"

        if recommended == "draw":
            return "推荐平局方向，让球盘建议回避"
        if margin > 0.25:
            return f"推荐{direction_cn[recommended]}方向（穿盘）"
        elif margin > 0.12:
            return f"推荐{direction_cn[recommended]}方向（赢半或全赢）"
        else:
            return f"推荐{direction_cn[recommended]}方向（谨慎）"

    def _generate_score(self, home: TeamData, away: TeamData, home_adv: float, recommended: str) -> str:
        """Generate predicted score consistent with recommended bet direction."""
        # Estimate total goals
        total_goals = 2.5

        if home.goals_for and away.goals_against:
            total_goals = (home.goals_for + away.goals_against) / 2
        if away.goals_for and home.goals_against:
            total_goals = (total_goals + (away.goals_for + home.goals_against) / 2) / 2

        total_goals = max(1.5, min(5.0, total_goals))
        total_goals = round(total_goals)

        if recommended == "draw":
            base = total_goals // 2
            if total_goals % 2 == 0:
                home_goals = base
                away_goals = base
            else:
                home_goals = base
                away_goals = base + 1
                if home_goals == away_goals:
                    home_goals = max(0, base - 1)
                    away_goals = home_goals
        elif recommended == "home":
            home_goals = max(1, round(total_goals * 0.6))
            away_goals = total_goals - home_goals
            if home_goals <= away_goals:
                home_goals = away_goals + 1
        else:  # away
            away_goals = max(1, round(total_goals * 0.6))
            home_goals = total_goals - away_goals
            if away_goals <= home_goals:
                away_goals = home_goals + 1

        # Clamp
        home_goals = max(0, min(6, home_goals))
        away_goals = max(0, min(6, away_goals))

        return f"{home_goals}-{away_goals}"
