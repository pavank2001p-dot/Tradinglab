"use client";

import { useEffect, useState } from "react";
import { api, type BailEpisode } from "@/lib/api";
import { mirrorReady, money, useMirror } from "./MoneyMirror";

const LETTERS = ["A", "B", "C", "D"];

/** The balance month by month; months not yet lived are hidden until the walk is over. */
function Walk({ e, upto, limitPct, reveal }: { e: BailEpisode; upto: number; limitPct: number; reveal: boolean }) {
  const W = 640, H = 220, pad = 18;
  const months = reveal ? e.months : e.months.slice(0, upto + 1);
  const n = (reveal ? e.months.length : e.window + 1) - 1;
  const levels = [...(reveal ? e.months : e.months.slice(0, e.window + 1)).map((m) => m.level), 100 - limitPct, 100];
  const lo = Math.min(...levels) - 3, hi = Math.max(...levels) + 3;
  const x = (i: number) => (i / n) * W;
  const y = (v: number) => pad + (1 - (v - lo) / (hi - lo)) * (H - pad * 2);
  const pts = months.map((m, i) => `${x(i).toFixed(1)},${y(m.level).toFixed(1)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label="Your balance month by month">
      {!reveal && <rect x={x(upto)} y={0} width={W - x(upto)} height={H} fill="var(--gold)" fillOpacity={0.06} />}
      {reveal && <rect x={x(e.window)} y={0} width={W - x(e.window)} height={H} fill="var(--calm)" fillOpacity={0.07} />}
      <line x1={0} x2={W} y1={y(100)} y2={y(100)} stroke="var(--border)" />
      <line x1={0} x2={W} y1={y(100 - limitPct)} y2={y(100 - limitPct)} stroke="var(--down)" strokeDasharray="5 4" />
      <text x={W - 6} y={y(100 - limitPct) - 6} textAnchor="end" fontSize={11} fill="var(--down)" stroke="var(--background)" strokeWidth={4} paintOrder="stroke">your quiz limit -{limitPct}%</text>
      <polyline points={pts} fill="none" stroke="var(--gold)" strokeWidth={2.5} strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
      {months.map((m, i) => (
        <circle key={m.t} cx={x(i)} cy={y(m.level)} r={i === months.length - 1 ? 5 : 2.5} fill={i === upto ? "var(--gold)" : "var(--surface)"} stroke="var(--gold)" strokeWidth={1.5} />
      ))}
      {reveal && <text x={x(e.window) + 6} y={H - 6} fontSize={11} fill="var(--calm)">the year after</text>}
    </svg>
  );
}

/** Walk your own money through one of gold's worst years, a month at a time, and see where you would bail. */
export default function StayOrBail({ limitPct }: { limitPct: number }) {
  const [eps, setEps] = useState<BailEpisode[] | null>(null);
  const [pick, setPick] = useState(0);
  const [month, setMonth] = useState(0);
  const [bailed, setBailed] = useState<number | null>(null);
  const [mirror] = useMirror();
  const [amountIn, setAmountIn] = useState("");
  useEffect(() => { api.stayOrBail().then((r) => setEps(r.episodes), () => setEps([])); }, []);
  if (!eps?.length) return null;

  const currency = mirrorReady(mirror) ? mirror.currency : "USD";
  const amount = Number(amountIn.replace(/[^0-9.]/g, "")) || (mirrorReady(mirror) ? mirror.stake : 10_000);
  const e = eps[pick];
  const done = bailed != null || month >= e.window;
  const at = (i: number) => (amount * e.months[Math.min(i, e.months.length - 1)].level) / 100;
  const dd = (i: number) => e.months[i].level - 100;
  const startDate = new Date(e.start * 1000).toLocaleDateString("en-GB", { month: "long", year: "numeric", timeZone: "UTC" });
  const restart = (i: number) => { setPick(i); setMonth(0); setBailed(null); };

  const end = bailed ?? e.window;
  const passedLimit = e.months.slice(0, end + 1).some((m) => m.level - 100 <= -limitPct);
  const yearEnd = at(e.window), later = at(e.months.length - 1);

  return (
    <section className="rounded-2xl border border-border bg-surface p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">Stay or bail</h2>
          <p className="mt-1 max-w-xl text-sm text-muted">
            The quiz asked how a fall would feel. This shows you. Put your own money into one of gold&apos;s worst years and live it a month at a time.
            The month you bail is your real limit.
          </p>
        </div>
        <label className="text-xs text-muted">Your money ({currency})
          <input id="bail-amount" value={amountIn} onChange={(ev) => setAmountIn(ev.target.value)} inputMode="decimal" placeholder={String(amount)}
            disabled={month > 0 && !done} className="mt-1 block w-36 rounded-lg border border-border bg-background px-3 py-1.5 text-sm text-foreground outline-none focus:border-gold/60" />
        </label>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        {eps.map((_, i) => (
          <button key={i} type="button" onClick={() => restart(i)} aria-pressed={i === pick}
            className={`rounded-full border px-3 py-1 text-sm ${i === pick ? "border-gold/60 bg-gold/10 text-gold" : "border-border text-muted hover:border-muted"}`}>
            Year {LETTERS[i]}
          </button>
        ))}
        <span className="self-center text-xs text-muted">The dates stay hidden until you finish.</span>
      </div>

      <div className="mt-4 grid gap-4 md:grid-cols-[minmax(0,1fr)_240px]">
        <div className="rounded-xl border border-border bg-background/40 p-2">
          <Walk e={e} upto={done ? end : month} limitPct={limitPct} reveal={done} />
        </div>
        <div className="space-y-3">
          {!done ? (
            <>
              <p className="text-xs uppercase tracking-wider text-muted">Month {month} of {e.window}</p>
              <div>
                <p className="text-sm text-muted">Your {money(amount, currency)} is now</p>
                <p className="text-3xl font-bold tabular-nums">{money(at(month), currency)}</p>
                <p className={`text-sm tabular-nums ${dd(month) < 0 ? "text-down" : "text-up"}`}>{dd(month) >= 0 ? "+" : ""}{dd(month).toFixed(1)}% since you started</p>
              </div>
              {dd(month) <= -limitPct && (
                <p className="rounded-lg border border-down/40 bg-down/10 p-2 text-xs">You said you could live with a {limitPct}% fall. You are past it.</p>
              )}
              <div className="grid grid-cols-2 gap-2">
                <button type="button" onClick={() => setMonth(month + 1)} className="rounded-xl border border-gold/60 py-2.5 text-sm font-semibold text-gold hover:bg-gold/10">
                  {month === 0 ? "Start" : "Stay"}
                </button>
                <button type="button" disabled={month === 0} onClick={() => setBailed(month)} className="rounded-xl border border-border py-2.5 text-sm text-muted hover:bg-surface-2 disabled:opacity-40">
                  Bail out
                </button>
              </div>
            </>
          ) : (
            <div className="rise-in space-y-2 text-sm">
              <p className="text-xs uppercase tracking-wider text-muted">Year {LETTERS[pick]} was gold from {startDate}</p>
              <p className="text-lg font-semibold">
                {bailed != null ? `You bailed in month ${bailed}, at ${dd(bailed).toFixed(1)}%.` : "You stayed the whole year."}
              </p>
              <p className="text-muted">
                {bailed != null
                  ? dd(bailed) > -limitPct
                    ? `That is before the ${limitPct}% fall the quiz says you can live with, so your real limit may be tighter. Consider a smaller risk setting.`
                    : `That is past the ${limitPct}% the quiz set. Your limit and your gut agree.`
                  : passedLimit
                    ? `You sat through more than the ${limitPct}% you chose in the quiz. Your tolerance may be higher than you think.`
                    : "The fall never reached your quiz limit."}
              </p>
              <p className="text-muted">
                Staying to the end of the year left {money(yearEnd, currency)} ({(e.months[e.window].level - 100).toFixed(1)}%), and a year later {money(later, currency)} ({(e.months[e.months.length - 1].level - 100).toFixed(1)}%).
              </p>
              <button type="button" onClick={() => restart((pick + 1) % eps.length)} className="text-gold hover:underline">Try year {LETTERS[(pick + 1) % eps.length]}</button>
            </div>
          )}
        </div>
      </div>
      <p className="mt-3 text-xs text-muted">Real monthly gold closes, no leverage. The past doesn&apos;t say what gold will do next; it shows how a fall feels.</p>
    </section>
  );
}
