"""Scoring model and data-merge logic."""
import math
import re
import unicodedata
from typing import Optional


# ── Probability helpers ──────────────────────────────────────────────────────

def american_to_prob(american_odds: int) -> float:
    """Convert American odds to implied probability (0-1)."""
    if american_odds >= 0:
        return 100.0 / (american_odds + 100.0)
    else:
        return abs(american_odds) / (abs(american_odds) + 100.0)


def remove_vig(prob_list: list) -> list:
    """Normalise a list of implied probabilities so they sum to 1.0."""
    total = sum(p for p in prob_list if p is not None)
    if total == 0:
        return prob_list
    return [(p / total if p is not None else None) for p in prob_list]


def calc_edge(model_prob: Optional[float], market_prob: Optional[float]) -> Optional[float]:
    """Return model_prob - market_prob, or None if either is missing."""
    if model_prob is None or market_prob is None:
        return None
    return model_prob - market_prob


def get_recommendation(edge: Optional[float]) -> str:
    if edge is None:
        return "No Data"
    if edge > 0.05:
        return "Strong Value"
    if edge > 0.02:
        return "Value"
    if edge > -0.02:
        return "Fair"
    return "Fade"


# ── Name normalisation ───────────────────────────────────────────────────────

def _norm_name(name: str) -> str:
    """Normalize player name for fuzzy matching across APIs.

    Strips accents, lowercases, removes non-alpha characters, collapses spaces.
    E.g. "Séamus Power" → "seamus power"
    """
    if not name:
        return ""
    # NFD decompose to separate base chars from combining accents
    nfd = unicodedata.normalize("NFD", name)
    # Drop combining characters (accents etc.), keep ASCII only
    ascii_name = nfd.encode("ascii", "ignore").decode("ascii")
    # Lowercase
    lower = ascii_name.lower()
    # Remove anything that is not a letter or whitespace
    clean = re.sub(r"[^a-z\s]", "", lower).strip()
    # Collapse multiple spaces
    return re.sub(r"\s+", " ", clean)


# Keep the old name as an alias so nothing outside this module breaks
_normalize_name = _norm_name


# ── ESPN stats → Win probability model ───────────────────────────────────────

def sg_to_win_probs(players: list[dict]) -> list[dict]:
    """Convert ESPN stats into estimated win/top5/top10/top20 probabilities.

    Uses a composite score built from ESPN stats, then applies softmax
    normalisation across the field with a tuned temperature.

    Composite score formula (all components are field-deviation-based):
        scoring_component  = -(scoring_avg - field_avg)   [lower avg = better]
        gir_component      = (gir_pct - field_avg) / 5.0  [scaled to ~same range]
        birdie_component   = (birdies_per_round - field_avg)
        putting_component  = -(putts_per_hole - field_avg) [lower = better]

        composite = (scoring * 0.45 + gir * 0.30 + birdie * 0.15 + putting * 0.10)

    Falls back to 0.0 for any missing individual stat. If ALL stats are missing
    for ALL players, assigns uniform probability.

    Returns:
        The same list with dg_win_prob, dg_top5_prob, dg_top10_prob,
        and dg_top20_prob populated on every dict.
    """
    field_size = len(players)
    if field_size == 0:
        return players

    # Collect per-stat values, using 0.0 as fallback for missing
    scoring_vals = [p.get("scoring_avg") for p in players]
    gir_vals = [p.get("gir_pct") for p in players]
    birdie_vals = [p.get("birdies_per_round") for p in players]
    putting_vals = [p.get("putts_per_hole") for p in players]

    # Check if we have ANY real stats at all
    has_any_stats = any(
        v is not None
        for vals in (scoring_vals, gir_vals, birdie_vals, putting_vals)
        for v in vals
    )

    if not has_any_stats:
        # Uniform probability — no stat data available
        uniform = 1.0 / field_size
        for p in players:
            p["dg_win_prob"] = round(uniform, 6)
            p["dg_top5_prob"] = round(min(uniform * 4.2, 0.95), 6)
            p["dg_top10_prob"] = round(min(uniform * 7.5, 0.95), 6)
            p["dg_top20_prob"] = round(min(uniform * 13.0, 0.95), 6)
        return players

    def _field_avg(vals: list) -> float:
        valid = [v for v in vals if v is not None]
        return sum(valid) / len(valid) if valid else 0.0

    field_avg_scoring = _field_avg(scoring_vals)
    field_avg_gir = _field_avg(gir_vals)
    field_avg_birdies = _field_avg(birdie_vals)
    field_avg_putts = _field_avg(putting_vals)

    scores = []
    for p in players:
        scoring_avg = p.get("scoring_avg")
        gir_pct = p.get("gir_pct")
        birdies_per_round = p.get("birdies_per_round")
        putts_per_hole = p.get("putts_per_hole")

        # Lower scoring_avg = better → invert so positive = good
        scoring_component = -(
            (scoring_avg - field_avg_scoring) if scoring_avg is not None else 0.0
        )
        # Higher GIR% = better; divide by 5 to scale to ~same range as scoring
        gir_component = (
            (gir_pct - field_avg_gir) / 5.0 if gir_pct is not None else 0.0
        )
        # Higher birdies/round = better
        birdie_component = (
            (birdies_per_round - field_avg_birdies) if birdies_per_round is not None else 0.0
        )
        # Lower putts/hole = better → invert
        putting_component = -(
            (putts_per_hole - field_avg_putts) if putts_per_hole is not None else 0.0
        )

        composite = (
            scoring_component * 0.45
            + gir_component * 0.30
            + birdie_component * 0.15
            + putting_component * 0.10
        )
        scores.append(composite)

    # Softmax with temperature = 0.35
    # Lower temperature → more concentration on top-scoring players
    temp = 0.35
    max_score = max(scores)
    exp_scores = [math.exp((s - max_score) / temp) for s in scores]
    total = sum(exp_scores)

    win_probs = [e / total for e in exp_scores]

    # Estimate top-N probabilities from win probability.
    # Empirical multipliers for a ~150-player field:
    #   top5  ≈ win * 4.2
    #   top10 ≈ win * 7.5
    #   top20 ≈ win * 13.0
    for i, p in enumerate(players):
        win_p = win_probs[i]
        p["dg_win_prob"] = round(win_p, 6)
        p["dg_top5_prob"] = round(min(win_p * 4.2, 0.95), 6)
        p["dg_top10_prob"] = round(min(win_p * 7.5, 0.95), 6)
        p["dg_top20_prob"] = round(min(win_p * 13.0, 0.95), 6)

    return players


# ── Blurb generator ──────────────────────────────────────────────────────────

def generate_blurb(player: dict) -> str:
    """Auto-generate a 1-2 sentence reasoning string for a player.

    References ESPN stats: scoring_avg, gir_pct, driving_dist, birdies_per_round,
    putts_per_hole. Returns a plain-English summary with edge conclusion.
    """
    name = player.get("player_name") or "Player"
    last_name = name.split()[-1] if name.split() else name

    scoring_avg = player.get("scoring_avg")
    gir_pct = player.get("gir_pct")
    driving_dist = player.get("driving_dist")
    birdies_per_round = player.get("birdies_per_round")
    putts_per_hole = player.get("putts_per_hole")
    edge_top10 = player.get("edge_top10")
    rec = player.get("recommendation") or "No Data"

    # No data path
    has_any_stat = any(v is not None for v in [
        scoring_avg, gir_pct, driving_dist, birdies_per_round, putts_per_hole
    ])

    if rec == "No Data" and not has_any_stat:
        return "No stat data available — recommendation based on market odds alone."

    if rec == "No Data":
        return "Insufficient data to generate a recommendation."

    parts = []

    # Scoring average summary
    if scoring_avg is not None:
        if scoring_avg < 69.5:
            parts.append(f"{last_name} scores well below the field average ({scoring_avg:.1f} scoring avg)")
        elif scoring_avg < 71.0:
            parts.append(f"{last_name} has a solid scoring average ({scoring_avg:.1f})")
        elif scoring_avg > 72.5:
            parts.append(f"{last_name} scores above par on average ({scoring_avg:.1f} scoring avg)")

    # GIR% and birdies
    if gir_pct is not None and birdies_per_round is not None:
        if gir_pct >= 70.0 and birdies_per_round >= 4.0:
            parts.append(
                f"leads the field in GIR% ({gir_pct:.1f}%) and birdies per round "
                f"({birdies_per_round:.1f}) — elite ball-striking"
            )
        elif gir_pct >= 68.0:
            parts.append(f"strong approach game (GIR% {gir_pct:.1f}%)")
        elif gir_pct < 60.0:
            parts.append(f"struggles with ball-striking (GIR% {gir_pct:.1f}%)")
    elif gir_pct is not None:
        if gir_pct >= 68.0:
            parts.append(f"solid GIR% ({gir_pct:.1f}%)")
        elif gir_pct < 60.0:
            parts.append(f"poor GIR% ({gir_pct:.1f}%)")
    elif birdies_per_round is not None:
        if birdies_per_round >= 4.0:
            parts.append(f"makes birdies at a high rate ({birdies_per_round:.1f}/round)")
        elif birdies_per_round < 3.0:
            parts.append(f"low birdie rate ({birdies_per_round:.1f}/round)")

    # Putting
    if putts_per_hole is not None:
        if putts_per_hole < 1.70:
            parts.append(f"excellent putter ({putts_per_hole:.2f} putts/hole)")
        elif putts_per_hole > 1.80:
            parts.append(f"putting is a weakness ({putts_per_hole:.2f} putts/hole)")

    # Driving distance (context only, not primary)
    if driving_dist is not None and len(parts) == 0:
        parts.append(f"{last_name} averages {driving_dist:.0f} yards off the tee")

    # Edge conclusion
    if edge_top10 is not None:
        edge_pp = abs(edge_top10) * 100
        if rec == "Strong Value":
            conclusion = f"Model shows a {edge_pp:.1f}pp edge over market odds."
        elif rec == "Value":
            conclusion = f"Model finds a {edge_pp:.1f}pp edge — worth a look."
        elif rec == "Fade":
            conclusion = f"Model finds a {edge_pp:.1f}pp negative edge — consider fading."
        else:
            conclusion = "Model sees roughly fair value here."
    else:
        if rec == "Fade":
            conclusion = f"{last_name} is overpriced at these odds; model finds no edge."
        elif rec in ("Strong Value", "Value"):
            conclusion = "Model finds value at current odds."
        else:
            conclusion = "Model sees roughly fair value here."

    if not parts:
        if rec == "Fade":
            return f"{last_name} ranks poorly by ESPN metrics. {conclusion}"
        return f"Model analysis for {last_name}. {conclusion}"

    sentence1 = parts[0][0].upper() + parts[0][1:]
    if len(parts) > 1:
        sentence1 += " and " + parts[1]
    sentence1 += "."

    return f"{sentence1} {conclusion}"


# ── Main merge & score ───────────────────────────────────────────────────────

def merge_and_score(
    field: dict,
    preds: list,
    skills: list,
    decomps: list,
    odds_data: dict,
) -> list[dict]:
    """Merge all data sources and return a scored, sorted player list.

    Args:
        field:     Output of espn.get_field() — contains event info and player list.
        preds:     Unused (kept for API compatibility).
        skills:    Output of espn.get_stats() — ESPN stats per player, keyed by
                   athlete_id and player_name.
        decomps:   Unused (kept for API compatibility).
        odds_data: Dict keyed by normalised player name from odds fetcher.

    Player IDs from the scoreboard (competitor["id"]) should match
    athlete["id"] from the stats API, so we index by both id and name.
    """
    players_raw = field.get("players", [])

    # Index skills by ESPN athlete_id (int) and normalised name
    skills_by_id: dict[int, dict] = {
        s["athlete_id"]: s for s in skills if s.get("athlete_id") is not None
    }
    skills_by_name: dict[str, dict] = {
        _norm_name(s["player_name"]): s for s in skills if s.get("player_name")
    }

    players: list[dict] = []
    for raw in players_raw:
        pid = raw.get("dg_id")   # ESPN athlete id (int or None)
        name = raw.get("player_name") or ""
        norm = _norm_name(name)

        # Prefer id match, fall back to name match
        skill = (
            (skills_by_id.get(pid) if pid is not None else None)
            or skills_by_name.get(norm)
            or {}
        )

        player: dict = {
            "dg_id": pid,
            "player_name": name,
            "country": raw.get("country") or "",
            # ESPN stats — stored in both raw keys (for model) and sg_* keys (for DB/display)
            # sg_total is not available from ESPN; shown as N/A
            "sg_total": None,
            "sg_ott": skill.get("driving_dist"),      # repurposed: driving distance
            "sg_app": skill.get("gir_pct"),            # repurposed: GIR %
            "sg_atg": skill.get("birdies_per_round"),  # repurposed: birdies/round
            "sg_putt": skill.get("putts_per_hole"),    # repurposed: putts/hole
            # Raw ESPN stats for model calculation
            "scoring_avg": skill.get("scoring_avg"),
            "gir_pct": skill.get("gir_pct"),
            "driving_dist": skill.get("driving_dist"),
            "driving_acc": skill.get("driving_acc"),
            "birdies_per_round": skill.get("birdies_per_round"),
            "putts_per_hole": skill.get("putts_per_hole"),
            # Course/form not available from ESPN
            "course_history_sg": None,
            "course_history_rounds": None,
            "recent_form_sg": None,
            # Model probabilities (filled by sg_to_win_probs below)
            "dg_win_prob": None,
            "dg_top5_prob": None,
            "dg_top10_prob": None,
            "dg_top20_prob": None,
            # Market probabilities (filled from odds below)
            "mkt_win_prob": None,
            "mkt_top10_prob": None,
            "odds_win_american": None,
            "odds_top10_american": None,
            # Edges and output
            "edge_win": None,
            "edge_top10": None,
            "recommendation": "No Data",
            "blurb": "",
        }
        players.append(player)

    # Generate model probabilities from ESPN stats
    players = sg_to_win_probs(players)

    # ── Merge odds ──────────────────────────────────────────────────────────
    if odds_data:
        # Collect raw implied win probabilities for vig removal across the field
        raw_win_probs: list[Optional[float]] = []
        for p in players:
            norm = _norm_name(p["player_name"])
            odd = odds_data.get(norm) or {}
            win_am = odd.get("win_american")
            raw_prob = american_to_prob(win_am) if win_am is not None else None
            raw_win_probs.append(raw_prob)

        # Remove vig across all players with odds
        valid_probs = [prob for prob in raw_win_probs if prob is not None]
        if valid_probs:
            total_overround = sum(valid_probs)
            vig_removed: list[Optional[float]] = [
                (prob / total_overround if prob is not None else None)
                for prob in raw_win_probs
            ]
        else:
            vig_removed = list(raw_win_probs)

        for i, p in enumerate(players):
            norm = _norm_name(p["player_name"])
            odd = odds_data.get(norm) or {}
            win_am = odd.get("win_american")
            top10_am = odd.get("top10_american")

            p["odds_win_american"] = win_am
            p["odds_top10_american"] = top10_am
            p["mkt_win_prob"] = vig_removed[i]
            if top10_am is not None:
                p["mkt_top10_prob"] = american_to_prob(top10_am)

            p["edge_win"] = calc_edge(p["dg_win_prob"], p["mkt_win_prob"])
            p["edge_top10"] = calc_edge(p["dg_top10_prob"], p["mkt_top10_prob"])

    # ── Recommendations and blurbs ──────────────────────────────────────────
    for p in players:
        # Prefer top10 edge for recommendation; fall back to win edge
        edge = p["edge_top10"] if p["edge_top10"] is not None else p["edge_win"]
        p["recommendation"] = get_recommendation(edge)
        p["blurb"] = generate_blurb(p)

    # ── Sort ────────────────────────────────────────────────────────────────
    # Primary: players with any edge first, nulls last
    # Secondary: edge_top10 DESC, then edge_win DESC
    players.sort(key=lambda p: (
        p["edge_top10"] is None and p["edge_win"] is None,
        -(p["edge_top10"] or p["edge_win"] or 0),
    ))

    return players
