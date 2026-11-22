"use client";

import { useEffect, useState } from "react";
import FitPanel from "@/components/FitPanel";
import ReportView from "@/components/ReportView";
import TrustPanel from "@/components/TrustPanel";
import ShareButton, { resultShare } from "@/components/ShareCard";
import SignInPrompt from "@/components/SignInPrompt";
import { Chips, Empty, Icon, PageHeader } from "@/components/ui";
import Link from "next/link";
import MarketPicker from "@/components/markets/MarketPicker";
import { api, asStrategy, fmtPct, fmtUsd, type Backtest, type BacktestParams, type BacktestSummary, type BacktestTf, type DayStats, type Market, type SavedStrategy, type Strategy, type TradingHours } from "@/lib/api";
import { GOLD, ticker, useMarket } from "@/lib/markets";
import { useUser } from "@/lib/useUser";

const input = "w-full rounded-lg border border-border bg-background px-3 py-1.5 outline-none focus:border-gold";

const DEFAULTS: Omit<BacktestParams, "strategy" | "params"> = {
  tf: "1d",
  start: "2015-01-01",
  end: null,
  direction: "both",
  capital: 10000,
  units: 5,
  spread: 0.3,
  swap_long: -0.25,
  swap_short: 0.05,
  stop_loss_pct: null,
  take_profit_pct: null,
  size_pct: null,
  realistic_fills: true,
  commission_pct: null,
  commission_per_unit: null,
  commission_min: null,
  slippage: null,
  session: "any",
  session_start: null,
  session_end: null,
  session_tz: "America/New_York",
  day_trade: false,
  max_trades_per_day: null,
  daily_loss_limit_pct: null,
};

const TF_LABEL: Record<BacktestTf, string> = { "5m": "5-minute", "15m": "15-minute", "1h": "hourly", "1d": "daily" };
const SESSIONS: { key: TradingHours; label: string; hint: string }[] = [
  { key: "any", label: "Any time", hint: "Trades can open at any hour the market is open." },
  { key: "asia", label: "Tokyo", hint: "09:00 to 15:00 Tokyo time." },
  { key: "london", label: "London", hint: "08:00 to 16:30 London time." },
  { key: "new_york", label: "New York", hint: "09:30 to 16:00 New York time, the US stock market's hours." },
  { key: "overlap", label: "London + New York", hint: "08:00 to 12:00 New York time, when both are open and markets move most." },
  { key: "custom", label: "Custom hours", hint: "Your own hours. An end earlier than the start runs past midnight." },
];
const fmtDay = (iso: string) => new Date(`${iso}T00:00:00Z`).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });

function DayStatsCard({ d }: { d: DayStats }) {
  if (!d.traded) return null;
  const cell = (label: string, value: string, tone?: "up" | "down") => (
    <div className="rounded-xl border border-border bg-background px-3 py-2">
      <p className="text-xs text-muted">{label}</p>
      <p className={`mt-0.5 font-semibold tabular-nums ${tone === "up" ? "text-up" : tone === "down" ? "text-down" : ""}`}>{value}</p>
    </div>
  );
  return (
    <div className="rounded-2xl border border-border bg-surface p-4">
      <h3 className="flex items-center gap-2 text-sm font-medium"><Icon name="calendar" className="h-4 w-4 text-gold" />Day by day</h3>
      <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
        {cell("Days traded", String(d.traded))}
        {cell("Green days", d.green_pct == null ? "–" : `${d.green_pct}%`)}
        {cell("Average day", d.avg_day == null ? "–" : fmtUsd(d.avg_day), (d.avg_day ?? 0) >= 0 ? "up" : "down")}
        {cell("Best day", d.best == null ? "–" : fmtUsd(d.best), "up")}
        {cell("Worst day", d.worst == null ? "–" : fmtUsd(d.worst), "down")}
        {cell("Trades a day", d.avg_trades == null ? "–" : String(d.avg_trades))}
      </div>
      <p className="mt-2 text-xs text-muted">Days run from 17:00 to 17:00 New York, and each trade counts on the day it closed.</p>
    </div>
  );
}

/** A market's usual trade size and broker costs. A swap charged as a yearly % of the position is left empty
 *  so the server applies it. */
const costsFor = (m: Market) => ({
  symbol: m.symbol, units: m.default_units, spread: m.spread, swap_long: m.swap_long, swap_short: m.swap_short,
  commission_pct: m.commission_pct ?? null, commission_per_unit: m.commission_per_unit ?? null,
  commission_min: m.commission_min ?? null, slippage: m.slippage ?? null,
});
const unitName = (m: Market) => (m.unit === "ounce" ? "oz" : m.unit === "MMBtu" ? "MMBtu" : `${m.unit}s`);

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block text-sm">
      <span className="text-muted">{label}</span>
      <div className="mt-1">{children}</div>
      {hint && <span className="mt-0.5 block text-xs text-muted">{hint}</span>}
    </label>
  );
}

function Num({ value, onChange, step = "any", min, max, placeholder }: {
  value: number | null | undefined; onChange: (v: number | null) => void; step?: number | "any"; min?: number; max?: number; placeholder?: string;
}) {
  return (
    <input type="number" className={input} value={value ?? ""} step={step} min={min} max={max} placeholder={placeholder}
      onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))} />
  );
}

const label = (strategies: Strategy[], p: BacktestParams, markets: Market[] = []) => {
  const m = p.symbol && p.symbol !== GOLD.symbol ? markets.find((x) => x.symbol === p.symbol) : null;
  const base = baseLabel(strategies, p);
  return m ? `${m.name} · ${base}` : p.symbol && p.symbol !== GOLD.symbol ? `${p.symbol} · ${base}` : base;
};

const baseLabel = (strategies: Strategy[], p: BacktestParams) => {
  const tf = `${TF_LABEL[p.tf] ?? p.tf}${p.day_trade ? " day trades" : ""}`;
  if (p.strategy === "custom") return `${p.rules?.name ?? "Custom strategy"} · ${tf}`;
  const s = strategies.find((x) => x.key === p.strategy);
  const vals = Object.values(p.params);
  return `${s?.label ?? p.strategy}${vals.length ? ` (${vals.join("/")})` : ""} · ${tf}`;
};

export default function BacktestPage() {
  const { user } = useUser();
  const [market, setSymbol, markets] = useMarket();
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [form, setForm] = useState<BacktestParams | null>(null);
  const [result, setResult] = useState<Backtest | null>(null);
  const [history, setHistory] = useState<BacktestSummary[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [kind, setKind] = useState<"all" | Strategy["kind"]>("all");
  const [search, setSearch] = useState("");
  const [mine, setMine] = useState<SavedStrategy[]>([]);
  const [customKey, setCustomKey] = useState<string | null>(null);

  useEffect(() => {
    api.strategies().then((list) => {
      setStrategies(list);
      const s = list[0];
      // The strategy finder links here with a full set of settings.
      let plan: Partial<BacktestParams> | null = null;
      try {
        plan = JSON.parse(new URLSearchParams(window.location.search).get("plan") ?? "null");
      } catch {}
      if (plan?.strategy && (list.some((x) => x.key === plan.strategy) || (plan.strategy === "custom" && plan.rules))) setForm({ ...DEFAULTS, params: {}, ...plan } as BacktestParams);
      else setForm({ ...DEFAULTS, strategy: s.key, params: Object.fromEntries(s.params.map((p) => [p.key, p.default])) });
    });
  }, []);
  useEffect(() => {
    if (user) api.backtests().then(setHistory, () => {});
    if (user) api.customList().then((list) => {
      setMine(list);
      // The strategy builder links here with ?custom=<id>.
      const id = Number(new URLSearchParams(window.location.search).get("custom"));
      const m = list.find((x) => x.id === id);
      if (m) {
        setCustomKey(`custom:${m.id}`);
        setForm((f) => f && { ...f, strategy: "custom", params: {}, rules: m.rules });
      }
    }, () => {});
  }, [user]);

  // Picking another market resets the size and costs to that market's usual ones.
  useEffect(() => {
    setForm((f) => (f && (f.symbol ?? GOLD.symbol) !== market.symbol ? { ...f, ...costsFor(market) } : f));
  }, [market]);

  if (user === null) return <SignInPrompt what="backtest trading strategies" next="/backtest" />;
  if (!form || user === undefined) return null;

  const all = [...strategies, ...mine.map(asStrategy)];
  const selected = form.strategy === "custom" ? customKey : form.strategy;
  const strategy: Strategy = all.find((s) => s.key === selected) ?? {
    key: "custom", label: form.rules?.name ?? "Custom strategy", summary: "", kind: "custom", kind_label: "Your strategy", params: [],
  };
  const set = (patch: Partial<BacktestParams>) => setForm({ ...form, ...patch });
  const intraday = form.tf !== "1d";
  const minuteTf = form.tf === "5m" || form.tf === "15m";
  // The first day this market has prices for the chosen candles.
  const dataFrom = minuteTf ? market.minutes_from : market.history_from;

  function setTf(tf: BacktestTf) {
    const patch: Partial<BacktestParams> = { tf };
    // Minute data covers months, not years: start where it starts.
    if ((tf === "5m" || tf === "15m") && market.minutes_from && form!.start < market.minutes_from) patch.start = market.minutes_from;
    if (tf === "1d") Object.assign(patch, { session: "any", day_trade: false });
    set(patch);
  }

  function pick(key: string) {
    if (key.startsWith("custom:")) {
      const m = mine.find((x) => `custom:${x.id}` === key)!;
      setCustomKey(key);
      set({ strategy: "custom", params: {}, rules: m.rules });
      return;
    }
    const s = strategies.find((x) => x.key === key)!;
    set({ strategy: key, params: Object.fromEntries(s.params.map((p) => [p.key, p.default])), rules: null });
  }

  async function run(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await api.runBacktest({ ...form!, symbol: form!.symbol ?? market.symbol, end: form!.end || null });
      setResult(r);
      // On narrow screens the results sit below the form.
      if (window.innerWidth < 1024) setTimeout(() => document.getElementById("results")?.scrollIntoView({ behavior: "smooth" }), 50);
      setHistory(await api.backtests());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Backtest failed");
    } finally {
      setBusy(false);
    }
  }

  async function open(id: number) {
    const r = await api.backtest(id);
    setResult(r);
    setForm({ ...r.params, end: r.params.end ?? null, symbol: r.params.symbol ?? GOLD.symbol });
    setSymbol(r.params.symbol ?? GOLD.symbol);
    const m = r.params.strategy === "custom" ? mine.find((x) => x.name === r.params.rules?.name) : null;
    setCustomKey(m ? `custom:${m.id}` : null);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function remove(id: number) {
    await api.deleteBacktest(id);
    setHistory(history.filter((h) => h.id !== id));
    if (result?.id === id) setResult(null);
  }

  return (
    <div className="mx-auto grid max-w-6xl gap-6 px-4 py-8 lg:grid-cols-[320px_1fr]">
      <form onSubmit={run} className="space-y-4">
        <PageHeader icon="backtest" title="Backtest a strategy" subtitle={`${strategies.length} strategies on ${market.symbol === GOLD.symbol ? "gold's" : `${market.name}'s`} history`} />
        <MarketPicker market={market} markets={markets} onChange={setSymbol} />
        <div className="rounded-2xl border border-border bg-surface p-3">
          <div className="flex items-center gap-2 rounded-lg border border-border bg-background px-2.5">
            <Icon name="search" className="h-4 w-4 text-muted" />
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search strategies"
              className="w-full bg-transparent py-1.5 text-sm outline-none" />
          </div>
          <div className="mt-2.5">
            <Chips value={kind} onChange={setKind} options={[
              { key: "all", label: "All", count: all.length },
              { key: "trend", label: "Trend", count: strategies.filter((x) => x.kind === "trend").length },
              { key: "reversion", label: "Reversion", count: strategies.filter((x) => x.kind === "reversion").length },
              { key: "benchmark", label: "Benchmark", count: strategies.filter((x) => x.kind === "benchmark").length },
              ...(mine.length ? [{ key: "custom" as const, label: "Mine", count: mine.length }] : []),
            ]} />
          </div>
          <div role="radiogroup" aria-label="Strategy" className="mt-2.5 max-h-64 space-y-1 overflow-y-auto pr-1">
            {all
              .filter((x) => (kind === "all" || x.kind === kind) && `${x.label} ${x.summary}`.toLowerCase().includes(search.toLowerCase()))
              .map((x) => {
                const on = x.key === selected;
                return (
                  <button key={x.key} type="button" role="radio" aria-checked={on} onClick={() => pick(x.key)}
                    className={`flex w-full items-center gap-2.5 rounded-lg border px-2.5 py-2 text-left text-sm transition-colors ${on ? "border-gold bg-gold/10" : "border-transparent hover:bg-background"}`}>
                    <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-lg ${x.kind === "trend" ? "bg-up/15 text-up" : x.kind === "reversion" ? "bg-calm/15 text-calm" : "bg-gold/15 text-gold"}`}>
                      <Icon name={x.kind === "trend" ? "backtest" : x.kind === "reversion" ? "scale" : x.kind === "custom" ? "bolt" : "layers"} className="h-4 w-4" />
                    </span>
                    <span className="min-w-0 flex-1 truncate">{x.label}</span>
                    {on && <Icon name="check" className="h-4 w-4 text-gold" />}
                  </button>
                );
              })}
          </div>
          <Link href="/strategies/builder" className="mt-2.5 flex items-center justify-center gap-1.5 rounded-lg border border-dashed border-gold/40 py-2 text-sm text-gold transition-colors hover:bg-gold/10">
            <Icon name="bolt" className="h-4 w-4" /> Build your own strategy
          </Link>
        </div>
        <p className="text-xs leading-relaxed text-muted">
          <span className="mr-1.5 rounded bg-surface px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-gold">{strategy.kind_label}</span>
          {strategy.summary}
        </p>
        {strategy.params.map((p) =>
          p.min === 0 && p.max === 1 && p.step === 1 ? (
            <label key={p.key} className="flex items-center gap-2 text-sm text-muted">
              <input type="checkbox" checked={!!form.params[p.key]} className="accent-[var(--gold)]"
                onChange={(e) => set({ params: { ...form.params, [p.key]: e.target.checked ? 1 : 0 } })} />
              {p.label.replace(" (1 = yes)", "")}
            </label>
          ) : (
            <Field key={p.key} label={p.label}>
              <Num value={form.params[p.key]} step={p.step} min={p.min} max={p.max}
                onChange={(v) => set({ params: { ...form.params, [p.key]: v ?? p.default } })} />
            </Field>
          ),
        )}

        <div className="grid grid-cols-2 gap-3">
          <Field label="Candles">
            <select className={input} value={form.tf} onChange={(e) => setTf(e.target.value as BacktestTf)}>
              <option value="1d">Daily</option>
              <option value="1h">Hourly</option>
              <option value="15m">15 minutes</option>
              <option value="5m">5 minutes</option>
            </select>
          </Field>
          <Field label="Trade">
            <select className={input} value={form.direction} onChange={(e) => set({ direction: e.target.value as BacktestParams["direction"] })}>
              <option value="both">Long and short</option>
              <option value="long_only">Long only</option>
              <option value="short_only">Short only</option>
            </select>
          </Field>
          <Field label="From">
            <input type="date" className={input} value={form.start} min={dataFrom ?? "2003-05-01"} onChange={(e) => set({ start: e.target.value })} />
          </Field>
          <Field label="To">
            <input type="date" className={input} value={form.end ?? ""} onChange={(e) => set({ end: e.target.value || null })} />
          </Field>
        </div>
        {dataFrom ? (
          <p className="-mt-2 text-xs text-muted">
            {minuteTf ? "Minute prices" : "Prices"} for {market.name} start on {fmtDay(dataFrom)}.
            {minuteTf && " 5- and 15-minute tests cover months, not years."}
          </p>
        ) : minuteTf ? (
          <p className="-mt-2 text-xs text-muted">No minute prices for {market.name} yet. They load once the market has been opened.</p>
        ) : null}

        <details className="rounded-lg border border-border p-3" open={intraday}>
          <summary className="cursor-pointer text-sm font-medium">Day trading</summary>
          <div className="mt-3 space-y-3">
            <Field label="Trading hours" hint={intraday ? SESSIONS.find((x) => x.key === (form.session ?? "any"))?.hint : "Pick hourly, 15-minute or 5-minute candles to set hours."}>
              <select className={input} value={form.session ?? "any"} disabled={!intraday}
                onChange={(e) => set({ session: e.target.value as TradingHours, ...(e.target.value === "custom" && !form.session_start ? { session_start: "09:30", session_end: "11:30" } : {}) })}>
                {SESSIONS.map((x) => <option key={x.key} value={x.key}>{x.label}</option>)}
              </select>
            </Field>
            {intraday && form.session === "custom" && (
              <div className="grid grid-cols-3 gap-2">
                <Field label="From"><input type="time" className={input} value={form.session_start ?? ""} onChange={(e) => set({ session_start: e.target.value })} /></Field>
                <Field label="To"><input type="time" className={input} value={form.session_end ?? ""} onChange={(e) => set({ session_end: e.target.value })} /></Field>
                <Field label="Clock">
                  <select className={input} value={form.session_tz} onChange={(e) => set({ session_tz: e.target.value as BacktestParams["session_tz"] })}>
                    <option value="America/New_York">New York</option>
                    <option value="Europe/London">London</option>
                    <option value="Asia/Tokyo">Tokyo</option>
                    <option value="UTC">UTC</option>
                  </select>
                </Field>
              </div>
            )}
            <label className={`flex items-start gap-2 text-sm ${intraday ? "" : "opacity-50"}`}>
              <input type="checkbox" checked={!!form.day_trade} disabled={!intraday} className="mt-1 accent-[var(--gold)]"
                onChange={(e) => set({ day_trade: e.target.checked })} />
              <span>Close every trade the same day<span className="block text-xs text-muted">
                {form.session && form.session !== "any" ? "At the end of the trading hours." : "Before the 17:00 New York rollover."} Nothing is held overnight, so no swap is paid.
              </span></span>
            </label>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Most trades a day"><Num value={form.max_trades_per_day} min={1} max={100} step={1} placeholder="no limit" onChange={(v) => set({ max_trades_per_day: v })} /></Field>
              <Field label="Daily loss limit (%)" hint="Stops for the day"><Num value={form.daily_loss_limit_pct} min={0.1} max={50} placeholder="none" onChange={(v) => set({ daily_loss_limit_pct: v })} /></Field>
            </div>
          </div>
        </details>

        <details className="rounded-lg border border-border p-3" open>
          <summary className="cursor-pointer text-sm font-medium">Money and risk</summary>
          <div className="mt-3 grid grid-cols-2 gap-3">
            <Field label="Starting capital ($)"><Num value={form.capital} min={1} onChange={(v) => set({ capital: v ?? 10000 })} /></Field>
            {form.size_pct ? (
              <Field label="Size (% of account)" hint={`${(form.size_pct / 100).toFixed(2)}x, resized each trade`}>
                <Num value={form.size_pct} min={0.1} onChange={(v) => set({ size_pct: v })} />
              </Field>
            ) : (
              <Field label={`${unitName(market)[0].toUpperCase()}${unitName(market).slice(1)} per trade`} hint={market.lot > 1 ? `1 lot = ${market.lot.toLocaleString()} ${unitName(market)}` : undefined}>
                <Num value={form.units} min={0.0001} onChange={(v) => set({ units: v ?? market.default_units })} />
              </Field>
            )}
            <Field label="Stop loss (%)"><Num value={form.stop_loss_pct} min={0.1} placeholder="none" onChange={(v) => set({ stop_loss_pct: v })} /></Field>
            <Field label="Take profit (%)"><Num value={form.take_profit_pct} min={0.1} placeholder="none" onChange={(v) => set({ take_profit_pct: v })} /></Field>
          </div>
          <label className="mt-3 flex items-center gap-2 text-sm text-muted">
            <input type="checkbox" checked={!!form.size_pct} className="accent-[var(--gold)]"
              onChange={(e) => set({ size_pct: e.target.checked ? 100 : null })} />
            Size each trade as a % of the account
          </label>
        </details>
        <details className="rounded-lg border border-border p-3">
          <summary className="cursor-pointer text-sm font-medium">Broker costs</summary>
          <div className="mt-3 grid grid-cols-2 gap-3">
            <Field label={`Spread ($ per ${market.unit})`}><Num value={form.spread} min={0} onChange={(v) => set({ spread: v ?? 0 })} /></Field>
            <Field label={`Slippage ($ per ${market.unit})`} hint="Market orders and stops fill this far past the price">
              <Num value={form.slippage} min={0} placeholder={market.slippage != null ? String(market.slippage) : "default"} onChange={(v) => set({ slippage: v })} />
            </Field>
            <Field label="Commission (% of value)" hint="Each side: on entry and on exit">
              <Num value={form.commission_pct} min={0} placeholder={String(market.commission_pct ?? 0)} onChange={(v) => set({ commission_pct: v })} />
            </Field>
            <Field label={`Commission ($ per ${market.unit})`} hint="Each side">
              <Num value={form.commission_per_unit} min={0} placeholder={String(market.commission_per_unit ?? 0)} onChange={(v) => set({ commission_per_unit: v })} />
            </Field>
            <Field label="Minimum commission ($ per order)">
              <Num value={form.commission_min} min={0} placeholder={String(market.commission_min ?? 0)} onChange={(v) => set({ commission_min: v })} />
            </Field>
            <div />
            <Field label={`Swap long ($/${market.unit}/night)`}><Num value={form.swap_long} placeholder={`${market.swap_long_pct}% a year`} onChange={(v) => set({ swap_long: v })} /></Field>
            <Field label={`Swap short ($/${market.unit}/night)`}><Num value={form.swap_short} placeholder={`${market.swap_short_pct}% a year`} onChange={(v) => set({ swap_short: v })} /></Field>
          </div>
          <label className="mt-3 flex items-start gap-2 text-sm">
            <input type="checkbox" checked={form.realistic_fills ?? true} className="mt-1 accent-[var(--gold)]"
              onChange={(e) => set({ realistic_fills: e.target.checked })} />
            <span>Realistic fills<span className="block text-xs text-muted">Wider spreads at the 5pm New York rollover (hourly candles) and around high-impact releases, and stops that slip past their price when a release lands inside their candle.</span></span>
          </label>
          <p className="mt-2 text-xs text-muted">
            Defaults are rough estimates for {market.name} on a standard retail account. An empty swap charges the yearly rate
            shown on the position&apos;s value, and an empty commission or slippage uses the market&apos;s default. Take profits are
            limit orders and don&apos;t slip. Check your broker&apos;s spread, commission and swap rates.
          </p>
        </details>

        {error && <p className="text-sm text-down">{error}</p>}
        <button disabled={busy} className="w-full rounded-lg bg-gold py-2 font-medium text-black transition disabled:opacity-60">
          {busy ? "Running…" : "Run backtest"}
        </button>
        <p className="text-xs text-muted">
          Signals use each candle&apos;s close and trade at the next candle&apos;s open. The last 30% of the period is
          also reported on its own, as a check on prices the strategy wasn&apos;t tuned on. Past results don&apos;t predict future ones.
        </p>
      </form>

      <section id="results" className="min-w-0 space-y-6">
        {result ? (
          <div>
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <h2 className="flex min-w-0 flex-1 items-center gap-2 font-medium"><Icon name="backtest" className="h-4 w-4 text-gold" />{label(strategies, result.params, markets)}</h2>
              {result.stats.trades > 0 && (
                <ShareButton data={resultShare("Backtest", label(strategies, result.params, markets),
                  `${ticker(markets.find((x) => x.symbol === (result.params.symbol ?? GOLD.symbol)) ?? GOLD)} · ${result.params.tf} candles · ${result.params.start.slice(0, 4)} to ${(result.params.end ?? new Date().toISOString()).slice(0, 4)} · ${fmtUsd(result.params.capital)} start`,
                  result.stats, result.equity)} />
              )}
            </div>
            <div className="space-y-4">
              {result.period && result.period.start * 1000 > Date.parse(`${result.params.start}T00:00:00Z`) + 30 * 864e5 && (
                <p className="rounded-xl border border-border bg-surface px-3 py-2 text-sm text-muted">
                  <Icon name="clock" className="mr-1.5 inline h-4 w-4 text-gold" />
                  Prices for this market start on {new Date(result.period.start * 1000).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })}, so the test starts there instead of {fmtDay(result.params.start)}.
                </p>
              )}
              {result.robustness && result.stats.trades > 0 && <TrustPanel robustness={result.robustness} split={result.split} />}
              {result.days && <DayStatsCard d={result.days} />}
              <FitPanel load={() => api.backtestFit(result.id)} deps={[result.id]} />
              <ReportView report={result} kind="backtest" />
            </div>
          </div>
        ) : (
          <Empty icon="backtest" title="No backtest yet">
            Pick a strategy and press Run to see its equity curve, drawdown, trades and statistics.
          </Empty>
        )}
        {history.length > 0 && (
          <div>
            <h2 className="mb-2 font-medium">Your backtests</h2>
            <div className="overflow-x-auto rounded-2xl border border-border">
              <table className="w-full text-sm tabular-nums">
                <thead className="bg-surface text-left text-xs text-muted">
                  <tr>
                    <th className="px-3 py-2">Strategy</th>
                    <th className="px-3 py-2 text-right">Return</th>
                    <th className="px-3 py-2 text-right">Max DD</th>
                    <th className="px-3 py-2 text-right">Trades</th>
                    <th className="px-3 py-2" />
                  </tr>
                </thead>
                <tbody>
                  {history.map((h) => (
                    <tr key={h.id} className={`border-t border-border transition-colors hover:bg-surface ${result?.id === h.id ? "bg-surface" : ""}`}>
                      <td className="px-3 py-1.5">
                        <button onClick={() => open(h.id)} className="text-left hover:text-gold">{label(strategies, h.params, markets)}</button>
                      </td>
                      <td className={`px-3 py-1.5 text-right ${(h.stats.total_return_pct ?? 0) >= 0 ? "text-up" : "text-down"}`}>
                        {fmtPct(h.stats.total_return_pct)}
                      </td>
                      <td className="px-3 py-1.5 text-right text-down">{fmtPct(h.stats.max_drawdown_pct)}</td>
                      <td className="px-3 py-1.5 text-right">{h.stats.trades}</td>
                      <td className="px-3 py-1.5 text-right">
                        <button onClick={() => remove(h.id)} className="text-xs text-muted hover:text-down">Delete</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
