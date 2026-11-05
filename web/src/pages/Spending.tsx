import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Bar as RBar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useCashflow, useCategories, useSubscriptions, useTransactions, type Subscription } from "../lib/api";
import { fmtBucket, fmtBucketLong, fmtDate, fmtEur, fmtPeriod, leaf, shortAccount } from "../lib/format";
import { usePeriod, type Period } from "../lib/period";
import { PeriodPicker } from "../components/PeriodPicker";
import { Bar, Card, Delta, Empty, ErrorNote, H2, Money, PageTitle, Skeleton, SkeletonRows } from "../components/ui";
import { TxnList } from "./Transactions";

function Cashflow({ period }: { period?: Period }) {
  const multiYear = !!period && period.start.slice(0, 4) !== period.end.slice(0, 4);
  const { data, isLoading, error } = useCashflow(period, period && period.months > 24 ? "quarter" : "month");
  if (error) return <ErrorNote error={error} />;
  if (isLoading || !data) return <Skeleton className="h-52 w-full" />;
  return (
    <div className="h-52">
      <ResponsiveContainer>
        <BarChart data={data} margin={{ top: 8, right: 0, bottom: 0, left: 0 }} barGap={2} barCategoryGap="30%">
          <CartesianGrid vertical={false} stroke="var(--line)" />
          <XAxis
            dataKey="period"
            tickFormatter={(p: string) => fmtBucket(p, multiYear)}
            tick={{ fill: "var(--muted)", fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            interval={data.length > 14 ? 1 : 0}
          />
          <YAxis
            tickFormatter={(v) => (v >= 1000 ? `${Math.round(v / 1000)}k` : String(v))}
            tick={{ fill: "var(--muted)", fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            width={32}
          />
          <Tooltip
            cursor={{ fill: "var(--line)", opacity: 0.5 }}
            content={({ payload }) => {
              const p = payload?.[0]?.payload;
              if (!p) return null;
              return (
                <div className="rounded-lg border border-line bg-surface px-2.5 py-1.5 text-xs shadow">
                  <div className="mb-1 text-muted">{fmtBucketLong(p.period)}</div>
                  <div className="money num">Income {fmtEur(p.income, { round: true })}</div>
                  <div className="money num">Spending {fmtEur(p.expenses, { round: true })}</div>
                  <div className="money num font-medium">Savings {fmtEur(p.savings, { round: true })}</div>
                </div>
              );
            }}
          />
          <RBar dataKey="income" name="Income" fill="var(--accent)" radius={[3, 3, 0, 0]} isAnimationActive={false} />
          <RBar dataKey="expenses" name="Spending" fill="var(--muted)" fillOpacity={0.45} radius={[3, 3, 0, 0]} isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function Categories({ period, selected, onSelect }: { period?: Period; selected: string; onSelect: (a: string) => void }) {
  const { data, isLoading, error } = useCategories(period);
  const [open, setOpen] = useState<string | null>(null);
  if (error) return <ErrorNote error={error} />;
  if (isLoading || !data) return <SkeletonRows n={6} />;
  const rows = data.filter((c) => c.total > 0);
  if (!rows.length) return <Empty>No spending in this period</Empty>;
  const total = rows.reduce((s, c) => s + c.total, 0);
  const prevTotal = data.some((c) => c.prev !== null) ? data.reduce((s, c) => s + (c.prev ?? 0), 0) : null;
  const max = rows[0].total;
  return (
    <>
      <div className="mb-4 flex items-baseline justify-between">
        <span className="text-sm text-muted">Total</span>
        <span className="flex items-baseline gap-2">
          <Delta value={total} base={prevTotal} good="down" />
          <Money value={total} className="text-lg font-semibold" />
        </span>
      </div>
      <ul className="flex flex-col gap-2">
        {rows.map((c) => {
          const expanded = open === c.account;
          const multi = c.children.length > 1;
          return (
            <li key={c.account}>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => onSelect(selected === c.account ? "" : c.account)}
                  className={`min-w-0 flex-1 rounded-lg px-2 py-1.5 text-left hover:bg-line/50 ${selected === c.account ? "bg-accent-soft" : ""}`}
                >
                  <div className="mb-1 flex items-baseline justify-between gap-3 text-sm">
                    <span className="flex min-w-0 items-baseline gap-2">
                      <span className={`truncate ${selected === c.account ? "text-accent" : ""}`}>{leaf(c.account)}</span>
                      <Delta value={c.total} base={c.prev} good="down" label="" />
                    </span>
                    <span className="shrink-0">
                      <Money value={c.total} className="font-medium" />
                      <span className="num ml-2 text-xs text-muted">{Math.round(c.share * 100)}%</span>
                    </span>
                  </div>
                  <Bar value={c.total} max={max} />
                </button>
                {multi && (
                  <button
                    type="button"
                    onClick={() => setOpen(expanded ? null : c.account)}
                    className="rounded-md p-1 text-muted hover:text-text"
                    aria-label={expanded ? "Collapse" : "Expand"}
                  >
                    <svg viewBox="0 0 24 24" className={`h-4 w-4 transition ${expanded ? "rotate-180" : ""}`} fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M6 9l6 6 6-6" />
                    </svg>
                  </button>
                )}
              </div>
              {expanded && (
                <ul className="mb-2 ml-2 mt-1 flex flex-col border-l border-line pl-3">
                  {c.children.map((ch) => (
                    <li key={ch.account}>
                      <button
                        type="button"
                        onClick={() => onSelect(selected === ch.account ? "" : ch.account)}
                        className={`flex w-full items-center justify-between gap-3 rounded-md px-2 py-1.5 text-sm hover:bg-line/50 ${
                          selected === ch.account ? "text-accent" : "text-muted"
                        }`}
                      >
                        <span className="flex min-w-0 items-baseline gap-2">
                          <span className="truncate">
                            {leaf(ch.account)} <span className="num text-xs opacity-70">×{ch.count}</span>
                          </span>
                          <Delta value={ch.total} base={ch.prev} label="" />
                        </span>
                        <Money value={ch.total} />
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </li>
          );
        })}
      </ul>
    </>
  );
}

function SubscriptionRow({ s }: { s: Subscription }) {
  return (
    <li className={`flex items-center gap-3 py-2.5 ${s.active ? "" : "opacity-50"}`}>
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm">{s.payee}</div>
        <div className="text-xs text-muted">
          {shortAccount(s.account)} · {s.months} months · last {fmtDate(s.last_date)}
        </div>
      </div>
      <div className="w-20 text-right">
        <Money value={s.amount} className="text-sm font-medium" />
        <div className="text-[11px] text-muted">
          <Money value={s.yearly} round /> / year
        </div>
      </div>
    </li>
  );
}

function Subscriptions() {
  const { data, isLoading, error } = useSubscriptions();
  if (error) return <ErrorNote error={error} />;
  if (isLoading || !data) return <SkeletonRows n={4} />;
  const active = data.filter((s) => s.active);
  const monthly = active.reduce((s, x) => s + x.amount, 0);
  if (!data.length) return <Empty>Nothing recurring detected</Empty>;
  return (
    <>
      <div className="mb-3 flex items-baseline justify-between text-sm">
        <span className="text-muted">{active.length} active</span>
        <span>
          <Money value={monthly} className="font-medium" />
          <span className="text-muted"> / month</span>
        </span>
      </div>
      <ul className="divide-y divide-line">
        {data.map((s) => (
          <SubscriptionRow key={s.payee} s={s} />
        ))}
      </ul>
    </>
  );
}

export function Spending() {
  const [sp, setSp] = useSearchParams();
  const { range, setRange, period, error } = usePeriod("6m");
  const selected = sp.get("cat") ?? "";
  const setSelected = (a: string) => {
    const n = new URLSearchParams(sp);
    a ? n.set("cat", a) : n.delete("cat");
    setSp(n, { replace: true });
  };
  const drill = useTransactions({ start: period?.start, end: period?.end, account: selected, limit: 200 }, !!selected && !!period);
  const label = period ? fmtPeriod(period.start, period.end) : "";

  return (
    <div className="flex flex-col gap-6">
      <PageTitle right={<PeriodPicker range={range} period={period} onChange={setRange} />}>Spending</PageTitle>
      {error && <ErrorNote error={error} />}

      <Card className="p-4 md:p-5">
        <H2
          right={
            <span className="flex items-center gap-3 text-[11px] text-muted">
              <span className="flex items-center gap-1">
                <i className="inline-block h-1.5 w-3 rounded-full bg-accent" /> income
              </span>
              <span className="flex items-center gap-1">
                <i className="inline-block h-1.5 w-3 rounded-full bg-muted/50" /> spending
              </span>
            </span>
          }
        >
          Cash flow · {label}
        </H2>
        <Cashflow period={period} />
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card className="p-4 md:p-5">
          <H2 right={<span className="text-xs text-muted">{label}</span>}>Categories</H2>
          <Categories period={period} selected={selected} onSelect={setSelected} />
        </Card>

        <div className="flex flex-col gap-6">
          {selected && (
            <Card className="p-4 md:p-5">
              <H2
                right={
                  <button type="button" onClick={() => setSelected("")} className="text-xs text-muted hover:text-text">
                    close
                  </button>
                }
              >
                {shortAccount(selected)} · {label}
              </H2>
              <TxnList items={drill.data?.items} loading={drill.isFetching} error={drill.error} />
            </Card>
          )}
          <Card className="p-4 md:p-5">
            <H2>Recurring</H2>
            <Subscriptions />
          </Card>
        </div>
      </div>
    </div>
  );
}
