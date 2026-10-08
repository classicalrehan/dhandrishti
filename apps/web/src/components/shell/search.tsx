"use client";

import type { SearchResult } from "@dd/contracts";
import { Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";
import { browserApiBase } from "@/lib/browser-api";


export function StockSearch() {
  const router = useRouter();
  const listId = useId();
  const [q, setQ] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [active, setActive] = useState(0);
  const [open, setOpen] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const term = q.trim();
    if (!term) {
      setResults([]);
      return;
    }
    const ctrl = new AbortController();
    const t = setTimeout(() => {
      fetch(`${browserApiBase()}/v1/search?q=${encodeURIComponent(term)}`, { signal: ctrl.signal })
        .then((r) => (r.ok ? r.json() : { data: [] }))
        .then((b) => {
          setResults(b.data ?? []);
          setActive(0);
        })
        .catch(() => {});
    }, 150);
    return () => {
      clearTimeout(t);
      ctrl.abort();
    };
  }, [q]);

  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (!boxRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  const go = (symbol: string) => {
    setOpen(false);
    setQ("");
    router.push(`/stock/${encodeURIComponent(symbol)}`);
  };

  return (
    <div ref={boxRef} className="relative w-full max-w-xl">
      <Search aria-hidden className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-faint" />
      <input
        role="combobox"
        aria-expanded={open && results.length > 0}
        aria-controls={listId}
        aria-label="Search stocks"
        value={q}
        onChange={(e) => {
          setQ(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") setActive((a) => Math.min(a + 1, results.length - 1));
          else if (e.key === "ArrowUp") setActive((a) => Math.max(a - 1, 0));
          else if (e.key === "Enter" && results[active]) go(results[active].symbol);
          else if (e.key === "Escape") setOpen(false);
        }}
        placeholder="Search stocks by name or symbol…"
        className="h-10 w-full rounded-lg border border-line bg-surface pl-9 pr-3 text-sm text-ink placeholder:text-faint focus:border-brand/40 focus:outline-none"
      />
      {open && results.length > 0 && (
        <ul
          id={listId}
          role="listbox"
          className="absolute z-30 mt-1 w-full overflow-hidden rounded-lg border border-line-strong bg-surface-2 py-1 shadow-2xl"
        >
          {results.map((r, i) => (
            <li
              key={r.symbol}
              role="option"
              aria-selected={i === active}
              onMouseDown={(e) => {
                e.preventDefault();
                go(r.symbol);
              }}
              onMouseEnter={() => setActive(i)}
              className={`flex cursor-pointer items-center justify-between px-3 py-2 text-sm ${i === active ? "bg-surface-3" : ""}`}
            >
              <span>
                <span className="font-medium text-ink">{r.name}</span>
                <span className="ml-2 font-mono text-xs text-muted">{r.symbol}</span>
              </span>
              <span className="text-xs text-faint">{r.sector}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
