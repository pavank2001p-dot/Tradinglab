"use client";

import PriceChart from "@/components/PriceChart";
import PriceTicker from "@/components/PriceTicker";
import MarketPicker from "@/components/markets/MarketPicker";
import { SignedOut } from "@/components/HomeTop";
import { ticker, useMarket } from "@/lib/markets";

/** One of each lab, so the home chart shows at a glance that it isn't only gold. */
const QUICK = ["EURUSD", "USA500IDXUSD", "INDIDXUSD", "AAPLUSUSD", "XAUUSD", "LIGHTCMDUSD", "BTCUSD"];

/** The home page chart. It follows the market the visitor picks, shared with the chart and paper pages. */
export default function HomeChart() {
  const [market, setSymbol, markets] = useMarket();
  const quick = QUICK.map((s) => markets.find((m) => m.symbol === s)).filter((m) => m != null);
  return (
    <section data-tour="chart" className="card mt-6 space-y-4 p-4 sm:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-xs font-medium uppercase tracking-wider text-gold">Live markets</p>
          <h2 className="mt-1 text-lg font-semibold">Pick a market to explore</h2>
        </div>
        <MarketPicker market={market} markets={markets} onChange={setSymbol} />
      </div>
      {quick.length > 1 && (
        <div className="-mx-4 flex gap-2 overflow-x-auto px-4 [scrollbar-width:none] sm:mx-0 sm:flex-wrap sm:px-0">
          {quick.map((m) => (
            <button key={m.symbol} type="button" onClick={() => setSymbol(m.symbol)} aria-pressed={m.symbol === market.symbol}
              className={`shrink-0 rounded-full border px-3 py-1 text-xs transition-colors ${m.symbol === market.symbol
                ? "border-gold bg-gold/15 text-gold" : "border-border text-muted hover:border-gold/50 hover:text-foreground"}`}>
              {m.asset_class === "forex" ? ticker(m) : m.name}
            </button>
          ))}
        </div>
      )}
      <SignedOut><PriceTicker market={market} /></SignedOut>
      <PriceChart height={380} market={market} />
    </section>
  );
}
