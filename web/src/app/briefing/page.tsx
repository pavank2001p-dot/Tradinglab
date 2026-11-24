"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import MarketPicker from "@/components/markets/MarketPicker";
import SignInPrompt from "@/components/SignInPrompt";
import { Icon, PageHeader } from "@/components/ui";
import { api, ApiError, type Briefing, type BriefingStatus, type BriefingStrategy } from "@/lib/api";
import { useMarket } from "@/lib/markets";
import { useUser } from "@/lib/useUser";

const TONE = {
  mostly_positive: { label: "Headlines mostly positive", cls: "bg-up/15 text-up" },
  mostly_negative: { label: "Headlines mostly negative", cls: "bg-down/15 text-down" },
  mixed: { label: "Headlines mixed", cls: "bg-border text-foreground" },
  quiet: { label: "Few headlines", cls: "bg-border text-muted" },
} as const;

const pct = (v: number | null | undefined, digits = 1) => (v == null ? "–" : `${v > 0 ? "+" : ""}${v.toFixed(digits)}%`);

function Card({ icon, title, children }: { icon: string; title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-2xl border border-border bg-surface p-4 sm:p-5">
      <h2 className="flex items-center gap-2 text-sm font-semibold">
        <Icon name={icon} className="h-4 w-4 text-gold" />
        {title}
      </h2>
      <div className="mt-2 space-y-2 text-sm leading-relaxed">{children}</div>
    </section>
  );
}

function Points({ items, tone }: { items: string[]; tone?: "good" | "weak" }) {
  if (!items.length) return null;
  const dot = tone === "good" ? "bg-up" : tone === "weak" ? "bg-down" : "bg-gold";
  return (
    <ul className="space-y-1.5">
      {items.map((p, i) => (
        <li key={i} className="flex gap-2">
          <span className={`mt-2 h-1.5 w-1.5 shrink-0 rounded-full ${dot}`} />
          <span>{p}</span>
        </li>
      ))}
    </ul>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-border px-3 py-2">
      <p className="text-[11px] text-muted">{label}</p>
      <p className="text-sm font-medium tabular-nums">{value}</p>
    </div>
  );
}

/** The backtests the briefing ran, so every claim about them can be checked. */
function StrategyTable({ rows, hold }: { rows: BriefingStrategy[]; hold: number | null }) {
  return (
    <div className="-mx-1 overflow-x-auto">
      <table className="w-full min-w-[460px] text-xs tabular-nums">
        <thead className="text-left text-muted">
          <tr>
            <th className="px-1 py-1 font-normal">Strategy</th>
            <th className="px-1 py-1 text-right font-normal">Return</th>
            <th className="px-1 py-1 text-right font-normal">Worst drop</th>
            <th className="px-1 py-1 text-right font-normal">Held-back part</th>
            <th className="px-1 py-1 text-right font-normal">Trades</th>
            <th className="px-1 py-1 font-normal">Trust</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.strategy} className="border-t border-border">
              <td className="px-1 py-1.5">{r.label}</td>
              <td className={`px-1 py-1.5 text-right ${hold != null && r.total_return_pct != null && r.strategy !== "buy_and_hold" && r.total_return_pct < hold ? "text-muted" : ""}`}>{pct(r.total_return_pct)}</td>
              <td className="px-1 py-1.5 text-right">{pct(r.max_drawdown_pct)}</td>
              <td className={`px-1 py-1.5 text-right ${r.held_back_return_pct != null && r.held_back_return_pct < 0 ? "text-down" : ""}`}>{r.strategy === "buy_and_hold" ? "" : pct(r.held_back_return_pct)}</td>
              <td className="px-1 py-1.5 text-right">{r.trades ?? "–"}</td>
              <td className="px-1 py-1.5 text-muted">{r.trust ?? ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function BriefingPage() {
  const [market, setSymbol, markets] = useMarket();
  const { user } = useUser();
  const [status, setStatus] = useState<BriefingStatus | null>(null);
  const [b, setB] = useState<Briefing | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (user) api.briefingStatus().then(setStatus).catch(() => {});
  }, [user]);
  useEffect(() => { setB(null); setError(null); }, [market.symbol]);

  const run = useCallback(async (fresh: boolean) => {
    setBusy(true);
    setError(null);
    try {
      const { id } = await api.startBriefing(market.symbol, fresh);
      for (;;) {
        const got = await api.briefing(id);
        if (got.status !== "pending") { setB(got); break; }
        await new Promise((r) => setTimeout(r, 2000));
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't reach the briefing. Please try again.");
    } finally {
      setBusy(false);
      api.briefingStatus().then(setStatus).catch(() => {});
    }
  }, [market.symbol]);

  if (user === null) return <SignInPrompt what="get a Claude briefing on any market" next="/briefing" />;
  if (user === undefined) return null;

  const r = b?.report;
  const f = b?.facts;
  const sameMarket = b?.symbol === market.symbol;

  return (
    <div className="mx-auto max-w-3xl px-4 py-8">
      <PageHeader icon="assistant" title="Claude briefing"
        subtitle="Claude reads this site's data on one market (the news, the chart, a set of backtests and your own practice trades) and explains what it shows. It's analysis to learn from, never a buy or sell call."
      />

      <div className="mt-4 flex items-start gap-3 rounded-2xl border border-gold/40 bg-gold/10 p-3 text-sm">
        <Icon name="scale" className="mt-0.5 h-4 w-4 shrink-0 text-gold" />
        <p><strong>Analysis, not a signal.</strong> A briefing explains what the data shows. It doesn&apos;t predict prices or tell you to buy or sell, and past results don&apos;t guarantee future ones. Any write-up that reads like a trading call is held back automatically.</p>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <MarketPicker market={market} markets={markets} onChange={setSymbol} />
        <button type="button" onClick={() => run(false)} disabled={busy || status?.configured === false || status?.remaining === 0}
          className="rounded-lg bg-gold px-4 py-2 text-sm font-medium text-black disabled:opacity-50">
          {busy ? "Reading the data…" : sameMarket && b ? "Show latest" : `Brief me on ${market.name}`}
        </button>
        {sameMarket && b?.status === "done" && !busy && (
          <button type="button" onClick={() => run(true)} disabled={status?.remaining === 0}
            className="rounded-lg border border-border px-3 py-2 text-sm text-muted hover:text-foreground disabled:opacity-50">Refresh</button>
        )}
        {status?.configured && (
          <span className="ml-auto text-xs tabular-nums text-muted">{status.remaining} of {status.limit} left today</span>
        )}
      </div>
      {status?.configured === false && <p className="mt-3 text-sm text-muted">The Claude briefing isn&apos;t switched on for this site yet.</p>}
      {error && <p className="mt-3 text-sm text-down">{error}</p>}

      {busy && !b && (
        <div className="mt-6 space-y-3">
          {[0, 1, 2].map((i) => <div key={i} className="h-24 animate-pulse rounded-2xl bg-surface" />)}
          <p className="text-center text-xs text-muted">Re-testing strategies and reading the headlines. This takes about half a minute.</p>
        </div>
      )}

      {b && sameMarket && (
        <div className="mt-6 space-y-4">
          {b.status === "error" && <p className="rounded-2xl border border-down/40 bg-down/10 p-3 text-sm">{b.note}</p>}
          {b.note && b.status === "done" && <p className="rounded-2xl border border-border bg-surface p-3 text-sm text-muted">{b.note}</p>}

          {f && (
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <Stat label="Price" value={f.price?.price != null ? `${f.price.price} (${pct(f.price.change_24h_pct, 2)} 24h)` : "–"} />
              <Stat label="vs 200-day average" value={pct(f.chart?.vs_sma200_pct)} />
              <Stat label="RSI (14 days)" value={f.chart?.rsi14 != null ? String(f.chart.rsi14) : "–"} />
              <Stat label="Daily range (ATR)" value={f.chart?.atr14_pct_of_price != null ? `${f.chart.atr14_pct_of_price}% of price` : "–"} />
            </div>
          )}
          {f?.price?.data_source === "sample" && <p className="text-xs text-muted">These are demo prices, not real market prices.</p>}

          {r && (
            <>
              <p className="text-lg font-medium leading-snug">{r.headline}</p>

              <Card icon="news" title="News and sentiment">
                <span className={`inline-block rounded-full px-2.5 py-0.5 text-xs ${TONE[r.news.tone].cls}`}>
                  {TONE[r.news.tone].label}{f?.news?.count ? ` · ${f.news.count} in 3 days` : ""}
                </span>
                <p>{r.news.summary}</p>
                <Points items={r.news.points} />
                <p className="text-xs text-muted">Tone describes the headlines, not where the price goes next. <Link href="/news" className="underline">Read them</Link></p>
              </Card>

              <Card icon="candles" title="Chart setup explained">
                <p>{r.chart.summary}</p>
                <Points items={r.chart.points} />
              </Card>

              <Card icon="backtest" title="Strategies tested on this market">
                <p>{r.strategies.summary}</p>
                {r.strategies.held_up.length > 0 && <p className="pt-1 text-xs font-medium text-up">Held up on unseen data</p>}
                <Points items={r.strategies.held_up} tone="good" />
                {r.strategies.weak_points.length > 0 && <p className="pt-1 text-xs font-medium text-down">Weak points</p>}
                <Points items={r.strategies.weak_points} tone="weak" />
              </Card>

              <Card icon="check" title="Your trading habits">
                <p>{r.habits.summary}</p>
                <Points items={r.habits.points} />
                <p className="text-xs text-muted">From your paper trades in the last 90 days. <Link href="/coach" className="underline">Open the coach</Link></p>
              </Card>

              {r.watch.length > 0 && (
                <Card icon="calendar" title="Worth keeping an eye on">
                  <Points items={r.watch} />
                </Card>
              )}
            </>
          )}

          {f?.strategy_comparison?.strategies?.length ? (
            <Card icon="layers" title={`The backtests behind this (${f.strategy_comparison.years} years, daily)`}>
              <StrategyTable rows={f.strategy_comparison.strategies} hold={f.strategy_comparison.buy_and_hold_pct} />
              <p className="text-xs text-muted">Each strategy used the whole account per trade with no leverage, including spread and costs. The held-back part is the last stretch of the period, judged on its own. <Link href={`/backtest?symbol=${market.symbol}`} className="underline">Test your own</Link></p>
            </Card>
          ) : null}

          {r && r.limits.length > 0 && (
            <Card icon="scale" title="What this briefing can't tell you">
              <Points items={r.limits} />
            </Card>
          )}

          <p className="text-xs text-muted">
            Written by Claude from this site&apos;s data{b.created_at ? ` on ${new Date(b.created_at).toLocaleString()}` : ""}. AI can be wrong.
            Educational only, not financial advice. Questions? <Link href="/assistant" className="underline">Ask the assistant</Link> or read the{" "}
            <Link href="/disclaimer" className="underline">disclaimer</Link>.
          </p>
        </div>
      )}
    </div>
  );
}
