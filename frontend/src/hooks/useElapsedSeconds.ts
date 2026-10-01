import { useEffect, useRef, useState } from "react";

/**
 * Tracks whole seconds elapsed while `active` is true, resetting to 0 the
 * moment it goes false (or flips true again after being false). Used to
 * give the user a live "this is still working" signal for long-running,
 * no-progress-event operations (e.g. reading hundreds of files live from
 * GitHub one at a time) that would otherwise look identical to a frozen
 * page for minutes at a time.
 */
export function useElapsedSeconds(active: boolean): number {
  const [seconds, setSeconds] = useState(0);
  const startRef = useRef<number | null>(null);

  useEffect(() => {
    if (!active) {
      startRef.current = null;
      setSeconds(0);
      return;
    }
    startRef.current = Date.now();
    setSeconds(0);
    const interval = setInterval(() => {
      if (startRef.current !== null) {
        setSeconds(Math.floor((Date.now() - startRef.current) / 1000));
      }
    }, 1000);
    return () => clearInterval(interval);
  }, [active]);

  return seconds;
}
