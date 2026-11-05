import { thisMonth } from "../lib/format";
import { isCustom, PRESETS, type Period } from "../lib/period";

export function PeriodPicker({ range, period, onChange }: { range: string; period?: Period; onChange: (r: string) => void }) {
  const custom = isCustom(range);
  const [from, to] = custom ? range.split("..") : [period?.start.slice(0, 7) ?? thisMonth(), period?.end.slice(0, 7) ?? thisMonth()];
  const seg = (active: boolean) =>
    `rounded-md px-2.5 py-1 transition ${active ? "bg-accent-soft text-accent" : "text-muted hover:text-text"}`;
  return (
    <div className="flex flex-wrap items-center justify-end gap-2">
      <div role="tablist" className="inline-flex rounded-lg border border-line bg-surface p-0.5 text-xs font-medium">
        {PRESETS.map(([k, label]) => (
          <button key={k} type="button" role="tab" aria-selected={range === k} onClick={() => onChange(k)} className={seg(range === k)}>
            {label}
          </button>
        ))}
        <button type="button" role="tab" aria-selected={custom} onClick={() => onChange(`${from}..${to}`)} className={seg(custom)}>
          Custom
        </button>
      </div>
      {custom && (
        <div className="flex items-center gap-1.5 text-xs">
          <input type="month" value={from} max={to} onChange={(e) => e.target.value && onChange(`${e.target.value}..${to}`)} className="num !min-h-8 !py-1" aria-label="From" />
          <span className="text-muted">–</span>
          <input type="month" value={to} min={from} max={thisMonth()} onChange={(e) => e.target.value && onChange(`${from}..${e.target.value}`)} className="num !min-h-8 !py-1" aria-label="To" />
        </div>
      )}
    </div>
  );
}
