"""DataGolf compatibility shim.

DataGolf requires a paid subscription, so we use free alternatives:
  - ESPN unofficial API  for field/event data  (data.fetchers.espn)
  - PGA Tour public stats API for strokes gained (data.fetchers.pgatour)

Importing code that previously called datagolf.get_field(),
datagolf.get_skill_ratings(), etc. will transparently use the new sources.
"""
from .espn import get_field            # noqa: F401  (re-exported)
from .pgatour import get_skill_ratings, get_decompositions  # noqa: F401


def get_pre_tournament_preds() -> list:
    """DataGolf provided pre-built win/top5/top10/top20 model probabilities.

    Without DataGolf these probabilities are computed in model.py from SG stats
    via sg_to_win_probs(). Return empty list; model.merge_and_score() handles it.
    """
    return []
