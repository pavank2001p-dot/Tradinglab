import Link from "next/link";
import DailyCandle from "@/components/DailyCandle";
import HomeTop, { SignedOut } from "@/components/HomeTop";
import Reveal from "@/components/Reveal";
import CountUp from "@/components/home/CountUp";
import HeroBoard from "@/components/home/HeroBoard";
import HomeChart from "@/components/home/HomeChart";
import MarketStrip from "@/components/home/MarketStrip";
import MarketBrowser from "@/components/markets/MarketBrowser";
import Showcase from "@/components/home/Showcase";
import Spotlight from "@/components/home/Spotlight";
import { Icon } from "@/components/ui";
import { LOOP, STAGE_ICON } from "@/lib/loop";

type Tone = React.CSSProperties & { "--tone": string };
const tone = (c: string): Tone => ({ "--tone": c });

const habits = [
  { tone: "var(--rose)", icon: "drop", title: "Decide the loss first", body: "Set where you would be wrong before you enter, and see it in dollars." },
  { tone: "var(--calm)", icon: "scale", title: "Size from the stop", body: "Let the distance to your stop set the size, so one trade can't hurt much." },
  { tone: "var(--up)", icon: "clock", title: "There's always another trade", body: "Missing a move costs nothing. Taking a rushed one can." },
];

const STATS: { value: number; prefix?: string; label: string; tone: string }[] = [
  { value: 5, label: "Market labs", tone: "var(--gold)" },
  { value: 23, label: "Strategies, plus your own", tone: "var(--violet)" },
  { value: 2000, label: "Paths per scenario", tone: "var(--calm)" },
  { value: 0, prefix: "$", label: "Real money at risk", tone: "var(--up)" },
];

/** Where the numbers come from. Each line is something the site really does. */
const SOURCES = [
  { icon: "candles", text: "Price history from Dukascopy" },
  { icon: "bolt", text: "Live quotes from OANDA" },
  { icon: "backtest", text: "Charts by TradingView Lightweight Charts" },
  { icon: "seal", text: "Records sealed with SHA-256" },
];

/** Each stop of the loop has its own colour, so the five read as a sequence. */
const STEP_TONES = ["var(--gold)", "var(--violet)", "var(--calm)", "var(--up)", "var(--rose)"];

const GRID = "bg-[linear-gradient(to_right,color-mix(in_srgb,var(--foreground)_3%,transparent)_1px,transparent_1px),linear-gradient(to_bottom,color-mix(in_srgb,var(--foreground)_3%,transparent)_1px,transparent_1px)] bg-[size:56px_56px]";

export default function Home() {
  return (
    <div className="mx-auto max-w-6xl px-4">
      <Spotlight />
      <HomeTop hero={<section className="relative pb-12 pt-16 sm:pb-16 sm:pt-28">
        <div aria-hidden className="pointer-events-none absolute inset-x-0 -top-24 bottom-0">
          <div className="glow-drift absolute -top-10 left-1/2 h-96 w-[52rem] max-w-full -translate-x-1/2 rounded-full bg-gold/15 blur-3xl" />
          <div className="absolute right-0 top-24 h-80 w-80 rounded-full bg-[color-mix(in_srgb,var(--violet)_20%,transparent)] blur-3xl" />
          <div className="absolute -left-10 top-72 h-64 w-64 rounded-full bg-[color-mix(in_srgb,var(--up)_10%,transparent)] blur-3xl" />
          <div className="absolute bottom-10 right-1/4 h-56 w-80 rounded-full bg-[color-mix(in_srgb,var(--calm)_12%,transparent)] blur-3xl" />
        </div>
        <div aria-hidden className={`pointer-events-none absolute inset-0 ${GRID} [mask-image:radial-gradient(ellipse_at_top,black,transparent_70%)]`} />
        <div aria-hidden className="grain pointer-events-none absolute -inset-x-[50vw] -top-24 bottom-0" />

        <div className="relative grid items-center gap-12 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,0.8fr)]">
          <div>
            <span className="rise-in inline-flex items-center gap-2.5 rounded-full border border-gold/30 bg-gold/10 py-1 pl-1.5 pr-3.5 text-xs font-medium text-gold backdrop-blur">
              <span className="rounded-full bg-gold px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-black">Free</span>
              A practice lab for every market
            </span>
            <h1 className="rise-in mt-7 text-[2.5rem] font-semibold leading-[1.04] tracking-[-0.035em] [animation-delay:80ms] sm:text-7xl lg:text-[3.5rem]">
              Master <span className="font-display text-aurora pr-1 text-[1.14em] leading-none">the markets</span>
              <br />
              before you risk a&nbsp;cent.
            </h1>
            <p className="rise-in mt-7 max-w-xl text-lg leading-relaxed text-muted [animation-delay:160ms]">
              Commodities, forex, indices, stocks in every sector, ETFs and crypto in one place. Learn an idea, test it on real price
              history, then trade it with virtual money, with the risk shown before every move.
            </p>
            <div className="rise-in mt-10 flex flex-wrap items-center gap-3 [animation-delay:240ms]">
              <Link href="/risk" className="btn-gold group flex w-full items-center justify-center gap-2 rounded-full px-7 py-3.5 font-semibold sm:w-auto">
                <span className="relative z-10">Start with your risk profile</span>
                <Icon name="arrow" className="relative z-10 h-4 w-4 transition-transform duration-300 group-hover:translate-x-0.5" />
              </Link>
              <Link href="/chart" className="btn-ghost w-full rounded-full px-7 py-3.5 text-center font-medium sm:w-auto">
                See all markets
              </Link>
            </div>
            <p className="rise-in mt-5 flex flex-wrap items-center gap-x-5 gap-y-1.5 text-xs text-muted [animation-delay:300ms]">
              {["No card, no deposit", "Virtual money only", "Free to use"].map((s) => (
                <span key={s} className="inline-flex items-center gap-1.5"><Icon name="check" className="h-3.5 w-3.5 text-up" />{s}</span>
              ))}
            </p>
          </div>
          <div className="hidden lg:block"><HeroBoard /></div>
        </div>

        <dl className="rise-in lux relative mt-16 grid grid-cols-2 divide-border [animation-delay:360ms] max-sm:[&>*:nth-child(-n+2)]:border-b max-sm:[&>*:nth-child(odd)]:border-r sm:grid-cols-4 sm:divide-x">
          {STATS.map((s) => (
            <div key={s.label} className="flex flex-col border-border px-5 py-6 sm:px-7 sm:py-7" style={tone(s.tone)}>
              <dt className="mt-1.5 text-[11px] uppercase leading-snug tracking-[0.14em] text-muted">{s.label}</dt>
              <dd className="order-first text-4xl font-semibold tabular-nums tracking-tight sm:text-5xl">
                <span className="bg-gradient-to-b from-foreground to-[var(--tone)] bg-clip-text text-transparent"><CountUp value={s.value} prefix={s.prefix} /></span>
              </dd>
            </div>
          ))}
        </dl>

        <div className="relative mt-10"><MarketStrip /></div>
        <ul className="relative mt-8 flex flex-wrap items-center justify-center gap-x-8 gap-y-3 text-xs text-muted">
          {SOURCES.map((s) => (
            <li key={s.text} className="inline-flex items-center gap-2"><Icon name={s.icon} className="h-3.5 w-3.5 text-gold" />{s.text}</li>
          ))}
        </ul>
      </section>} />

      <HomeChart />

      <section className="mt-10">
        <MarketBrowser title="Every market, every sector"
          subtitle="Commodities, currencies, world indices, stocks across every sector, ETFs and crypto. Pick one and the chart, paper account, backtests and news all follow it." />
      </section>

      <Reveal as="section" className="mt-28 sm:mt-36">
        <div className="mx-auto max-w-2xl text-center">
          <p className="eyebrow">The full desk</p>
          <h2 className="h-section mt-4">Everything a trading desk has, <span className="font-display text-aurora">with nothing at stake</span></h2>
          <p className="mt-4 text-muted">
            Six tools that work together. What you set in one is used by the others, so practice adds up.
          </p>
        </div>
        <div className="mt-12"><Showcase /></div>
      </Reveal>

      <Reveal as="section" className="mt-28 sm:mt-36">
        <div className="mx-auto max-w-2xl text-center">
          <p className="eyebrow">How it works</p>
          <h2 className="h-section mt-4">One loop, <span className="font-display text-aurora">played again and again</span></h2>
          <p className="mt-4 text-muted">
            Every idea goes round the same five stops. Each lap earns XP for good habits, never for profit, and the
            next lap starts a little sharper.
          </p>
        </div>
        <ol className="relative -mx-4 mt-12 flex snap-x snap-mandatory scroll-px-4 gap-3 overflow-x-auto px-4 pb-2 [scrollbar-width:none] lg:mx-0 lg:grid lg:grid-cols-5 lg:gap-0 lg:overflow-visible lg:px-0 lg:pb-0">
          <span aria-hidden className="absolute left-[10%] right-[10%] top-7 hidden h-px bg-[linear-gradient(90deg,var(--gold),var(--violet),var(--calm),var(--up),var(--rose))] opacity-50 lg:block" />
          {LOOP.map((p, i) => (
            <li key={p.key} style={tone(STEP_TONES[i])}
              className="group relative flex w-[72%] shrink-0 snap-start flex-col rounded-2xl border border-border bg-surface/60 p-5 sm:w-[42%] lg:w-auto lg:items-center lg:border-0 lg:bg-transparent lg:px-4 lg:py-0 lg:text-center">
              <span className="tone-tile relative flex h-14 w-14 items-center justify-center rounded-2xl bg-background shadow-[0_0_0_6px_var(--background)] transition-transform duration-300 group-hover:-translate-y-1">
                <span aria-hidden className="absolute inset-0 rounded-2xl bg-background" />
                <span aria-hidden className="tone-tile absolute inset-0 rounded-2xl border-0" />
                <Icon name={STAGE_ICON[p.key]} className="relative h-6 w-6" />
              </span>
              <p className="tone-text mt-5 font-mono text-[11px] font-semibold tracking-[0.2em]">STEP 0{i + 1}</p>
              <h3 className="mt-1 text-lg font-semibold tracking-tight">{p.name}</h3>
              <p className="mt-1.5 flex-1 text-sm leading-relaxed text-muted">{p.body}</p>
              <div className="mt-4 flex flex-wrap gap-1.5 lg:justify-center">
                {p.links.map((l) => (
                  <Link key={l.href} href={l.href}
                    className="rounded-full border border-border px-2.5 py-1 text-xs transition-colors hover:border-[var(--tone)] hover:text-[var(--tone)]">
                    {l.label}
                  </Link>
                ))}
              </div>
            </li>
          ))}
        </ol>
      </Reveal>

      <Reveal className="mt-24 sm:mt-32"><DailyCandle /></Reveal>

      <Reveal as="section" className="lux mt-28 grid gap-10 p-7 sm:mt-36 sm:p-12 md:grid-cols-[1fr_2fr]">
        <div>
          <p className="eyebrow">The mindset</p>
          <h2 className="mt-4 text-3xl font-semibold leading-tight tracking-tight">Habits of a <span className="font-display text-aurora text-[1.12em]">composed trader</span></h2>
          <p className="mt-3 text-sm leading-relaxed text-muted">
            The tools here are built around these, so the next decision feels considered rather than rushed.
          </p>
          <Link href="/assistant" className="mt-6 inline-flex items-center gap-1.5 text-sm font-medium text-gold hover:underline">
            <Icon name="assistant" className="h-4 w-4" /> Ask the assistant anything
          </Link>
        </div>
        <ul className="grid gap-7 sm:grid-cols-3">
          {habits.map((h, i) => (
            <li key={h.title} className="flex gap-4 sm:block" style={tone(h.tone)}>
              <span className="tone-tile flex h-11 w-11 shrink-0 items-center justify-center rounded-xl"><Icon name={h.icon} className="h-5 w-5" /></span>
              <div>
                <p className="tone-text font-mono text-[11px] font-semibold tracking-[0.2em] max-sm:hidden sm:mt-5">0{i + 1}</p>
                <p className="font-semibold sm:mt-1">{h.title}</p>
                <p className="mt-1 text-sm leading-relaxed text-muted">{h.body}</p>
              </div>
            </li>
          ))}
        </ul>
      </Reveal>

      <SignedOut>
      <Reveal as="section" className="lux lux-static relative mt-28 mb-10 overflow-hidden px-6 py-16 text-center sm:mt-36 sm:px-12 sm:py-24">
        <div aria-hidden className="pointer-events-none absolute inset-0 bg-[radial-gradient(60%_80%_at_50%_0%,color-mix(in_srgb,var(--gold)_24%,transparent),transparent_70%),radial-gradient(40%_60%_at_85%_100%,color-mix(in_srgb,var(--violet)_22%,transparent),transparent_70%),radial-gradient(40%_60%_at_10%_100%,color-mix(in_srgb,var(--calm)_16%,transparent),transparent_70%)]" />
        <div aria-hidden className={`pointer-events-none absolute inset-0 ${GRID} [mask-image:radial-gradient(ellipse_at_center,black,transparent_75%)]`} />
        <div className="relative mx-auto max-w-2xl">
          <p className="eyebrow">Begin</p>
          <h2 className="mt-5 text-[2.1rem] font-semibold leading-[1.06] tracking-[-0.03em] sm:text-6xl">
            Your first hundred trades should <span className="font-display text-aurora text-[1.12em]">cost you nothing.</span>
          </h2>
          <p className="mx-auto mt-5 max-w-lg text-muted">
            A free account keeps your risk profile, backtests, paper account and track record in one place.
          </p>
          <div className="mt-9 flex flex-wrap justify-center gap-3">
            <Link href="/signup" className="btn-gold group flex w-full items-center justify-center gap-2 rounded-full px-8 py-3.5 font-semibold sm:w-auto">
              <span className="relative z-10">Create a free account</span>
              <Icon name="arrow" className="relative z-10 h-4 w-4 transition-transform duration-300 group-hover:translate-x-0.5" />
            </Link>
            <Link href="/learn" className="btn-ghost w-full rounded-full px-8 py-3.5 text-center font-medium sm:w-auto">Start with a lesson</Link>
          </div>
        </div>
      </Reveal>
      </SignedOut>
    </div>
  );
}
