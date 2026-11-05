import { Link } from "react-router-dom";
import { Area, AreaChart, ResponsiveContainer, Tooltip, YAxis } from "recharts";
import { useClose, useNetWorthMonths, useOverview, useStatus, type Totals } from "../lib/api";
import { fmtDate, fmtEur, fmtMonth, fmtMonthLong, fmtPct, fmtPeriod, leaf } from "../lib/format";
import { usePeriod } from "../lib/period";
import { PeriodPicker } from "../components/PeriodPicker";
import { GroupArea, NW_GROUPS, toRows } from "../components/NetWorthHistory";
import { relevant } from "../components/StatusList";
import { Bar, Card, Delta, Empty, ErrorNote, H2, Money, Rows, Skeleton, SkeletonRows, Tip } from "../components/ui";
import { defaultCloseMonth } from "./Close";

function TotalArea({ series }: { series: { date: string; total: number }[] }) {
  return (
    <ResponsiveContainer>
      <AreaChart data={series} margin={{ top: 4, right: 0, bottom: 0, left: 0 }}>
        <defs>
          <linearGradient id="nw" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--accent)" stopOpacity={0.25} />
            <stop offset="100%" stopColor="var(--accent)" stopOpacity={0} />
          </linearGradient>
        </defs>
        <YAxis hide domain={["dataMin - 2000", "dataMax + 2000"]} />
        <Tooltip
          cursor={{ stroke: "var(--line)" }}
          content={({ payload }) => {
            const p = payload?.[0]?.payload;
            if (!p) return null;
            return (
              <div className="rounded-lg border border-line bg-surface px-2.5 py-1.5 text-xs shadow">
                <div className="text-muted">{fmtDate(p.date, true)}</div>
                <div className="money num font-medium">{fmtEur(p.total, { round: true })}</div>
              </div>
            );
          }}
        />
        <Area type="monotone" dataKey="total" stroke="var(--accent)" strokeWidth={2} fill="url(#nw)" dot={false} activeDot={{ r: 4, strokeWidth: 0 }} isAnimationActive={false} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

function Notice({ to, children, tone = "line" }: { to: string; children: React.ReactNode; tone?: "accent" | "warn" | "line" }) {
  const cls = {
    warn: "border-warn/40 bg-warn/10 text-warn hover:border-warn",
    accent: "border-accent/40 bg-accent-soft text-accent hover:border-accent",
    line: "border-line hover:border-accent hover:text-accent",
  }[tone];
  return (
    <Link to={to} className={`flex items-center justify-between rounded-xl border px-4 py-3 text-sm ${cls}`}>
      <span>{children}</span>
      <span aria-hidden>→</span>
    </Link>
  );
}

function Notices({ pending }: { pending: number }) {
  const month = defaultCloseMonth();
  const close = useClose(month);
  const status = useStatus();
  const issues = status.data ? relevant(status.data.accounts).filter((a) => a.status !== "ok").length : 0;
  const todo = close.data ? close.data.checklist.filter((i) => !i.ok).length : null;
  return (
    <div className="flex flex-col gap-3">
      {pending > 0 && (
        <Notice to="/review" tone="accent">
          <strong className="font-semibold">{pending}</strong> to review
        </Notice>
      )}
      {issues > 0 && (
        <Notice to="/sources" tone="warn">
          <strong className="font-semibold">{issues}</strong> account{issues === 1 ? "" : "s"} need attention
        </Notice>
      )}
      {todo !== null && todo > 0 && (
        <Notice to={`/close?month=${month}`}>
          Close {fmtMonthLong(month)}
          <span className="text-muted"> · {todo} to do</span>
        </Notice>
      )}
    </div>
  );
}

const STATS: { key: keyof Totals; label: string; good: "up" | "down" }[] = [
  { key: "income", label: "Income", good: "up" },
  { key: "expenses", label: "Spent", good: "down" },
  { key: "savings", label: "Saved", good: "up" },
];

const eur = (v: number | null | undefined) => (v === null || v === undefined ? "—" : fmtEur(v, { round: true }));

export function Overview() {
  const { range, setRange, period, error: perr } = usePeriod("1m");
  const { data, isLoading, error } = useOverview(period);
  const history = useNetWorthMonths(period && { start: period.start, end: period.end, months: period.months });

  const picker = <PeriodPicker range={range} period={period} onChange={setRange} />;
  if (error || perr) return <ErrorNote error={error ?? perr} />;
  if (isLoading || !data || !period)
    return (
      <div className="flex flex-col gap-6">
        {picker}
        <Skeleton className="h-12 w-56" />
        <Skeleton className="h-28 w-full" />
        <SkeletonRows n={4} />
      </div>
    );

  const nw = data.net_worth;
  const series = data.series;
  const multiYear = period.start.slice(0, 4) !== period.end.slice(0, 4);
  const axis = (d: string) => (period.months > 12 ? fmtMonth(d.slice(0, 7), true) : fmtDate(d, multiYear));
  const label = fmtPeriod(period.start, period.end);
  const cats = data.categories.filter((c) => c.total > 0).slice(0, 5);
  const max = Math.max(1, ...cats.map((c) => c.total));
  const rows = history.data ? toRows(history.data) : [];
  const stacked = rows.length > 2; // one month: the daily total line says more than two stacked points
  const t = data.totals;
  const rate = t.income > 0 ? Math.round((t.savings / t.income) * 100) : null;
  const groups = NW_GROUPS.filter((g) => nw.groups[g.key] !== 0).map((g) => [g.label, eur(nw.groups[g.key])] as [string, string]);

  return (
    <div className="flex flex-col gap-8">
      {picker}

      <section>
        <Tip content={<Rows rows={groups} />}>
          <span className="text-sm text-muted">Net worth</span>
        </Tip>
        <div className="mt-1 flex flex-wrap items-baseline gap-x-4 gap-y-1">
          <Money value={nw.total} round className="text-4xl font-semibold tracking-tight md:text-5xl" />
          <Tip content={<Rows rows={[["Since", fmtDate(series[0].date, true)], ["Change", nw.change_pct === null ? "—" : fmtPct(nw.change_pct)]]} />}>
            <Money value={nw.change} round sign tone="auto" className="text-sm" />
          </Tip>
        </div>
        <div className="mt-4 h-28 md:h-36">
          {history.error ? (
            <ErrorNote error={history.error} />
          ) : stacked ? (
            <GroupArea rows={rows} />
          ) : history.isLoading ? (
            <Skeleton className="h-full w-full" />
          ) : series.length > 1 ? (
            <TotalArea series={series} />
          ) : (
            <Empty>No history yet</Empty>
          )}
        </div>
        <div className="mt-1 flex justify-between text-[11px] text-muted">
          <span>{axis(series[0].date)}</span>
          <span>{axis(series[series.length - 1].date)}</span>
        </div>
      </section>

      <Notices pending={data.pending} />

      <Card className="p-4 md:p-5">
        <H2>{label}</H2>
        <dl className="grid grid-cols-3 gap-4">
          {STATS.map((s) => (
            <div key={s.key}>
              <dt className="text-xs text-muted">
                <Tip
                  content={
                    <Rows
                      rows={[
                        ["Previous period", eur(t.prev?.[s.key])],
                        ["Same period last year", eur(t.yoy?.[s.key])],
                        ...(s.key === "savings" ? [["Savings rate", rate === null ? "—" : fmtPct(rate, false)] as [string, string]] : []),
                      ]}
                    />
                  }
                >
                  {s.label}
                </Tip>
              </dt>
              <dd className="flex flex-col">
                <Money value={t[s.key]} round tone={s.key === "savings" ? "auto" : "none"} className="text-lg font-medium md:text-xl" />
                <Delta value={t[s.key]} base={t.prev?.[s.key]} good={s.good} />
              </dd>
            </div>
          ))}
        </dl>
      </Card>

      <Card className="p-4 md:p-5">
        <H2 right={<Link to={`/spending?range=${range}`} className="text-xs font-medium text-accent hover:underline">All →</Link>}>Top spending</H2>
        {cats.length === 0 ? (
          <Empty>Nothing spent yet</Empty>
        ) : (
          <ul className="flex flex-col gap-3">
            {cats.map((c) => (
              <li key={c.account}>
                <div className="mb-1 flex items-baseline justify-between gap-3 text-sm">
                  <Link to={`/spending?range=${range}&cat=${encodeURIComponent(c.account)}`} className="truncate hover:text-accent">
                    {leaf(c.account)}
                  </Link>
                  <span className="flex shrink-0 items-baseline gap-2">
                    {c.prev ? (
                      <Tip content={<Rows rows={[["Previous period", eur(c.prev)], ["Last year", eur(c.yoy)]]} />}>
                        <Delta value={c.total} base={c.prev} good="down" label="" />
                      </Tip>
                    ) : null}
                    <Money value={c.total} round className="font-medium" />
                  </span>
                </div>
                <Bar value={c.total} max={max} />
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
