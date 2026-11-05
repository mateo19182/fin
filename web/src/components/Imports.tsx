import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { importSavings, importStocks, type SavingsImport } from "../lib/api";
import { fmtDate, fmtEur } from "../lib/format";
import { Button, ErrorNote } from "./ui";

function Upload({ label, busy, onFile }: { label: string; busy: boolean; onFile: (f: File) => void }) {
  return (
    <label className={`inline-flex min-h-8 cursor-pointer items-center rounded-lg border border-line bg-surface px-2.5 text-xs font-medium hover:bg-bg ${busy ? "opacity-50" : ""}`}>
      {busy ? "Working…" : label}
      <input
        type="file"
        accept=".csv,text/csv"
        className="hidden"
        disabled={busy}
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) onFile(f);
          e.target.value = "";
        }}
      />
    </label>
  );
}

/** Revolut Invest "Account statement" CSV: imported straight away (idempotent). */
export function StocksImport() {
  const qc = useQueryClient();
  const m = useMutation({ mutationFn: importStocks, onSuccess: () => qc.invalidateQueries() });
  const r = m.data;
  return (
    <>
      <Upload label="Upload CSV" busy={m.isPending} onFile={(f) => m.mutate(f)} />
      {r && (
        <p className="basis-full text-xs text-muted">
          Imported {r.imported}, skipped {r.skipped}
          {r.unsupported.length > 0 && ` · ${r.unsupported.length} unsupported`}
          {r.errors.length > 0 && <span className="text-neg"> · {r.errors.join("; ")}</span>}
        </p>
      )}
      {m.error && <div className="basis-full"><ErrorNote error={m.error} /></div>}
    </>
  );
}

/** Revolut savings statement CSV: dry-run preview, then confirm. */
export function SavingsStatementImport() {
  const qc = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<SavingsImport | null>(null);
  const dry = useMutation({
    mutationFn: (f: File) => importSavings(f, true),
    onSuccess: (r, f) => {
      setFile(f);
      setPreview(r);
    },
  });
  const confirm = useMutation({
    mutationFn: () => importSavings(file!, false),
    onSuccess: () => {
      setPreview(null);
      setFile(null);
      qc.invalidateQueries();
    },
  });
  const r = confirm.data;
  return (
    <>
      {!preview && <Upload label="Upload statement" busy={dry.isPending} onFile={(f) => dry.mutate(f)} />}
      {preview && (
        <div className="basis-full rounded-lg bg-bg p-3 text-xs">
          <p>
            Statement to <span className="font-medium">{fmtDate(preview.statement_end, true)}</span> · balance{" "}
            <span className="money num font-medium">{fmtEur(Number(preview.balance.amount))}</span>
          </p>
          {preview.interest.length > 0 ? (
            <ul className="mt-1 text-muted">
              {preview.interest.map((i) => (
                <li key={i.id}>
                  Interest {fmtDate(i.date)}: <span className="money num">{fmtEur(Number(i.amount))}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-1 text-muted">No new interest to book</p>
          )}
          {preview.unmatched_transfers.length > 0 && (
            <p className="mt-1 text-warn">
              {preview.unmatched_transfers.length} transfer{preview.unmatched_transfers.length === 1 ? "" : "s"} not in the ledger:{" "}
              {preview.unmatched_transfers.map((t) => `${fmtDate(t.date)} ${t.amount} €`).join(", ")}
            </p>
          )}
          <div className="mt-2 flex justify-end gap-2">
            <Button variant="ghost" className="!min-h-8 !text-xs" onClick={() => setPreview(null)}>Cancel</Button>
            <Button variant="primary" className="!min-h-8 !text-xs" disabled={confirm.isPending} onClick={() => confirm.mutate()}>
              {confirm.isPending ? "Importing…" : "Import"}
            </Button>
          </div>
          {confirm.error && <div className="mt-2"><ErrorNote error={confirm.error} /></div>}
        </div>
      )}
      {r && !preview && (
        <p className="basis-full text-xs text-muted">
          Booked {r.imported} interest month{r.imported === 1 ? "" : "s"}, balance set for {fmtDate(r.balance.date)}
          {r.errors.length > 0 && <span className="text-neg"> · {r.errors.join("; ")}</span>}
        </p>
      )}
      {dry.error && <div className="basis-full"><ErrorNote error={dry.error} /></div>}
    </>
  );
}
