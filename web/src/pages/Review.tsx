import { useState } from "react";
import { approvePending, dismissPending, recategorize, useLedgerWrite, usePending, useRecentAuto, type Pending } from "../lib/api";
import { useDetailParam } from "../lib/detail";
import { fmtDate, shortAccount } from "../lib/format";
import { sourceLabel } from "../lib/labels";
import { AccountPicker, CategoryButton } from "../components/AccountPicker";
import { Button, Card, Chip, Empty, ErrorNote, H2, Money, PageTitle, SkeletonRows } from "../components/ui";

function PendingCard({ item }: { item: Pending }) {
  const [picking, setPicking] = useState(false);
  const [hidden, setHidden] = useState(false);
  const approve = useLedgerWrite((account: string) => approvePending(item.external_id, account));
  const dismiss = useLedgerWrite((_: string) => dismissPending(item.external_id));
  const busy = approve.isPending || dismiss.isPending;
  const amount = Number(item.amount);

  if (hidden) return null;
  const run = (m: typeof approve, v: string) =>
    m.mutate(v, { onSuccess: () => setHidden(true) });

  return (
    <Card className={`p-4 transition ${busy ? "opacity-60" : ""}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate font-medium">{item.payee || item.narration || "—"}</div>
          <div className="truncate text-xs text-muted">
            {fmtDate(item.date)} · {sourceLabel(item.source)}
            {item.narration && item.narration !== item.payee && ` · ${item.narration}`}
          </div>
        </div>
        <Money value={amount} tone="auto" className="shrink-0 text-base font-medium" />
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {item.suggestions.slice(0, 3).map((s) => (
          <Chip key={s.account} onClick={() => run(approve, s.account)}>
            {shortAccount(s.account)}
            <span className="ml-1.5 text-muted">{Math.round(s.p * 100)}%</span>
          </Chip>
        ))}
        <span className="relative">
          <Chip onClick={() => setPicking(true)}>Other…</Chip>
          {picking && (
            <AccountPicker
              onClose={() => setPicking(false)}
              onPick={(a) => {
                setPicking(false);
                run(approve, a);
              }}
            />
          )}
        </span>
        <Button variant="ghost" className="ml-auto" onClick={() => run(dismiss, "")} disabled={busy}>
          Dismiss
        </Button>
      </div>
      {(approve.error || dismiss.error) && (
        <div className="mt-2">
          <ErrorNote error={approve.error ?? dismiss.error} />
        </div>
      )}
    </Card>
  );
}

function AutoRow({ t }: { t: { id: string; date: string; payee: string; amount: number; account: string; auto: string | null } }) {
  const m = useLedgerWrite((account: string) => recategorize(t.id, account));
  const { open } = useDetailParam();
  return (
    <li className="-mx-2 flex cursor-pointer items-center gap-3 rounded-lg px-2 py-2.5 hover:bg-line/40" onClick={() => open(t.id)}>
      <span className="w-12 shrink-0 text-xs text-muted">{fmtDate(t.date)}</span>
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm">{t.payee}</div>
        <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
          <CategoryButton account={t.account} onChange={(a) => m.mutate(a)} busy={m.isPending} />
          {t.auto && <span className="text-[10px] uppercase tracking-wide text-muted/70">{t.auto}</span>}
        </div>
        {m.error && <ErrorNote error={m.error} />}
      </div>
      <Money value={t.amount} tone="auto" className="shrink-0 text-sm" />
    </li>
  );
}

export function Review() {
  const pending = usePending();
  const auto = useRecentAuto(30);

  return (
    <div className="flex flex-col gap-8">
      <section>
        <PageTitle
          right={pending.data && <span className="text-sm text-muted">{pending.data.length} pending</span>}
        >
          Review
        </PageTitle>
        {pending.error && <ErrorNote error={pending.error} />}
        {pending.isLoading && <SkeletonRows n={3} />}
        {pending.data && pending.data.length === 0 && <Empty>All reviewed</Empty>}
        <div className="flex flex-col gap-3">
          {pending.data?.map((p) => (
            <PendingCard key={p.external_id} item={p} />
          ))}
        </div>
      </section>

      <Card className="p-4 md:p-5">
        <H2>Auto-booked (30 days)</H2>
        {auto.error && <ErrorNote error={auto.error} />}
        {auto.isLoading && <SkeletonRows n={4} />}
        {auto.data && auto.data.length === 0 && <Empty>None yet</Empty>}
        <ul className="divide-y divide-line">
          {auto.data?.map((t) => (
            <AutoRow key={t.id} t={t} />
          ))}
        </ul>
      </Card>
    </div>
  );
}
