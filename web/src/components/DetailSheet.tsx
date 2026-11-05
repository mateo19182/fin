import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { addRule, attachDocument, documentUrl, recategorize, setDeductible, updateDetail, useDetail, useLedgerWrite, type Detail } from "../lib/api";
import { escapeRegex, useDetailParam } from "../lib/detail";
import { fmtDate, shortAccount } from "../lib/format";
import { sourceLabel } from "../lib/labels";
import { CategoryButton } from "./AccountPicker";
import { Button, ErrorNote, Money, Skeleton, Toggle } from "./ui";

const CATEGORY = /^(Expenses|Income):/;
const OWN = /^(Assets|Liabilities):/;

/** Borderless text that saves on blur / Enter when changed. */
function Field({ label, value, onSave, busy }: { label: string; value: string; onSave: (v: string) => void; busy: boolean }) {
  const [v, setV] = useState(value);
  useEffect(() => setV(value), [value]);
  const commit = () => v.trim() !== value && onSave(v.trim());
  return (
    <label className="block">
      <span className="text-xs text-muted">{label}</span>
      <input
        type="text"
        value={v}
        disabled={busy}
        onChange={(e) => setV(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
        placeholder="—"
        className="!min-h-8 w-full !rounded-md !border-transparent !bg-transparent !px-0 !py-0.5 text-sm hover:!border-line focus:!border-line focus:!bg-surface focus:!px-2"
      />
    </label>
  );
}

function RuleForm({ d, account, onDone }: { d: Detail; account: string; onDone: (added: boolean) => void }) {
  const qc = useQueryClient();
  const [match, setMatch] = useState(`^${escapeRegex(d.payee || d.narration || "")}$`);
  const m = useMutation({
    mutationFn: () => addRule({ match, account }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["rules"] });
      onDone(true);
    },
  });
  return (
    <form
      className="flex flex-col gap-2 rounded-lg bg-bg p-3 text-sm"
      onSubmit={(e) => {
        e.preventDefault();
        m.mutate();
      }}
    >
      <p className="text-xs text-muted">
        New transactions whose payee or bank text matches this pattern will be booked to{" "}
        <span className="text-text">{shortAccount(account)}</span> without review.
      </p>
      <input type="text" value={match} onChange={(e) => setMatch(e.target.value)} className="num w-full font-mono text-xs" aria-label="Pattern" required />
      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={() => onDone(false)}>Cancel</Button>
        <Button type="submit" variant="primary" disabled={m.isPending || !match}>Add rule</Button>
      </div>
      {m.error && <ErrorNote error={m.error} />}
    </form>
  );
}

/** Autónomo deductibility: switch plus a % field when the share is partial. */
function DeductibleRow({ d }: { d: Detail }) {
  const qc = useQueryClient();
  const dd = d.deductible;
  const [pct, setPct] = useState(String(dd.pct || 100));
  useEffect(() => setPct(String(dd.pct || 100)), [dd.pct]);
  const m = useMutation({
    mutationFn: ({ on, p }: { on: boolean; p?: number }) => setDeductible(d.id, on, p),
    onSuccess: (next) => {
      qc.setQueryData(["detail", d.id], next);
      qc.invalidateQueries({ queryKey: ["quarter"] });
    },
  });
  const hint = dd.iva_blocked ? "IRPF only: attach the invoice for the IVA" : dd.reason === "rule" ? "payee rule" : dd.vat ? `vat ${dd.vat}` : null;
  return (
    <>
      <dt className="text-muted">Deductible</dt>
      <dd className="flex min-w-0 items-center gap-2">
        <Toggle on={dd.on} disabled={m.isPending} label="Deductible" onChange={(on) => m.mutate({ on, p: on ? Number(pct) : undefined })} />
        {dd.on && (
          <span className="flex items-center gap-1 text-xs text-muted">
            <input
              type="number"
              min={1}
              max={100}
              value={pct}
              disabled={m.isPending}
              onChange={(e) => setPct(e.target.value)}
              onBlur={() => Number(pct) !== dd.pct && Number(pct) >= 1 && Number(pct) <= 100 && m.mutate({ on: true, p: Number(pct) })}
              className="num !min-h-6 w-14 !rounded-md !px-1.5 !py-0 text-xs"
              aria-label="Deductible percent"
            />
            %{dd.equipment && " · equipment"}
          </span>
        )}
        {hint && <span className="truncate text-xs text-muted">{hint}</span>}
        {m.error && <ErrorNote error={m.error} />}
      </dd>
    </>
  );
}

function Body({ d }: { d: Detail }) {
  const qc = useQueryClient();
  const [ruling, setRuling] = useState(false);
  const [ruled, setRuled] = useState(false);
  const cats = d.postings.filter((p) => CATEGORY.test(p.account));
  const own = d.postings.find((p) => OWN.test(p.account));
  const main = own ?? cats[0] ?? d.postings[0];
  const amount = main === own ? Number(main.amount) : -Number(main.amount);
  const category = cats.length === 1 ? cats[0].account : null;

  const edit = useMutation({
    mutationFn: (body: Parameters<typeof updateDetail>[1]) => updateDetail(d.id, body),
    onSuccess: (next) => {
      qc.setQueryData(["detail", d.id], next);
      qc.invalidateQueries({ predicate: (q) => q.queryKey[0] !== "detail" });
    },
  });
  const recat = useLedgerWrite((account: string) => recategorize(d.id, account));
  const attach = useMutation({
    mutationFn: (f: File) => attachDocument(d.id, f),
    onSuccess: (next) => qc.setQueryData(["detail", d.id], next),
  });
  const busy = edit.isPending;
  const source = sourceLabel(d.meta.source);
  const how = d.meta.auto ? `auto · ${d.meta.auto}` : d.meta.source ? "reviewed" : null;

  return (
    <div className="flex flex-col gap-5">
      <div>
        <div className="text-sm text-muted">{fmtDate(d.date, true)}</div>
        {main.currency === "EUR" || !main.currency ? (
          <Money value={amount} tone="auto" className="text-3xl font-semibold tracking-tight" />
        ) : (
          <span className={`money num text-3xl font-semibold tracking-tight ${amount > 0 ? "text-pos" : "text-neg"}`}>
            {amount} {main.currency}
          </span>
        )}
      </div>

      <div className="flex flex-col gap-3">
        <Field label="Payee" value={d.payee ?? ""} busy={busy} onSave={(payee) => edit.mutate({ payee })} />
        <Field label="Description" value={d.narration ?? ""} busy={busy} onSave={(narration) => edit.mutate({ narration })} />
        <Field label="Note" value={d.meta.note ?? ""} busy={busy} onSave={(note) => edit.mutate({ note })} />
        {edit.error && <ErrorNote error={edit.error} />}
      </div>

      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
        {category && (
          <>
            <dt className="text-muted">Category</dt>
            <dd className="-ml-1.5 min-w-0">
              <CategoryButton account={category} onChange={(a) => recat.mutate(a)} busy={recat.isPending} className="!text-sm !text-text" />
              {recat.error && <ErrorNote error={recat.error} />}
            </dd>
          </>
        )}
        {own && (
          <>
            <dt className="text-muted">Account</dt>
            <dd className="truncate">{shortAccount(own.account)}</dd>
          </>
        )}
        <dt className="text-muted">Source</dt>
        <dd className="truncate">
          {source}
          {how && <span className="text-muted"> · {how}</span>}
        </dd>
        {amount < 0 && category?.startsWith("Expenses:") && <DeductibleRow d={d} />}
        {d.meta.bank_payee && (
          <>
            <dt className="text-muted">Bank text</dt>
            <dd className="break-words text-muted">{d.meta.bank_payee}</dd>
          </>
        )}
      </dl>

      {d.postings.length > 2 && (
        <ul className="flex flex-col gap-1 rounded-lg bg-bg p-3 text-xs">
          {d.postings.map((p, i) => (
            <li key={i} className="flex justify-between gap-3">
              <span className="truncate text-muted">{shortAccount(p.account)}</span>
              <span className="money num shrink-0">{p.amount ? `${p.amount} ${p.currency}` : "—"}</span>
            </li>
          ))}
        </ul>
      )}

      <div>
        <div className="mb-1.5 flex items-center justify-between">
          <span className="text-xs text-muted">Attachments</span>
          <label className="cursor-pointer text-xs font-medium text-accent hover:underline">
            {attach.isPending ? "Uploading…" : "Add file"}
            <input
              type="file"
              accept="image/*,application/pdf"
              className="hidden"
              disabled={attach.isPending}
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) attach.mutate(f);
                e.target.value = "";
              }}
            />
          </label>
        </div>
        {d.documents.length === 0 ? (
          <p className="text-sm text-muted">None</p>
        ) : (
          <ul className="flex flex-col gap-1 text-sm">
            {d.documents.map((doc) => (
              <li key={doc}>
                <a href={documentUrl(doc)} target="_blank" rel="noopener" className="truncate text-accent hover:underline">
                  {doc.split("/").pop()}
                </a>
              </li>
            ))}
          </ul>
        )}
        {attach.error && <div className="mt-2"><ErrorNote error={attach.error} /></div>}
      </div>

      {category && (ruled ? (
        <p className="text-sm text-pos">Rule added</p>
      ) : ruling ? (
        <RuleForm
          d={d}
          account={category}
          onDone={(added) => {
            setRuling(false);
            setRuled(added);
          }}
        />
      ) : (
        <Button className="self-start" onClick={() => setRuling(true)}>Always categorize this payee like this</Button>
      ))}

      <p className="truncate text-[11px] text-muted/70">{d.file}</p>
    </div>
  );
}

export function DetailSheet() {
  const { id, close } = useDetailParam();
  const q = useDetail(id);
  useEffect(() => {
    if (!id) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && close();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [id, close]);
  if (!id) return null;
  return (
    <>
      <div className="fixed inset-0 z-20 bg-black/30" onClick={close} aria-hidden />
      <aside
        role="dialog"
        aria-label="Transaction"
        className="fixed inset-x-0 bottom-0 z-30 max-h-[88dvh] overflow-y-auto rounded-t-2xl border border-line bg-surface p-5 pb-[max(1.25rem,env(safe-area-inset-bottom))] shadow-xl md:inset-y-0 md:left-auto md:right-0 md:w-[26rem] md:max-h-none md:rounded-none md:border-y-0 md:border-r-0"
      >
        <div className="mb-4 flex items-center justify-between">
          <span className="text-sm font-medium text-muted">Transaction</span>
          <button type="button" onClick={close} className="rounded-lg p-1.5 text-muted hover:bg-line/60 hover:text-text" aria-label="Close">
            <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><path d="M6 6l12 12M18 6L6 18" /></svg>
          </button>
        </div>
        {q.error && <ErrorNote error={q.error} />}
        {q.isLoading && (
          <div className="flex flex-col gap-4">
            <Skeleton className="h-4 w-24" />
            <Skeleton className="h-9 w-40" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-2/3" />
          </div>
        )}
        {q.data && <Body d={q.data} />}
      </aside>
    </>
  );
}
