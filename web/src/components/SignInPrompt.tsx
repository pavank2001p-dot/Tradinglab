import Link from "next/link";
import { Icon } from "./ui";

export default function SignInPrompt({ what, next }: { what: string; next: string }) {
  return (
    <div className="relative mx-auto max-w-md px-4 py-20 text-center">
      <div aria-hidden className="glow-drift pointer-events-none absolute left-1/2 top-6 h-56 w-80 max-w-full -translate-x-1/2 rounded-full bg-gold/15 blur-3xl" />
      <div className="lux relative px-6 py-10">
      <span className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl border border-gold/30 bg-gradient-to-br from-gold/25 to-gold/5 text-gold">
        <Icon name="account" className="h-7 w-7" />
      </span>
      <h1 className="mt-5 text-2xl font-semibold tracking-tight">Free to use, <span className="font-display text-aurora text-[1.14em]">nothing at stake</span></h1>
      <p className="mt-2 text-muted">Create a free account or log in to {what}.</p>
      <div className="mt-6 flex flex-wrap justify-center gap-3">
        <Link href={`/signup?next=${next}`} className="btn-gold rounded-full px-6 py-2.5 font-semibold"><span className="relative z-10">Sign up free</span></Link>
        <Link href={`/login?next=${next}`} className="btn-ghost rounded-full px-6 py-2.5 font-medium">Log in</Link>
      </div>
      </div>
    </div>
  );
}
