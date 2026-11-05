import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { recategorize, useAccounts, useLedgerWrite, useTransactions, type Txn } from "../lib/api";
import { useDetailParam } from "../lib/detail";
import { fmtDate, leaf, monthRange, shiftMonth, thisMonth } from "../lib/format";
import { CategoryButton } from "../components/AccountPicker";
import { Button, Empty, ErrorNote, Money, PageTitle, SkeletonRows } from "../components/ui";

const PAGE = 100;

function TxnRow({ t }: { t: Txn }) {
  const m = useLedgerWrite((account: string) => recategorize(t.id, account));
  const { open } = useDetailParam();
  return (
    <li className="-mx-2 flex cursor-pointer items-center gap-3 rounded-lg px-2 py-2.5 hover:bg-line/40" onClick={() => open(t.id)}>
      <span className="w-12 shrink-0 text-xs text-muted">{fmtDate(t.date)}</span>
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm">
          {t.payee || t.narration}
          {t.narration && t.narration !== t.payee && t.payee && (
            <span className="text-muted"> · {t.narration}</span>
          )}
        </div>
        <div className="flex items-center gap-1.5" onClick={(e) => e.stopPropagation()}>
          <CategoryButton account={t.account} onChange={(a) => m.mutate(a)} busy={m.isPending} />
          {t.auto && <span className="text-[10px] uppercase tracking-wide text-muted/70">auto</span>}
        </div>
        {m.error && <ErrorNote error={m.error} />}
      </div>
      <Money value={t.amount} tone="auto" className="shrink-0 text-sm" />
    </li>
  );
}

export function TxnList({ items, loading, error }: { items?: Txn[]; loading: boolean; error: unknown }) {
  if (error) return <ErrorNote error={error} />;
  if (loading && !items) return <SkeletonRows n={8} />;
  if (!items?.length) return <Empty>No transactions</Empty>;
  return (
    <ul className={`divide-y divide-line ${loading ? "opacity-60" : ""}`}>
      {items.map((t) => (
        <TxnRow key={t.id} t={t} />
      ))}
    </ul>
  );
}

export function Transactions() {
  const [sp, setSp] = useSearchParams();
  const month = sp.get("month") ?? "";
  const cat = sp.get("cat") ?? "";
  const bank = sp.get("bank") ?? "";
  const [q, setQ] = useState(sp.get("q") ?? "");
  const [limit, setLimit] = useState(PAGE);
  const { data: accounts = [] } = useAccounts();

  const set = (k: string, v: string) => {
    const n = new URLSearchParams(sp);
    v ? n.set(k, v) : n.delete(k);
    setSp(n, { replace: true });
    setLimit(PAGE);
  };

  const cats = useMemo(
    () => [...new Set(accounts.filter((a) => /^(Expenses|Income):/.test(a)).map((a) => a.split(":").slice(0, 2).join(":")))],
    [accounts],
  );
  const banks = useMemo(() => accounts.filter((a) => /^Assets:(Bank|Cash):/.test(a)), [accounts]);

  const [start, end] = month ? monthRange(month) : [undefined, undefined];
  const account = cat || bank || undefined;
  const query = useTransactions({ start, end, account, q: q || undefined, limit });
  const both = cat && bank;
  const items = both ? query.data?.items.filter((t) => t.accounts.some((a) => a.startsWith(bank))) : query.data?.items;

  return (
    <div className="flex flex-col gap-4">
      <PageTitle right={query.data && <span className="num text-sm text-muted">{query.data.total}</span>}>
        Transactions
      </PageTitle>

      <div className="flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-1">
          <Button variant="ghost" onClick={() => set("month", shiftMonth(month || thisMonth(), -1))} title="Previous month">
            ‹
          </Button>
          <input type="month" value={month} onChange={(e) => set("month", e.target.value)} className="num" aria-label="Month" />
          <Button variant="ghost" onClick={() => set("month", shiftMonth(month || thisMonth(), 1))} title="Next month">
            ›
          </Button>
        </div>
        <div className="flex min-w-0 flex-1 basis-full gap-2 sm:basis-auto">
          <select value={cat} onChange={(e) => set("cat", e.target.value)} aria-label="Category" className="min-w-0 flex-1">
            <option value="">All categories</option>
            {cats.map((c) => (
              <option key={c} value={c}>
                {c.startsWith("Income") ? `↑ ${leaf(c)}` : leaf(c)}
              </option>
            ))}
          </select>
          {banks.length > 1 && (
            <select value={bank} onChange={(e) => set("bank", e.target.value)} aria-label="Account" className="min-w-0 flex-1">
              <option value="">All accounts</option>
              {banks.map((b) => (
                <option key={b} value={b}>
                  {b.split(":").slice(2).join(" ")}
                </option>
              ))}
            </select>
          )}
        </div>
        <input
          type="search"
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setLimit(PAGE);
          }}
          placeholder="Search…"
          className="min-w-0 flex-1 basis-40"
        />
      </div>

      <TxnList items={items} loading={query.isFetching} error={query.error} />
      {query.data && query.data.total > limit && (
        <Button className="self-center" onClick={() => setLimit((l) => l + PAGE)}>
          Show more
        </Button>
      )}
    </div>
  );
}
