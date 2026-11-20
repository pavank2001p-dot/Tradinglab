"use client";

import Link from "next/link";
import { useState } from "react";
import type { Market } from "@/lib/api";
import { CLASSES, fmtMarketPrice, labName, ticker, useMarket } from "@/lib/markets";
import { groupMarkets } from "./MarketPicker";

const BLURB: Record<string, string> = {
  metals: "Gold, silver, platinum, palladium and copper",
  energy: "Crude oil, natural gas and diesel",
  agriculture: "Grains and softs: wheat, soybeans, coffee, cocoa, sugar, cotton",
  forex: "Majors, crosses and exotics, from EUR/USD to USD/MXN",
  indices: "Americas, Europe and Asia-Pacific, including the DAX, Nikkei and Nifty",
  stocks: "Every sector: tech, banks, healthcare, energy, consumer, industrials",
  etfs: "Whole sectors, regions, commodities and bonds in one trade",
  crypto: "Bitcoin, Ethereum and the other large coins",
};

/** Every market on offer, one card per asset class with its sectors or regions. Picking a market makes it the one
 *  the whole site uses (chart, paper trading, backtests, news). */
export default function MarketBrowser({ title = "Pick any market", subtitle, href = "/chart" }: {
  title?: string; subtitle?: string; href?: string;
}) {
  const [market, setSymbol, markets] = useMarket();
  const [cls, setCls] = useState<string | null>(null);
  const counts: Record<string, number> = {};
  for (const m of markets) counts[m.asset_class] = (counts[m.asset_class] ?? 0) + 1;
  const loaded = markets.length > 1;

  return (
    <div className="rounded-2xl border border-border bg-surface p-4 sm:p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-semibold">{title}</h2>
        <p className="text-xs text-muted">{loaded ? `${markets.length} markets` : "Loading markets…"} · now on <b className="text-foreground">{market.name}</b></p>
      </div>
      {subtitle && <p className="mt-1 text-sm text-muted">{subtitle}</p>}
      <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
        {CLASSES.filter(([k]) => counts[k] || !loaded).map(([k, label]) => (
          <button key={k} type="button" onClick={() => setCls(cls === k ? null : k)} aria-expanded={cls === k}
            className={`rounded-xl border p-3 text-left transition ${cls === k ? "border-gold bg-gold/10" : "border-border hover:border-muted"}`}>
            <p className="flex items-baseline justify-between gap-2 text-sm font-medium">{label}<span className="text-xs tabular-nums text-muted">{counts[k] ?? ""}</span></p>
            <p className="mt-1 text-[11px] leading-snug text-muted">{BLURB[k]}</p>
            <p className="mt-1.5 text-[10px] uppercase tracking-wide text-muted/80">{labName({ asset_class: k })}</p>
          </button>
        ))}
      </div>
      {cls && (
        <div className="mt-4 space-y-3">
          {groupMarkets(markets, cls, "").map((g) => (
            <div key={g.label}>
              <p className="text-[11px] uppercase tracking-wide text-muted">{g.label}</p>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {g.items.map((m: Market) => (
                  <Link key={m.symbol} href={`${href}?symbol=${m.symbol}`} onClick={() => setSymbol(m.symbol)}
                    className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs transition hover:border-gold ${m.symbol === market.symbol ? "border-gold text-gold" : "border-border"}`}>
                    <span>{m.name}</span>
                    {ticker(m) !== m.name && <span className="text-muted">{ticker(m)}</span>}
                    {m.price != null && <span className="tabular-nums text-muted">{fmtMarketPrice(m.price, m)}</span>}
                  </Link>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
