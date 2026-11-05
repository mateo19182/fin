import { Link, useSearchParams } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { setDeductible, useClose, useQuarter, type CheckItem, type CloseStats, type DeductRow, type Deductions } from "../lib/api";
import { useDetailParam } from "../lib/detail";
import { fmtDate, fmtEur, fmtMonthLong, fmtPct, leaf, shiftMonth, shortAccount, thisMonth } from "../lib/format";
import { SavingsStatementImport, StocksImport } from "../components/Imports";
import { Bar, Button, Card, Empty, ErrorNote, H2, Money, PageTitle, Rows, Skeleton, SkeletonRows, Tip, Trend } from "../components/ui";

// The month to close is the last finished one: "covers month end" checks cannot pass before.
export const defaultCloseMonth = () => shiftMonth(thisMonth(), -1);

const CHECK: Record<CheckItem["key"], { label: string; to?: string }> = {
  pending: { label: "Review pending", to: "/review" },
  stocks_csv: { label: "Revolut Invest CSV" },
  savings_csv: { label: "Savings statement" },
  balances: { label: "Balances OK", to: "/sources" },
  banks: { label: "Banks synced", to: "/sources" },
};
const ORDER = Object.keys(CHECK) as CheckItem["key"][];
const n = (x: string) => Number(x);
const eur = (x: string | number) => fmtEur(Number(x), { round: true });
const signed = (x: string | number) => fmtEur(Number(x), { round: true, sign: true });

function Check({ item }: { item: CheckItem }) {
  const c = CHECK[item.key];
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-2 py-2.5">
      <span
        className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full border ${item.ok ? "border-accent bg-accent text-white" : "border-line"}`}
        aria-label={item.ok ? "done" : "to do"}
      >
        {item.ok && (
          <svg viewBox="0 0 24 24" className="h-3 w-3" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12l4 4L19 6" /></svg>
        )}
      </span>
      <span className={`min-w-0 flex-1 text-sm ${item.ok ? "text-muted" : "font-medium"}`}>
        <Tip content={item.detail}>{c.label}</Tip>
      </span>
      {item.key === "stocks_csv" && <StocksImport />}
      {item.key === "savings_csv" && <SavingsStatementImport />}
      {!item.ok && c.to && (
        <Link to={c.to} className="text-xs font-medium text-accent hover:underline">
          Open →
        </Link>
      )}
    </li>
  );
}

// Meaningless when spending dwarfs income (e.g. the salary is not in yet).
const rate = (r: number | null) => (r === null || r < -1 ? "—" : fmtPct(Math.round(r * 100), false));

function Stats({ s }: { s: CloseStats }) {
  const nw = s.net_worth;
  const cats = s.top_categories.slice(0, 5);
  const max = Math.max(1, ...cats.map((c) => n(c.amount)));
  return (
    <>
      <Card className="p-4 md:p-5">
        <dl className="grid grid-cols-2 gap-x-4 gap-y-4 sm:grid-cols-4">
          <div>
            <dt className="text-xs text-muted">
              <Tip content={<Rows rows={Object.entries(s.income_by_account).map(([a, v]) => [shortAccount(a), eur(v)])} />}>Income</Tip>
            </dt>
            <dd><Money value={n(s.income)} round className="text-lg font-medium" /></dd>
          </div>
          <div>
            <dt className="text-xs text-muted">
              <Tip content={<Rows rows={[["Per day", eur(s.avg_daily_spend)], ["Expenses", `${s.expense_transactions} of ${s.transactions} entries`]]} />}>Spent</Tip>
            </dt>
            <dd><Money value={n(s.expenses)} round className="text-lg font-medium" /></dd>
          </div>
          <div>
            <dt className="text-xs text-muted">
              <Tip content={<Rows rows={[["Savings rate", rate(s.savings_rate)], ["Previous month", rate(s.prev_savings_rate)]]} />}>Saved</Tip>
            </dt>
            <dd><Money value={n(s.income) - n(s.expenses)} round tone="auto" className="text-lg font-medium" /></dd>
          </div>
          <div>
            <dt className="text-xs text-muted">
              <Tip content={<Rows rows={[["Saved", signed(nw.saved)], ["Invested", signed(nw.contributions)], ["Market", signed(nw.market)], ["Total now", eur(nw.total)]]} />}>
                Net worth
              </Tip>
            </dt>
            <dd><Money value={n(nw.change)} round sign tone="auto" className="text-lg font-medium" /></dd>
          </div>
        </dl>
      </Card>

      <Card className="p-4 md:p-5">
        <H2 right={<span className="text-[11px] text-muted">arrow: vs 6-month average</span>}>Top categories</H2>
        {cats.length === 0 ? (
          <Empty>Nothing spent</Empty>
        ) : (
          <ul className="flex flex-col gap-3">
            {cats.map((c) => (
              <li key={c.account}>
                <div className="mb-1 flex items-baseline justify-between gap-3 text-sm">
                  <span className="flex min-w-0 items-baseline gap-2">
                    <Link to={`/transactions?month=${s.month}&cat=${encodeURIComponent(c.account)}`} className="truncate hover:text-accent">
                      {leaf(c.account)}
                    </Link>
                    <Trend value={n(c.amount)} base={n(c.avg6)} />
                  </span>
                  <Tip
                    content={
                      <Rows
                        rows={[
                          ["Previous month", `${eur(c.prev)} (${signed(c.vs_prev)})`],
                          ["6-month average", `${eur(c.avg6)}${c.vs_avg6_pct === null ? "" : ` (${fmtPct(c.vs_avg6_pct)})`}`],
                        ]}
                      />
                    }
                  >
                    <Money value={n(c.amount)} round className="font-medium" />
                  </Tip>
                </div>
                <Bar value={n(c.amount)} max={max} />
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Details s={s} />
    </>
  );
}

function Details({ s }: { s: CloseStats }) {
  const { open } = useDetailParam();
  return (
    <details className="group rounded-xl border border-line bg-surface">
      <summary className="cursor-pointer select-none px-4 py-3 text-sm font-medium text-muted hover:text-text md:px-5">
        Details
      </summary>
      <div className="grid gap-6 border-t border-line p-4 md:grid-cols-2 md:p-5">
        <div>
          <H2>Top payees</H2>
          {s.top_payees.length === 0 && <Empty>None</Empty>}
          <ul className="divide-y divide-line">
            {s.top_payees.map((p) => (
              <li key={p.payee} className="flex items-center justify-between gap-3 py-2 text-sm">
                <Link to={`/transactions?month=${s.month}&q=${encodeURIComponent(p.payee)}`} className="truncate hover:text-accent">{p.payee}</Link>
                <Money value={n(p.amount)} round className="shrink-0" />
              </li>
            ))}
          </ul>
        </div>
        <div>
          <H2>Biggest expenses</H2>
          {s.biggest_expenses.length === 0 && <Empty>None</Empty>}
          <ul className="divide-y divide-line">
            {s.biggest_expenses.map((b) => (
              <li key={b.id}>
                <button type="button" onClick={() => open(b.id)} className="flex w-full items-center gap-3 py-2 text-left text-sm hover:text-accent">
                  <span className="w-12 shrink-0 text-xs text-muted">{fmtDate(b.date)}</span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate">{b.payee || "—"}</span>
                    <span className="block truncate text-xs text-muted">{leaf(b.account)}</span>
                  </span>
                  <Money value={n(b.amount)} round className="shrink-0" />
                </button>
              </li>
            ))}
          </ul>
        </div>
        <div className="md:col-span-2">
          <H2>Notes</H2>
          <ul className="flex flex-col gap-1.5 text-sm">
            {s.insights.map((i) => (
              <li key={i} className="flex gap-2">
                <span className="text-muted" aria-hidden>–</span>
                <span className="money">{i}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </details>
  );
}

/** Shown only when a quarter just ended or a 303/130 deadline is near. */
function DeductRowItem({ r, children }: { r: DeductRow; children?: React.ReactNode }) {
  const { open } = useDetailParam();
  return (
    <li className="flex items-center gap-3 py-2 text-sm">
      <button type="button" onClick={() => open(r.id)} className="min-w-0 flex-1 truncate text-left hover:text-accent">
        <span className="num text-xs text-muted">{fmtDate(r.date)}</span> {r.payee}
      </button>
      <Money value={n(r.amount)} className="text-sm" />
      {children}
    </li>
  );
}

function Deduct({ d }: { d: Deductions }) {
  const qc = useQueryClient();
  const m = useMutation({
    mutationFn: ({ id, on }: { id: string; on: boolean }) => setDeductible(id, on),
    onSuccess: () => qc.invalidateQueries({ predicate: (q) => ["close", "quarter", "detail"].includes(q.queryKey[0] as string) }),
  });
  if (!d.deducted.length && !d.needs_receipt.length && !d.maybe.length) return null;
  return (
    <Card className="p-4 md:p-5">
      <H2
        right={
          <Tip content={<Rows rows={d.deducted.map((x) => [`${fmtDate(x.date)} ${x.payee}`, eur(x.base)] as [string, string])} />}>
            <span className="num text-xs text-muted">
              {d.deducted.length} deducted · {eur(d.base)} + IVA {eur(d.iva)}
            </span>
          </Tip>
        }
      >
        To deduct
      </H2>
      {d.needs_receipt.length > 0 && (
        <>
          <div className="mt-1 text-xs text-muted">Needs a receipt (tap to attach)</div>
          <ul className="divide-y divide-line">{d.needs_receipt.map((r) => <DeductRowItem key={r.id} r={r} />)}</ul>
        </>
      )}
      {d.maybe.length > 0 && (
        <>
          <div className="mt-3 text-xs text-muted">Work expense?</div>
          <ul className="divide-y divide-line">
            {d.maybe.map((r) => (
              <DeductRowItem key={r.id} r={r}>
                <Button variant="ghost" disabled={m.isPending} onClick={() => m.mutate({ id: r.id, on: true })}>Yes</Button>
                <Button variant="ghost" disabled={m.isPending} onClick={() => m.mutate({ id: r.id, on: false })}>No</Button>
              </DeductRowItem>
            ))}
          </ul>
        </>
      )}
      {m.error && <ErrorNote error={m.error} />}
    </Card>
  );
}

function QuarterCard() {
  const { data: q } = useQuarter();
  const { open } = useDetailParam();
  if (!q || !q.show_card) return null;
  const due = q.days_to_deadline;
  const paid = q.payments.find((p) => p.form === "303");
  return (
    <Card className="p-4 md:p-5">
      <H2 right={!paid && <span className={`num text-xs ${due >= 0 && due <= 7 ? "text-neg" : "text-muted"}`}>{due < 0 ? `was due ${fmtDate(q.deadline)}` : `due ${fmtDate(q.deadline)} · ${due} d`}</span>}>
        Quarter {q.period}
      </H2>
      <div className="text-xs text-muted">303 IVA</div>
      <Tip content={<Rows rows={[["Ledger estimate", `${eur(q.modelo_303.resultado)} ${q.modelo_303.sentido}`]]} />}>
        <Money value={Number(paid ? paid.amount : q.modelo_303.resultado)} className="text-lg font-medium" />
      </Tip>{" "}
      <span className="text-xs text-muted">{paid ? "paid" : q.modelo_303.sentido}</span>
      {q.open_decisions.length > 0 && (
        <ul className="mt-3 border-t border-line pt-3 text-xs text-muted">
          {q.open_decisions.map((o) => (
            <li key={o.id}>
              <button type="button" onClick={() => open(o.id)} className="hover:text-accent">
                AEAT payment {fmtDate(o.date)} {eur(o.amount)} — classify as 303 or 130
              </button>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

export function Close() {
  const [sp, setSp] = useSearchParams();
  const month = /^\d{4}-\d{2}$/.test(sp.get("month") ?? "") ? sp.get("month")! : defaultCloseMonth();
  const setMonth = (m: string) => {
    const next = new URLSearchParams(sp);
    next.set("month", m);
    setSp(next, { replace: true });
  };
  const { data, isLoading, error } = useClose(month);
  const todo = data?.checklist.filter((i) => !i.ok).length ?? 0;

  return (
    <div className="flex flex-col gap-6">
      <PageTitle
        right={
          <div className="flex items-center gap-1">
            <Button variant="ghost" onClick={() => setMonth(shiftMonth(month, -1))} title="Previous month">‹</Button>
            <input type="month" value={month} max={thisMonth()} onChange={(e) => e.target.value && setMonth(e.target.value)} className="num" aria-label="Month" />
            <Button variant="ghost" onClick={() => setMonth(shiftMonth(month, 1))} disabled={month >= thisMonth()} title="Next month">›</Button>
          </div>
        }
      >
        {fmtMonthLong(month)}
      </PageTitle>

      {error && <ErrorNote error={error} />}

      <QuarterCard />

      <Card className="p-4 md:p-5">
        <H2 right={data && <span className="num text-xs text-muted">{todo === 0 ? "all done" : `${todo} to do`}</span>}>To do this month</H2>
        {isLoading && !data && <SkeletonRows n={5} />}
        <ul className="divide-y divide-line">
          {data?.checklist
            .slice()
            .sort((a, b) => ORDER.indexOf(a.key) - ORDER.indexOf(b.key))
            .map((i) => <Check key={i.key} item={i} />)}
        </ul>
      </Card>

      {isLoading && !data && <Skeleton className="h-28 w-full" />}
      {data && <Deduct d={data.deductions} />}
      {data && <Stats s={data.stats} />}
    </div>
  );
}
