import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, useBanks, useSyncState, type Bank } from "../lib/api";
import { fmtDateTime } from "../lib/format";
import { Button, Card, Empty, ErrorNote, H2, PageTitle, SkeletonRows } from "../components/ui";
import { StatusList } from "../components/StatusList";
import { SavingsStatementImport, StocksImport } from "../components/Imports";

function BankRow({ b }: { b: Bank }) {
  const qc = useQueryClient();
  const [url, setUrl] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const start = useMutation({
    mutationFn: () => api<{ url: string }>(`/banks/${b.key}/auth/start`, { method: "POST" }),
    onSuccess: (r) => {
      setUrl(r.url);
      window.open(r.url, "_blank", "noopener");
    },
  });
  const complete = useMutation({
    mutationFn: () => api(`/banks/${b.key}/auth/complete`, { method: "POST", body: JSON.stringify({ code }) }),
    onSuccess: () => {
      setUrl(null);
      setCode("");
      qc.invalidateQueries({ queryKey: ["banks"] });
    },
  });
  const status = !b.authorized ? ["Not connected", "text-muted"] : b.expired ? ["Expired", "text-neg"] : ["Connected", "text-pos"];

  return (
    <li className="py-3">
      <div className="flex items-center gap-3">
        <div className="min-w-0 flex-1">
          <div className="font-medium">{b.name}</div>
          <div className="text-xs text-muted">
            <span className={status[1]}>{status[0]}</span>
            {b.valid_until && ` · until ${fmtDateTime(b.valid_until)}`}
            {b.last_sync && ` · sync ${fmtDateTime(b.last_sync)}`}
          </div>
        </div>
        <Button onClick={() => start.mutate()} disabled={start.isPending}>
          {b.authorized ? "Renew" : "Connect"}
        </Button>
      </div>
      {start.error && <div className="mt-2"><ErrorNote error={start.error} /></div>}
      {url && (
        <form
          className="mt-3 flex flex-col gap-2 rounded-lg bg-bg p-3 text-sm"
          onSubmit={(e) => {
            e.preventDefault();
            complete.mutate();
          }}
        >
          <p className="text-muted">
            The bank's page opened in a new tab.{" "}
            <a href={url} target="_blank" rel="noopener" className="text-accent underline">
              Open again
            </a>
            . When done, paste the URL it redirects you to:
          </p>
          <div className="flex gap-2">
            <input type="url" value={code} onChange={(e) => setCode(e.target.value)} placeholder="https://…?code=…" className="min-w-0 flex-1" required />
            <Button type="submit" variant="primary" disabled={complete.isPending || !code}>
              Complete
            </Button>
          </div>
          {complete.error && <ErrorNote error={complete.error} />}
        </form>
      )}
    </li>
  );
}

function Sync() {
  const qc = useQueryClient();
  const [polling, setPolling] = useState(false);
  const state = useSyncState(polling);
  const running = state.data?.running ?? false;
  if (polling && state.data && !running) {
    setPolling(false);
    qc.invalidateQueries();
  }
  const start = useMutation({
    mutationFn: () => api("/sync", { method: "POST", body: JSON.stringify({}) }),
    onSuccess: () => setPolling(true),
  });
  const last = state.data?.last;
  const summary = last?.result ? Object.entries(last.result).map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : String(v)}`) : [];

  return (
    <>
      <div className="flex items-center gap-3">
        <div className="min-w-0 flex-1 text-sm">
          {last ? (
            <>
              <span className={last.ok ? "text-pos" : "text-neg"}>{last.ok ? "OK" : "Error"}</span>
              <span className="text-muted"> · {fmtDateTime(last.finished)}</span>
            </>
          ) : (
            <span className="text-muted">Never synced</span>
          )}
        </div>
        <Button variant="primary" onClick={() => start.mutate()} disabled={running || start.isPending}>
          {running ? "Syncing…" : "Sync now"}
        </Button>
      </div>
      {start.error && <div className="mt-2"><ErrorNote error={start.error} /></div>}
      {last?.error && <p className="mt-2 break-words text-xs text-neg">{last.error}</p>}
      {summary.length > 0 && (
        <ul className="mt-2 flex flex-col gap-0.5 text-xs text-muted">
          {summary.map((s) => (
            <li key={s} className="break-words">{s}</li>
          ))}
        </ul>
      )}
    </>
  );
}

export function Sources() {
  const banks = useBanks();
  return (
    <div className="flex flex-col gap-6">
      <PageTitle right={<Link to="/guide" className="text-sm text-accent hover:underline">How it works →</Link>}>Sources</PageTitle>

      <Card className="p-4 md:p-5">
        <StatusList />
      </Card>

      <Card className="p-4 md:p-5">
        <H2>Banks</H2>
        {banks.error && <ErrorNote error={banks.error} />}
        {banks.isLoading && <SkeletonRows n={2} />}
        {banks.data && banks.data.length === 0 && <Empty>No banks configured in config.toml</Empty>}
        <ul className="divide-y divide-line">
          {banks.data?.map((b) => (
            <BankRow key={b.key} b={b} />
          ))}
        </ul>
      </Card>

      <Card className="p-4 md:p-5">
        <H2>Sync</H2>
        <Sync />
      </Card>

      <Card className="p-4 md:p-5">
        <H2>Imports</H2>
        <ul className="divide-y divide-line text-sm">
          <li className="flex flex-wrap items-center gap-x-3 gap-y-2 py-2.5">
            <span className="min-w-0 flex-1">
              Revolut Invest statement
              <span className="block text-xs text-muted">Invest → ⋯ → Documents → Brokerage account → Account statement → CSV</span>
            </span>
            <StocksImport />
          </li>
          <li className="flex flex-wrap items-center gap-x-3 gap-y-2 py-2.5">
            <span className="min-w-0 flex-1">
              Revolut savings statement
              <span className="block text-xs text-muted">Savings → Statement → CSV</span>
            </span>
            <SavingsStatementImport />
          </li>
        </ul>
      </Card>
    </div>
  );
}
