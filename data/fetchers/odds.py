"""The Odds API fetcher for golf markets.

Module-level CREDITS_REMAINING is updated after each successful API call.
"""
import unicodedata
import re
import requests
import config

_BASE = config.ODDS_API_BASE_URL
_KEY = config.ODDS_API_KEY
_TIMEOUT = 15

# Updated after each successful odds fetch
CREDITS_REMAINING: int | None = None


def _normalize_name(name: str) -> str:
    """Lowercase, strip accents, strip punctuation."""
    nfkd = unicodedata.normalize("NFD", name)
    ascii_name = nfkd.encode("ascii", "ignore").decode("ascii")
    ascii_name = ascii_name.lower()
    ascii_name = re.sub(r"[^a-z0-9\s]", "", ascii_name)
    ascii_name = re.sub(r"\s+", " ", ascii_name).strip()
    return ascii_name


def _american_to_prob(odds: float) -> float:
    if odds >= 0:
        return 100.0 / (odds + 100.0)
    else:
        return abs(odds) / (abs(odds) + 100.0)


def get_golf_odds() -> dict:
    """Return dict mapping normalized_player_name -> odds info.

    Shape:
        {
          "scottie scheffler": {
            "win_american": -200,
            "win_prob": 0.667,
            "top10_american": -400,
            "top10_prob": 0.8,
          },
          ...
        }
    """
    global CREDITS_REMAINING

    if not _KEY:
        print("[odds] ODDS_API_KEY not set — skipping odds fetch")
        return {}

    try:
        # Step 1: find active golf sport keys
        sports_resp = requests.get(
            f"{_BASE}/sports/",
            params={"apiKey": _KEY},
            timeout=_TIMEOUT,
        )
        sports_resp.raise_for_status()

        # Update credits from header if present
        remaining_header = sports_resp.headers.get("X-Requests-Remaining")
        if remaining_header is not None:
            try:
                CREDITS_REMAINING = int(remaining_header)
            except ValueError:
                pass

        sports = sports_resp.json()
        golf_keys = [
            s["key"]
            for s in sports
            if s.get("group", "").lower() == "golf" and s.get("active", False)
        ]

        if not golf_keys:
            print("[odds] No active golf sport keys found")
            return {}

        # Step 2: fetch odds for each golf sport key
        # Accumulate: player_name -> list of (win_odds, top10_odds)
        win_accumulator: dict[str, list] = {}
        top10_accumulator: dict[str, list] = {}

        for sport_key in golf_keys:
            try:
                odds_resp = requests.get(
                    f"{_BASE}/sports/{sport_key}/odds/",
                    params={
                        "apiKey": _KEY,
                        "regions": "us",
                        "markets": "outrights",
                        "oddsFormat": "american",
                        "bookmakers": "draftkings,fanduel",
                    },
                    timeout=_TIMEOUT,
                )
                odds_resp.raise_for_status()

                remaining_header = odds_resp.headers.get("X-Requests-Remaining")
                if remaining_header is not None:
                    try:
                        CREDITS_REMAINING = int(remaining_header)
                    except ValueError:
                        pass

                events = odds_resp.json()
                if not isinstance(events, list):
                    continue

                for event in events:
                    for bookmaker in event.get("bookmakers", []):
                        for market in bookmaker.get("markets", []):
                            mkt_key = market.get("key", "")
                            outcomes = market.get("outcomes", [])

                            for outcome in outcomes:
                                raw_name = outcome.get("name", "")
                                price = outcome.get("price")
                                if not raw_name or price is None:
                                    continue

                                norm = _normalize_name(raw_name)

                                # outrights = win market; h2h with 3+ outcomes = outrights too
                                # "outrights" key covers win; look for top10 in key name
                                if "top_10" in mkt_key or "top10" in mkt_key:
                                    top10_accumulator.setdefault(norm, []).append(float(price))
                                else:
                                    # treat outrights as win market
                                    win_accumulator.setdefault(norm, []).append(float(price))

            except Exception as inner_exc:
                print(f"[odds] Failed fetching odds for sport_key={sport_key}: {inner_exc}")
                continue

        # Step 3: average odds across bookmakers, compute probs, build result
        result: dict = {}
        all_norms = set(win_accumulator) | set(top10_accumulator)

        # Collect raw probs for vig removal
        win_probs_raw: dict[str, float] = {}
        top10_probs_raw: dict[str, float] = {}

        for norm in all_norms:
            win_odds_list = win_accumulator.get(norm, [])
            if win_odds_list:
                avg_win = sum(win_odds_list) / len(win_odds_list)
                win_probs_raw[norm] = _american_to_prob(avg_win)

            top10_odds_list = top10_accumulator.get(norm, [])
            if top10_odds_list:
                avg_top10 = sum(top10_odds_list) / len(top10_odds_list)
                top10_probs_raw[norm] = _american_to_prob(avg_top10)

        # Vig-remove win probs
        if win_probs_raw:
            total_win = sum(win_probs_raw.values())
            win_probs_vigfree = {n: p / total_win for n, p in win_probs_raw.items()} if total_win > 0 else win_probs_raw
        else:
            win_probs_vigfree = {}

        # Vig-remove top10 probs
        if top10_probs_raw:
            total_top10 = sum(top10_probs_raw.values())
            top10_probs_vigfree = {n: p / total_top10 for n, p in top10_probs_raw.items()} if total_top10 > 0 else top10_probs_raw
        else:
            top10_probs_vigfree = {}

        for norm in all_norms:
            win_odds_list = win_accumulator.get(norm, [])
            top10_odds_list = top10_accumulator.get(norm, [])

            avg_win_american = int(round(sum(win_odds_list) / len(win_odds_list))) if win_odds_list else None
            avg_top10_american = int(round(sum(top10_odds_list) / len(top10_odds_list))) if top10_odds_list else None

            result[norm] = {
                "win_american": avg_win_american,
                "win_prob": win_probs_vigfree.get(norm),
                "top10_american": avg_top10_american,
                "top10_prob": top10_probs_vigfree.get(norm),
            }

        return result

    except Exception as exc:
        print(f"[odds] get_golf_odds failed: {exc}")
        return {}
