"""Market news: pull headlines from Finnhub, work out which markets and sectors each one is about, and have
Claude tag each as bullish, bearish or neutral for the market it is mainly about, with a one-line reason.

A headline is matched to markets by their names and nicknames (app.instruments), to asset classes and
stock sectors by keywords ("oil", "bank stocks", "chipmakers"), and to the macro picture (rates,
inflation, jobs) when it is about the economy in general. Company news for the stocks people are using
comes from Finnhub's per-company feed and is tied to that stock directly. Each stored item keeps:
- symbols: the markets it names,
- sectors: "class" and "class:group" keys ("stocks", "stocks:Financials", "energy"),
- focus: the one market its tag is about (the first market named; the S&P 500 for macro news).
"""

import json
import logging
import re
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache

import anthropic
import httpx
from fastapi import APIRouter, Query

from . import config, db
from . import instruments as ins

log = logging.getLogger("news")
router = APIRouter(prefix="/news", tags=["news"])

FINNHUB = "https://finnhub.io/api/v1/news"
FINNHUB_COMPANY = "https://finnhub.io/api/v1/company-news"
CATEGORIES = ("general", "forex", "crypto", "merger")
COMPANY_MAX = 20  # stocks whose own feed is read per run (Finnhub's free plan allows 60 calls a minute)
MACRO_FOCUS = "USA500IDXUSD"

MACRO = re.compile(
    r"\b(fed|fomc|federal reserve|powell|interest rates?|rate (cut|hike)s?|inflation|cpi|pce|payrolls?|"
    r"jobs report|treasur(y|ies)|bond yields?|yields?|recession|central banks?|safe[- ]haven|"
    r"geopolitic\w*|war|sanctions?|tariffs?|gdp|economy|economic)\b",
    re.I,
)
GOLD = re.compile(r"\b(gold|xau|bullion)\b", re.I)  # kept for callers that still ask about gold alone

# Words that point at a whole asset class or a stock sector, when no single market is named.
SECTOR_WORDS: list[tuple[str, str]] = [
    (r"precious metals?|metals? prices?|miners?|mining", "metals"),
    (r"oil|crude|opec\+?|natural gas|lng|gasoline|refiner\w*|energy prices?", "energy"),
    (r"grains?|crops?|harvest|wheat|corn|soy\w*|coffee|cocoa|sugar|cotton|farm\w*", "agriculture"),
    (r"forex|currenc(y|ies)|exchange rates?|dollar|euro|yen|sterling|franc|yuan|renminbi|rupee|peso|lira|"
     r"rand|ecb|boj|bank of japan|boe|bank of england|rba|snb|rbnz|pboc|fx", "forex"),
    (r"stocks?|equit(y|ies)|wall street|s&p|nasdaq|dow|ftse|dax|nikkei|hang seng|sensex|nifty|"
     r"stock markets?|index futures", "indices"),
    (r"bitcoin|crypto\w*|ethereum|blockchain|stablecoins?|tokens?|defi|binance|coinbase", "crypto"),
    (r"etfs?|exchange-traded", "etfs"),
    (r"tech(nology)? stocks|chip\w*|semiconductor\w*|software|artificial intelligence|\bai\b|cloud|big tech",
     "stocks:Technology"),
    (r"banks?|lenders?|bank stocks|financials|insurers?|brokerage|fintech|payments?", "stocks:Financials"),
    (r"drug\w*|pharma\w*|biotech|healthcare|health care|vaccines?|fda", "stocks:Healthcare"),
    (r"retail(ers)?|consumer spending|automakers?|carmakers?|evs?|electric vehicles?|restaurants?", "stocks:Consumer"),
    (r"grocer\w*|supermarkets?|beverages?|household goods|consumer staples", "stocks:Staples"),
    (r"airlines?|aerospace|defen[cs]e (stocks|contractors?)|manufactur\w*|industrials?|railroads?|freight",
     "stocks:Industrials"),
    (r"telecoms?|media|streaming|social media|advertis\w*", "stocks:Communication"),
    (r"oil majors?|oil stocks|energy stocks|drillers?", "stocks:Energy"),
]

# Short words that are also tickers or common English; matched only in these exact forms.
CURRENCY_WORDS = {
    "EURUSD": r"euro", "GBPUSD": r"sterling|british pound|the pound", "USDJPY": r"yen", "USDCHF": r"swiss franc",
    "AUDUSD": r"australian dollar|aussie dollar", "USDCAD": r"canadian dollar|loonie",
    "NZDUSD": r"new zealand dollar|kiwi dollar", "USDCNH": r"yuan|renminbi", "USDMXN": r"mexican peso",
    "USDTRY": r"turkish lira|lira", "USDZAR": r"rand", "INDIDXUSD": r"india|indian|sensex|nifty|rbi|rupee",
    "INDAUSUSD": r"india|indian", "JPNIDXJPY": r"japan|japanese|nikkei", "DEUIDXEUR": r"germany|german|dax",
    "GBRIDXGBP": r"ftse|britain|british|uk economy", "CHIIDXUSD": r"china|chinese", "HKGIDXHKD": r"hong kong|hang seng",
}


@lru_cache(maxsize=1)
def _patterns() -> list[tuple[re.Pattern, str]]:
    """(pattern, symbol) for every market: its name, nicknames and, for stocks, its ticker as written in
    news ("$AAPL", "(AAPL)", or any ticker of four letters or more)."""
    out = []
    for i in ins.ENABLED:
        words = set()
        name = re.sub(r"\s*\(.*?\)", "", i.name)  # "Germany 40 (DAX)" -> "Germany 40"; the tag covers DAX
        if i.asset_class == "stocks" and len(name) >= 3 or i.asset_class not in ("forex", "etfs", "stocks") and len(name) > 3:
            words.add(re.escape(name))
        if i.asset_class != "etfs":  # an ETF's tags ("oil", "banks") describe its sector, not the fund
            for t in i.tags:
                if len(t) >= 4 or len(t) == 3 and t.upper() != t:
                    words.add(re.escape(t))
        if i.asset_class in ("stocks", "etfs"):
            tk = re.escape(i.ticker)
            out.append((re.compile(rf"\$({tk})\b|\(({tk})\)|\b(NYSE|NASDAQ|Nasdaq): ?{tk}\b"), i.symbol))
        if i.asset_class == "forex":
            out.append((re.compile(rf"\b{i.symbol[:3]}/?{i.symbol[3:]}\b"), i.symbol))
        if i.symbol in CURRENCY_WORDS:
            out.append((re.compile(rf"\b({CURRENCY_WORDS[i.symbol]})\b", re.I), i.symbol))
        if words:
            # Names of companies and coins are matched case-sensitively ("Apple", not "apple"; "Stellar", not
            # "stellar"); commodity and index names are not.
            flags = 0 if i.asset_class in ("stocks", "etfs", "crypto") else re.I
            out.append((re.compile(rf"\b({'|'.join(sorted(words, key=len, reverse=True))})\b", flags), i.symbol))
    return out


_SECTOR_RE = [(re.compile(rf"\b({w})\b", re.I), key) for w, key in SECTOR_WORDS]


def classify_text(text: str, related: str = "") -> tuple[list[str], list[str]]:
    """(symbols, sectors) a headline is about. `related` is Finnhub's comma list of tickers, when given."""
    symbols: list[str] = []
    for pat, sym in _patterns():
        if sym not in symbols and pat.search(text):
            symbols.append(sym)
    for t in (x.strip().upper() for x in related.split(",") if x.strip()):
        sym = f"{t}USUSD"
        if sym in ins.BY_SYMBOL and sym not in symbols:
            symbols.insert(0, sym)
    sectors: list[str] = []

    def add(key: str) -> None:
        if key not in sectors:
            sectors.append(key)

    for sym in symbols:
        m = ins.BY_SYMBOL[sym]
        add(m.asset_class)
        if m.group:
            add(f"{m.asset_class}:{m.group}")
    for pat, key in _SECTOR_RE:
        if pat.search(text):
            add(key.split(":")[0])
            add(key)
    return symbols, sectors


def relevance(text: str) -> int:
    """2 = about a market or sector we carry, 1 = about the economy in general, 0 = ignore."""
    symbols, sectors = classify_text(text)
    if symbols or sectors:
        return 2
    return 1 if MACRO.search(text) else 0


def focus_of(symbols: list[str], relevance_: int) -> str | None:
    return symbols[0] if symbols else (MACRO_FOCUS if relevance_ else None)


def _item(item: dict, source: str = "finnhub") -> dict | None:
    text = f"{item.get('headline', '')} {item.get('summary', '')}"
    if not item.get("headline"):
        return None
    symbols, sectors = classify_text(text, item.get("related") or "")
    rel = 2 if symbols or sectors else (1 if MACRO.search(text) else 0)
    if not rel:
        return None
    return {
        "source": source,
        "external_id": str(item.get("id") or item.get("url")),
        "headline": item["headline"].strip()[:500],
        "summary": (item.get("summary") or "").strip()[:2000],
        "url": item.get("url") or "",
        "publisher": item.get("source") or "",
        "published_at": datetime.fromtimestamp(int(item["datetime"]), timezone.utc),
        "relevance": rel,
        "symbols": symbols,
        "sectors": sectors,
        "focus": focus_of(symbols, rel),
    }


def _company_symbols() -> list[str]:
    """Stocks to read company news for: the core list first, then those in use."""
    from .ingest import active_symbols  # imported here: ingest is heavy and news is imported early

    try:
        active = active_symbols()
    except Exception:  # noqa: BLE001
        active = set()
    stocks = [i for i in ins.ENABLED if i.asset_class == "stocks"]
    order = [i for i in stocks if i.symbol in ins.CORE] + [i for i in stocks if i.symbol in active and i.symbol not in ins.CORE]
    return [i.ticker for i in order][:COMPANY_MAX]


def fetch_finnhub() -> list[dict]:
    out = []
    with httpx.Client(timeout=20) as client:
        for category in CATEGORIES:
            try:
                r = client.get(FINNHUB, params={"category": category, "token": config.FINNHUB_API_KEY})
                r.raise_for_status()
            except httpx.HTTPError as e:
                log.warning("news %s failed: %s", category, e)
                continue
            out += [x for x in (_item(i) for i in r.json()) if x]
        today = date.today()
        for tk in _company_symbols():
            try:
                r = client.get(FINNHUB_COMPANY, params={"symbol": tk, "from": (today - timedelta(days=2)).isoformat(),
                                                        "to": today.isoformat(), "token": config.FINNHUB_API_KEY})
                r.raise_for_status()
            except httpx.HTTPError as e:
                log.warning("company news %s failed: %s", tk, e)
                continue
            for i in r.json()[:10]:
                x = _item({**i, "related": i.get("related") or tk})
                if x:
                    out.append(x)
    return out


def store(items: list[dict]) -> int:
    if not items:
        return 0
    rows = []
    for it in items:
        if "symbols" not in it:
            syms, secs = classify_text(f"{it['headline']} {it.get('summary', '')}")
            it = {**it, "symbols": syms, "sectors": secs, "focus": focus_of(syms, it.get("relevance", 1))}
        rows.append(it)
    with db.conn() as c, c.cursor() as cur:
        cur.executemany(
            """INSERT INTO news (source, external_id, headline, summary, url, publisher, published_at, relevance,
                                 symbols, sectors, focus)
               VALUES (%(source)s, %(external_id)s, %(headline)s, %(summary)s, %(url)s, %(publisher)s,
                       %(published_at)s, %(relevance)s, %(symbols)s, %(sectors)s, %(focus)s)
               ON CONFLICT (source, external_id) DO NOTHING""",
            rows,
        )
        return cur.rowcount


def backfill_markets() -> int:
    """Give headlines stored before markets were tracked their markets and sectors. Their tags were made for
    gold, so their focus is gold."""
    with db.conn() as c:
        rows = c.execute("SELECT id, headline, summary, impact, relevance FROM news WHERE symbols IS NULL").fetchall()
        for r in rows:
            syms, secs = classify_text(f"{r['headline']} {r['summary']}")
            focus = "XAUUSD" if r["impact"] else focus_of(syms, r["relevance"])
            if focus == "XAUUSD" and "XAUUSD" not in syms:
                syms = ["XAUUSD", *syms]
                secs = list(dict.fromkeys(["metals", "metals:Precious metals", *secs]))
            c.execute("UPDATE news SET symbols = %s, sectors = %s, focus = %s WHERE id = %s", (syms, secs, focus, r["id"]))
    return len(rows)


# ---------------------------------------------------------------------------
# Tagging with Claude
# ---------------------------------------------------------------------------

SYSTEM = (
    "You assess how news headlines are likely to affect the price of one named market in the short term: a "
    "commodity, currency pair, stock index, single stock, ETF or cryptocurrency. For each item, decide whether "
    "it is bullish, bearish or neutral for that market and give one plain-English sentence (under 25 words) "
    "saying why, written for a beginner. For a currency pair, bullish means the pair's price rises (the first "
    "currency strengthens against the second). Use neutral when the effect is unclear or minor. This is "
    "educational context, not a trading recommendation: never tell the reader to buy or sell."
)

SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "impact": {"type": "string", "enum": ["bullish", "bearish", "neutral"]},
                    "reason": {"type": "string"},
                },
                "required": ["id", "impact", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}


def market_label(symbol: str | None) -> str:
    m = ins.BY_SYMBOL.get(symbol or "") if symbol else None
    if not m:
        return "US stocks (S&P 500)"
    return m.name if m.ticker == m.name else f"{m.name} ({m.ticker})"


def classify(client: anthropic.Anthropic, rows: list[dict]) -> list[dict]:
    """One request per batch of headlines; returns [{id, impact, reason}]."""
    listing = "\n\n".join(
        f"id: {r['id']}\nmarket: {market_label(r.get('focus') or 'XAUUSD')}\nheadline: {r['headline']}\n"
        f"summary: {r['summary'][:600]}" for r in rows
    )
    resp = client.beta.messages.create(
        model=config.NEWS_MODEL,
        max_tokens=4000,
        system=SYSTEM,
        messages=[{"role": "user", "content": f"Tag each of these news items for its market:\n\n{listing}"}],
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if resp.stop_reason == "refusal":
        log.warning("news tagging declined: %s", getattr(resp.stop_details, "category", None))
        return []
    if resp.stop_reason == "max_tokens":
        log.warning("news tagging hit max_tokens; will retry next run")
        return []
    text = next(b.text for b in resp.content if b.type == "text")
    valid = {r["id"] for r in rows}
    return [i for i in json.loads(text)["items"] if i["id"] in valid]


def tag_pending(limit: int = 100) -> int:
    if not config.ANTHROPIC_API_KEY:
        return 0
    with db.conn() as c:
        rows = c.execute(
            "SELECT id, headline, summary, focus FROM news WHERE impact IS NULL ORDER BY published_at DESC LIMIT %s",
            (limit,),
        ).fetchall()
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    done = 0
    for i in range(0, len(rows), TAG_BATCH):
        try:
            tags = classify(client, rows[i : i + TAG_BATCH])
        except anthropic.APIError as e:
            log.warning("news tagging failed: %s", e)
            break
        with db.conn() as c:
            for t in tags:
                c.execute(
                    "UPDATE news SET impact = %s, reason = %s, tagged_at = now() WHERE id = %s",
                    (t["impact"], t["reason"].strip()[:300], t["id"]),
                )
        done += len(tags)
    return done


TAG_BATCH = 20


def update() -> tuple[int, int]:
    backfill_markets()
    added = store(fetch_finnhub()) if config.FINNHUB_API_KEY else 0
    return added, tag_pending()


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


@router.get("")
def list_(limit: int = Query(50, ge=1, le=200), gold_only: bool = False,
          symbol: str | None = Query(None, description="Headlines about this market or its sector"),
          sector: str | None = Query(None, description='An asset class ("energy") or class and group '
                                                       '("stocks:Financials"); "macro" for the economy in general')):
    if gold_only:
        symbol = "XAUUSD"
    where, args = [], []
    if symbol:
        m = ins.BY_SYMBOL.get(symbol.upper())
        if m:
            # The market itself, its sector, or (for anything priced in dollars) the big macro stories.
            keys = [f"{m.asset_class}:{m.group}"] if m.group and m.asset_class in ("stocks", "etfs") else [m.asset_class]
            where.append("(%s = ANY(symbols) OR sectors && %s::text[] OR focus = %s)")
            args += [m.symbol, keys, m.symbol]
    if sector:
        if sector == "macro":
            where.append("relevance = 1")
        else:
            where.append("%s = ANY(sectors)")
            args.append(sector)
    sql = ("SELECT id, headline, summary, url, publisher, published_at, relevance, impact, reason, "
           "coalesce(symbols, '{}') AS symbols, coalesce(sectors, '{}') AS sectors, focus FROM news")
    if where:
        sql += " WHERE " + " AND ".join(where)
    with db.conn() as c:
        rows = c.execute(sql + " ORDER BY published_at DESC LIMIT %s", (*args, limit)).fetchall()
    for r in rows:
        f = ins.BY_SYMBOL.get(r["focus"] or "")
        r["focus_name"] = (f.ticker if f and f.asset_class in ("stocks", "etfs", "forex", "crypto") else f.name) if f else None
    return {
        "configured": bool(config.FINNHUB_API_KEY),
        "tagging": bool(config.ANTHROPIC_API_KEY),
        "items": rows,
    }
