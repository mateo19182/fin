import { useState } from "react";
import { useStatus, type AccountStatus } from "../lib/api";
import { fmtDate } from "../lib/format";
import { SOURCE } from "../lib/labels";
import { Empty, ErrorNote, H2, Money, SkeletonRows } from "./ui";

const VIA: Record<AccountStatus["updates_via"], string> = { bank: "bank sync", wallet: "wallet", indexa: "Indexa", csv: "CSV", manual: "manual" };
const RECENT_DAYS = 90;

function Dot({ status, className = "" }: { status: AccountStatus["status"]; className?: string }) {
  const color = { ok: "bg-pos", warn: "bg-warn", error: "bg-neg" }[status];
  return <i className={`inline-block h-2 w-2 shrink-0 rounded-full ${color} ${className}`} aria-label={status} />;
}

/** Hide accounts that are empty and quiet: nothing to check there. */
export function relevant(rows: AccountStatus[], today = new Date()) {
  const cutoff = new Date(today.getTime() - RECENT_DAYS * 86_400_000).toISOString().slice(0, 10);
  const order = { error: 0, warn: 1, ok: 2 };
  return rows
    .filter((r) => Number(r.balance_eur) !== 0 || r.status !== "ok" || (r.last_txn ?? "") >= cutoff)
    .sort((a, b) => order[a.status] - order[b.status] || Math.abs(Number(b.balance_eur)) - Math.abs(Number(a.balance_eur)));
}

const name = (account: string) => account.split(":").slice(1).join(" · ");

function Row({ r }: { r: AccountStatus }) {
  const [open, setOpen] = useState(false);
  const via = r.updater && SOURCE[r.updater] ? `${VIA[r.updates_via]} · ${SOURCE[r.updater]}` : VIA[r.updates_via];
  const reasons = [
    r.stale_reason,
    r.balance_check && !r.balance_check.ok ? `balance check ${fmtDate(r.balance_check.date)} failed: ${r.balance_check.error ?? ""}` : null,
    r.balance_check?.ok ? `balance check ${fmtDate(r.balance_check.date)} ok` : null,
    Number(r.reconciled_30d) !== 0 ? `reconciled ${r.reconciled_30d} € in the last 30 days` : null,
  ].filter(Boolean) as string[];
  return (
    <li>
      <button type="button" onClick={() => setOpen((v) => !v)} className="flex w-full items-center gap-3 py-2.5 text-left">
        <Dot status={r.status} />
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm">{name(r.account)}</div>
          <div className="truncate text-xs text-muted">
            {via}
            {r.last_update ? ` · ${fmtDate(r.last_update)}` : " · never"}
          </div>
        </div>
        <Money value={Number(r.balance_eur)} round className="shrink-0 text-sm" />
      </button>
      {open && (
        <ul className="-mt-1 mb-2 ml-5 flex flex-col gap-0.5 text-xs text-muted">
          {reasons.length === 0 && <li>Fresh and reconciled</li>}
          {reasons.map((x) => (
            <li key={x} className={x.includes("failed") ? "text-neg" : x === r.stale_reason ? "text-warn" : ""}>{x}</li>
          ))}
        </ul>
      )}
    </li>
  );
}

export function StatusList() {
  const { data, isLoading, error } = useStatus();
  const rows = data ? relevant(data.accounts) : [];
  const c = data?.summary.accounts;
  return (
    <>
      <H2
        right={
          c && (
            <span className="text-xs text-muted">
              {c.ok} ok{c.warn > 0 && <> · <span className="text-warn">{c.warn} warn</span></>}
              {c.error > 0 && <> · <span className="text-neg">{c.error} error</span></>}
            </span>
          )
        }
      >
        Accounts
      </H2>
      {error && <ErrorNote error={error} />}
      {isLoading && <SkeletonRows n={5} />}
      {data && rows.length === 0 && <Empty>No accounts yet</Empty>}
      <ul className="divide-y divide-line">
        {rows.map((r) => (
          <Row key={r.account} r={r} />
        ))}
      </ul>
      {data && data.summary.banks_expiring.length > 0 && (
        <p className="mt-3 text-xs text-warn">
          {data.summary.banks_expiring.map((b) => `${b.name} session expires in ${b.days} day${b.days === 1 ? "" : "s"}`).join(" · ")}
        </p>
      )}
      {data && data.summary.ledger_errors > 0 && (
        <p className="mt-2 text-xs text-neg">{data.summary.ledger_errors} ledger error{data.summary.ledger_errors === 1 ? "" : "s"}</p>
      )}
    </>
  );
}
