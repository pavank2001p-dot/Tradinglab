"""Economic calendar: the releases that move markets (central bank decisions, inflation, jobs, growth) for the
US and the other big economies, each tied to the markets it moves through Instrument.currencies. US releases
matter to every market, since everything here is priced against the dollar or trades through it."""

import logging
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Query

from . import config, db
from . import instruments as ins

log = logging.getLogger("calendar")
router = APIRouter(prefix="/calendar", tags=["calendar"])

# FOMC rate decisions for 2026 (second day of each meeting, statement at 14:00 New York = 18:00/19:00 UTC).
# Source: Federal Reserve meeting calendar. Re-check against federalreserve.gov each December.
FOMC_2026 = ["2026-01-28T19:00", "2026-03-18T18:00", "2026-04-29T18:00", "2026-06-17T18:00",
             "2026-07-29T18:00", "2026-09-16T18:00", "2026-10-28T18:00", "2026-12-09T19:00"]

# Economies the calendar keeps (the feed's currency codes). Others are left out.
COUNTRIES = {"USD", "EUR", "GBP", "JPY", "AUD", "NZD", "CAD", "CHF", "CNY"}
ECONOMY = {"USD": "US", "EUR": "euro-area", "GBP": "UK", "JPY": "Japanese", "AUD": "Australian",
           "NZD": "New Zealand", "CAD": "Canadian", "CHF": "Swiss", "CNY": "Chinese"}

# Why each kind of release matters, shown next to the event. {e} is the economy, {c} its currency.
EXPLAIN = [
    (("fomc", "federal funds", "fed chair", "powell", "interest rate decision", "rate decision", "rate statement",
      "monetary policy", "cash rate", "refinancing rate", "bank rate", "policy rate"),
     "Sets {e} interest rates. Rates move the {c} first, then bonds, stocks and commodities priced against it."),
    (("cpi", "pce", "ppi", "inflation"),
     "Measures {e} inflation. Hotter numbers can mean higher rates for longer: usually a stronger {c} and "
     "weaker stocks and gold in the short run."),
    (("non-farm", "nonfarm", "payroll", "unemployment", "jobless", "employment change", "claimant"),
     "Shows the {e} job market's strength, which shapes where rates go next and moves the {c}."),
    (("gdp", "retail sales", "ism", "pmi"),
     "Measures {e} growth. Weak numbers raise rate-cut hopes: often a softer {c} and mixed for stocks."),
]


def why(title: str, country: str = "USD") -> str:
    t = title.lower()
    text = next((text for keys, text in EXPLAIN if any(k in t for k in keys)), "")
    return text.format(e=ECONOMY.get(country, country), c="dollar" if country == "USD" else country)


def countries_for(symbol: str | None) -> set[str] | None:
    """The calendar currencies that move a market, or None for every one when no market is given."""
    if not symbol:
        return None
    try:
        return ins.get(symbol).currencies & COUNTRIES | {"USD"}
    except KeyError:
        return None


def seed_fomc() -> None:
    rows = [(datetime.fromisoformat(d).replace(tzinfo=timezone.utc), "FOMC rate decision") for d in FOMC_2026]
    with db.conn() as c, c.cursor() as cur:
        cur.executemany(
            """INSERT INTO events (ts, country, title, impact, source) VALUES (%s, 'USD', %s, 'High', 'federalreserve.gov')
               ON CONFLICT (title, ts) DO NOTHING""",
            rows,
        )


def fetch_feed() -> int:
    """Pull this week's high- and medium-impact events for the big economies from the public calendar feed."""
    if not config.CALENDAR_FEED_URL:
        return 0
    r = httpx.get(config.CALENDAR_FEED_URL, timeout=20, headers={"User-Agent": "tradinglab/1.0"})
    r.raise_for_status()
    rows = []
    for e in r.json():
        country = e.get("country")
        if country not in COUNTRIES or e.get("impact") not in ("High", "Medium"):
            continue
        try:
            ts = datetime.fromisoformat(e["date"]).astimezone(timezone.utc)
        except (KeyError, ValueError):
            continue
        rows.append((ts, country, e["title"][:200], e["impact"], e.get("forecast") or "", e.get("previous") or ""))
    with db.conn() as c, c.cursor() as cur:
        cur.executemany(
            """INSERT INTO events (ts, country, title, impact, forecast, previous, source)
               VALUES (%s, %s, %s, %s, %s, %s, 'forexfactory')
               ON CONFLICT (title, ts) DO UPDATE SET impact = EXCLUDED.impact,
                 forecast = EXCLUDED.forecast, previous = EXCLUDED.previous""",
            rows,
        )
    return len(rows)


def update() -> int:
    seed_fomc()
    try:
        return fetch_feed()
    except httpx.HTTPError as e:
        log.warning("calendar feed failed: %s", e)
        return 0


@router.get("")
def list_(days: int = Query(14, ge=1, le=90), past_days: int = Query(2, ge=0, le=30),
          symbol: str | None = Query(None, description="Only the economies that move this market")):
    now = datetime.now(timezone.utc)
    want = countries_for(symbol)
    with db.conn() as c:
        rows = c.execute(
            """SELECT id, ts, country, title, impact, forecast, previous, source FROM events
               WHERE ts >= %s AND ts < %s AND (%s::text[] IS NULL OR country = ANY(%s::text[])) ORDER BY ts""",
            (now - timedelta(days=past_days), now + timedelta(days=days), sorted(want) if want else None,
             sorted(want) if want else None),
        ).fetchall()
    return [{**r, "why": why(r["title"], r["country"])} for r in rows]


# ---------------------------------------------------------------------------
# Chart markers: scheduled releases from the calendar, plus a short list of turning points from
# recent market history, so a chart shows what was happening when the price moved. Each turning point
# names the markets it belongs on: an asset class, a symbol, or "*" for every market.
# ---------------------------------------------------------------------------

# (UTC date, title, kind, where). Kinds: fed, inflation, jobs, growth, dollar, shock.
HISTORY = [
    ("2008-03-16", "Bear Stearns rescued by JPMorgan", "shock", "*"),
    ("2008-09-15", "Lehman Brothers files for bankruptcy", "shock", "*"),
    ("2008-11-25", "Fed announces its first bond-buying programme (QE1)", "fed", "*"),
    ("2008-12-16", "Fed cuts rates to near zero", "fed", "*"),
    ("2010-05-06", "US stocks' flash crash", "shock", "indices stocks etfs"),
    ("2010-11-03", "Fed launches QE2", "fed", "*"),
    ("2011-08-05", "S&P downgrades the US credit rating", "shock", "*"),
    ("2011-09-06", "Swiss central bank caps the franc; gold near its 2011 peak", "dollar", "metals forex"),
    ("2012-07-26", "ECB's Draghi: \"whatever it takes\" to save the euro", "fed", "forex indices EURUSD"),
    ("2012-09-13", "Fed launches open-ended QE3", "fed", "*"),
    ("2013-04-15", "Gold's sharpest one-day fall in decades", "shock", "metals"),
    ("2013-05-22", "Fed chair Bernanke hints at slowing bond buying", "fed", "*"),
    ("2013-12-18", "Fed starts tapering bond purchases", "fed", "*"),
    ("2014-11-27", "OPEC declines to cut output; oil slides", "shock", "energy"),
    ("2015-01-15", "Swiss central bank drops the franc cap", "dollar", "forex metals"),
    ("2015-08-24", "China devalues the yuan; global stocks sell off", "shock", "*"),
    ("2015-12-16", "Fed raises rates for the first time since 2006", "fed", "*"),
    ("2016-06-24", "UK votes to leave the EU", "shock", "*"),
    ("2016-11-09", "US election result", "shock", "*"),
    ("2017-12-17", "Bitcoin peaks near $20,000", "shock", "crypto"),
    ("2018-02-05", "Volatility spike: the Dow's biggest point fall so far", "shock", "indices stocks etfs"),
    ("2019-07-31", "Fed's first rate cut since 2008", "fed", "*"),
    ("2020-03-03", "Fed makes an emergency half-point cut", "fed", "*"),
    ("2020-03-09", "Oil price war and pandemic fears crash markets", "shock", "*"),
    ("2020-03-15", "Fed cuts rates to near zero", "fed", "*"),
    ("2020-03-23", "Fed promises unlimited bond buying", "fed", "*"),
    ("2020-04-20", "US oil futures fall below zero", "shock", "energy"),
    ("2020-08-06", "Gold sets a record above $2,000", "shock", "metals"),
    ("2020-11-09", "First effective vaccine announced; stocks rally", "shock", "indices stocks etfs energy"),
    ("2021-11-10", "US inflation hits 6.2%, a 30-year high", "inflation", "*"),
    ("2022-02-24", "Russia invades Ukraine", "shock", "*"),
    ("2022-03-16", "Fed's first hike of the 2022 cycle", "fed", "*"),
    ("2022-06-10", "US inflation hits 8.6%", "inflation", "*"),
    ("2022-06-15", "Fed hikes by three quarters of a point", "fed", "*"),
    ("2022-09-23", "UK mini-budget: the pound and gilts plunge", "shock", "GBPUSD EURGBP GBPJPY GBPCHF GBPAUD GBRIDXGBP"),
    ("2022-09-28", "US dollar index at a 20-year high", "dollar", "*"),
    ("2022-10-21", "Japan buys yen to stop its slide", "dollar", "USDJPY EURJPY GBPJPY AUDJPY CADJPY CHFJPY NZDJPY JPNIDXJPY"),
    ("2022-11-11", "Crypto exchange FTX collapses", "shock", "crypto"),
    ("2023-03-10", "Silicon Valley Bank collapses", "shock", "*"),
    ("2023-07-26", "Fed's last hike of the cycle", "fed", "*"),
    ("2024-01-10", "US approves spot bitcoin ETFs", "shock", "crypto"),
    ("2024-08-05", "Yen carry trade unwinds; the Nikkei falls 12% in a day", "shock", "*"),
    ("2024-09-18", "Fed's first cut in four years, half a point", "fed", "*"),
    ("2025-01-27", "A cheap Chinese AI model knocks chip stocks", "shock", "NVDAUSUSD AVGOUSUSD AMDUSUSD USATECHIDXUSD QQQUSUSD XLKUSUSD"),
    ("2025-04-02", "US announces sweeping tariffs", "shock", "*"),
]

WHY_KIND = {
    "fed": "Central bank decisions change interest rates and the currency, which moves almost every market.",
    "inflation": "Inflation data shapes where rates go next, which moves currencies, bonds, stocks and gold.",
    "jobs": "Jobs data moves rate expectations and the currency, and the markets priced against it.",
    "growth": "Growth data shifts rate-cut hopes and earnings expectations.",
    "dollar": "Big currency moves show up in everything priced in that currency.",
    "shock": "Market shocks send money toward safety and force sales elsewhere, so many markets jump at once.",
}


def _belongs(where: str, inst: ins.Instrument | None) -> bool:
    if where == "*" or inst is None:
        return True
    keys = where.split()
    return inst.symbol in keys or inst.asset_class in keys


def kind_of(title: str) -> str:
    t = title.lower()
    for kind, keys in (("fed", ("fomc", "federal funds", "fed chair", "powell", "interest rate", "rate decision",
                                "monetary policy", "cash rate", "refinancing rate", "bank rate", "policy rate")),
                       ("inflation", ("cpi", "pce", "ppi", "inflation")),
                       ("jobs", ("non-farm", "nonfarm", "payroll", "unemployment", "jobless")),
                       ("growth", ("gdp", "retail sales", "ism", "pmi"))):
        if any(k in t for k in keys):
            return kind
    return "other"


@router.get("/markers")
def markers(start: int = Query(..., description="Unix seconds"), end: int = Query(...),
            scheduled: bool = Query(True, description="Include calendar releases, not only turning points"),
            symbol: str | None = Query(None, description="Only events that belong on this market's chart")):
    """Events between start and end for marking on a chart, oldest first."""
    a = datetime.fromtimestamp(start, tz=timezone.utc)
    b = datetime.fromtimestamp(end, tz=timezone.utc)
    inst = ins.BY_SYMBOL.get((symbol or "").upper()) if symbol else None
    want = countries_for(symbol)
    out = []
    for d, title, kind, where in HISTORY:
        ts = datetime.fromisoformat(d).replace(tzinfo=timezone.utc)
        if a <= ts < b and _belongs(where, inst):
            out.append({"t": int(ts.timestamp()), "title": title, "kind": kind, "impact": "High",
                        "why": WHY_KIND[kind], "history": True})
    if scheduled:
        with db.conn() as c:
            rows = c.execute("SELECT ts, country, title, impact FROM events WHERE ts >= %s AND ts < %s AND impact = 'High' "
                             "AND (%s::text[] IS NULL OR country = ANY(%s::text[])) ORDER BY ts LIMIT 2000",
                             (a, b, sorted(want) if want else None, sorted(want) if want else None)).fetchall()
        for r in rows:
            k = kind_of(r["title"])
            title = r["title"] if r["country"] == "USD" else f"{r['country']} {r['title']}"
            out.append({"t": int(r["ts"].timestamp()), "title": title, "kind": k, "impact": r["impact"],
                        "why": why(r["title"], r["country"]) or WHY_KIND.get(k, ""), "history": False})
    out.sort(key=lambda e: e["t"])
    return out
