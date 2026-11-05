import { useEffect, useRef, useState, type ReactNode } from "react";
import { fmtEur, fmtPct } from "../lib/format";

export function Money({
  value,
  round,
  sign,
  tone,
  className = "",
}: {
  value: number | null | undefined;
  round?: boolean;
  sign?: boolean;
  tone?: "auto" | "none";
  className?: string;
}) {
  const color =
    tone === "auto" && value ? (value > 0 ? "text-pos" : "text-neg") : "";
  return <span className={`money num ${color} ${className}`}>{fmtEur(value, { round, sign })}</span>;
}

export function Pct({ value, className = "" }: { value: number | null | undefined; className?: string }) {
  const color = value ? (value > 0 ? "text-pos" : "text-neg") : "text-muted";
  return <span className={`num ${color} ${className}`}>{fmtPct(value)}</span>;
}

const deltaColor = (diff: number, good: "up" | "down" | "none") =>
  good === "none" || diff === 0 ? "" : (diff > 0) === (good === "up") ? "text-pos" : "text-neg";

/** "+12 % vs prev" in muted text. `good` says which direction is desirable (colors the %); hidden without a base. */
export function Delta({
  value,
  base,
  good = "none",
  label = "vs prev",
  className = "",
}: {
  value: number;
  base: number | null | undefined;
  good?: "up" | "down" | "none";
  label?: string;
  className?: string;
}) {
  if (!base) return null;
  const diff = value - base;
  const pct = Math.round((diff / Math.abs(base)) * 100);
  // a % is meaningless against a negative or tiny base: fall back to the absolute change
  const text = base < 0 || Math.abs(pct) >= 300 ? fmtEur(diff, { round: true, sign: true }) : fmtPct(pct);
  return (
    <span className={`whitespace-nowrap text-xs text-muted ${className}`}>
      <span className={`num ${deltaColor(diff, good)}`}>{text}</span>
      {label && ` ${label}`}
    </span>
  );
}

/** Just the direction of a change as a colored arrow; `min` (fraction of base) hides noise. */
export function Trend({ value, base, good = "down", min = 0.1 }: { value: number; base: number | null | undefined; good?: "up" | "down"; min?: number }) {
  if (!base || base <= 0) return <span className="text-xs text-muted">·</span>;
  const diff = value - base;
  if (Math.abs(diff) / base < min) return <span className="text-xs text-muted">·</span>;
  return <span className={`text-xs ${deltaColor(diff, good)}`} aria-label={diff > 0 ? "above average" : "below average"}>{diff > 0 ? "↑" : "↓"}</span>;
}

/**
 * Secondary numbers live here: hover shows them on desktop, a tap (or Enter) toggles them on
 * phones; Escape or a tap elsewhere closes. The trigger gets a dotted underline so it reads as
 * "more behind this".
 */
export function Tip({ content, children, className = "" }: { content: ReactNode; children: ReactNode; className?: string }) {
  const [open, setOpen] = useState(false);
  const [right, setRight] = useState(false);
  const hover = useRef(false);
  const ref = useRef<HTMLSpanElement>(null);
  const show = () => {
    const r = ref.current?.getBoundingClientRect();
    if (r) setRight(r.left + r.width / 2 > window.innerWidth / 2);
    setOpen(true);
  };
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: PointerEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("pointerdown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);
  return (
    <span
      ref={ref}
      className={`relative inline-flex ${className}`}
      onPointerEnter={(e) => e.pointerType === "mouse" && ((hover.current = true), show())}
      onPointerLeave={(e) => e.pointerType === "mouse" && ((hover.current = false), setOpen(false))}
    >
      <button
        type="button"
        aria-expanded={open}
        onClick={() => (hover.current ? show() : open ? setOpen(false) : show())}
        className="cursor-help rounded-sm text-left underline decoration-line decoration-dotted underline-offset-4 hover:decoration-muted"
      >
        {children}
      </button>
      {open && (
        <span
          role="tooltip"
          className={`absolute top-full z-20 mt-1.5 w-max max-w-[min(18rem,85vw)] rounded-lg border border-line bg-surface px-2.5 py-2 text-left text-xs font-normal leading-5 text-text shadow-lg ${right ? "right-0" : "left-0"}`}
        >
          {content}
        </span>
      )}
    </span>
  );
}

/** Label/value rows for a tooltip body. */
export function Rows({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <span className="grid grid-cols-[auto_auto] gap-x-4 gap-y-0.5">
      {rows.map(([k, v]) => (
        <span key={k} className="contents">
          <span className="text-muted">{k}</span>
          <span className="text-right">{v}</span>
        </span>
      ))}
    </span>
  );
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <section className={`rounded-xl border border-line bg-surface ${className}`}>{children}</section>;
}

export function H2({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <div className="mb-3 flex items-baseline justify-between gap-3">
      <h2 className="text-sm font-medium text-muted">{children}</h2>
      {right}
    </div>
  );
}

export function PageTitle({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-center justify-between gap-x-3 gap-y-3">
      <h1 className="text-xl font-semibold tracking-tight">{children}</h1>
      {right}
    </div>
  );
}

export function Skeleton({ className = "h-4 w-24" }: { className?: string }) {
  return <div className={`skeleton ${className}`} aria-hidden />;
}

export function SkeletonRows({ n = 5 }: { n?: number }) {
  return (
    <div className="flex flex-col gap-3 py-1">
      {Array.from({ length: n }).map((_, i) => (
        <div key={i} className="flex items-center justify-between gap-3">
          <Skeleton className="h-4 w-2/5" />
          <Skeleton className="h-4 w-16" />
        </div>
      ))}
    </div>
  );
}

export function ErrorNote({ error }: { error: unknown }) {
  const msg = error instanceof Error ? error.message : String(error);
  return (
    <p role="alert" className="rounded-lg border border-neg/30 bg-neg/5 px-3 py-2 text-sm text-neg">
      {msg}
    </p>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="py-6 text-center text-sm text-muted">{children}</p>;
}

export function Button({
  children,
  onClick,
  variant = "default",
  disabled,
  type = "button",
  className = "",
  title,
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "default" | "primary" | "ghost" | "danger";
  disabled?: boolean;
  type?: "button" | "submit";
  className?: string;
  title?: string;
}) {
  const styles = {
    default: "border border-line bg-surface hover:bg-bg",
    primary: "bg-accent text-white hover:opacity-90",
    ghost: "text-muted hover:text-text hover:bg-line/60",
    danger: "text-neg hover:bg-neg/10",
  }[variant];
  return (
    <button
      type={type}
      title={title}
      onClick={onClick}
      disabled={disabled}
      className={`inline-flex min-h-9 items-center justify-center gap-1.5 rounded-lg px-3 text-sm font-medium transition disabled:opacity-50 ${styles} ${className}`}
    >
      {children}
    </button>
  );
}

export function Chip({
  children,
  onClick,
  active,
  className = "",
}: {
  children: ReactNode;
  onClick?: () => void;
  active?: boolean;
  className?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`inline-flex min-h-8 items-center rounded-full border px-3 text-xs font-medium transition ${
        active
          ? "border-accent bg-accent-soft text-accent"
          : "border-line bg-surface hover:border-accent hover:text-accent"
      } ${className}`}
    >
      {children}
    </button>
  );
}

/** Thin horizontal bar, value relative to max. */
export function Bar({ value, max, tone = "accent" }: { value: number; max: number; tone?: "accent" | "muted" }) {
  const w = max > 0 ? Math.max(0, Math.min(100, (value / max) * 100)) : 0;
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-line">
      <div
        className={`h-full rounded-full ${tone === "accent" ? "bg-accent" : "bg-muted/50"}`}
        style={{ width: `${w}%` }}
      />
    </div>
  );
}

/** Small switch; `label` is the accessible name. */
export function Toggle({ on, onChange, disabled, label }: { on: boolean; onChange: (v: boolean) => void; disabled?: boolean; label: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!on)}
      className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full border transition disabled:opacity-50 ${
        on ? "border-accent bg-accent" : "border-line bg-line/60"
      }`}
    >
      <span className={`inline-block h-3.5 w-3.5 rounded-full bg-white shadow transition ${on ? "translate-x-[18px]" : "translate-x-[3px]"}`} />
    </button>
  );
}
