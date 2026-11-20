"""The markets Trading Lab can chart, backtest and paper trade.

The account is kept in US dollars. Most markets are quoted in dollars too; the rest (USD/JPY, the DAX,
the FTSE...) have a `quote` currency, and `usd(price)` turns a move in their price into dollars: exactly
from the market's own price for pairs that start with the dollar (USD/JPY), otherwise at the day's
reference rate from app.fx. Every place that turns price moves into money goes through it.

History comes from Dukascopy's free datafeed (the same feed as gold; no key). Their stocks, ETFs,
indices and commodities are CFDs that track the underlying market. Live quotes come from Finnhub's
websocket when FINNHUB_API_KEY is set (free plan: US stocks, OANDA forex and CFDs, Binance crypto).
Prices are stored as bids, like gold.

Only the markets in CORE are kept up to date all the time. Every other market in the catalog is loaded
the first time someone opens it (app.ingest.ensure) and then kept up to date while people use it, so a
catalog of a couple of hundred markets doesn't fill the database with prices nobody looks at.

Per-class rules:
- trading hours (`hours`): "fx" is Sunday 18:00 to Friday 17:00 New York with a daily 17:00-18:00
  break (forex, metals, energy, most index CFDs); "us_stock" is 09:30-16:00 New York on weekdays;
  "eu" is 08:00-22:00 Frankfurt time on weekdays (European index CFDs); "in" is 09:15-15:30 India
  time on weekdays; "always" is around the clock (crypto).
- `max_leverage` caps the account's leverage for that market, like a broker's per-class limits.
- `spread` is in price units, paid once per round trip; swap is the overnight financing.
"""

import math
import os
from dataclasses import dataclass, field
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
FRANKFURT = ZoneInfo("Europe/Berlin")
INDIA = ZoneInfo("Asia/Kolkata")

# Asset classes in display order. Each market also has a `group` inside its class: a stock's sector,
# a pair's kind (majors, crosses, exotics), an index's region, a commodity's type.
CLASSES = {
    "metals": "Metals",
    "energy": "Energy",
    "agriculture": "Agriculture",
    "forex": "Forex",
    "indices": "Indices",
    "stocks": "Stocks",
    "etfs": "ETFs",
    "crypto": "Crypto",
}


@dataclass(frozen=True)
class Instrument:
    symbol: str          # our key, also the Dukascopy datafeed code
    name: str
    asset_class: str     # a key of CLASSES
    ref_price: float     # rough current price, used to check the feed's price scale
    decimals: int        # price decimals shown and rounded to
    unit: str            # what one unit is ("ounce", "share", "barrel"...)
    lot: float           # units in one standard lot / contract
    default_units: float  # a sensible starting trade size
    spread: float        # price units, paid once per round trip
    max_leverage: int
    hours: str           # "fx", "us_stock", "eu", "in" or "always"
    live: str = ""       # Finnhub symbol for live quotes
    # Overnight financing. Either fixed per unit per night (gold, kept as it always was) or
    # an annual rate on the position's value (everything else); negative is a cost.
    swap_long: float | None = None
    swap_short: float | None = None
    swap_long_pct: float = -6.0
    swap_short_pct: float = -1.0
    day: str = "ny17"    # when a daily bar closes: 17:00 New York ("ny17") or midnight UTC ("utc")
    point: float = 1000.0  # Dukascopy stores prices as integers; divide by this
    tags: tuple[str, ...] = field(default_factory=tuple)  # extra search words (tickers, nicknames)
    group: str = ""      # sector, region or kind inside the asset class
    quote: str = "USD"   # the currency prices are in
    country: str = ""    # the economy whose calendar moves it most (ISO currency code), if not the quote's

    @property
    def class_label(self) -> str:
        return CLASSES[self.asset_class]

    @property
    def base_usd(self) -> bool:
        """A pair that starts with the dollar (USD/JPY): its own price converts its moves to dollars."""
        return self.asset_class == "forex" and self.symbol.startswith("USD") and self.quote != "USD"

    def usd(self, price: float | None = None) -> float:
        """US dollars per one unit of the quote currency, at this price of the market.
        1 for dollar-quoted markets; 1 / price for USD/xxx pairs; otherwise the day's reference rate."""
        if self.quote == "USD":
            return 1.0
        if self.base_usd and price:
            return 1.0 / price
        from . import fx  # imported here: app.fx doesn't need the registry, and tests swap its rates
        return fx.usd_per(self.quote)

    @property
    def currencies(self) -> set[str]:
        """Currencies whose economic releases move this market: the dollar always, plus its own."""
        out = {"USD", self.quote}
        if self.asset_class == "forex":
            out |= {self.symbol[:3], self.symbol[3:6]}
        if self.country:
            out.add(self.country)
        return out

    def swap_per_unit(self, side: str, price: float) -> float:
        """Financing per unit for one night held, at this price, in US dollars."""
        fixed = self.swap_long if side == "long" else self.swap_short
        if fixed is not None:
            return fixed
        pct = self.swap_long_pct if side == "long" else self.swap_short_pct
        return price * pct / 100 / 365 * self.usd(price)

    def is_open(self, at: datetime) -> bool:
        """Inside normal trading hours (holidays aside; a stale price catches those)."""
        if self.hours == "always":
            return True
        if self.hours == "us_stock":
            ny = at.astimezone(NY)
            return ny.weekday() < 5 and time(9, 30) <= ny.time() < time(16, 0)
        if self.hours == "eu":
            fr = at.astimezone(FRANKFURT)
            return fr.weekday() < 5 and time(8, 0) <= fr.time() < time(22, 0)
        if self.hours == "in":
            ind = at.astimezone(INDIA)
            return ind.weekday() < 5 and time(9, 15) <= ind.time() < time(15, 30)
        ny = at.astimezone(NY)
        wd, h = ny.weekday(), ny.hour  # Monday = 0
        if h == 17 or wd == 5 or (wd == 4 and h >= 17) or (wd == 6 and h < 18):
            return False
        return True

    @property
    def session_hours(self) -> bool:
        """Trades in a set session each day (stocks, European and Indian indices), so a price left over
        from the last session must not count as the current one."""
        return self.hours in ("us_stock", "eu", "in")

    def hours_text(self) -> str:
        return {
            "fx": "Sunday 18:00 to Friday 17:00 New York time, with a break from 17:00 to 18:00 each day",
            "us_stock": "09:30 to 16:00 New York time, Monday to Friday",
            "eu": "08:00 to 22:00 Frankfurt time, Monday to Friday",
            "in": "09:15 to 15:30 India time, Monday to Friday",
            "always": "around the clock, every day",
        }[self.hours]

    def round(self, price: float) -> float:
        return round(price, self.decimals)

    @property
    def weekends(self) -> bool:
        """Trades on Saturdays and Sundays too (crypto)."""
        return self.hours == "always"

    @property
    def year_days(self) -> int:
        """Trading days in a year, for turning daily volatility into yearly."""
        return 365 if self.weekends else 252

    @property
    def tick(self) -> float:
        """The smallest price step shown (0.01 for gold, 0.00001 for EUR/USD)."""
        return 10 ** -self.decimals

    @property
    def ticker(self) -> str:
        """Short display code: "AAPL", "XAU/USD", "EUR/USD" or the name for indices and commodities."""
        if self.asset_class in ("stocks", "etfs"):
            return self.symbol.removesuffix("USUSD")
        if self.asset_class in ("forex", "crypto") or self.symbol in ("XAUUSD", "XAGUSD"):
            return f"{self.symbol[:3]}/{self.symbol[3:6]}"
        return self.name

    def units_text(self, n: float) -> str:
        """A size in this market's own unit, like "5 oz", "10,000 units" or "3 shares"."""
        u = "oz" if self.unit == "ounce" else self.unit if self.unit == "MMBtu" or n == 1 else f"{self.unit}s"
        return f"{n:,.{0 if float(n).is_integer() else 2}f} {u}"

    def price_text(self, p: float) -> str:
        sym = CURRENCY_SIGN.get(self.quote)
        num = f"{p:,.{self.decimals}f}"
        return f"{sym}{num}" if sym else f"{num} {self.quote}"

    def money_text(self, usd_amount: float) -> str:
        return f"${usd_amount:,.2f}"

    def public(self) -> dict:
        return {
            "symbol": self.symbol, "name": self.name, "asset_class": self.asset_class,
            "class_label": self.class_label, "group": self.group, "ticker": self.ticker, "tags": list(self.tags),
            "decimals": self.decimals, "unit": self.unit, "lot": self.lot,
            "default_units": self.default_units, "spread": self.spread, "max_leverage": self.max_leverage,
            "hours": self.hours_text(), "open_now": self.is_open(datetime.now(timezone.utc)),
            "live": bool(self.live), "swap_long": self.swap_long, "swap_short": self.swap_short,
            "swap_long_pct": self.swap_long_pct, "swap_short_pct": self.swap_short_pct,
            "tick": self.tick, "tick_value": round(self.tick * self.lot * self.usd(self.ref_price), 6),
            "weekends": self.weekends, "quote": self.quote, "base_usd": self.base_usd,
            "usd_rate": None if self.base_usd else round(self.usd(), 8), "core": self.symbol in CORE,
        }


CURRENCY_SIGN = {"USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥", "INR": "₹"}

# --- Building blocks --------------------------------------------------------------------------------

_FX = dict(asset_class="forex", unit="unit", lot=100_000, default_units=10_000, max_leverage=500, hours="fx",
           point=100_000, swap_long_pct=-2.0, swap_short_pct=-2.0)
_STOCK = dict(asset_class="stocks", unit="share", lot=1, default_units=10, max_leverage=20, hours="us_stock",
              decimals=2, swap_long_pct=-6.0, swap_short_pct=-3.0)
_ETF = dict(_STOCK, asset_class="etfs")
_INDEX = dict(asset_class="indices", unit="contract", lot=1, default_units=1, max_leverage=200, hours="fx",
              decimals=1, swap_long_pct=-6.0, swap_short_pct=-1.0)
_CRYPTO = dict(asset_class="crypto", unit="coin", lot=1, max_leverage=10, hours="always",
               swap_long_pct=-10.0, swap_short_pct=-10.0, day="utc", group="Coins")


def _pair(code: str, name: str, ref: float, spread: float, group: str, live: str = "", lev: int = 500,
          **kw) -> Instrument:
    """A currency pair. Pairs quoted in yen have 3 decimals, the rest 5; the quote is the last three letters."""
    quote = code[3:]
    dec = 3 if quote == "JPY" else (4 if ref >= 10 else 5)
    return Instrument(code, name, ref_price=ref, spread=spread, decimals=dec, live=live, group=group, quote=quote,
                      **{**_FX, "max_leverage": lev, **kw})


def _stock(code: str, name: str, ref: float, sector: str, live: str = "", tags: tuple[str, ...] = (),
           etf: bool = False) -> Instrument:
    """A US-listed stock or ETF; the spread is about 0.03% of the price, at least a cent."""
    base = _ETF if etf else _STOCK
    spread = max(round(ref * 0.0003, 2), 0.01)
    return Instrument(f"{code}USUSD", name, ref_price=ref, spread=spread, live=live or code, group=sector,
                      tags=(code, *tags), **base)


def _index(code: str, name: str, ref: float, spread: float, region: str, quote: str = "USD", live: str = "",
           hours: str = "fx", tags: tuple[str, ...] = (), country: str = "", **kw) -> Instrument:
    return Instrument(code, name, ref_price=ref, spread=spread, live=live, group=region, quote=quote, tags=tags,
                      country=country, **{**_INDEX, "hours": hours, "day": "ny17" if hours == "fx" else "utc", **kw})


# --- The catalog ------------------------------------------------------------------------------------
# Feed codes follow Dukascopy's naming. A code the feed turns out not to carry is found by
# app.ingest.probe and hidden from the list rather than shown empty.

ALL: list[Instrument] = [
    # Metals
    Instrument("XAUUSD", "Gold", "metals", 2600, 2, "ounce", 100, 5, 0.30, 1000, "fx", "OANDA:XAU_USD",
               swap_long=-0.25, swap_short=0.05, group="Precious metals", tags=("XAU", "bullion")),
    Instrument("XAGUSD", "Silver", "metals", 30, 3, "ounce", 5000, 200, 0.03, 500, "fx", "OANDA:XAG_USD",
               group="Precious metals", tags=("XAG",)),
    Instrument("XPTCMDUSD", "Platinum", "metals", 1000, 2, "ounce", 50, 5, 1.5, 100, "fx",
               group="Precious metals", tags=("XPT",)),
    Instrument("XPDCMDUSD", "Palladium", "metals", 1000, 2, "ounce", 100, 5, 3.0, 100, "fx",
               group="Precious metals", tags=("XPD",)),
    Instrument("COPPERCMDUSD", "Copper", "metals", 4.5, 4, "pound", 25_000, 1000, 0.004, 100, "fx",
               group="Industrial metals", tags=("HG",)),
    # Energy
    Instrument("LIGHTCMDUSD", "WTI crude oil", "energy", 70, 2, "barrel", 1000, 50, 0.04, 200, "fx",
               "OANDA:WTICO_USD", group="Oil", tags=("WTI", "crude", "oil", "CL")),
    Instrument("BRENTCMDUSD", "Brent crude oil", "energy", 75, 2, "barrel", 1000, 50, 0.04, 200, "fx",
               "OANDA:BCO_USD", group="Oil", tags=("Brent", "crude", "oil")),
    Instrument("GASCMDUSD", "Natural gas", "energy", 3, 3, "MMBtu", 10_000, 1000, 0.006, 200, "fx",
               "OANDA:NATGAS_USD", group="Gas", tags=("NG", "natgas")),
    Instrument("DIESELCMDUSD", "Gas oil (diesel)", "energy", 700, 2, "tonne", 100, 10, 1.0, 100, "fx",
               group="Oil", tags=("diesel", "gasoil")),
    # Agriculture
    Instrument("WHEATCMDUSX", "Wheat", "agriculture", 5.5, 4, "bushel", 5000, 500, 0.01, 50, "fx",
               group="Grains", tags=("ZW", "grain")),
    Instrument("SOYBEANCMDUSX", "Soybeans", "agriculture", 10.5, 4, "bushel", 5000, 200, 0.012, 50, "fx",
               group="Grains", tags=("ZS", "soy", "grain")),
    Instrument("COFFEECMDUSX", "Coffee", "agriculture", 3.5, 4, "pound", 37_500, 1000, 0.01, 50, "fx",
               group="Softs", tags=("KC", "arabica")),
    Instrument("COCOACMDUSD", "Cocoa", "agriculture", 6000, 0, "tonne", 10, 1, 15.0, 50, "fx",
               group="Softs", tags=("CC",)),
    Instrument("SUGARCMDUSD", "Sugar", "agriculture", 450, 2, "tonne", 50, 10, 1.0, 50, "fx",
               group="Softs", tags=("SB",)),
    Instrument("COTTONCMDUSX", "Cotton", "agriculture", 0.68, 4, "pound", 50_000, 5000, 0.003, 50, "fx",
               group="Softs", tags=("CT",)),
    Instrument("OJUICECMDUSX", "Orange juice", "agriculture", 2.5, 4, "pound", 15_000, 1000, 0.02, 20, "fx",
               group="Softs", tags=("OJ",)),

    # Forex: majors
    _pair("EURUSD", "Euro / US dollar", 1.1, 0.0001, "Majors", "OANDA:EUR_USD", tags=("fiber",)),
    _pair("GBPUSD", "British pound / US dollar", 1.3, 0.00015, "Majors", "OANDA:GBP_USD", tags=("cable",)),
    _pair("USDJPY", "US dollar / Japanese yen", 150, 0.012, "Majors", "OANDA:USD_JPY"),
    _pair("USDCHF", "US dollar / Swiss franc", 0.88, 0.00015, "Majors", "OANDA:USD_CHF", tags=("swissie",)),
    _pair("AUDUSD", "Australian dollar / US dollar", 0.66, 0.00012, "Majors", "OANDA:AUD_USD", tags=("aussie",)),
    _pair("USDCAD", "US dollar / Canadian dollar", 1.38, 0.00018, "Majors", "OANDA:USD_CAD", tags=("loonie",)),
    _pair("NZDUSD", "New Zealand dollar / US dollar", 0.6, 0.00018, "Majors", "OANDA:NZD_USD", tags=("kiwi",)),
    # Forex: crosses
    _pair("EURGBP", "Euro / British pound", 0.85, 0.00015, "Crosses", "OANDA:EUR_GBP"),
    _pair("EURJPY", "Euro / Japanese yen", 160, 0.018, "Crosses", "OANDA:EUR_JPY"),
    _pair("GBPJPY", "British pound / Japanese yen", 190, 0.025, "Crosses", "OANDA:GBP_JPY"),
    _pair("EURCHF", "Euro / Swiss franc", 0.94, 0.0002, "Crosses", "OANDA:EUR_CHF"),
    _pair("EURAUD", "Euro / Australian dollar", 1.65, 0.00025, "Crosses", "OANDA:EUR_AUD"),
    _pair("EURCAD", "Euro / Canadian dollar", 1.5, 0.00025, "Crosses", "OANDA:EUR_CAD"),
    _pair("GBPCHF", "British pound / Swiss franc", 1.12, 0.00028, "Crosses", "OANDA:GBP_CHF"),
    _pair("GBPAUD", "British pound / Australian dollar", 1.95, 0.0003, "Crosses", "OANDA:GBP_AUD"),
    _pair("AUDJPY", "Australian dollar / Japanese yen", 98, 0.018, "Crosses", "OANDA:AUD_JPY"),
    _pair("CADJPY", "Canadian dollar / Japanese yen", 108, 0.02, "Crosses", "OANDA:CAD_JPY"),
    _pair("CHFJPY", "Swiss franc / Japanese yen", 170, 0.025, "Crosses", "OANDA:CHF_JPY"),
    _pair("NZDJPY", "New Zealand dollar / Japanese yen", 90, 0.022, "Crosses", "OANDA:NZD_JPY"),
    _pair("AUDNZD", "Australian dollar / New Zealand dollar", 1.1, 0.00025, "Crosses", "OANDA:AUD_NZD"),
    _pair("AUDCAD", "Australian dollar / Canadian dollar", 0.91, 0.00022, "Crosses", "OANDA:AUD_CAD"),
    # Forex: exotics (wider spreads, lower leverage)
    _pair("USDCNH", "US dollar / Chinese yuan (offshore)", 7.2, 0.002, "Exotics", "OANDA:USD_CNH", lev=50,
          tags=("yuan", "renminbi", "CNY")),
    _pair("USDHKD", "US dollar / Hong Kong dollar", 7.8, 0.002, "Exotics", "OANDA:USD_HKD", lev=50),
    _pair("USDSGD", "US dollar / Singapore dollar", 1.34, 0.0003, "Exotics", "OANDA:USD_SGD", lev=50),
    _pair("USDMXN", "US dollar / Mexican peso", 18.5, 0.006, "Exotics", "OANDA:USD_MXN", lev=50),
    _pair("USDZAR", "US dollar / South African rand", 18.0, 0.01, "Exotics", "OANDA:USD_ZAR", lev=50),
    _pair("USDTRY", "US dollar / Turkish lira", 40.0, 0.05, "Exotics", "OANDA:USD_TRY", lev=20),
    _pair("USDNOK", "US dollar / Norwegian krone", 10.8, 0.004, "Exotics", "OANDA:USD_NOK", lev=50),
    _pair("USDSEK", "US dollar / Swedish krona", 10.5, 0.004, "Exotics", "OANDA:USD_SEK", lev=50),
    _pair("USDPLN", "US dollar / Polish zloty", 4.0, 0.002, "Exotics", "OANDA:USD_PLN", lev=50),

    # Indices
    _index("USA500IDXUSD", "S&P 500", 6000, 0.6, "Americas", live="OANDA:SPX500_USD", tags=("SPX", "US500", "S&P 500")),
    _index("USATECHIDXUSD", "Nasdaq 100", 21000, 1.5, "Americas", live="OANDA:NAS100_USD", tags=("NDX", "US100", "Nasdaq")),
    _index("USA30IDXUSD", "Dow Jones 30", 44000, 3.0, "Americas", live="OANDA:US30_USD", tags=("DJIA", "US30", "Dow Jones", "Dow")),
    _index("USSC2000IDXUSD", "Russell 2000", 2300, 0.5, "Americas", tags=("RUT", "US2000", "small caps")),
    _index("DEUIDXEUR", "Germany 40 (DAX)", 23000, 2.0, "Europe", quote="EUR", hours="eu", tags=("DAX", "DE40")),
    _index("GBRIDXGBP", "UK 100 (FTSE)", 8800, 1.5, "Europe", quote="GBP", hours="eu", tags=("FTSE", "UK100")),
    _index("FRAIDXEUR", "France 40 (CAC)", 7800, 1.5, "Europe", quote="EUR", hours="eu", tags=("CAC 40", "FR40")),
    _index("EUSIDXEUR", "Euro Stoxx 50", 5300, 2.0, "Europe", quote="EUR", hours="eu", tags=("SX5E", "EU50")),
    _index("ESPIDXEUR", "Spain 35 (IBEX)", 14000, 6.0, "Europe", quote="EUR", hours="eu", tags=("IBEX", "ES35")),
    _index("NLDIDXEUR", "Netherlands 25 (AEX)", 900, 0.3, "Europe", quote="EUR", hours="eu", decimals=2,
           tags=("AEX", "NL25")),
    _index("CHEIDXCHF", "Switzerland 20 (SMI)", 12000, 3.0, "Europe", quote="CHF", hours="eu", tags=("SMI", "CH20")),
    _index("JPNIDXJPY", "Japan 225 (Nikkei)", 39000, 10.0, "Asia-Pacific", quote="JPY", tags=("Nikkei", "JP225")),
    _index("HKGIDXHKD", "Hong Kong 50 (Hang Seng)", 23000, 8.0, "Asia-Pacific", quote="HKD", tags=("HSI", "HK50")),
    _index("AUSIDXAUD", "Australia 200 (ASX)", 8300, 1.0, "Asia-Pacific", quote="AUD", tags=("ASX", "AU200")),
    _index("CHIIDXUSD", "China A50", 13500, 8.0, "Asia-Pacific", country="CNY", tags=("A50", "CN50", "China")),
    _index("INDIDXUSD", "India 50 (Nifty)", 24500, 8.0, "Asia-Pacific", hours="in", country="INR",
           tags=("Nifty", "NSE", "IN50", "India")),

    # Stocks by sector (US-listed)
    _stock("AAPL", "Apple", 230, "Technology"),
    _stock("MSFT", "Microsoft", 450, "Technology"),
    _stock("NVDA", "Nvidia", 150, "Technology"),
    _stock("AMD", "AMD", 140, "Technology"),
    _stock("INTC", "Intel", 25, "Technology"),
    _stock("AVGO", "Broadcom", 230, "Technology"),
    _stock("ORCL", "Oracle", 180, "Technology"),
    _stock("ADBE", "Adobe", 450, "Technology"),
    _stock("CRM", "Salesforce", 300, "Technology"),
    _stock("CSCO", "Cisco", 60, "Technology"),
    _stock("IBM", "IBM", 230, "Technology"),
    _stock("QCOM", "Qualcomm", 160, "Technology"),
    _stock("GOOGL", "Alphabet (Google)", 190, "Communication", tags=("Google",)),
    _stock("META", "Meta (Facebook)", 600, "Communication", tags=("Facebook", "FB")),
    _stock("NFLX", "Netflix", 900, "Communication"),
    _stock("DIS", "Disney", 110, "Communication"),
    _stock("T", "AT&T", 25, "Communication"),
    _stock("VZ", "Verizon", 42, "Communication"),
    _stock("CMCSA", "Comcast", 38, "Communication"),
    _stock("AMZN", "Amazon", 210, "Consumer"),
    _stock("TSLA", "Tesla", 300, "Consumer"),
    _stock("HD", "Home Depot", 400, "Consumer"),
    _stock("MCD", "McDonald's", 300, "Consumer"),
    _stock("NKE", "Nike", 75, "Consumer"),
    _stock("SBUX", "Starbucks", 100, "Consumer"),
    _stock("F", "Ford", 10, "Consumer"),
    _stock("GM", "General Motors", 50, "Consumer"),
    _stock("WMT", "Walmart", 90, "Staples"),
    _stock("COST", "Costco", 900, "Staples"),
    _stock("KO", "Coca-Cola", 65, "Staples"),
    _stock("PEP", "PepsiCo", 150, "Staples"),
    _stock("PG", "Procter & Gamble", 165, "Staples"),
    _stock("JNJ", "Johnson & Johnson", 155, "Healthcare"),
    _stock("UNH", "UnitedHealth", 500, "Healthcare"),
    _stock("LLY", "Eli Lilly", 800, "Healthcare", tags=("Lilly",)),
    _stock("PFE", "Pfizer", 26, "Healthcare"),
    _stock("MRK", "Merck", 100, "Healthcare"),
    _stock("ABBV", "AbbVie", 180, "Healthcare"),
    _stock("JPM", "JPMorgan Chase", 240, "Financials", tags=("JPMorgan", "JP Morgan")),
    _stock("BAC", "Bank of America", 45, "Financials", tags=("BofA",)),
    _stock("WFC", "Wells Fargo", 70, "Financials"),
    _stock("C", "Citigroup", 70, "Financials"),
    _stock("GS", "Goldman Sachs", 580, "Financials"),
    _stock("MS", "Morgan Stanley", 130, "Financials"),
    _stock("V", "Visa", 320, "Financials"),
    _stock("MA", "Mastercard", 520, "Financials"),
    _stock("PYPL", "PayPal", 80, "Financials"),
    _stock("XOM", "Exxon Mobil", 110, "Energy", tags=("Exxon", "ExxonMobil")),
    _stock("CVX", "Chevron", 150, "Energy"),
    _stock("BA", "Boeing", 170, "Industrials"),
    _stock("CAT", "Caterpillar", 380, "Industrials"),
    _stock("GE", "GE Aerospace", 190, "Industrials"),
    _stock("MMM", "3M", 130, "Industrials"),
    _stock("UPS", "UPS", 120, "Industrials"),
    _stock("BABA", "Alibaba", 100, "International"),
    _stock("TSM", "TSMC", 190, "International", tags=("Taiwan Semiconductor",)),

    # ETFs: whole sectors, regions and asset classes in one trade
    _stock("SPY", "S&P 500 ETF", 600, "Broad market", etf=True),
    _stock("QQQ", "Nasdaq 100 ETF", 520, "Broad market", etf=True),
    _stock("IWM", "Russell 2000 ETF", 225, "Broad market", etf=True),
    _stock("XLK", "Technology sector ETF", 230, "Sectors", etf=True, tags=("tech",)),
    _stock("XLF", "Financials sector ETF", 48, "Sectors", etf=True, tags=("banks",)),
    _stock("XLE", "Energy sector ETF", 90, "Sectors", etf=True, tags=("oil",)),
    _stock("XLV", "Healthcare sector ETF", 145, "Sectors", etf=True, tags=("health",)),
    _stock("XLY", "Consumer discretionary ETF", 210, "Sectors", etf=True),
    _stock("XLP", "Consumer staples ETF", 80, "Sectors", etf=True),
    _stock("XLI", "Industrials sector ETF", 135, "Sectors", etf=True),
    _stock("XLB", "Materials sector ETF", 90, "Sectors", etf=True),
    _stock("XLU", "Utilities sector ETF", 78, "Sectors", etf=True),
    _stock("EEM", "Emerging markets ETF", 44, "Regions", etf=True),
    _stock("INDA", "India ETF", 53, "Regions", etf=True, tags=("India", "Nifty")),
    _stock("FXI", "China large-cap ETF", 32, "Regions", etf=True, tags=("China",)),
    _stock("EWJ", "Japan ETF", 70, "Regions", etf=True, tags=("Japan",)),
    _stock("EWZ", "Brazil ETF", 28, "Regions", etf=True, tags=("Brazil",)),
    _stock("GLD", "Gold ETF", 240, "Commodities & bonds", etf=True),
    _stock("SLV", "Silver ETF", 28, "Commodities & bonds", etf=True),
    _stock("USO", "Oil ETF", 75, "Commodities & bonds", etf=True),
    _stock("GDX", "Gold miners ETF", 40, "Commodities & bonds", etf=True),
    _stock("TLT", "20+ year Treasury bond ETF", 90, "Commodities & bonds", etf=True, tags=("bonds", "treasuries")),

    # Crypto
    Instrument("BTCUSD", "Bitcoin", ref_price=90_000, decimals=1, default_units=0.1, spread=30.0,
               live="BINANCE:BTCUSDT", tags=("BTC",), **_CRYPTO),
    Instrument("ETHUSD", "Ethereum", ref_price=3000, decimals=2, default_units=1, spread=2.0,
               live="BINANCE:ETHUSDT", tags=("ETH",), **_CRYPTO),
    Instrument("LTCUSD", "Litecoin", ref_price=90, decimals=2, default_units=10, spread=0.15,
               live="BINANCE:LTCUSDT", tags=("LTC",), **_CRYPTO),
    Instrument("BCHUSD", "Bitcoin Cash", ref_price=400, decimals=2, default_units=2, spread=0.8,
               live="BINANCE:BCHUSDT", tags=("BCH",), **_CRYPTO),
    Instrument("XRPUSD", "XRP", ref_price=2.2, decimals=4, default_units=500, spread=0.004,
               live="BINANCE:XRPUSDT", tags=("Ripple",), **_CRYPTO),
    Instrument("SOLUSD", "Solana", ref_price=180, decimals=2, default_units=5, spread=0.3,
               live="BINANCE:SOLUSDT", tags=("SOL",), **_CRYPTO),
    Instrument("ADAUSD", "Cardano", ref_price=0.7, decimals=4, default_units=1000, spread=0.0015,
               live="BINANCE:ADAUSDT", tags=("ADA",), **_CRYPTO),
    Instrument("DOGEUSD", "Dogecoin", ref_price=0.2, decimals=5, default_units=5000, spread=0.0004,
               live="BINANCE:DOGEUSDT", tags=("DOGE",), **_CRYPTO),
    Instrument("LNKUSD", "Chainlink", ref_price=18, decimals=3, default_units=50, spread=0.04,
               live="BINANCE:LINKUSDT", tags=("LINK",), **_CRYPTO),
    Instrument("XLMUSD", "Stellar", ref_price=0.3, decimals=5, default_units=3000, spread=0.0008,
               live="BINANCE:XLMUSDT", tags=("XLM",), **_CRYPTO),
    Instrument("UNIUSD", "Uniswap", ref_price=10, decimals=3, default_units=100, spread=0.03,
               live="BINANCE:UNIUSDT", tags=("UNI",), **_CRYPTO),
    Instrument("AVEUSD", "Aave", ref_price=250, decimals=2, default_units=4, spread=0.6,
               live="BINANCE:AAVEUSDT", tags=("AAVE",), **_CRYPTO),
]

DEFAULT = "XAUUSD"
GOLD = ALL[0]

# Markets kept up to date all the time; the rest load when first opened. MARKETS_PRELOAD overrides it.
CORE_DEFAULT = ("XAUUSD,XAGUSD,LIGHTCMDUSD,BRENTCMDUSD,GASCMDUSD,EURUSD,GBPUSD,USDJPY,AUDUSD,USA500IDXUSD,"
                "USATECHIDXUSD,USA30IDXUSD,DEUIDXEUR,INDIDXUSD,AAPLUSUSD,MSFTUSUSD,NVDAUSUSD,AMZNUSUSD,"
                "TSLAUSUSD,BTCUSD,ETHUSD")


def _enabled() -> list[Instrument]:
    """MARKETS picks which instruments are offered ("all" or a comma list of symbols)."""
    raw = os.getenv("MARKETS", "all").strip()
    if not raw or raw.lower() == "all":
        return ALL
    want = {s.strip().upper() for s in raw.split(",") if s.strip()} | {DEFAULT}
    return [i for i in ALL if i.symbol in want]


ENABLED: list[Instrument] = _enabled()
BY_SYMBOL: dict[str, Instrument] = {i.symbol: i for i in ENABLED}
CORE: frozenset[str] = frozenset(
    s for s in (x.strip().upper() for x in os.getenv("MARKETS_PRELOAD", CORE_DEFAULT).split(",")) if s in BY_SYMBOL
) | {DEFAULT}


def get(symbol: str | None) -> Instrument:
    """The instrument for a symbol (gold when none is given). Raises KeyError for unknown ones."""
    if not symbol:
        return GOLD
    return BY_SYMBOL[symbol.upper()]


def known(symbol: str | None) -> Instrument:
    """The rules of a stored row's market, even one switched off since (gold when unknown)."""
    sym = (symbol or DEFAULT).upper()
    return BY_SYMBOL.get(sym) or next((i for i in ALL if i.symbol == sym), GOLD)


def by_live_symbol(live: str) -> Instrument | None:
    return next((i for i in ENABLED if i.live == live), None)


def fit_point(raw: float, ref: float) -> float:
    """The power of ten that turns a raw feed integer into a price closest to the reference price.
    The feed's scale differs by instrument and isn't published, so it is checked against real data."""
    if raw <= 0 or ref <= 0:
        return 1000.0
    k = round(math.log10(raw / ref))
    return float(10 ** max(0, min(k, 8)))
