"use client";

import Link from "next/link";
import { useState } from "react";
import type { Dna, DnaPlan, DnaResult } from "@/lib/api";

const RESULT: Record<DnaResult, { label: string; color: string }> = {
  pass: { label: "Passed", color: "var(--up)" },
  daily: { label: "Daily limit broken", color: "var(--down)" },
  overall: { label: "Overall limit broken", color: "var(--gold)" },
  open: { label: "Not finished", color: "var(--muted)" },
};

/** Six scores on a hexagon; the weakest axis is named in red. */
function Radar({ scores, weakest }: { scores: Dna["scores"]; weakest?: string }) {
  const W = 340, H = 230, cx = W / 2, cy = H / 2 + 4, R = 78;
  const at = (i: number, r: number) => {
    const a = -Math.PI / 2 + (i * Math.PI * 2) / scores.length;
    return [cx + Math.cos(a) * r, cy + Math.sin(a) * r] as const;
  };
  const poly = (f: (i: number) => number) => scores.map((_, i) => at(i, f(i)).join(",")).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full max-w-[340px]" role="img"
      aria-label={scores.map((s) => `${s.label} ${Math.round(s.score)}`).join(", ")}>
      {[1 / 3, 2 / 3, 1].map((k) => <polygon key={k} points={poly(() => R * k)} fill="none" stroke="var(--border)" />)}
      {scores.map((_, i) => { const [x, y] = at(i, R); return <line key={i} x1={cx} y1={cy} x2={x} y2={y} stroke="var(--border)" />; })}
      <polygon points={poly((i) => (R * Math.max(scores[i].score, 3)) / 100)} fill="var(--gold)" fillOpacity={0.22} stroke="var(--gold)" strokeWidth={2} />
      {scores.map((s, i) => {
        const [x, y] = at(i, R + 16);
        const anchor = Math.abs(x - cx) < 4 ? "middle" : x > cx ? "start" : "end";
        return (
          <text key={s.key} x={x} y={y + 4} textAnchor={anchor} fontSize={11} fontWeight={s.key === weakest ? 600 : 400}
            fill={s.key === weakest ? "var(--down)" : "var(--muted)"}>{s.label} {Math.round(s.score)}</text>
        );
      })}
    </svg>
  );
}

/** The real order as a bold line over simulated paths, between the overall floor and the target. */
function Fan({ p }: { p: DnaPlan }) {
  const W = 640, H = 220, pad = 16;
  const target = 100 + p.rules.targets[0], floor = 100 - p.rules.max_loss_pct;
  const all = [...p.paths.flatMap((x) => x.path), ...p.actual_path, target, floor];
  const lo = Math.min(...all) - 1, hi = Math.max(...all) + 1;
  const n = Math.max(...p.paths.map((x) => x.path.length), p.actual_path.length) - 1 || 1;
  const x = (i: number) => (i / n) * W;
  const y = (v: number) => pad + (1 - (v - lo) / (hi - lo)) * (H - pad * 2);
  const line = (path: number[]) => path.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label={`${p.label}: simulated paths built from your trading days`}>
      <line x1={0} x2={W} y1={y(target)} y2={y(target)} stroke="var(--up)" strokeDasharray="5 4" />
      <line x1={0} x2={W} y1={y(floor)} y2={y(floor)} stroke="var(--down)" strokeDasharray="5 4" />
      <line x1={0} x2={W} y1={y(100)} y2={y(100)} stroke="var(--border)" />
      {p.paths.map((q, i) => (
        <polyline key={i} points={line(q.path)} fill="none" stroke={RESULT[q.result].color} strokeOpacity={0.3} strokeWidth={1.2} vectorEffect="non-scaling-stroke" />
      ))}
      <polyline points={line(p.actual_path)} fill="none" stroke="var(--foreground)" strokeWidth={2.4} strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
      <text x={6} y={y(target) - 6} fontSize={11} fill="var(--up)">+{p.rules.targets[0]}% target</text>
      <text x={6} y={y(floor) + 14} fontSize={11} fill="var(--down)">-{p.rules.max_loss_pct}% overall limit</text>
      <text x={W - 6} y={H - 4} textAnchor="end" fontSize={11} fill="var(--muted)">trading days →</text>
    </svg>
  );
}

function Odds({ odds }: { odds: DnaPlan["odds"] }) {
  const keys: DnaResult[] = ["pass", "daily", "overall", "open"];
  return (
    <div>
      <div className="flex h-2.5 overflow-hidden rounded-full bg-border">
        {keys.map((k) => odds[k] > 0 && <span key={k} style={{ width: `${odds[k]}%`, background: RESULT[k].color }} />)}
      </div>
      <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-muted">
        {keys.map((k) => (
          <span key={k} className="flex items-center gap-1">
            <span className="h-2 w-2 rounded-full" style={{ background: RESULT[k].color }} />{RESULT[k].label} {odds[k]}%
          </span>
        ))}
      </div>
    </div>
  );
}

export default function DnaCard({ d }: { d: Dna }) {
  const [pick, setPick] = useState(0);
  if (!d.ready) {
    return (
      <section className="card mt-8 p-5">
        <h2 className="font-semibold">Your trader DNA</h2>
        <p className="mt-1 text-sm text-muted">
          Close {d.needed! - d.trades} more paper trade{d.needed! - d.trades === 1 ? "" : "s"} and this turns into a scouting report: six behaviour
          scores and your odds of passing each challenge, worked out from your own trades.{" "}
          <Link href="/paper" className="text-gold hover:underline">Go to paper trading</Link>
        </p>
      </section>
    );
  }
  const weak = d.scores.find((s) => s.key === d.weakest);
  const p = d.plans[pick];
  return (
    <section className="card mt-8 space-y-6 p-5">
      <div>
        <h2 className="text-lg font-semibold">Your trader DNA</h2>
        <p className="mt-1 text-sm text-muted">
          A scouting report from your last {d.trades} closed paper trades over {d.days} trading days. It is the sheet a prop firm
          analyst would read: how you behave, not how much you made.
        </p>
      </div>
      <div className="grid items-center gap-6 md:grid-cols-[340px_minmax(0,1fr)]">
        <div className="flex justify-center"><Radar scores={d.scores} weakest={d.weakest} /></div>
        <ul className="space-y-2 text-sm">
          {d.scores.map((s) => (
            <li key={s.key} className="grid grid-cols-[6.5rem_minmax(0,1fr)_2.5rem] items-baseline gap-3">
              <span className={s.key === d.weakest ? "font-semibold text-down" : "font-medium"}>{s.label}</span>
              <span className="text-muted">{s.text}</span>
              <span className="text-right tabular-nums">{Math.round(s.score)}</span>
            </li>
          ))}
          {weak && <li className="pt-1 text-xs text-muted">Weakest trait: <span className="text-down">{weak.label.toLowerCase()}</span>. That is the one to work on before a real evaluation.</li>}
        </ul>
      </div>

      <div className="space-y-3">
        <div>
          <h3 className="font-semibold">Rulebook remix</h3>
          <p className="mt-1 text-sm text-muted">
            Your trading days, replayed against each plan&apos;s phase 1 rules in their real order (bold line), then 1,000 times as 60 more
            days picked at random from your own. It shows which rulebook fits the way you trade before you sit one.
          </p>
        </div>
        <div className="grid gap-2 sm:grid-cols-3">
          {d.plans.map((q, i) => (
            <button key={q.plan} type="button" onClick={() => setPick(i)} aria-pressed={i === pick}
              className={`space-y-2 rounded-xl border p-3 text-left transition-colors ${i === pick ? "border-gold/60 bg-gold/5" : "border-border hover:border-muted"}`}>
              <span className="flex items-baseline justify-between gap-2">
                <span className="font-medium">{q.label}</span>
                <span className="text-lg font-bold tabular-nums" style={{ color: "var(--up)" }}>{q.odds.pass}%</span>
              </span>
              <span className="block text-xs text-muted">
                In your real order: <span style={{ color: RESULT[q.actual].color }}>{RESULT[q.actual].label.toLowerCase()}</span>
                {q.actual !== "open" ? ` on day ${q.actual_days}` : ""}
              </span>
              <Odds odds={q.odds} />
            </button>
          ))}
        </div>
        <div className="rounded-xl border border-border bg-background/40 p-2"><Fan p={p} /></div>
        <p className="text-xs text-muted">
          Only closed results are counted, so losses inside open trades don&apos;t show here and a real challenge is somewhat harder.
          Two-step plans show phase 1 only. Past trades don&apos;t predict future ones; the odds describe your habits so far.
        </p>
      </div>
    </section>
  );
}
