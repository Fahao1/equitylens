import {
  useEffect,
  useId,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Clock3, LoaderCircle, RefreshCw, Search } from "lucide-react";
import { api, ApiError } from "./api";
import { dateTime } from "./ui";
import { normalizeTicker } from "./tickerState";
import type { StockSearchResponse, StockSearchResult } from "./types";

const RECENT_KEY = "equitylens.recent-searches";
function readRecent(): StockSearchResult[] {
  try {
    const items = JSON.parse(window.localStorage.getItem(RECENT_KEY) || "[]");
    return Array.isArray(items)
      ? items
          .filter(
            (item) =>
              typeof item?.symbol === "string" && normalizeTicker(item.symbol),
          )
          .slice(0, 8)
          .map((item) => ({
            symbol: normalizeTicker(item.symbol)!,
            name:
              typeof item.name === "string"
                ? item.name
                : normalizeTicker(item.symbol)!,
            exchange: typeof item.exchange === "string" ? item.exchange : null,
            asset_type:
              typeof item.asset_type === "string" ? item.asset_type : null,
          }))
      : [];
  } catch {
    return [];
  }
}
function searchOptions(term: string) {
  return {
    queryKey: ["stock-search", term.toLowerCase()],
    queryFn: ({ signal }: { signal: AbortSignal }) =>
      api<StockSearchResponse>(`/search?q=${encodeURIComponent(term)}`, {
        signal,
      }),
    staleTime: 300_000,
    retry: false as const,
  };
}
export default function StockSearch({
  onSelect,
}: {
  onSelect: (ticker: string) => void;
}) {
  const [value, setValue] = useState("");
  const [debounced, setDebounced] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [message, setMessage] = useState("");
  const [resolving, setResolving] = useState(false);
  const [recent, setRecent] = useState(readRecent);
  const root = useRef<HTMLDivElement>(null);
  const sequence = useRef(0);
  const id = useId();
  const client = useQueryClient();
  const term = value.trim();
  const search = useQuery({
    ...searchOptions(debounced),
    enabled: Boolean(debounced),
  });
  const current = term.toLowerCase() === debounced.toLowerCase();
  const results = current ? search.data?.results || [] : [];
  const choices = term ? results : recent;
  const loading = resolving || Boolean(term && (!current || search.isFetching));
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(term), 300);
    return () => window.clearTimeout(timer);
  }, [term]);
  useEffect(() => {
    const dismiss = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", dismiss);
    return () => {
      sequence.current++;
      document.removeEventListener("pointerdown", dismiss);
    };
  }, []);
  const choose = (result: StockSearchResult) => {
    const symbol = normalizeTicker(result.symbol);
    if (!symbol) return;
    sequence.current++;
    const item = { ...result, symbol };
    const next = [
      item,
      ...recent.filter((previous) => previous.symbol !== symbol),
    ].slice(0, 8);
    setRecent(next);
    try {
      window.localStorage.setItem(RECENT_KEY, JSON.stringify(next));
    } catch {
      /* Storage may be disabled; search still works. */
    }
    setValue("");
    setOpen(false);
    setMessage("");
    setResolving(false);
    setActive(-1);
    onSelect(symbol);
  };
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (active >= 0 && choices[active]) {
      choose(choices[active]);
      return;
    }
    if (!term) {
      setOpen(true);
      setMessage("Enter a ticker symbol or company name.");
      return;
    }
    setOpen(true);
    setMessage("");
    const request = ++sequence.current;
    setResolving(true);
    try {
      const data =
        current && search.isSuccess
          ? search.data
          : await client.fetchQuery(searchOptions(term));
      if (request !== sequence.current) return;
      const exact = data.results.find(
        (result) => result.symbol.toUpperCase() === term.toUpperCase(),
      );
      const companyName = data.results.find((result) => {
        const name = result.name?.toLowerCase();
        return (
          name === term.toLowerCase() ||
          name?.startsWith(term.toLowerCase() + " ")
        );
      });
      if (exact) choose(exact);
      else if (companyName) choose(companyName);
      else if (normalizeTicker(term) && term === term.toUpperCase())
        choose({
          symbol: normalizeTicker(term)!,
          name: term,
          exchange: null,
          asset_type: null,
        });
      else if (data.results.length) choose(data.results[0]);
      else {
        const symbol = normalizeTicker(term);
        if (
          symbol &&
          (term === term.toUpperCase() || term === term.toLowerCase())
        )
          choose({ symbol, name: symbol, exchange: null, asset_type: null });
        else
          setMessage(
            "No matching listing found. Select a result or enter an exact Yahoo Finance ticker.",
          );
      }
    } catch (error) {
      if (request !== sequence.current) return;
      const symbol = normalizeTicker(term);
      if (symbol && term === term.toUpperCase())
        choose({ symbol, name: symbol, exchange: null, asset_type: null });
      else
        setMessage(
          error instanceof Error
            ? `${error.message} Enter an exact uppercase ticker to analyze it directly.`
            : "Search is unavailable. Please retry or enter an exact ticker.",
        );
    } finally {
      if (request === sequence.current) setResolving(false);
    }
  };
  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      sequence.current++;
      setOpen(false);
      setResolving(false);
      setActive(-1);
    }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      setOpen(true);
      setActive((index) =>
        choices.length
          ? index < 0
            ? event.key === "ArrowDown"
              ? 0
              : choices.length - 1
            : (index + (event.key === "ArrowDown" ? 1 : -1) + choices.length) %
              choices.length
          : -1,
      );
    }
  };
  const error = current ? search.error : null;
  const showError = message || (error instanceof Error ? error.message : "");
  const retryable = !(error instanceof ApiError) || error.retryable;
  return (
    <div className="stock-search" ref={root}>
      <form className="search-field" onSubmit={submit} role="search">
        <Search size={19} />
        <input
          role="combobox"
          aria-label="Search stock ticker or company"
          aria-autocomplete="list"
          aria-expanded={open}
          aria-controls={id}
          aria-activedescendant={
            open && active >= 0 ? `${id}-${active}` : undefined
          }
          placeholder="Search a stock ticker or company name"
          value={value}
          onFocus={() => setOpen(true)}
          onChange={(event) => {
            sequence.current++;
            setValue(event.target.value);
            setOpen(true);
            setActive(-1);
            setMessage("");
            setResolving(false);
          }}
          onKeyDown={onKeyDown}
          maxLength={100}
        />
        <button type="submit" className="search-enter" aria-label="Search">
          {loading ? <LoaderCircle size={13} className="spin" /> : "↵"}
        </button>
      </form>
      {open && (
        <div className="search-dropdown">
          <div className="search-dropdown-label">
            {term ? "YAHOO FINANCE LISTINGS" : "RECENTLY SEARCHED STOCKS"}
            {search.data?.cache_stale && current && (
              <span>
                Cached search results · {dateTime(search.data.fetched_at)}
              </span>
            )}
          </div>
          {loading && (
            <p className="search-feedback" role="status">
              <LoaderCircle size={13} className="spin" />
              Searching listings…
            </p>
          )}
          {showError && (
            <div className="search-feedback search-error" role="alert">
              <span>{showError}</span>
              {retryable && term && (
                <button
                  type="button"
                  className="text-button"
                  onClick={() => {
                    setMessage("");
                    setDebounced(term);
                    if (current) search.refetch();
                  }}
                >
                  <RefreshCw size={12} />
                  Retry search
                </button>
              )}
            </div>
          )}
          <ul
            id={id}
            role="listbox"
            aria-label={
              term ? "Stock search results" : "Recently searched stocks"
            }
          >
            {choices.map((result, index) => (
              <li
                id={`${id}-${index}`}
                role="option"
                aria-selected={index === active}
                className={index === active ? "active" : ""}
                key={result.symbol}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => choose(result)}
              >
                {!term && <Clock3 size={13} />}
                <strong>{result.symbol}</strong>
                <div>
                  <span>{result.name || result.symbol}</span>
                  <small>
                    {[result.exchange, result.asset_type]
                      .filter(Boolean)
                      .join(" · ") || "Yahoo Finance symbol"}
                  </small>
                </div>
              </li>
            ))}
          </ul>
          {!loading && !showError && !choices.length && (
            <p className="search-feedback">
              {term
                ? "No matching listings. Press Enter to try an exact ticker."
                : "Search by company name or any valid Yahoo Finance ticker."}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
