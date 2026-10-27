import { useCallback, useEffect, useState } from "react";
export const TICKER_PATTERN = /^[A-Za-z0-9^][A-Za-z0-9.^=&-]{0,31}$/;
export function normalizeTicker(value: string): string | null {
  const trimmed = value.trim();
  return TICKER_PATTERN.test(trimmed) ? trimmed.toUpperCase() : null;
}
export function tickerFromLocation(fallback = "NVDA"): string {
  return (
    normalizeTicker(
      new URL(window.location.href).searchParams.get("ticker") || "",
    ) || fallback
  );
}
export function useTickerLocation() {
  const [ticker, setTicker] = useState(tickerFromLocation);
  useEffect(() => {
    const initial = new URL(window.location.href);
    initial.searchParams.set("ticker", tickerFromLocation());
    window.history.replaceState(null, "", initial);
    const handleBack = () => setTicker(tickerFromLocation());
    window.addEventListener("popstate", handleBack);
    return () => window.removeEventListener("popstate", handleBack);
  }, []);
  const selectTicker = useCallback((value: string) => {
    const normalized = normalizeTicker(value);
    if (!normalized) return;
    const url = new URL(window.location.href);
    if (url.searchParams.get("ticker") !== normalized) {
      url.searchParams.set("ticker", normalized);
      window.history.pushState(null, "", url);
    }
    setTicker(normalized);
  }, []);
  return [ticker, selectTicker] as const;
}
