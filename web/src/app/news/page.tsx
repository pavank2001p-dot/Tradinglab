"use client";

import { useEffect, useMemo, useState } from "react";
import MarketPicker from "@/components/markets/MarketPicker";
import { Chips, Empty, Icon, PageHeader } from "@/components/ui";
import { api, type CalendarEvent, type Market, type NewsFeed, type NewsItem } from "@/lib/api";
import { CLASSES, ticker, useMarket } from "@/lib/markets";

const IMPACT = {
  bullish: { label: "Good for", cls: "bg-up/15 text-up", bar: "bg-up", icon: "up" },
  bearish: { label: "Bad for", cls: "bg-down/15 text-down", bar: "bg-down", icon: "down" },
  neutral: { label: "Neutral for", cls: "bg-border text-muted", bar: "bg-muted/50", icon: "scale" },
} as const;

/** What the feed is narrowed to: everything, the economy in general, one market, an asset class or a sector. */
type Scope = { kind: "all" } | { kind: "macro" } | { kind: "market"; symbol: string } | { kind: "sector"; key: string };

/** Sector chips for an asset class, from the markets on offer ("stocks:Financials", "forex:Majors"...). */
function sectorsOf(markets: Market[], cls: string): string[] {
  const out: string[] = [];
  for (const m of markets) if (m.asset_class === cls && m.group && !out.includes(m.group)) out.push(m.group);
  return out;
}

type Tone = "all" | "bullish" | "bearish" | "neutral";

function ago(iso: string) {
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 60) return `${Math.max(mins, 1)} min ago`;
  if (mins < 60 * 24) return `${Math.round(mins / 60)} h ago`;
  return new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

function countdown(iso: string, now: number) {
  const mins = Math.round((new Date(iso).getTime() - now) / 60000);
  if (mins < 0) return "Released";
  if (mins < 60) return `in ${mins} min`;
  if (mins < 60 * 24) return `in ${Math.round(mins / 60)} h`;
  const d = Math.round(mins / 1440);
  return `in ${d} ${d === 1 ? "day" : "days"}`;
}

const dayKey = (iso: string) => new Date(iso).toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "short" });
const time = (iso: string) => new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });

/** Share of good, bad and neutral headlines. */
function Mood({ items }: { items: NewsItem[] }) {
  const tagged = items.filter((n) => n.impact);
  if (tagged.length === 0) return null;
  const pct = (k: keyof typeof IMPACT) => (tagged.filter((n) => n.impact === k).length / tagged.length) * 100;
  return (
    <div className="rounded-2xl border border-border bg-surface p-4">
      <div className="flex items-baseline justify-between">
        <p className="text-sm font-medium">Headline mood</p>
        <p className="text-xs text-muted">{tagged.length} tagged headlines</p>
      </div>
      <div className="mt-3 flex h-2.5 overflow-hidden rounded-full bg-border">
        {(["bullish", "neutral", "bearish"] as const).map((k) => (
          <div key={k} className={`bar-grow h-full ${IMPACT[k].bar}`} style={{ width: `${pct(k)}%` }} />
        ))}
      </div>
      <div className="mt-2 flex justify-between text-xs tabular-nums">
        <span className="text-up">{pct("bullish").toFixed(0)}% good</span>
        <span className="text-muted">{pct("neutral").toFixed(0)}% neutral</span>
        <span className="text-down">{pct("bearish").toFixed(0)}% bad</span>
      </div>
    </div>
  );
}

export default function NewsPage() {
  const [market, setSymbol, markets] = useMarket();
  const [feed, setFeed] = useState<NewsFeed | null>(null);
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [scope, setScope] = useState<Scope>({ kind: "all" });
  const [tone, setTone] = useState<Tone>("all");
  const [open, setOpen] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [mine, setMine] = useState(false); // calendar: only the economies that move the chosen market

  const filter = scope.kind === "market" ? { symbol: scope.symbol } : scope.kind === "sector" ? { sector: scope.key }
    : scope.kind === "macro" ? { sector: "macro" } : {};
  const filterKey = JSON.stringify(filter);
  useEffect(() => {
    setFeed(null);
    api.news(JSON.parse(filterKey)).then(setFeed, () => setFeed({ configured: false, tagging: false, items: [] }));
  }, [filterKey]);
  useEffect(() => {
    api.calendar(21, mine ? market.symbol : undefined).then(setEvents, () => {});
  }, [mine, market.symbol]);
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 60_000);
    return () => clearInterval(id);
  }, []);

  const bySymbol = useMemo(() => new Map(markets.map((m) => [m.symbol, m])), [markets]);
  const cls = scope.kind === "sector" ? scope.key.split(":")[0] : null;
  const sectors = cls ? sectorsOf(markets, cls) : [];
  const scopeName = scope.kind === "market" ? (bySymbol.get(scope.symbol)?.name ?? scope.symbol)
    : scope.kind === "sector" ? (scope.key.includes(":") ? scope.key.split(":")[1] : CLASSES.find(([k]) => k === scope.key)?.[1] ?? scope.key)
    : scope.kind === "macro" ? "the economy" : null;

  const items = feed?.items ?? [];
  const shown = items.filter((n) => tone === "all" || n.impact === tone);
  const next = events.find((e) => new Date(e.ts).getTime() >= now);
  const days: [string, CalendarEvent[]][] = [];
  for (const e of events) {
    const k = dayKey(e.ts);
    const last = days[days.length - 1];
    if (last && last[0] === k) last[1].push(e);
    else days.push([k, [e]]);
  }

  return (
    <div className="mx-auto grid max-w-6xl gap-8 px-4 py-8 lg:grid-cols-[minmax(0,1fr)_340px]">
      <section className="min-w-0 space-y-5">
        <PageHeader icon="news" title={scopeName ? `News: ${scopeName}` : "Market news"}
          subtitle="Headlines for every market and sector: commodities, forex, indices, stocks by sector, ETFs and crypto. Each is tagged by AI as likely good, bad or neutral for the market it is mainly about, with a short reason. Tags are educational context, not trading advice, and can be wrong." />

        <div className="space-y-2 rounded-2xl border border-border bg-surface p-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-muted">Show</span>
            <button type="button" onClick={() => setScope({ kind: "all" })} aria-pressed={scope.kind === "all"}
              className={`rounded-full border px-3 py-1 text-xs ${scope.kind === "all" ? "border-gold bg-gold/15" : "border-border text-muted hover:text-foreground"}`}>All news</button>
            <button type="button" onClick={() => setScope({ kind: "market", symbol: market.symbol })}
              aria-pressed={scope.kind === "market" && scope.symbol === market.symbol}
              className={`rounded-full border px-3 py-1 text-xs ${scope.kind === "market" && scope.symbol === market.symbol ? "border-gold bg-gold/15" : "border-border text-muted hover:text-foreground"}`}>
              {market.name} and its sector</button>
            <MarketPicker market={market} markets={markets} onChange={(s) => { setSymbol(s); setScope({ kind: "market", symbol: s }); }} />
            <button type="button" onClick={() => setScope({ kind: "macro" })} aria-pressed={scope.kind === "macro"}
              className={`rounded-full border px-3 py-1 text-xs ${scope.kind === "macro" ? "border-gold bg-gold/15" : "border-border text-muted hover:text-foreground"}`}>Economy and rates</button>
          </div>
          <div className="flex gap-1.5 overflow-x-auto pb-0.5">
            {CLASSES.map(([k, label]) => (
              <button key={k} type="button" onClick={() => setScope({ kind: "sector", key: k })} aria-pressed={cls === k}
                className={`shrink-0 rounded-full border px-3 py-1 text-xs ${cls === k ? "border-gold bg-gold/15" : "border-border text-muted hover:text-foreground"}`}>{label}</button>
            ))}
          </div>
          {cls && sectors.length > 1 && (
            <div className="flex gap-1.5 overflow-x-auto border-t border-border pt-2">
              <span className="shrink-0 self-center text-xs text-muted">{cls === "stocks" || cls === "etfs" ? "Sector" : cls === "indices" ? "Region" : "Kind"}</span>
              {sectors.map((g) => {
                const key = `${cls}:${g}`;
                const on = scope.kind === "sector" && scope.key === key;
                return (
                  <button key={g} type="button" onClick={() => setScope({ kind: "sector", key: on ? cls : key })} aria-pressed={on}
                    className={`shrink-0 rounded-full border px-3 py-1 text-xs ${on ? "border-gold bg-gold/15" : "border-border text-muted hover:text-foreground"}`}>{g}</button>
                );
              })}
            </div>
          )}
        </div>

        <Mood items={items} />

        <div className="flex flex-wrap items-center gap-3">
          <Chips<Tone> value={tone} onChange={setTone} options={[
            { key: "all", label: "All", count: items.length },
            { key: "bullish", label: "Good for its market", count: items.filter((n) => n.impact === "bullish").length, dot: "var(--up)" },
            { key: "bearish", label: "Bad for its market", count: items.filter((n) => n.impact === "bearish").length, dot: "var(--down)" },
            { key: "neutral", label: "Neutral", count: items.filter((n) => n.impact === "neutral").length, dot: "var(--muted)" },
          ]} />
        </div>

        <div className="space-y-3">
          {!feed && <p className="text-sm text-muted">Loading headlines…</p>}
          {feed && items.length === 0 && (
            <Empty icon="news" title={!feed.configured ? "News feed not connected yet" : scopeName ? `No headlines about ${scopeName} yet` : "No headlines yet"}>
              {feed.configured ? "New headlines arrive every 30 minutes. Try a wider filter, like the whole asset class." : "Headlines will appear here once the news feed is switched on."}
            </Empty>
          )}
          {feed && items.length > 0 && shown.length === 0 && <Empty icon="search" title="No headlines match that filter" />}
          {shown.map((n, i) => {
            const imp = n.impact ? IMPACT[n.impact] : null;
            const expanded = open === n.id;
            return (
              <article key={n.id} className="rise-in group relative overflow-hidden rounded-2xl border border-border bg-surface p-4 pl-5 transition hover:border-muted"
                style={{ animationDelay: `${Math.min(i, 10) * 30}ms` }}>
                <span className={`absolute inset-y-0 left-0 w-1 ${imp?.bar ?? "bg-border"}`} />
                <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
                  {imp ? (
                    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-medium ${imp.cls}`}>
                      <Icon name={imp.icon} className="h-3 w-3" strokeWidth={2.4} />{imp.label} {n.focus_name ?? "markets"}
                    </span>
                  ) : (
                    <span className="rounded-full bg-border px-2 py-0.5">Not tagged yet</span>
                  )}
                  <span>{n.publisher}</span>
                  <span>·</span>
                  <span>{ago(n.published_at)}</span>
                </div>
                <h2 className="mt-2 font-medium leading-snug">
                  {n.url ? <a href={n.url} target="_blank" rel="noopener noreferrer" className="hover:text-gold">{n.headline}</a> : n.headline}
                </h2>
                {n.reason && <p className="mt-1.5 text-sm text-muted">{n.reason}</p>}
                {!!n.symbols?.length && (
                  <div className="mt-2 flex flex-wrap gap-1">
                    {n.symbols.slice(0, 5).map((s) => {
                      const m = bySymbol.get(s);
                      return m ? (
                        <button key={s} type="button" onClick={() => setScope({ kind: "market", symbol: s })}
                          className="rounded-full border border-border px-2 py-0.5 text-[11px] text-muted hover:border-gold hover:text-foreground">
                          {ticker(m) !== m.name ? ticker(m) : m.name}
                        </button>
                      ) : null;
                    })}
                  </div>
                )}
                {n.summary && (
                  <>
                    {expanded && <p className="mt-2 text-sm leading-relaxed">{n.summary}</p>}
                    <button onClick={() => setOpen(expanded ? null : n.id)} className="mt-2 text-xs text-gold hover:underline">
                      {expanded ? "Show less" : "Read summary"}
                    </button>
                  </>
                )}
              </article>
            );
          })}
        </div>
      </section>

      <aside className="space-y-4 lg:sticky lg:top-20 lg:self-start">
        <div className="flex items-center gap-2">
          <Icon name="calendar" className="h-4 w-4 text-gold" />
          <h2 className="font-medium">Economic calendar</h2>
        </div>
        <p className="-mt-2 text-xs text-muted">Big releases from the US, euro area, UK, Japan, China and other major economies for the next three weeks, in your local time.</p>
        <label className="flex cursor-pointer items-center gap-2 text-xs text-muted">
          <input type="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} className="accent-[var(--gold)]" />
          Only releases that move {market.name}
        </label>

        {next && (
          <div className="rounded-2xl border border-gold/40 bg-gradient-to-br from-gold/15 to-transparent p-4">
            <p className="flex items-center gap-1.5 text-xs text-gold"><Icon name="clock" className="h-3.5 w-3.5" /> Next up · {countdown(next.ts, now)}</p>
            <p className="mt-1.5 font-medium">{next.title}</p>
            <p className="text-xs text-muted">{dayKey(next.ts)}, {time(next.ts)}</p>
            {next.why && <p className="mt-2 text-xs leading-relaxed text-muted">{next.why}</p>}
          </div>
        )}

        {events.length === 0 ? (
          <Empty icon="calendar" title="No upcoming events loaded" />
        ) : (
          <div className="max-h-[70vh] space-y-4 overflow-y-auto pr-1">
            {days.map(([d, evs]) => (
              <div key={d}>
                <p className="sticky top-0 bg-background py-1 text-xs font-medium uppercase tracking-wide text-muted">{d}</p>
                <ol className="mt-1 space-y-2 border-l border-border pl-3">
                  {evs.map((e) => {
                    const past = new Date(e.ts).getTime() < now;
                    return (
                      <li key={e.id} className={`relative rounded-lg border border-border p-3 ${past ? "opacity-50" : "bg-surface"}`}>
                        <span className={`absolute -left-[17px] top-4 h-2 w-2 rounded-full ring-4 ring-background ${e.impact === "High" ? "bg-down" : "bg-gold"}`} />
                        <div className="flex items-center justify-between text-xs text-muted">
                          <span className="tabular-nums">{time(e.ts)} <span className="ml-1 rounded bg-background px-1 py-0.5 text-[10px] font-medium">{e.country}</span></span>
                          <span className={past ? "" : "text-gold"}>{countdown(e.ts, now)}</span>
                        </div>
                        <p className="mt-1 text-sm font-medium">{e.title}</p>
                        {(e.forecast || e.previous) && (
                          <div className="mt-1.5 flex gap-2 text-[11px]">
                            {e.forecast && <span className="rounded bg-background px-1.5 py-0.5"><span className="text-muted">Forecast</span> {e.forecast}</span>}
                            {e.previous && <span className="rounded bg-background px-1.5 py-0.5"><span className="text-muted">Previous</span> {e.previous}</span>}
                          </div>
                        )}
                        {e.why && <p className="mt-1.5 text-xs text-muted">{e.why}</p>}
                      </li>
                    );
                  })}
                </ol>
              </div>
            ))}
          </div>
        )}
      </aside>
    </div>
  );
}
