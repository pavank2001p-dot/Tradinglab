"use client";

import { useEffect, useRef, useState } from "react";

/** Counts a figure up from zero once it's on screen. The final value is rendered first, so it reads
 *  correctly without JavaScript, in a screenshot, or with reduced motion. */
export default function CountUp({ value, prefix = "", ms = 1200 }: { value: number; prefix?: string; ms?: number }) {
  const ref = useRef<HTMLSpanElement>(null);
  const [n, setN] = useState(value);
  useEffect(() => {
    const el = ref.current;
    if (!el || value === 0 || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    let raf = 0;
    const io = new IntersectionObserver(([e]) => {
      if (!e.isIntersecting) return;
      io.disconnect();
      const t0 = performance.now();
      const step = (t: number) => {
        const p = Math.min(1, (t - t0) / ms);
        setN(Math.round(value * (1 - Math.pow(1 - p, 3))));
        if (p < 1) raf = requestAnimationFrame(step);
      };
      setN(0);
      raf = requestAnimationFrame(step);
    });
    io.observe(el);
    return () => { io.disconnect(); cancelAnimationFrame(raf); };
  }, [value, ms]);
  return <span ref={ref}>{prefix}{n.toLocaleString("en-US")}</span>;
}
