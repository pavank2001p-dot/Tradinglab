import { fmtPct, type Robustness, type Split } from "@/lib/api";
import { Icon } from "./ui";

const LEVEL = {
  strong: { box: "border-up/50 bg-up/10", dot: "bg-up", text: "text-up" },
  fair: { box: "border-gold/50 bg-gold/10", dot: "bg-gold", text: "text-gold" },
  weak: { box: "border-down/50 bg-down/10", dot: "bg-down", text: "text-down" },
  thin: { box: "border-down/50 bg-down/10", dot: "bg-down", text: "text-down" },
};
const MARK = { pass: ["check", "text-up"], warn: ["drop", "text-gold"], fail: ["down", "text-down"] } as const;

const SUMMARY = {
  strong: "The result held up on data the strategy wasn't tuned on, with enough trades, and rarely lost when the trades were reshuffled.",
  fair: "Promising, but at least one check is borderline. Treat the numbers as optimistic.",
  weak: "At least one check failed. The past profit may be a fit to this stretch of history rather than a real edge.",
  thin: "Too few trades to say whether this is skill or luck.",
};

const year = (t: number) => new Date(t * 1000).toLocaleDateString(undefined, { month: "short", year: "numeric" });
const tone = (v: number | null | undefined) => (v == null ? "" : v >= 0 ? "text-up" : "text-down");

/** How far a backtest can be trusted: the trust level, the checks behind it, and the development part against
 *  the held-back part. */
export default function TrustPanel({ robustness: r, split, compact = false }: { robustness: Robustness; split?: Split | null; compact?: boolean }) {
  const lv = LEVEL[r.level];
  const rows = split ? ([
    ["Return", (s: Split["development"]) => s.total_return_pct, fmtPct],
    ["Per trade", (s: Split["development"]) => s.avg_trade_return_pct, (v: number) => `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`],
    ["Max drawdown", (s: Split["development"]) => s.max_drawdown_pct, fmtPct],
    ["Profit factor", (s: Split["development"]) => s.profit_factor, (v: number) => v.toFixed(2)],
    ["Trades", (s: Split["development"]) => s.trades, (v: number) => String(v)],
  ] as const) : [];
  return (
    <section className={`rounded-2xl border p-4 ${lv.box}`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className={`h-2.5 w-2.5 rounded-full ${lv.dot}`} />
        <h3 className="font-semibold">Will it hold up? <span className={lv.text}>{r.label}</span></h3>
      </div>
      <p className="mt-1 text-sm text-muted">{SUMMARY[r.level]}</p>
      <ul className="mt-3 space-y-2">
        {r.checks.map((c) => {
          const [icon, colour] = MARK[c.status];
          return (
            <li key={c.key} className="flex gap-2 text-sm">
              <Icon name={icon} className={`mt-0.5 h-4 w-4 shrink-0 ${colour}`} />
              <span><b className="font-medium">{c.label}.</b> <span className="text-muted">{c.detail}</span></span>
            </li>
          );
        })}
      </ul>
      {split && !compact && (
        <div className="mt-4 overflow-x-auto rounded-xl border border-border bg-background/60">
          <table className="w-full text-sm tabular-nums">
            <thead className="text-left text-xs text-muted">
              <tr>
                <th className="px-3 py-2 font-normal" />
                <th className="px-3 py-2 text-right font-normal">Development<span className="block text-[10px]">to {year(split.cut)}</span></th>
                <th className="px-3 py-2 text-right font-normal">Held back<span className="block text-[10px]">from {year(split.cut)}</span></th>
              </tr>
            </thead>
            <tbody>
              {rows.map(([label, get, fmt]) => {
                const a = get(split.development), b = get(split.held_back);
                const colour = label === "Return" || label === "Per trade";
                return (
                  <tr key={label} className="border-t border-border">
                    <td className="px-3 py-1.5 text-muted">{label}</td>
                    <td className={`px-3 py-1.5 text-right ${colour ? tone(a) : ""}`}>{a == null ? "–" : fmt(a)}</td>
                    <td className={`px-3 py-1.5 text-right ${colour ? tone(b) : ""}`}>{b == null ? "–" : fmt(b)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {r.monte_carlo && !compact && (
        <p className="mt-3 text-xs text-muted">
          Luck test: the {r.monte_carlo.paths} reshuffled runs ended between {fmtPct(r.monte_carlo.return_p5)} and{" "}
          {fmtPct(r.monte_carlo.return_p95)} in 9 out of 10 cases (middle {fmtPct(r.monte_carlo.return_p50)}).
          Plan for a drawdown of {fmtPct(r.monte_carlo.drawdown_p95)}, not just the one this test happened to show.
        </p>
      )}
      <p className="mt-2 text-[11px] text-muted">
        {split
          ? "Tune your settings by looking at the development part only. The held-back part is the closest thing here to how the strategy would do on prices it has never seen."
          : "Nothing was held back in this test, so its result can't be checked on unseen prices."}
      </p>
    </section>
  );
}
