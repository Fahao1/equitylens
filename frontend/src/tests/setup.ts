import "@testing-library/jest-dom/vitest";
import { afterEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";
const stored = new Map<string, string>();
// Node 25's experimental storage can mask jsdom's browser storage.
Object.defineProperty(window, "localStorage", {
  configurable: true,
  value: {
    getItem: (key: string) => stored.get(key) ?? null,
    setItem: (key: string, value: string) => {
      stored.set(key, String(value));
    },
    removeItem: (key: string) => {
      stored.delete(key);
    },
    clear: () => stored.clear(),
    key: (index: number) => Array.from(stored.keys())[index] ?? null,
    get length() {
      return stored.size;
    },
  },
});
afterEach(() => {
  cleanup();
  window.localStorage.clear();
  window.history.replaceState(null, "", "/");
  vi.useRealTimers();
});
Object.defineProperty(window, "scrollTo", { value: vi.fn(), writable: true });
