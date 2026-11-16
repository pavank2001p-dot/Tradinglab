import Link from "next/link";
import DailyCandle from "@/components/DailyCandle";
import HomeTop, { SignedOut } from "@/components/HomeTop";
import PriceChart from "@/components/PriceChart";
import PriceTicker from "@/components/PriceTicker";
import Reveal from "@/components/Reveal";
import CountUp from "@/components/home/CountUp";
import MarketStrip from "@/components/home/MarketStrip";
import RotatingWord from "@/components/home/RotatingWord";
import { Icon } from "@/components/ui";
import { LOOP, STAGE_ICON } from "@/lib/loop";

const habits = [
  { icon: "drop", title: "Decide the loss first", body: "Set where you would be wrong before you enter, and see it in dollars." },
  { icon: "scale", title: "Size from the stop", body: "Let the distance to your stop set the size, so one trade can't hurt much." },
  { icon: "clock", title: "There's always another trade", body: "Missing a move costs nothing. Taking a rushed one can." },
];

/** The motto names every market in turn; screen readers and the first paint get "any market". */
const MARKET_WORDS = ["any market", "gold", "stocks", "forex", "crypto", "indices", "oil"];

const STATS: { value: number; prefix?: string; label: string }[] = [
  { value: 5, label: "Market labs" },
  { value: 23, label: "Strategies, plus your own" },
  { value: 2000, label: "Paths per scenario" },
  { value: 0, prefix: "$", label: "Real money at risk" },
];

export default function Home() {
  return (
    <div className="mx-auto max-w-6xl px-4">
      <HomeTop hero={<section className="relative pb-10 pt-16 sm:pb-14 sm:pt-24">
        <div aria-hidden className="glow-drift pointer-events-none absolute -top-32 left-1/2 h-80 w-[48rem] max-w-full -translate-x-1/2 rounded-full bg-gold/10 blur-3xl" />
        <div aria-hidden className="pointer-events-none absolute inset-0 bg-[linear-gradient(to_right,color-mix(in_srgb,var(--foreground)_3%,transparent)_1px,transparent_1px),linear-gradient(to_bottom,color-mix(in_srgb,var(--foreground)_3%,transparent)_1px,transparent_1px)] bg-[size:56px_56px] [mask-image:radial-gradient(ellipse_at_top,black,transparent_70%)]" />
        <div className="relative">
          <span className="rise-in inline-flex items-center gap-2 rounded-full border border-gold/30 bg-gold/10 px-3 py-1 text-xs font-medium text-gold">
            <span className="breathe h-1.5 w-1.5 rounded-full bg-gold" /> Free practice lab for every market
          </span>
          <h1 className="rise-in mt-5 max-w-3xl text-[2.15rem] font-bold leading-[1.15] tracking-tight [animation-delay:80ms] sm:text-6xl">
            Master{" "}
            <RotatingWord words={MARKET_WORDS} label="any market"
              wordClass="bg-gradient-to-r from-gold via-gold-hi to-gold bg-clip-text text-transparent" />
            <br />
            before you risk a cent.
          </h1>
          <p className="rise-in mt-6 max-w-xl text-lg leading-relaxed text-muted [animation-delay:160ms]">
            Gold, forex, stocks, indices, energy and crypto in one place. Learn an idea, test it on real price
            history, then trade it with virtual money, with the risk shown before every move.
          </p>
          <div className="rise-in mt-9 flex flex-wrap gap-3 [animation-delay:240ms]">
            <Link href="/risk" className="group flex w-full items-center justify-center gap-2 rounded-full bg-gradient-to-b from-gold-hi to-gold px-6 py-3 font-semibold text-black shadow-[0_10px_30px_-12px_var(--gold),inset_0_1px_0_rgb(255_255_255/0.35)] transition-[filter,transform] hover:brightness-105 active:scale-[0.98] sm:w-auto">
              Start with your risk profile
              <Icon name="arrow" className="h-4 w-4 transition-transform duration-300 group-hover:translate-x-0.5" />
            </Link>
            <Link href="/chart" className="w-full rounded-full border border-border bg-surface/60 px-6 py-3 text-center sm:w-auto font-medium backdrop-blur transition-colors hover:border-gold/40">
              Explore the markets
            </Link>
          </div>
          <dl className="rise-in mt-12 grid max-w-3xl grid-cols-2 gap-y-6 border-t border-border pt-8 [animation-delay:320ms] sm:grid-cols-4">
            {STATS.map((s) => (
              <div key={s.label} className="flex flex-col sm:border-l sm:border-border sm:pl-5 sm:first:border-l-0 sm:first:pl-0">
                <dt className="mt-0.5 text-xs uppercase tracking-wider text-muted">{s.label}</dt>
                <dd className="order-first text-2xl font-bold tabular-nums tracking-tight"><CountUp value={s.value} prefix={s.prefix} /></dd>
              </div>
            ))}
          </dl>
        </div>
        <div className="relative mt-10"><MarketStrip /></div>
      </section>} />

      <section data-tour="chart" className="card mt-6 space-y-4 p-4 sm:p-6">
        <SignedOut><PriceTicker /></SignedOut>
        <PriceChart height={380} />
      </section>

      <Reveal as="section" className="mt-20">
        <p className="text-xs font-medium uppercase tracking-wider text-gold">How it works</p>
        <h2 className="mt-2 text-2xl font-bold sm:text-3xl">One loop, played again and again</h2>
        <p className="mt-2 max-w-xl text-muted">
          Every idea goes round the same five stops. Each lap earns XP for good habits, never for profit, and the
          next lap starts a little sharper.
        </p>
        <ol className="-mx-4 mt-8 flex snap-x snap-mandatory scroll-px-4 gap-3 overflow-x-auto px-4 pb-2 [scrollbar-width:none] sm:mx-0 sm:grid sm:grid-cols-2 sm:gap-4 sm:overflow-visible sm:px-0 sm:pb-0 lg:grid-cols-5">
          {LOOP.map((p, i) => (
            <li key={p.key} className="card lift group relative flex w-[78%] shrink-0 snap-start flex-col p-5 hover:border-gold/40 sm:w-auto">
              <div className="flex items-center justify-between">
                <span className="flex h-10 w-10 items-center justify-center rounded-xl border border-gold/25 bg-gradient-to-br from-gold/20 to-gold/5 text-gold">
                  <Icon name={STAGE_ICON[p.key]} className="h-5 w-5" />
                </span>
                <span className="font-mono text-2xl font-bold text-border transition-colors group-hover:text-gold/40">0{i + 1}</span>
              </div>
              <h3 className="mt-4 font-semibold">{p.name}</h3>
              <p className="mt-1.5 flex-1 text-sm leading-relaxed text-muted">{p.body}</p>
              <div className="mt-4 flex flex-wrap gap-1.5">
                {p.links.map((l) => (
                  <Link key={l.href} href={l.href}
                    className="rounded-full border border-border px-2.5 py-1 text-xs transition-colors hover:border-gold/60 hover:text-gold">
                    {l.label}
                  </Link>
                ))}
              </div>
            </li>
          ))}
        </ol>
      </Reveal>

      <Reveal className="mt-14"><DailyCandle /></Reveal>

      <Reveal as="section" className="card mt-20 grid gap-8 rounded-3xl p-6 sm:p-10 md:grid-cols-[1fr_2fr]">
        <div>
          <h2 className="text-2xl font-bold">Habits of a composed trader</h2>
          <p className="mt-2 text-sm leading-relaxed text-muted">
            The tools here are built around these, so the next decision feels considered rather than rushed.
          </p>
          <Link href="/assistant" className="mt-5 inline-flex items-center gap-1.5 text-sm text-gold hover:underline">
            <Icon name="assistant" className="h-4 w-4" /> Ask the assistant anything
          </Link>
        </div>
        <ul className="grid gap-6 sm:grid-cols-3">
          {habits.map((h) => (
            <li key={h.title} className="flex gap-4 sm:block">
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-border bg-background text-gold"><Icon name={h.icon} className="h-4 w-4" /></span>
              <div>
                <p className="font-semibold sm:mt-3">{h.title}</p>
                <p className="mt-1 text-sm leading-relaxed text-muted">{h.body}</p>
              </div>
            </li>
          ))}
        </ul>
      </Reveal>

      <SignedOut>
      <Reveal as="section" className="mt-20 mb-6 flex flex-col items-start justify-between gap-4 rounded-3xl border border-gold/30 bg-gradient-to-r from-gold/15 via-gold/5 to-transparent p-6 sm:flex-row sm:items-center sm:p-8">
        <div>
          <h2 className="text-lg font-medium">Keep your work in one place</h2>
          <p className="mt-1 text-sm text-muted">A free account saves your risk profile, backtests, paper account and trades.</p>
        </div>
        <Link href="/signup" className="rounded-full bg-gradient-to-b from-gold-hi to-gold px-5 py-2.5 font-semibold text-black shadow-[inset_0_1px_0_rgb(255_255_255/0.35)] transition-[filter] hover:brightness-105">
          Create a free account
        </Link>
      </Reveal>
      </SignedOut>
    </div>
  );
}
