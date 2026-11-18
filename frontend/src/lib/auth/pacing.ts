import { useEffect, useState } from "react";

/** How long each step of a loading screen stays on show. The real requests answer in tens of
 * milliseconds on a warm API, which made the screens a flash with nothing to read; this is the pace of
 * the approved prototype (docs/design/prototypes/loading-screen). It is a floor, never a ceiling: a slow
 * request still holds its step for as long as it takes. */
export const STEP_MS = 650;

export const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

/** The stage to display on the way to `target`: it moves one stage at a time, each shown for at least
 * `STEP_MS`, and never goes back. */
export function usePacedStage(target: number): number {
  const [shown, setShown] = useState(0);
  useEffect(() => {
    if (shown >= target) return;
    const timer = setTimeout(() => setShown((s) => s + 1), STEP_MS);
    return () => clearTimeout(timer);
  }, [shown, target]);
  return shown;
}
