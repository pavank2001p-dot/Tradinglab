import Link from "next/link";
import DailyCandle from "@/components/DailyCandle";
import HomeTop, { SignedOut } from "@/components/HomeTop";
import Reveal from "@/components/Reveal";
import CountUp from "@/components/home/CountUp";
import HeroBoard from "@/components/home/HeroBoard";
import HomeChart from "@/components/home/HomeChart";
import MarketStrip from "@/components/home/MarketStrip";
import { Icon } from "@/components/ui";
import { LOOP, STAGE_ICON } from "@/lib/loop";

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

/** Each stop of the loop has its own colour, so the five cards read as a sequence rather than a wall. */
const STEP_TONES = ["var(--gold)", "var(--violet)", "var(--calm)", "var(--up)", "var(--rose)"];

export default function Home() {
  return (
    <div className="mx-auto max-w-6xl px-4">
      <HomeTop hero={<section className="relative pb-10 pt-16 sm:pb-14 sm:pt-24">
        <div aria-hidden className="pointer-events-none absolute inset-x-0 -top-24 bottom-0">
          <div className="glow-drift absolute -top-10 left-1/2 h-80 w-[48rem] max-w-full -translate-x-1/2 rounded-full bg-gold/15 blur-3xl" />
          <div className="absolute right-0 top-24 h-72 w-72 rounded-full bg-[color-mix(in_srgb,var(--violet)_22%,transparent)] blur-3xl" />
          <div className="absolute -left-10 top-72 h-64 w-64 rounded-full bg-[color-mix(in_srgb,var(--up)_12%,transparent)] blur-3xl" />
          <div className="absolute bottom-10 right-1/4 h-56 w-80 rounded-full bg-[color-mix(in_srgb,var(--calm)_14%,transparent)] blur-3xl" />
        </div>
        <div aria-hidden className="pointer-events-none absolute inset-0 bg-[linear-gradient(to_right,color-mix(in_srgb,var(--foreground)_3%,transparent)_1px,transparent_1px),linear-gradient(to_bottom,color-mix(in_srgb,var(--foreground)_3%,transparent)_1px,transparent_1px)] bg-[size:56px_56px] [mask-image:radial-gradient(ellipse_at_top,black,transparent_70%)]" />
        <div className="relative grid items-center gap-10 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,0.85fr)]">
        <div>
          <span className="rise-in inline-flex items-center gap-2 rounded-full border border-gold/30 bg-gold/10 px-3 py-1 text-xs font-medium text-gold">
            <span className="breathe h-1.5 w-1.5 rounded-full bg-gold" /> Free practice lab for every market
          </span>
          <h1 className="rise-in mt-5 max-w-3xl text-[2.15rem] font-bold leading-[1.15] tracking-tight [animation-delay:80ms] sm:text-6xl lg:text-[3.35rem]">
            Master{" "}
            <span className="text-aurora">the markets</span>
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
              See all markets
            </Link>
          </div>
        </div>
        <div className="hidden lg:block"><HeroBoard /></div>
        </div>
        <dl className="rise-in relative mt-12 grid grid-cols-2 gap-3 [animation-delay:320ms] sm:grid-cols-4 sm:gap-4">
          {STATS.map((s) => (
            <div key={s.label} className="card tone-card flex flex-col px-4 py-4 sm:px-5" style={{ "--tone": s.tone } as React.CSSProperties}>
              <dt className="relative mt-1 text-[11px] uppercase leading-snug tracking-wider text-muted">{s.label}</dt>
              <dd className="tone-text relative order-first text-3xl font-bold tabular-nums tracking-tight"><CountUp value={s.value} prefix={s.prefix} /></dd>
            </div>
          ))}
        </dl>
        <div className="relative mt-8"><MarketStrip /></div>
      </section>} />

      <HomeChart />

      <Reveal as="section" className="mt-20">
        <p className="text-xs font-semibold uppercase tracking-wider text-[var(--violet)]">How it works</p>
        <h2 className="mt-2 text-2xl font-bold sm:text-3xl">One loop, played again and again</h2>
        <p className="mt-2 max-w-xl text-muted">
          Every idea goes round the same five stops. Each lap earns XP for good habits, never for profit, and the
          next lap starts a little sharper.
        </p>
        <ol className="-mx-4 mt-8 flex snap-x snap-mandatory scroll-px-4 gap-3 overflow-x-auto px-4 pb-2 [scrollbar-width:none] sm:mx-0 sm:grid sm:grid-cols-2 sm:gap-4 sm:overflow-visible sm:px-0 sm:pb-0 lg:grid-cols-5">
          {LOOP.map((p, i) => (
            <li key={p.key} style={{ "--tone": STEP_TONES[i] } as React.CSSProperties}
              className="card tone-card lift group relative flex w-[78%] shrink-0 snap-start flex-col p-5 sm:w-auto">
              <div className="flex items-center justify-between">
                <span className="tone-tile relative flex h-10 w-10 items-center justify-center rounded-xl">
                  <Icon name={STAGE_ICON[p.key]} className="h-5 w-5" />
                </span>
                <span className="tone-text font-mono text-2xl font-bold opacity-30 transition-opacity group-hover:opacity-70">0{i + 1}</span>
              </div>
              <h3 className="mt-4 font-semibold">{p.name}</h3>
              <p className="mt-1.5 flex-1 text-sm leading-relaxed text-muted">{p.body}</p>
              <div className="mt-4 flex flex-wrap gap-1.5">
                {p.links.map((l) => (
                  <Link key={l.href} href={l.href}
                    className="relative rounded-full border border-border px-2.5 py-1 text-xs transition-colors hover:border-[var(--tone)] hover:text-[var(--tone)]">
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
          <p className="text-xs font-semibold uppercase tracking-wider text-up">The mindset</p>
          <h2 className="mt-2 text-2xl font-bold">Habits of a composed trader</h2>
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
              <span className="tone-tile flex h-10 w-10 shrink-0 items-center justify-center rounded-xl" style={{ "--tone": h.tone } as React.CSSProperties}><Icon name={h.icon} className="h-5 w-5" /></span>
              <div>
                <p className="font-semibold sm:mt-3">{h.title}</p>
                <p className="mt-1 text-sm leading-relaxed text-muted">{h.body}</p>
              </div>
            </li>
          ))}
        </ul>
      </Reveal>

      <SignedOut>
      <Reveal as="section" className="relative mt-20 mb-6 flex flex-col items-start justify-between gap-5 overflow-hidden rounded-3xl border border-gold/40 bg-[linear-gradient(110deg,color-mix(in_srgb,var(--gold)_26%,var(--surface)),color-mix(in_srgb,var(--violet)_20%,var(--surface))_55%,color-mix(in_srgb,var(--calm)_18%,var(--surface)))] p-7 sm:flex-row sm:items-center sm:p-10">
        <div aria-hidden className="shimmer pointer-events-none absolute inset-0 opacity-60" />
        <div className="relative">
          <h2 className="text-2xl font-bold">Keep your work in one place</h2>
          <p className="mt-1.5 text-sm text-foreground/75">A free account saves your risk profile, backtests, paper account and trades.</p>
        </div>
        <Link href="/signup" className="relative w-full rounded-full bg-gradient-to-b from-gold-hi to-gold px-6 py-3 text-center font-semibold sm:w-auto text-black shadow-[inset_0_1px_0_rgb(255_255_255/0.35)] transition-[filter] hover:brightness-105">
          Create a free account
        </Link>
      </Reveal>
      </SignedOut>
    </div>
  );
}
