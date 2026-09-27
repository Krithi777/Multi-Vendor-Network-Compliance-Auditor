"use client";

// Replaces the native <select> used for "canonical field" picking in the
// Training Studio. The native control rendered as a huge, unstyled OS
// listbox that could cover most of the page -- this is a small, properly
// themed combobox instead: button + panel, filterable (there can be 20+
// controls), closes on outside click / Escape / selection.

import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown, Search } from "lucide-react";

export interface FieldOption {
  value: string;
  label: string;
}

export default function FieldSelect({
  value,
  onChange,
  options,
  placeholder = "Select…",
  className = "",
}: {
  value: string;
  onChange: (value: string) => void;
  options: FieldOption[];
  placeholder?: string;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false);
        setQuery("");
      }
    }
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        setOpen(false);
        setQuery("");
      }
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  const selected = options.find((o) => o.value === value) ?? null;
  const filtered = query.trim()
    ? options.filter((o) => o.label.toLowerCase().includes(query.trim().toLowerCase()))
    : options;

  return (
    <div
      ref={rootRef}
      onClick={(e) => e.stopPropagation()}
      className={`relative ${className}`}
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={`w-full flex items-center justify-between gap-2 rounded-xl border bg-panel px-3.5 py-2.5 text-sm font-mono text-left transition-colors ${
          open ? "border-ink ring-2 ring-ink/10" : "border-line hover:border-ink-soft"
        }`}
      >
        <span className={`truncate ${selected ? "text-ink" : "text-ink-soft"}`}>
          {selected ? selected.label : placeholder}
        </span>
        <ChevronDown
          className={`w-4 h-4 shrink-0 text-ink-soft transition-transform duration-150 ${open ? "rotate-180" : ""}`}
          strokeWidth={2}
        />
      </button>

      {open && (
        <div className="absolute z-30 mt-1.5 w-full rounded-xl border border-line bg-panel shadow-lg overflow-hidden">
          <div className="flex items-center gap-2 border-b border-line-soft px-3 py-2">
            <Search className="w-3.5 h-3.5 text-ink-soft shrink-0" strokeWidth={2} />
            <input
              autoFocus
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Filter controls…"
              className="w-full bg-transparent text-sm font-mono text-ink placeholder:text-ink-soft outline-none"
            />
          </div>
          <div className="max-h-60 overflow-y-auto py-1">
            {filtered.length === 0 ? (
              <p className="px-3.5 py-3 text-xs text-ink-soft">No matching control.</p>
            ) : (
              filtered.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => {
                    onChange(opt.value);
                    setOpen(false);
                    setQuery("");
                  }}
                  className={`w-full flex items-center justify-between gap-2 px-3.5 py-2 text-left text-sm font-mono transition-colors ${
                    opt.value === value ? "bg-paper-dim text-ink" : "text-ink-soft hover:bg-paper-dim hover:text-ink"
                  }`}
                >
                  <span className="truncate">{opt.label}</span>
                  {opt.value === value && <Check className="w-3.5 h-3.5 text-pass shrink-0" strokeWidth={2} />}
                </button>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}