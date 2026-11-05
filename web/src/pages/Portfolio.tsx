import { useMemo, useState } from "react";
import { Area, ComposedChart, Line, ResponsiveContainer, Tooltip, YAxis } from "recharts";
import { useHoldings, usePortfolioSeries, type Position } from "../lib/api";
import { fmtDate, fmtEur, fmtMonth, fmtPct, fmtPeriod, fmtUnits } from "../lib/format";
import { usePeriod, type Period } from "../lib/period";
import { PeriodPicker } from "../components/PeriodPicker";
import { Card, Empty, ErrorNote, H2, Money, PageTitle, Pct, Skeleton, SkeletonRows } from "../components/ui";

type Key = "symbol" | "value" | "period_pl" | "period_pct" | "pl_pct" | "weight";
const COLS: { key: Key; label: string; align?: "right"; wide?: boolean }[] = [
  { key: "symbol", label: "Position" },
  { key: "value", label: "Value", align: "right" },
  { key: "period_pl", label: "Period", align: "right" },
  { key: "period_pct", label: "%", align: "right" },
  { key: "pl_pct", label: "All-time", align: "right", wide: true },
  { key: "weight", label: "Weight", align: "right", wide: true },
];
const GROUP_STYLE: Record<string, string> = {
  Revolut: "bg-accent",
  Indexa: "bg-accent/50",
  Crypto: "bg-muted/60",
};

function ValueChart({ period }: { period?: Period }) {
  const { data, isLoading, error } = usePortfolioSeries(period);
  if (error) return <ErrorNote error={error} />;
  if (isLoading || !data || !period) return <Skeleton className="h-40 w-full" />;
  const first = data[0], last = data[data.length - 1];
  const change = last.value - first.value;
  const ret = last.value - last.cost - (first.value - first.cost);
  const multiYear = period.start.slice(0, 4) !== period.end.slice(0, 4);
  const axis = (d: string) => (period.months > 12 ? fmtMonth(d.slice(0, 7), true) : fmtDate(d, multiYear));
  return (
    <>
      <H2
        right={
          <span className="flex items-center gap-3 text-[11px] text-muted">
            <span className="flex items-center gap-1">
              <i className="inline-block h-1.5 w-3 rounded-full bg-accent" /> value
            </span>
            <span className="flex items-center gap-1">
              <i className="inline-block h-0 w-3 border-t border-dashed border-muted" /> cost
            </span>
          </span>
        }
      >
        Value · {fmtPeriod(period.start, period.end)}
      </H2>
      <dl className="mb-3 flex flex-wrap gap-x-6 gap-y-1 text-sm">
        <div>
          <Money value={change} round sign tone="auto" className="font-medium" />
          <span className="text-muted"> since {fmtDate(first.date)}</span>
        </div>
        <div>
          <Money value={ret} round sign tone="auto" className="font-medium" />
          <span className="text-muted"> return in period</span>
        </div>
      </dl>
      <div className="h-36 md:h-40">
        <ResponsiveContainer>
          <ComposedChart data={data} margin={{ top: 4, right: 0, bottom: 0, left: 0 }}>
            <defs>
              <linearGradient id="pf" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="var(--accent)" stopOpacity={0.25} />
                <stop offset="100%" stopColor="var(--accent)" stopOpacity={0} />
              </linearGradient>
            </defs>
            <YAxis hide domain={["dataMin - 500", "dataMax + 500"]} />
            <Tooltip
              cursor={{ stroke: "var(--line)" }}
              content={({ payload }) => {
                const p = payload?.[0]?.payload;
                if (!p) return null;
                return (
                  <div className="rounded-lg border border-line bg-surface px-2.5 py-1.5 text-xs shadow">
                    <div className="text-muted">{fmtDate(p.date, true)}</div>
                    <div className="money num font-medium">{fmtEur(p.value, { round: true })}</div>
                    <div className="money num text-muted">cost {fmtEur(p.cost, { round: true })}</div>
                  </div>
                );
              }}
            />
            <Area type="monotone" dataKey="value" stroke="var(--accent)" strokeWidth={2} fill="url(#pf)" dot={false} activeDot={{ r: 4, strokeWidth: 0 }} isAnimationActive={false} />
            <Line type="monotone" dataKey="cost" stroke="var(--muted)" strokeWidth={1} strokeDasharray="3 3" dot={false} activeDot={false} isAnimationActive={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-1 flex justify-between text-[11px] text-muted">
        <span>{axis(first.date)}</span>
        <span>{axis(last.date)}</span>
      </div>
    </>
  );
}

export function Portfolio() {
  const { range, setRange, period, error: perr } = usePeriod("1y");
  const { data, isLoading, error } = useHoldings(period);
  const [sort, setSort] = useState<{ key: Key; dir: 1 | -1 }>({ key: "value", dir: -1 });

  const rows = useMemo(() => {
    if (!data) return [];
    const v = (p: Position) => (sort.key === "symbol" ? p.symbol : (p[sort.key] ?? -Infinity));
    return [...data.positions].sort((a, b) => {
      const x = v(a), y = v(b);
      return (x < y ? -1 : x > y ? 1 : 0) * sort.dir;
    });
  }, [data, sort]);

  if (error || perr) return <ErrorNote error={error ?? perr} />;
  if (isLoading || !data)
    return (
      <div className="flex flex-col gap-6">
        <Skeleton className="h-12 w-48" />
        <SkeletonRows n={8} />
      </div>
    );

  const groups = data.groups.filter((g) => g.value > 0);
  const stale = data.positions.some((p) => !p.priced);
  const toggle = (key: Key) =>
    setSort((s) => ({ key, dir: s.key === key ? ((s.dir * -1) as 1 | -1) : key === "symbol" ? 1 : -1 }));

  return (
    <div className="flex flex-col gap-6">
      <section>
        <PageTitle right={<PeriodPicker range={range} period={period} onChange={setRange} />}>Portfolio</PageTitle>
        <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
          <Money value={data.total} round className="text-4xl font-semibold tracking-tight md:text-5xl" />
          <span className="text-sm">
            <Money value={data.pl} round sign tone="auto" /> <Pct value={data.pl_pct} className="text-muted" />
            <span className="text-muted"> on cost</span>
          </span>
        </div>
        {stale && <p className="mt-2 text-xs text-warn">Some positions have no price; cost is used instead.</p>}
      </section>

      <Card className="p-4 md:p-5">
        <ValueChart period={period} />
      </Card>

      <Card className="p-4 md:p-5">
        <H2>Allocation</H2>
        <div className="flex h-2.5 w-full gap-0.5 overflow-hidden rounded-full">
          {groups.map((g) => (
            <div key={g.name} className={`${GROUP_STYLE[g.name] ?? "bg-muted"} rounded-sm`} style={{ width: `${g.weight}%` }} title={`${g.name} ${fmtPct(g.weight, false)}`} />
          ))}
        </div>
        <dl className="mt-4 grid grid-cols-3 gap-4">
          {groups.map((g) => (
            <div key={g.name}>
              <dt className="flex items-center gap-1.5 text-xs text-muted">
                <i className={`inline-block h-2 w-2 rounded-full ${GROUP_STYLE[g.name] ?? "bg-muted"}`} />
                {g.name}
                <span className="num">{Math.round(g.weight)}%</span>
              </dt>
              <dd>
                <Money value={g.value} round className="text-base font-medium" />
                <div className="text-xs">
                  <Money value={g.pl} round sign tone="auto" />
                </div>
              </dd>
            </div>
          ))}
        </dl>
      </Card>

      <Card className="overflow-hidden">
        {rows.length === 0 ? (
          <Empty>No positions</Empty>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line text-xs text-muted">
                {COLS.map((c) => (
                  <th
                    key={c.key}
                    className={`px-3 py-2.5 font-medium first:pl-4 last:pr-4 ${c.align === "right" ? "text-right" : "text-left"} ${
                      c.wide ? "hidden sm:table-cell" : ""
                    }`}
                  >
                    <button type="button" onClick={() => toggle(c.key)} className={`hover:text-text ${sort.key === c.key ? "text-text" : ""}`}>
                      {c.label}
                      {sort.key === c.key && <span className="ml-0.5">{sort.dir === 1 ? "↑" : "↓"}</span>}
                    </button>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {rows.map((p) => (
                <tr key={`${p.group}-${p.symbol}`}>
                  <td className="px-3 py-2.5 pl-4">
                    <div className="flex items-center gap-2">
                      <i className={`inline-block h-2 w-2 shrink-0 rounded-full ${GROUP_STYLE[p.group] ?? "bg-muted"}`} title={p.group} />
                      <div>
                        <div className="font-medium">{p.symbol}</div>
                        <div className="num text-xs text-muted">
                          {fmtUnits(p.units)}
                          {p.price !== null && (
                            <span className="hidden sm:inline">
                              {" "}
                              × <Money value={p.price} />
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                  </td>
                  <td className="px-3 py-2.5 text-right">
                    <Money value={p.value} round className="font-medium" />
                    {p.cost !== null && (
                      <div className="text-xs text-muted">
                        <Money value={p.cost} round />
                      </div>
                    )}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2.5 text-right">
                    <Money value={p.period_pl ?? null} round sign tone="auto" />
                  </td>
                  <td className="whitespace-nowrap px-3 py-2.5 text-right">
                    <Pct value={p.period_pct ?? null} />
                  </td>
                  <td className="hidden whitespace-nowrap px-3 py-2.5 text-right text-muted sm:table-cell">
                    <Pct value={p.pl_pct} />
                  </td>
                  <td className="num hidden px-3 py-2.5 pr-4 text-right text-muted sm:table-cell">{fmtPct(p.weight, false)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}
