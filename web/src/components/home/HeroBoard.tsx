"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, type Bar, type Market } from "@/lib/api";
import { fmtMarketPrice, labName, ticker, useMarkets } from "@/lib/markets";

/** One market from four different labs, so the first screen already shows the range on offer. */
const PICKS = ["XAUUSD", "USA500IDXUSD", "EURUSD", "BTCUSD"];
const TONES: Record<string, string> = {
  metals: "var(--gold)", energy: "var(--gold)", indices: "var(--calm)", forex: "var(--up)", stocks: "var(--rose)", crypto: "var(--violet)",
};
const HOURS = 48;

function Spark({ bars, up }: { bars: Bar[]; up: boolean }) {
  const w = 120, h = 36;
  const lo = Math.min(...bars.map((b) => b.c)), hi = Math.max(...bars.map((b) => b.c));
  const pts = bars.map((b, i) => [(i / (bars.length - 1)) * w, h - 3 - ((b.c - lo) / (hi - lo || 1)) * (h - 6)] as const);
  const line = pts.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`).join("");
  const colour = up ? "var(--up)" : "var(--down)";
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="h-9 w-[7.5rem] shrink-0" aria-hidden>
      <path d={`${line}L${w} ${h}L0 ${h}Z`} fill={colour} opacity="0.12" />
      <path d={line} fill="none" stroke={colour} strokeWidth="1.6" strokeLinejoin="round" strokeLinecap="round" pathLength={1} className="spark-draw" />
    </svg>
  );
}

function Row({ m, delay }: { m: Market; delay: number }) {
  const [bars, setBars] = useState<Bar[] | null>(null);
  useEffect(() => { api.candles("1h", { symbol: m.symbol, limit: HOURS }).then(setBars, () => {}); }, [m.symbol]);
  const ok = bars && bars.length > 2;
  const first = ok ? bars[0].c : 0, last = ok ? bars[bars.length - 1].c : 0;
  const pct = ok ? ((last - first) / first) * 100 : 0;
  const tone = TONES[m.asset_class] ?? "var(--gold)";
  return (
    <li className="rise-in" style={{ animationDelay: `${delay}ms` }}>
      <Link href={`/chart?symbol=${m.symbol}`}
        className="flex items-center gap-3 rounded-xl border border-transparent px-3 py-2.5 transition-colors hover:border-border hover:bg-surface-2">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-[11px] font-bold"
          style={{ color: tone, background: `color-mix(in srgb, ${tone} 16%, transparent)` }}>
          {ticker(m).replace(/[^A-Za-z0-9&]/g, "").slice(0, 3).toUpperCase()}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-semibold">{m.asset_class === "forex" ? ticker(m) : m.name}</span>
          <span className="block text-[11px] text-muted">{labName(m)}</span>
        </span>
        {ok ? <Spark bars={bars} up={pct >= 0} /> : <span className="h-9 w-[7.5rem] shrink-0" />}
        <span className="w-20 shrink-0 text-right tabular-nums">
          <span className="block text-sm font-semibold">{fmtMarketPrice(ok ? last : m.price, m)}</span>
          {ok && <span className={`block text-[11px] ${pct >= 0 ? "text-up" : "text-down"}`}>{pct >= 0 ? "+" : ""}{pct.toFixed(2)}%</span>}
        </span>
      </Link>
    </li>
  );
}

/** A floating board of four markets beside the headline: real hourly prices, each row opens its chart. */
export default function HeroBoard() {
  const markets = useMarkets();
  const picks = PICKS.map((s) => markets.find((m) => m.symbol === s)).filter((m) => m != null);
  if (picks.length < 2) return null;
  return (
    <div className="float-slow relative">
      <div aria-hidden className="absolute -inset-6 rounded-[2.5rem] bg-[conic-gradient(from_140deg,var(--gold),var(--violet),var(--calm),var(--up),var(--gold))] opacity-25 blur-3xl" />
      <div className="lux relative p-3.5">
        <div className="flex items-center justify-between px-3 pb-3 pt-2">
          <p className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-muted">
            <span className="breathe h-1.5 w-1.5 rounded-full bg-up" /> Markets · last {HOURS} hours
          </p>
          <Link href="/chart" className="text-xs font-medium text-gold hover:underline">All {markets.length}</Link>
        </div>
        <ul>{picks.map((m, i) => <Row key={m.symbol} m={m} delay={200 + i * 90} />)}</ul>
      </div>
    </div>
  );
}
