import Link from "next/link";
import Spotlight from "@/components/home/Spotlight";
import { Icon } from "@/components/ui";

// The panel shared by the sign-in, sign-up, password and email pages, in the same finish as the home page.
export const authInput =
  "w-full rounded-xl border border-border bg-background/70 px-3.5 py-2.5 outline-none transition focus:border-gold focus:shadow-[0_0_0_3px_color-mix(in_srgb,var(--gold)_18%,transparent)]";
export const authButton = "btn-gold w-full rounded-full py-3 font-semibold disabled:opacity-60";

const POINTS = [
  { icon: "risk", title: "Know your limits first", body: "A short risk profile sets how much you're comfortable losing, and every tool checks against it." },
  { icon: "backtest", title: "Test before you trust", body: "Run an idea on years of real prices, with real costs, before a single practice trade." },
  { icon: "wallet", title: "Practise with nothing at stake", body: "Commodities, forex, indices, stocks in every sector, ETFs and crypto, all with virtual money." },
];

/** The last word or two of a title are set in the display serif, as on the home page. */
function Title({ text }: { text: string }) {
  const words = text.split(" ");
  const tail = words.length > 3 ? 2 : 1;
  const head = words.slice(0, -tail).join(" ");
  return (
    <h1 className="mt-5 text-[1.9rem] font-semibold leading-[1.1] tracking-[-0.03em]">
      {head}{head && " "}<span className="font-display text-aurora pr-0.5 text-[1.14em]">{words.slice(-tail).join(" ")}</span>
    </h1>
  );
}

export default function AuthShell({ title, intro, children }: { title: string; intro?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="relative mx-auto max-w-5xl px-4 py-12 sm:py-20">
      <Spotlight />
      <div aria-hidden className="pointer-events-none absolute inset-x-0 -top-10 bottom-0">
        <div className="glow-drift absolute left-1/2 top-0 h-72 w-[40rem] max-w-full -translate-x-1/2 rounded-full bg-gold/15 blur-3xl" />
        <div className="absolute right-0 top-32 h-64 w-64 rounded-full bg-[color-mix(in_srgb,var(--violet)_18%,transparent)] blur-3xl" />
        <div className="absolute bottom-0 left-0 h-56 w-64 rounded-full bg-[color-mix(in_srgb,var(--calm)_12%,transparent)] blur-3xl" />
      </div>
      <div aria-hidden className="grain pointer-events-none absolute -inset-x-[50vw] -top-10 bottom-0" />

      <div className="relative grid items-center gap-12 lg:grid-cols-[minmax(0,1fr)_minmax(0,26rem)] lg:gap-16">
        <aside className="hidden lg:block">
          <p className="eyebrow">Trading Lab</p>
          <p className="mt-5 text-[2.6rem] font-semibold leading-[1.06] tracking-[-0.035em]">
            Master <span className="font-display text-aurora pr-1 text-[1.14em]">the markets</span>
            <br />
            before you risk a&nbsp;cent.
          </p>
          <ul className="mt-10 space-y-6">
            {POINTS.map((p) => (
              <li key={p.title} className="flex gap-4">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-gold/30 bg-gradient-to-br from-gold/25 to-gold/5 text-gold">
                  <Icon name={p.icon} className="h-5 w-5" />
                </span>
                <div>
                  <p className="font-semibold">{p.title}</p>
                  <p className="mt-0.5 max-w-sm text-sm leading-relaxed text-muted">{p.body}</p>
                </div>
              </li>
            ))}
          </ul>
        </aside>

        <div className="rise-in lux mx-auto w-full max-w-md p-7 sm:p-9">
          <Link href="/" aria-label="Trading Lab home" className="flex h-11 w-11 items-center justify-center rounded-2xl bg-gradient-to-br from-gold-hi to-gold-deep shadow-[0_10px_24px_-10px_var(--gold),inset_0_1px_0_rgb(255_255_255/0.4)]">
            <span className="h-3 w-3 rotate-45 rounded-[3px] bg-black/80" />
          </Link>
          <Title text={title} />
          {intro && <p className="mt-2 text-sm text-muted">{intro}</p>}
          {children}
        </div>
      </div>
    </div>
  );
}
