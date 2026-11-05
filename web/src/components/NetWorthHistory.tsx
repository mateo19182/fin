import { Area, AreaChart, ResponsiveContainer, Tooltip, YAxis } from "recharts";
import type { NetWorthMonth } from "../lib/api";
import { fmtEur, fmtMonthLong } from "../lib/format";

export const NW_GROUPS = [
  { key: "cash", label: "Cash", opacity: 0.9 },
  { key: "stocks", label: "Revolut", opacity: 0.65 },
  { key: "indexa", label: "Indexa", opacity: 0.45 },
  { key: "crypto", label: "Crypto", opacity: 0.3 },
  { key: "receivables", label: "Receivables", opacity: 0.15 },
] as const;
type GroupKey = (typeof NW_GROUPS)[number]["key"];

export type Row = Record<GroupKey, number> & { month: string; total: number };

export const toRows = (data: NetWorthMonth[]): Row[] =>
  data.map((r) => ({
    month: r.month,
    total: Number(r.total),
    ...(Object.fromEntries(NW_GROUPS.map((g) => [g.key, Number(r.groups[g.key] ?? 0)])) as Record<GroupKey, number>),
  }));

/** Stacked monthly net worth by group. `rows[0]` is the month before the period (the baseline). */
export function GroupArea({ rows }: { rows: Row[] }) {
  const groups = NW_GROUPS.filter((g) => rows.some((r) => r[g.key] !== 0));
  return (
    <ResponsiveContainer>
      <AreaChart data={rows} margin={{ top: 4, right: 0, bottom: 0, left: 0 }}>
        <YAxis hide domain={[0, "dataMax + 1000"]} />
        <Tooltip
          cursor={{ stroke: "var(--line)" }}
          content={({ payload }) => {
            const r = (payload as { payload: Row }[] | undefined)?.[0]?.payload;
            if (!r) return null;
            return (
              <div className="rounded-lg border border-line bg-surface px-2.5 py-1.5 text-xs shadow">
                <div className="text-muted">{fmtMonthLong(r.month)}</div>
                <div className="money num font-medium">{fmtEur(r.total, { round: true })}</div>
                {groups.map((g) => (
                  <div key={g.key} className="flex justify-between gap-4 text-muted">
                    <span>{g.label}</span>
                    <span className="money num">{fmtEur(r[g.key], { round: true })}</span>
                  </div>
                ))}
              </div>
            );
          }}
        />
        {groups.map((g) => (
          <Area
            key={g.key}
            type="monotone"
            dataKey={g.key}
            stackId="nw"
            stroke="var(--bg)"
            strokeWidth={1}
            fill="var(--accent)"
            fillOpacity={g.opacity}
            dot={false}
            activeDot={{ r: 3, strokeWidth: 0, fill: "var(--accent)" }}
            isAnimationActive={false}
          />
        ))}
      </AreaChart>
    </ResponsiveContainer>
  );
}
