"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { Market } from "@/lib/api";
import { CLASSES, fmtMarketPrice, ticker } from "@/lib/markets";
import { Icon } from "@/components/ui";
import { useKeepInView } from "@/lib/useKeepInView";

/** Every word a market can be found by: name, ticker, symbol, tags, sector or region, and asset class. */
function haystack(m: Market): string {
  return [m.name, m.symbol, ticker(m), m.group ?? "", m.class_label, ...(m.tags ?? [])].join(" ").toLowerCase();
}

/** Markets of one class (or all) matching a search, grouped by sector, region or kind. */
export function groupMarkets(markets: Market[], cls: string, q: string): { label: string; items: Market[] }[] {
  const words = q.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const hit = (m: Market) => (cls === "all" || m.asset_class === cls) && words.every((w) => haystack(m).includes(w));
  const out: { label: string; items: Market[] }[] = [];
  for (const m of markets.filter(hit)) {
    const label = cls === "all" ? `${m.class_label}${m.group ? ` · ${m.group}` : ""}` : m.group || m.class_label;
    const g = out.find((x) => x.label === label);
    if (g) g.items.push(m);
    else out.push({ label, items: [m] });
  }
  return out;
}

/** A compact button showing the current market. It opens a browser of every market: tabs for each asset class,
 *  markets grouped by sector, region or kind, and a search over names, tickers, sectors and nicknames. */
export default function MarketPicker({ market, markets, onChange, className = "" }: {
  market: Market; markets: Market[]; onChange: (symbol: string) => void; className?: string;
}) {
  const [open, setOpen] = useState(false);
  const panel = useKeepInView<HTMLDivElement>(open);
  const [q, setQ] = useState("");
  const [cls, setCls] = useState<string>("all");
  const wrap = useRef<HTMLDivElement>(null);
  const search = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    setCls(q ? "all" : market.asset_class);
    search.current?.focus();
    const away = (e: MouseEvent) => { if (!wrap.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", away); document.removeEventListener("keydown", esc); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // Typing searches every class; clearing the search goes back to the class that was open.
  const tab = q.trim() ? "all" : cls;
  const groups = useMemo(() => groupMarkets(markets, tab, q), [markets, tab, q]);
  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const m of markets) c[m.asset_class] = (c[m.asset_class] ?? 0) + 1;
    return c;
  }, [markets]);
  const tabs = [["all", "All"] as [string, string], ...CLASSES.filter(([k]) => counts[k])];

  const pick = (s: string) => { onChange(s); setOpen(false); setQ(""); };

  return (
    <div ref={wrap} className={`relative ${className}`}>
      <button type="button" onClick={() => setOpen(!open)} aria-haspopup="listbox" aria-expanded={open}
        className="flex items-center gap-2 rounded-lg border border-border bg-surface px-3 py-1.5 text-sm transition hover:border-muted">
        <span className="font-medium">{market.name}</span>
        <span className="text-xs text-muted">{ticker(market) !== market.name ? ticker(market) : market.class_label}</span>
        <svg viewBox="0 0 24 24" className="h-3.5 w-3.5 text-muted" fill="none" stroke="currentColor" strokeWidth={2}><path d="m6 9 6 6 6-6" /></svg>
      </button>
      {open && (
        <div ref={panel} className="absolute left-0 z-40 mt-1.5 w-[min(30rem,calc(100vw-2rem))] overflow-hidden rounded-xl border border-border bg-surface shadow-xl">
          <div className="flex items-center gap-2 border-b border-border px-3">
            <Icon name="search" className="h-4 w-4 text-muted" />
            <input ref={search} value={q} onChange={(e) => setQ(e.target.value)}
              placeholder={`Search ${markets.length} markets: name, ticker or sector`}
              className="w-full bg-transparent py-2.5 text-base outline-none sm:text-sm"
              onKeyDown={(e) => { if (e.key === "Enter" && groups[0]?.items[0]) pick(groups[0].items[0].symbol); }} />
            {q && <button type="button" onClick={() => setQ("")} className="text-xs text-muted hover:text-foreground">Clear</button>}
          </div>
          <div role="tablist" aria-label="Asset class" className="flex gap-1 overflow-x-auto border-b border-border px-2 py-1.5">
            {tabs.map(([k, label]) => (
              <button key={k} type="button" role="tab" aria-selected={tab === k} onClick={() => { setCls(k); setQ(""); }}
                className={`shrink-0 rounded-full px-2.5 py-1 text-xs transition ${tab === k ? "bg-gold/15 text-gold" : "text-muted hover:bg-background hover:text-foreground"}`}>
                {label}{k !== "all" && <span className="ml-1 tabular-nums opacity-60">{counts[k]}</span>}
              </button>
            ))}
          </div>
          <ul role="listbox" aria-label="Markets" className="max-h-[22rem] overflow-y-auto py-1">
            {groups.map((g) => (
              <li key={g.label}>
                <p className="sticky top-0 bg-surface px-3 pb-1 pt-2 text-[11px] uppercase tracking-wide text-muted">{g.label}</p>
                <ul>
                  {g.items.map((m) => (
                    <li key={m.symbol}>
                      <button type="button" role="option" aria-selected={m.symbol === market.symbol} onClick={() => pick(m.symbol)}
                        className={`flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm transition hover:bg-background ${m.symbol === market.symbol ? "text-gold" : ""}`}>
                        <span className="truncate">{m.name}</span>
                        {ticker(m) !== m.name && <span className="shrink-0 text-xs text-muted">{ticker(m)}</span>}
                        <span className="ml-auto shrink-0 tabular-nums text-xs text-muted">
                          {m.price != null ? fmtMarketPrice(m.price, m)
                            : m.status === "loading" ? "Loading…" : <span title="Prices load the first time it is opened">Opens fresh</span>}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              </li>
            ))}
            {!groups.length && <li className="px-3 py-3 text-sm text-muted">No market matches &ldquo;{q}&rdquo;.</li>}
          </ul>
          <p className="border-t border-border px-3 py-1.5 text-[11px] text-muted">
            Profit and loss is in US dollars; for markets quoted in other currencies it is converted at the day&apos;s rate.
          </p>
        </div>
      )}
    </div>
  );
}
