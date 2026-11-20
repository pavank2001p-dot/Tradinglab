"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type Market, type MarketList } from "./api";

export const DEFAULT_SYMBOL = "XAUUSD";
const KEY = "goldlab-market";
const EVENT = "goldlab-market";

// Gold's rules, so pages render at once before the list arrives (and the fallback when nothing is chosen yet).
export const GOLD: Market = {
  symbol: "XAUUSD", name: "Gold", asset_class: "metals", class_label: "Metals", decimals: 2, unit: "ounce", lot: 100,
  default_units: 5, spread: 0.3, max_leverage: 1000, hours: "Sunday 18:00 to Friday 17:00 New York time, with a break from 17:00 to 18:00 each day", open_now: true, live: true, swap_long: -0.25,
  swap_short: 0.05, swap_long_pct: 0, swap_short_pct: 0, price: null, as_of: null, has_seconds: true, has_history: true,
  group: "Precious metals", ticker: "XAU/USD", quote: "USD", core: true,
};

/** The app is Trading Lab; each kind of market has its own lab. Metals, energy and agriculture are commodities;
 *  ETFs sit with stocks. */
export const APP_NAME = "Trading Lab";
export const LABS: Record<string, string> = {
  metals: "Commodity Lab", energy: "Commodity Lab", agriculture: "Commodity Lab", forex: "Forex Lab", indices: "Index Lab",
  stocks: "Stock Lab", etfs: "Stock Lab", crypto: "Crypto Lab",
};
/** Asset classes in display order, with their labels (the server sends the same list). */
export const CLASSES: [string, string][] = [
  ["metals", "Metals"], ["energy", "Energy"], ["agriculture", "Agriculture"], ["forex", "Forex"], ["indices", "Indices"],
  ["stocks", "Stocks"], ["etfs", "ETFs"], ["crypto", "Crypto"],
];

/** US dollars per one unit of the market's quote currency at this price: 1 for dollar-quoted markets, 1 / price for
 *  USD/xxx pairs (USD/JPY), else the day's rate. Multiply a price move times units by this to get dollars. */
export function toUsd(m: Pick<Market, "quote" | "base_usd" | "usd_rate">, price?: number | null): number {
  if (!m.quote || m.quote === "USD") return 1;
  if (m.base_usd) return price ? 1 / price : 0;
  return m.usd_rate ?? 1;
}
export const labName = (m: Pick<Market, "asset_class">) => LABS[m.asset_class] ?? APP_NAME;

let cache: Promise<MarketList> | null = null;
export function loadMarkets(): Promise<MarketList> {
  if (!cache) cache = api.markets().catch((e) => { cache = null; throw e; });
  return cache;
}

/** Every market on offer (gold alone until the list loads). */
export function useMarkets(): Market[] {
  const [list, setList] = useState<Market[]>([GOLD]);
  useEffect(() => { loadMarkets().then((m) => setList(m.markets), () => {}); }, []);
  return list;
}

function readSymbol(): string {
  try { return localStorage.getItem(KEY) || DEFAULT_SYMBOL; } catch { return DEFAULT_SYMBOL; }
}

const opened = new Set<string>();
/** Markets outside the core list load their prices the first time someone opens them; tell the server once per page. */
function openOnce(symbol: string) {
  if (opened.has(symbol)) return;
  opened.add(symbol);
  api.openMarket(symbol).then((r) => { if (r.status === "loading") cache = null; }, () => opened.delete(symbol));
}

/** Whether this browser has picked a market yet (the home page asks first-time visitors which one). */
export function hasChosenMarket(): boolean {
  try { return !!localStorage.getItem(KEY); } catch { return true; }
}

/** The market the user is looking at, shared by the chart, paper trading and backtests and kept in this
 *  browser, so switching to Apple on the chart opens Apple on the paper page too. */
export function useMarket(): [Market, (symbol: string) => void, Market[]] {
  const markets = useMarkets();
  const [symbol, setSymbolState] = useState(DEFAULT_SYMBOL);
  useEffect(() => {
    const fromUrl = new URLSearchParams(window.location.search).get("symbol")?.toUpperCase();
    const first = fromUrl || readSymbol();
    setSymbolState(first);
    openOnce(first);
    const on = () => setSymbolState(readSymbol());
    window.addEventListener(EVENT, on);
    window.addEventListener("storage", on);
    return () => { window.removeEventListener(EVENT, on); window.removeEventListener("storage", on); };
  }, []);
  const setSymbol = useCallback((s: string) => {
    try { localStorage.setItem(KEY, s); } catch {}
    setSymbolState(s);
    window.dispatchEvent(new Event(EVENT));
    openOnce(s);
  }, []);
  const market = markets.find((m) => m.symbol === symbol) ?? (symbol === DEFAULT_SYMBOL ? GOLD : markets[0] ?? GOLD);
  return [market, setSymbol, markets];
}

/** A price with the market's own decimals (5 for EUR/USD, 2 for gold and stocks). */
export function fmtMarketPrice(p: number | null | undefined, m: Pick<Market, "decimals">): string {
  if (p == null) return "–";
  return p.toLocaleString("en-US", { minimumFractionDigits: m.decimals, maximumFractionDigits: m.decimals });
}

/** Short display name for the market's ticker, like "XAU/USD", "AAPL" or "S&P 500". */
export function ticker(m: Pick<Market, "symbol" | "asset_class" | "name" | "ticker">): string {
  if (m.ticker) return m.ticker;
  if (m.asset_class === "stocks" || m.asset_class === "etfs") return m.symbol.replace(/USUSD$/, "");
  if (["indices", "energy", "agriculture"].includes(m.asset_class)) return m.name;
  if (m.symbol.length === 6) return `${m.symbol.slice(0, 3)}/${m.symbol.slice(3)}`;
  return m.symbol;
}

/** "ounces", "shares", "units"... for sizes. */
export function unitsLabel(m: Pick<Market, "unit">, n?: number): string {
  const u = m.unit === "MMBtu" ? "MMBtu" : m.unit;
  if (n === 1 || u === "MMBtu") return u;
  return `${u}s`;
}
