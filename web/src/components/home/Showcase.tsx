import Link from "next/link";
import { Icon } from "@/components/ui";

type Tone = React.CSSProperties & { "--tone": string };
const tone = (c: string): Tone => ({ "--tone": c });

function Tile({ href, icon, title, body, cta, colour, className = "", children }: {
  href: string; icon: string; title: string; body: string; cta: string; colour: string; className?: string; children: React.ReactNode;
}) {
  return (
    <Link href={href} style={tone(colour)} className={`lux group flex w-[86%] shrink-0 snap-start flex-col overflow-hidden p-6 sm:p-7 md:w-auto ${className}`}>
      <div className="flex items-center gap-3">
        <span className="tone-tile flex h-10 w-10 items-center justify-center rounded-xl"><Icon name={icon} className="h-5 w-5" /></span>
        <h3 className="text-lg font-semibold tracking-tight">{title}</h3>
      </div>
      <p className="mt-3 max-w-md text-sm leading-relaxed text-muted">{body}</p>
      <div className="mt-6 flex-1">{children}</div>
      <span className="tone-text mt-6 inline-flex items-center gap-1.5 text-sm font-medium">
        {cta} <Icon name="arrow" className="h-4 w-4 transition-transform duration-300 group-hover:translate-x-1" />
      </span>
    </Link>
  );
}

/** An order ticket in miniature: the risk is the first thing on it. The figures are an example. */
function Ticket() {
  return (
    <div className="grid gap-3 sm:grid-cols-[1fr_1.1fr]" aria-hidden>
      <div className="rounded-xl border border-border bg-background/60 p-4">
        <div className="grid grid-cols-2 gap-2 text-center text-xs font-semibold">
          <span className="rounded-lg border border-up/50 bg-up/15 py-2 text-up">Buy</span>
          <span className="rounded-lg border border-border py-2 text-muted">Sell</span>
        </div>
        {[["Entry", "Market"], ["Stop loss", "Set first"], ["Target", "2 × risk"]].map(([k, v]) => (
          <div key={k} className="mt-2.5 flex items-center justify-between text-xs">
            <span className="text-muted">{k}</span><span className="font-medium tabular-nums">{v}</span>
          </div>
        ))}
      </div>
      <div className="rounded-xl border border-border bg-background/60 p-4">
        <p className="text-[11px] uppercase tracking-wider text-muted">If this trade loses</p>
        <p className="mt-1 text-2xl font-semibold tabular-nums tracking-tight">1.0% <span className="text-sm font-normal text-muted">of the account</span></p>
        <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-border">
          <div className="bar-grow h-full w-1/3 rounded-full bg-gradient-to-r from-up to-gold" />
        </div>
        <p className="mt-2 text-[11px] text-muted">Inside your limit. Size is worked out from the stop.</p>
      </div>
    </div>
  );
}

function Equity() {
  const line = "M0 70 L18 66 L34 68 L52 58 L70 61 L88 49 L104 53 L122 40 L140 44 L158 31 L176 35 L196 22 L216 26 L240 12";
  return (
    <svg viewBox="0 0 240 84" className="h-28 w-full" preserveAspectRatio="none" aria-hidden>
      <defs><linearGradient id="eq" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stopColor="var(--tone)" stopOpacity="0.35" /><stop offset="1" stopColor="var(--tone)" stopOpacity="0" /></linearGradient></defs>
      {[21, 42, 63].map((y) => <line key={y} x1="0" x2="240" y1={y} y2={y} stroke="var(--border)" strokeDasharray="2 4" />)}
      <path d={`${line} L240 84 L0 84Z`} fill="url(#eq)" />
      <path d={line} fill="none" stroke="var(--tone)" strokeWidth="2" strokeLinejoin="round" pathLength={1} className="line-draw" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

function Candles() {
  const c: [number, number, number, number][] = [[30, 44, 26, 48], [42, 34, 30, 46], [35, 24, 20, 38], [25, 30, 22, 34], [30, 18, 14, 33], [19, 26, 16, 30], [26, 12, 8, 28], [13, 20, 10, 24]];
  return (
    <svg viewBox="0 0 240 84" className="h-28 w-full" aria-hidden>
      {c.map(([o, cl, h, l], i) => {
        const up = cl < o, x = 14 + i * 22;
        return (
          <g key={i} className="candle-in" style={{ animationDelay: `${i * 120}ms` }} fill={up ? "var(--up)" : "var(--down)"} stroke={up ? "var(--up)" : "var(--down)"}>
            <line x1={x + 5} x2={x + 5} y1={h + 14} y2={l + 14} strokeWidth="1.4" />
            <rect x={x} y={Math.min(o, cl) + 14} width="10" height={Math.max(2, Math.abs(o - cl))} rx="1.5" stroke="none" />
          </g>
        );
      })}
      <line x1="196" x2="196" y1="6" y2="78" stroke="var(--tone)" strokeDasharray="3 4" />
      <circle cx="218" cy="42" r="13" fill="color-mix(in srgb, var(--tone) 18%, transparent)" stroke="var(--tone)" />
      <path d="M214 36v12l10-6z" fill="var(--tone)" />
    </svg>
  );
}

function Ring({ pct, label, value }: { pct: number; label: string; value: string }) {
  const len = 2 * Math.PI * 26;
  return (
    <div className="flex items-center gap-3">
      <svg viewBox="0 0 64 64" className="h-14 w-14 -rotate-90" aria-hidden>
        <circle cx="32" cy="32" r="26" fill="none" stroke="var(--border)" strokeWidth="5" />
        <circle cx="32" cy="32" r="26" fill="none" stroke="var(--tone)" strokeWidth="5" strokeLinecap="round"
          strokeDasharray={len} strokeDashoffset={len * (1 - pct)} className="ring-fill" style={{ "--len": len } as React.CSSProperties} />
      </svg>
      <div><p className="text-sm font-semibold tabular-nums">{value}</p><p className="text-[11px] text-muted">{label}</p></div>
    </div>
  );
}

function Chat() {
  return (
    <div className="space-y-2 text-xs" aria-hidden>
      <p className="ml-auto w-fit max-w-[85%] rounded-2xl rounded-br-md bg-[color-mix(in_srgb,var(--tone)_22%,transparent)] px-3 py-2">Why did my stop get hit before the move?</p>
      <p className="w-fit max-w-[90%] rounded-2xl rounded-bl-md border border-border bg-background/60 px-3 py-2 text-muted">It sat inside the usual hourly range. Here is how to place it outside the noise…</p>
      <p className="flex w-fit gap-1 rounded-2xl border border-border bg-background/60 px-3 py-2.5">
        {[0, 1, 2].map((i) => <span key={i} className="typing-dot h-1.5 w-1.5 rounded-full bg-muted" style={{ animationDelay: `${i * 0.15}s` }} />)}
      </p>
    </div>
  );
}

function Chain() {
  return (
    <div className="flex items-center gap-2 overflow-hidden" aria-hidden>
      {["a3f9…1c", "7be2…90", "d41c…e7", "09aa…5f"].map((h, i) => (
        <div key={h} className="flex items-center gap-2">
          {i > 0 && <span className="h-px w-5 bg-[var(--tone)] opacity-60 sm:w-8" />}
          <span className="rounded-lg border border-border bg-background/60 px-2.5 py-2 font-mono text-[11px] text-muted">{h}</span>
        </div>
      ))}
      <span className="h-px w-5 bg-[var(--tone)] opacity-60 sm:w-8" />
      <span className="tone-tile flex h-9 w-9 shrink-0 items-center justify-center rounded-full"><Icon name="seal" className="h-4 w-4" /></span>
    </div>
  );
}

/** The tools, each shown with a small picture of what it does. Figures inside the pictures are examples. */
export default function Showcase() {
  return (
    <div className="-mx-4 flex snap-x snap-mandatory scroll-px-4 gap-3 overflow-x-auto px-4 pb-3 [scrollbar-width:none] md:mx-0 md:grid md:grid-cols-2 md:gap-4 md:overflow-visible md:px-0 md:pb-0 lg:grid-cols-3">
      <Tile href="/paper" icon="wallet" title="Paper trading" colour="var(--gold)" className="lg:col-span-2" cta="Open the trading desk"
        body="Trade live prices with virtual money. Every ticket shows what the trade could lose before you place it.">
        <Ticket />
      </Tile>
      <Tile href="/backtest" icon="backtest" title="Backtests" colour="var(--violet)" cta="Test an idea"
        body="23 built-in strategies, or rules of your own, run on years of real prices with real costs.">
        <Equity />
      </Tile>
      <Tile href="/paper/replay" icon="clock" title="Market replay" colour="var(--calm)" cta="Replay a day"
        body="Step through any past day candle by candle and trade it as if it were live.">
        <Candles />
      </Tile>
      <Tile href="/paper/prop" icon="risk" title="Prop challenge" colour="var(--up)" cta="Try a challenge"
        body="Practise a funded-trader evaluation: a profit target inside daily and overall loss limits.">
        <div className="grid gap-3">
          <Ring pct={0.62} value="Target +8%" label="Profit to pass" />
          <Ring pct={0.25} value="Limit 6% a day" label="Loss that ends it" />
        </div>
      </Tile>
      <Tile href="/coach" icon="assistant" title="Coach and assistant" colour="var(--rose)" cta="Meet your coach"
        body="A coach that reviews your own trades, and an assistant that answers in plain language.">
        <Chat />
      </Tile>
      <Tile href="/record" icon="seal" title="Verified track record" colour="var(--gold)" className="md:col-span-2 lg:col-span-3" cta="See how it's sealed"
        body="Every closed trade is sealed into a tamper-evident ledger, so the record you share is one anyone can check.">
        <Chain />
      </Tile>
    </div>
  );
}
