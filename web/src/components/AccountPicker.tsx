import { useEffect, useMemo, useRef, useState } from "react";
import { useAccounts } from "../lib/api";
import { shortAccount } from "../lib/format";

/**
 * Searchable account picker. Renders as a small popover anchored to its parent
 * (parent should be `relative`). Expense/Income accounts first.
 */
export function AccountPicker({
  current,
  onPick,
  onClose,
  prefixes = ["Expenses:", "Income:"],
}: {
  current?: string;
  onPick: (account: string) => void;
  onClose: () => void;
  prefixes?: string[];
}) {
  const { data: accounts = [] } = useAccounts();
  const [q, setQ] = useState("");
  const ref = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    input.current?.focus();
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  const list = useMemo(() => {
    const words = q.toLowerCase().split(/\s+/).filter(Boolean);
    const pool = accounts.filter((a) => prefixes.some((p) => a.startsWith(p)));
    return pool
      .filter((a) => words.every((w) => a.toLowerCase().includes(w)))
      .sort((a, b) => a.localeCompare(b))
      .slice(0, 12);
  }, [accounts, q, prefixes]);

  return (
    <div
      ref={ref}
      className="fixed inset-x-0 bottom-0 z-30 rounded-t-2xl border border-line bg-surface p-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] shadow-lg sm:absolute sm:inset-x-auto sm:bottom-auto sm:right-0 sm:mt-1 sm:w-72 sm:rounded-xl sm:p-2"
    >
      <input
        ref={input}
        type="search"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && list[0] && onPick(list[0])}
        placeholder="Search accounts…"
        className="w-full"
      />
      <ul className="mt-1 max-h-64 overflow-auto">
        {list.map((a) => (
          <li key={a}>
            <button
              type="button"
              onClick={() => onPick(a)}
              className={`flex w-full items-center justify-between rounded-lg px-2 py-2 text-left text-sm hover:bg-accent-soft ${
                a === current ? "text-accent" : ""
              }`}
            >
              <span>{shortAccount(a)}</span>
              <span className="text-xs text-muted">{a.split(":")[0]}</span>
            </button>
          </li>
        ))}
        {list.length === 0 && <li className="px-2 py-3 text-sm text-muted">No results</li>}
      </ul>
    </div>
  );
}

/** Inline "category" button that opens a picker. */
export function CategoryButton({
  account,
  onChange,
  busy,
  className = "",
}: {
  account: string;
  onChange: (a: string) => void;
  busy?: boolean;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  return (
    <span className={`relative inline-block ${className}`}>
      <button
        type="button"
        onClick={() => setOpen(true)}
        disabled={busy}
        title="Change category"
        className={`max-w-full truncate rounded-md px-1.5 py-0.5 text-xs text-muted hover:bg-line/70 hover:text-text ${
          busy ? "opacity-50" : ""
        } ${account.endsWith("Uncategorized") ? "text-warn" : ""}`}
      >
        {shortAccount(account)}
      </button>
      {open && (
        <AccountPicker
          current={account}
          onClose={() => setOpen(false)}
          onPick={(a) => {
            setOpen(false);
            if (a !== account) onChange(a);
          }}
        />
      )}
    </span>
  );
}
