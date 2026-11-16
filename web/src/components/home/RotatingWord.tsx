"use client";

import { useEffect, useState } from "react";

/** Cycles through a few words in place, so one headline can name every market without getting longer.
 *  Screen readers get the plain `label`; reduced-motion visitors see the first word and nothing moves. */
export default function RotatingWord({ words, label, every = 2400, wordClass = "" }: { words: string[]; label: string; every?: number; wordClass?: string }) {
  const [i, setI] = useState(0);
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const t = setInterval(() => setI((n) => (n + 1) % words.length), every);
    return () => clearInterval(t);
  }, [words.length, every]);
  return (
    <span className="relative inline-grid align-bottom">
      <span className="sr-only">{label}</span>
      {/* The longest word holds the width, so the line doesn't jump as words change. */}
      <span aria-hidden className="invisible col-start-1 row-start-1 select-none">{words.reduce((a, b) => (b.length > a.length ? b : a))}</span>
      <span aria-hidden key={i} className={`word-in col-start-1 row-start-1 ${wordClass}`}>{words[i]}</span>
    </span>
  );
}
