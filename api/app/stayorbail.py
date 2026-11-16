"""Stay or Bail: feel a bad year of gold in your own money, one month at a time.

Episodes are the twelve-month stretches since 1971 (when gold began to trade freely) with the deepest fall from
the starting month, picked from the stored monthly closes so they never overlap. Each comes with the twelve months
that followed, so the page can show what staying longer would have meant. The page asks after each month whether
to stay or bail; the month someone bails, against the drawdown they said they could live with in the risk quiz, is
the point of the exercise.

History only; it says nothing about future prices."""

from datetime import datetime, timezone

from fastapi import APIRouter

from . import prices

router = APIRouter(prefix="/risk", tags=["risk"])

SINCE = datetime(1971, 1, 1, tzinfo=timezone.utc)
WINDOW = 12
AFTER = 12
EPISODES = 4
MIN_FALL = -0.10    # a stretch must fall at least this far to be worth sitting through


def worst(closes: list[float], window: int = WINDOW) -> list[tuple[float, int]]:
    """(deepest fall within `window` months as a fraction, start index) for every start that has room to finish."""
    out = []
    for s in range(len(closes) - window):
        dd = min(closes[s:s + window + 1]) / closes[s] - 1
        out.append((dd, s))
    return out


def pick(closes: list[float], n: int = EPISODES) -> list[int]:
    """Start indexes of the `n` deepest non-overlapping windows, oldest first. Among equally deep windows the
    latest start wins, so the fall begins soon after the first month instead of after a long flat stretch."""
    chosen: list[int] = []
    for dd, s in sorted(worst(closes), key=lambda x: (x[0], -x[1])):
        if dd > MIN_FALL:
            break
        if all(abs(s - c) > WINDOW + AFTER for c in chosen):
            chosen.append(s)
        if len(chosen) == n:
            break
    return sorted(chosen)


@router.get("/stay-or-bail")
def stay_or_bail():
    bars = prices.candles(tf="1mo", start=int(SINCE.timestamp()), end=None, limit=2000, symbol="XAUUSD")["bars"]
    closes = [b["c"] for b in bars]
    out = []
    for s in pick(closes):
        base = closes[s]
        seg = bars[s:s + WINDOW + AFTER + 1]
        months = [{"t": b["t"], "level": round(b["c"] / base * 100, 2)} for b in seg]
        low = min(m["level"] for m in months[:WINDOW + 1])
        out.append({"start": bars[s]["t"], "price": round(base, 2), "months": months, "window": WINDOW,
                    "worst_pct": round(low - 100, 1)})
    return {"episodes": out}
