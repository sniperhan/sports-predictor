// Sports Prediction System - Frontend Logic
const APP_VERSION = "1.2.0";

const API_URL = "/api/predict";

function onLeagueChange() {
    const league = document.getElementById("league").value;
    const saved = getSavedData(league);
    if (saved) {
        // Pre-fill common data for known leagues
        if (saved.total_teams) document.getElementById("total-teams").value = saved.total_teams;
    }
}

function getSavedData(league) {
    const presets = {
        "挪超": { total_teams: 16 },
        "巴甲": { total_teams: 20 },
        "美职联": { total_teams: 30 },
        "英超": { total_teams: 20 },
        "西甲": { total_teams: 20 },
        "意甲": { total_teams: 20 },
        "德甲": { total_teams: 18 },
        "法甲": { total_teams: 18 },
        "欧冠": { total_teams: 36 },
        "日职": { total_teams: 20 },
        "韩K联": { total_teams: 12 },
    };
    return presets[league] || null;
}

async function runPrediction() {
    const btn = document.getElementById("predict-btn");
    const resultCard = document.getElementById("result-card");
    const resultContent = document.getElementById("result-content");

    // Validate required fields
    const homeTeam = document.getElementById("home-team").value.trim();
    const awayTeam = document.getElementById("away-team").value.trim();
    const league = document.getElementById("league").value;

    if (!homeTeam || !awayTeam) {
        alert("请输入主队和客队名称");
        return;
    }
    if (!league) {
        alert("请选择联赛");
        return;
    }

    // Show loading with better status
    btn.disabled = true;
    btn.textContent = "⏳ 正在联网搜索数据...";
    resultCard.style.display = "block";
    resultContent.innerHTML = '<div class="loading"><div class="spinner"></div><p>正在搜索两队联赛排名、近期战绩、主客场数据...</p><p style="font-size:0.8rem;color:#64748b;margin-top:8px;">搜索维度: 排名 | 战绩 | 攻防 | 交锋 | 伤停 | 身价 | 欧战系数</p><p style="font-size:0.75rem;color:#f59e0b;margin-top:6px;">注意：首次请求可能需要60秒（服务器冷启动+数据抓取），请耐心等待...</p></div>';

    // Build request
    const data = {
        home_team: homeTeam,
        away_team: awayTeam,
        league: league,
        match_date: document.getElementById("match-date").value || null,
        handicap: document.getElementById("handicap").value || "",
        home_league_pos: parseOrNull("home-pos"),
        away_league_pos: parseOrNull("away-pos"),
        total_teams: parseOrNull("total-teams"),
        home_form: document.getElementById("home-form").value || null,
        away_form: document.getElementById("away-form").value || null,
        home_home_form: document.getElementById("home-home-form").value || null,
        away_away_form: document.getElementById("away-away-form").value || null,
        home_goals_for: parseFloatOrNull("home-gf"),
        home_goals_against: parseFloatOrNull("home-ga"),
        away_goals_for: parseFloatOrNull("away-gf"),
        away_goals_against: parseFloatOrNull("away-ga"),
        h2h_wins_home: parseIntOrZero("h2h-home-wins"),
        h2h_draws: parseIntOrZero("h2h-draws"),
        h2h_wins_away: parseIntOrZero("h2h-away-wins"),
        home_injuries: document.getElementById("home-injuries").value || "",
        away_injuries: document.getElementById("away-injuries").value || "",
        home_suspensions: document.getElementById("home-suspensions").value || "",
        away_suspensions: document.getElementById("away-suspensions").value || "",
        home_in_season: document.getElementById("home-season").value === "in",
        away_in_season: document.getElementById("away-season").value === "in",
        home_market_value: parseFloatOrNull("home-market-value"),
        away_market_value: parseFloatOrNull("away-market-value"),
        home_uefa_coefficient: parseFloatOrNull("home-uefa"),
        away_uefa_coefficient: parseFloatOrNull("away-uefa"),
        home_odds_win: parseFloatOrNull("home-odds"),
        away_odds_win: parseFloatOrNull("away-odds"),
        odds_draw: parseFloatOrNull("draw-odds"),
    };

    // AbortController for 90-second timeout
    const controller = new AbortController();
    const timeoutId = setTimeout(function() { controller.abort(); }, 90000);

    try {
        const resp = await fetch(API_URL, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(data),
            signal: controller.signal,
        });
        clearTimeout(timeoutId);

        if (!resp.ok) {
            const err = await resp.json();
            throw new Error(err.detail || "预测请求失败");
        }

        const result = await resp.json();
        console.log("API Response:", result);
        console.log("dimension_scores:", result.dimension_scores);

        // Verify dimension_scores exist
        if (!result.dimension_scores || Object.keys(result.dimension_scores).length === 0) {
            resultContent.innerHTML = '<div class="loading" style="color:#f87171;">❌ API返回了空白的维度得分数据。请检查浏览器控制台 (F12) 查看详情。</div>';
            btn.disabled = false;
            btn.textContent = "🔍 开始分析预测";
            return;
        }

        renderResult(result);
    } catch (e) {
        clearTimeout(timeoutId);
        if (e.name === "AbortError") {
            resultContent.innerHTML = '<div class="loading" style="color:#f59e0b;">⏰ 请求超时（90秒）。服务器可能正在冷启动，请刷新页面后重试，或等待1-2分钟后再次点击预测按钮。</div>';
        } else {
            resultContent.innerHTML = '<div class="loading" style="color:#f87171;">❌ 预测出错: ' + e.message + '</div>';
        }
    } finally {
        btn.disabled = false;
        btn.textContent = "🔍 开始分析预测";
    }
}

function renderResult(r) {
    const resultCard = document.getElementById("result-card");
    const resultContent = document.getElementById("result-content");

    resultCard.style.display = "block";

    const betClass = { home: "win", draw: "draw", away: "loss" }[r.recommended_bet] || "draw";

    // Dimension score bars
    const dimLabels = {
        home_away: "主客场", recent_form: "近期状态", h2h: "历史交锋",
        league_position: "联赛排名", team_strength: "球队实力",
        odds: "市场赔率", goals_data: "攻防数据",
        injuries: "伤病停赛", match_fitness: "比赛状态",
    };

    let dimRows = "";
    for (const [key, val] of Object.entries(r.dimension_scores)) {
        const label = dimLabels[key] || key;
        const absVal = Math.abs(val);
        const pct = absVal * 100;
        const positive = val > 0.005;
        const negative = val < -0.005;
        const neutral = !positive && !negative;
        const barClass = positive ? "positive" : (negative ? "negative" : "neutral");
        const barStyle = `width:${Math.min(pct, 100)}%`;
        let side, sideColor;
        if (neutral) {
            side = "-- 无数据";
            sideColor = "#64748b";
        } else if (positive) {
            side = "← 主优";
            sideColor = "#4ade80";
        } else {
            side = "客优 →";
            sideColor = "#f87171";
        }
        const scoreText = neutral ? "" : ` (${(val >= 0 ? "+" : "") + val.toFixed(2)})`;
        dimRows += `
            <tr>
                <td>${label}${scoreText}</td>
                <td><span class="dim-bar-track"><span class="dim-bar-fill ${barClass}" style="${barStyle}"></span></span></td>
                <td style="font-size:0.75rem;color:${sideColor}">${side}</td>
            </tr>`;
    }

    resultContent.innerHTML = `
        <div class="result-header">
            <span class="team">${r.home_team}</span>
            <span class="vs">VS</span>
            <span class="team">${r.away_team}</span>
        </div>

        <div class="score-prediction">
            ⚽ ${r.predicted_score}
        </div>

        <div class="recommendation">
            <span class="rec-badge ${betClass}">胜平负推荐: ${r.recommended_bet_cn}</span>
            <span class="rec-badge" style="background:rgba(59,130,246,0.2);color:#60a5fa;border:1px solid rgba(59,130,246,0.3);">${r.handicap_bet}</span>
        </div>

        <div class="confidence-badge">${r.confidence_label} | 数据一致性: ${r.data_consistency}</div>

        <div class="prob-bars">
            <div class="prob-row">
                <span class="prob-label">🏠 主胜</span>
                <div class="prob-track"><div class="prob-fill home-bar" style="width:${r.win_prob * 100}%">${(r.win_prob * 100).toFixed(0)}%</div></div>
                <span class="prob-value">${(r.win_prob * 100).toFixed(1)}%</span>
            </div>
            <div class="prob-row">
                <span class="prob-label">🤝 平局</span>
                <div class="prob-track"><div class="prob-fill draw-bar" style="width:${r.draw_prob * 100}%">${(r.draw_prob * 100).toFixed(0)}%</div></div>
                <span class="prob-value">${(r.draw_prob * 100).toFixed(1)}%</span>
            </div>
            <div class="prob-row">
                <span class="prob-label">✈️ 客胜</span>
                <div class="prob-track"><div class="prob-fill away-bar" style="width:${r.loss_prob * 100}%">${(r.loss_prob * 100).toFixed(0)}%</div></div>
                <span class="prob-value">${(r.loss_prob * 100).toFixed(1)}%</span>
            </div>
        </div>

        <div class="factors-grid">
            <div class="factors-col green">
                <h4>✅ 支持信号</h4>
                <ul>${r.key_factors.map(f => `<li>${f}</li>`).join("")}</ul>
            </div>
            <div class="factors-col red">
                <h4>⚠️ 风险因素</h4>
                <ul>${r.risk_factors.length ? r.risk_factors.map(f => `<li>${f}</li>`).join("") : "<li>无明显风险</li>"}</ul>
            </div>
        </div>

        <h4 style="margin-top:20px;font-size:0.9rem;">📊 维度得分详情</h4>
        <table class="dimensions-table">
            <thead><tr><th>维度</th><th>得分条</th><th>方向</th></tr></thead>
            <tbody>${dimRows}</tbody>
        </table>

        <div style="margin-top:12px;padding:10px 14px;background:rgba(59,130,246,0.08);border-radius:8px;font-size:0.8rem;color:#93c5fd;">
            📡 ${r.search_data_quality}
        </div>
        <details style="margin-top:8px;font-size:0.7rem;color:#64748b;">
            <summary style="cursor:pointer;">🔧 调试信息 (原始维度得分, 版本: ${APP_VERSION})</summary>
            <pre style="background:rgba(0,0,0,0.3);padding:8px;border-radius:4px;overflow-x:auto;margin-top:4px;">${JSON.stringify(r.dimension_scores, null, 2)}</pre>
        </details>
    `;

    resultCard.scrollIntoView({ behavior: "smooth" });
}

function parseOrNull(id) {
    const el = document.getElementById(id);
    if (!el || !el.value) return null;
    const v = parseInt(el.value);
    return isNaN(v) ? null : v;
}

function parseFloatOrNull(id) {
    const el = document.getElementById(id);
    if (!el || !el.value) return null;
    const v = parseFloat(el.value);
    return isNaN(v) ? null : v;
}

function parseIntOrZero(id) {
    const el = document.getElementById(id);
    if (!el || !el.value) return 0;
    const v = parseInt(el.value);
    return isNaN(v) ? 0 : v;
}

// Auto-update H2H total
document.addEventListener("DOMContentLoaded", () => {
    const h2hInputs = ["h2h-home-wins", "h2h-draws", "h2h-away-wins"];
    h2hInputs.forEach(id => {
        document.getElementById(id)?.addEventListener("input", updateH2hTotal);
    });

    // Set default date to today
    const today = new Date().toISOString().split("T")[0];
    document.getElementById("match-date").value = today;
});

function updateH2hTotal() {
    const wins = parseInt(document.getElementById("h2h-home-wins").value) || 0;
    const draws = parseInt(document.getElementById("h2h-draws").value) || 0;
    const losses = parseInt(document.getElementById("h2h-away-wins").value) || 0;
    document.getElementById("h2h-total").value = wins + draws + losses;
}
