"use client";

import Link from "next/link";
import { TourLink } from "./Tour";
import { useT } from "@/lib/i18n";
import { LANDINGS } from "./landing/Landing";
import { GROUPS } from "./Header";
import { APP_NAME } from "@/lib/markets";

export default function Footer() {
  const { t } = useT();
  return (
    <footer className="relative mt-24">
      <div aria-hidden className="h-px bg-[linear-gradient(90deg,transparent,color-mix(in_srgb,var(--gold)_60%,transparent),color-mix(in_srgb,var(--violet)_45%,transparent),transparent)]" />
      <div className="mx-auto max-w-6xl px-4 pb-8 pt-12">
        <div className="grid gap-10 md:grid-cols-[1.3fr_repeat(4,1fr)]">
          <div>
            <Link href="/" className="flex items-center gap-2 font-semibold tracking-tight">
              <span className="inline-block h-3 w-3 rotate-45 rounded-[3px] bg-gradient-to-br from-gold-hi to-gold-deep" />
              {APP_NAME}
            </Link>
            <p className="mt-4 text-xl font-semibold leading-tight tracking-[-0.03em]">
              Master <span className="font-display text-aurora text-[1.14em]">the markets</span>
              <br />before you risk a cent.
            </p>
          </div>
          {GROUPS.map((g) => (
            <nav key={g.label} aria-label={t(g.label)} className="max-md:hidden">
              <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-gold">{t(g.label)}</p>
              <ul className="mt-4 space-y-2.5 text-sm text-muted">
                {g.items.map((i) => (
                  <li key={i.href}><Link href={i.href} className="transition-colors hover:text-foreground">{t(i.label)}</Link></li>
                ))}
              </ul>
            </nav>
          ))}
        </div>
        <div className="mt-12 border-t border-border pt-6 text-xs leading-relaxed text-muted">
          {t("Trading Lab is an educational analysis tool. Nothing on this site is investment advice or a recommendation to buy or sell. Trading leveraged products such as CFDs, forex and crypto carries a high risk of loss. Past performance and backtests do not guarantee future results. AI answers can be wrong.")}{" "}
          <Link href="/disclaimer" className="underline hover:text-foreground">{t("Read the full disclaimer")}</Link>.
          <p className="mt-2">
            Charts by{" "}
            <a href="https://www.tradingview.com/" target="_blank" rel="noopener noreferrer" className="underline hover:text-foreground">
              TradingView
            </a>{" "}
            Lightweight Charts™. New here? <TourLink className="underline hover:text-foreground" />.
          </p>
          <p className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
            {LANDINGS.map((l) => <Link key={l.path} href={l.path} className="hover:text-foreground">{l.label}</Link>)}
          </p>
        </div>
      </div>
    </footer>
  );
}
