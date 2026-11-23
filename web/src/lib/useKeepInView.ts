"use client";

import { useLayoutEffect, useRef } from "react";

const GAP = 8;

/**
 * Keeps a dropdown or popover inside the window. Attach the returned ref to the popover; while `open`,
 * it is nudged sideways (by its left offset, so transforms and animations are untouched) when it would
 * run off either edge, and re-checked when the window resizes.
 */
export function useKeepInView<T extends HTMLElement>(open: boolean) {
  const ref = useRef<T>(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!open || !el) return;
    const fit = () => {
      el.style.left = el.style.right = "";
      const r = el.getBoundingClientRect();
      const vw = document.documentElement.clientWidth;
      let dx = 0;
      if (r.right > vw - GAP) dx = vw - GAP - r.right;
      if (r.left + dx < GAP) dx = GAP - r.left;
      if (!dx) return;
      // The computed left is the used offset in pixels, whichever edge the box is pinned by.
      const left = parseFloat(getComputedStyle(el).left) || 0;
      el.style.right = "auto";
      el.style.left = `${Math.round(left + dx)}px`;
    };
    fit();
    window.addEventListener("resize", fit);
    return () => window.removeEventListener("resize", fit);
  }, [open]);
  return ref;
}
