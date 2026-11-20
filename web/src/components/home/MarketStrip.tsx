"use client";

import Link from "next/link";
import { fmtMarketPrice, ticker, useMarkets } from "@/lib/markets";

const TONES: Record<string, string> = {
  metals: "var(--gold)", energy: "var(--gold)", agriculture: "var(--gold)", indices: "var(--calm)", forex: "var(--up)",
  stocks: "var(--rose)", etfs: "var(--rose)", crypto: "var(--violet)",
};

/** A slow, endless strip of the markets with live prices. Each one opens on the chart; hovering pauses it. */
export default function MarketStrip() {
  const markets = useMarkets().filter((m) => m.price != null);
  if (markets.length < 2) return <div className="h-[46px]" />;
  const row = (hidden: boolean) => (
    <ul aria-hidden={hidden || undefined} className="flex shrink-0 items-center gap-2 pr-2">
      {markets.map((m) => (
        <li key={m.symbol}>
          <Link href={`/chart?symbol=${m.symbol}`} tabIndex={hidden ? -1 : undefined}
            className="flex items-center gap-2 whitespace-nowrap rounded-full border border-border bg-surface/70 px-3.5 py-1.5 text-xs transition-colors hover:border-gold/50">
            <span aria-hidden className="h-1.5 w-1.5 rounded-full" style={{ background: TONES[m.asset_class] ?? "var(--gold)" }} />
            <span className="font-medium text-foreground">{m.name}</span>
            <span className="text-muted">{ticker(m) === m.name ? "" : ticker(m)}</span>
            {m.price != null && <span className="tabular-nums text-foreground/80">{fmtMarketPrice(m.price, m)}</span>}
          </Link>
        </li>
      ))}
    </ul>
  );
  return (
    <div className="marquee fan-in relative overflow-hidden py-1 [mask-image:linear-gradient(to_right,transparent,black_8%,black_92%,transparent)]" dir="ltr">
      <div className="marquee-track flex w-max">
        {row(false)}
        {row(true)}
      </div>
    </div>
  );
}
