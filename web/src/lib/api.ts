import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BASE } from "./base";

export type Groups = { cash: number; stocks: number; indexa: number; crypto: number; receivables: number };
export type NetWorth = {
  date: string;
  total: number;
  assets: number;
  liabilities: number;
  groups: Groups;
};
export type Totals = { income: number; expenses: number; savings: number };
/** Comparison values: null when that period predates the ledger. */
export type Compared = { prev?: number | null; yoy?: number | null };
export type Category = Compared & {
  account: string;
  total: number;
  count: number;
  share: number;
  children: (Compared & { account: string; total: number; count: number })[];
};
export type Overview = {
  net_worth: NetWorth & { change: number; change_pct: number | null };
  series: NetWorth[];
  totals: Totals & { prev: Totals | null; yoy: Totals | null };
  categories: Category[];
  pending: number;
};
export type CashflowBucket = { period: string; income: number; expenses: number; savings: number };
export type PortfolioPoint = { date: string; value: number; cost: number };
export type Txn = {
  id: string;
  date: string;
  payee: string;
  narration: string;
  amount: number;
  account: string;
  bank: string | null;
  source: string | null;
  auto: string | null;
  accounts: string[];
};
export type TxnPage = { total: number; items: Txn[] };
export type Position = {
  group: string;
  symbol: string;
  units: number;
  value: number;
  cost: number | null;
  pl: number | null;
  pl_pct: number | null;
  period_pl?: number | null;
  period_pct?: number | null;
  price: number | null;
  weight: number;
  accounts: string[];
  priced: boolean;
};
export type Holdings = {
  date: string;
  total: number;
  cost: number;
  pl: number;
  pl_pct: number | null;
  period_pl?: number | null;
  period_pct?: number | null;
  since?: string;
  groups: { name: string; value: number; cost: number; pl: number; weight: number; period_pl?: number | null; period_pct?: number | null }[];
  positions: Position[];
};
export type Subscription = {
  payee: string;
  account: string;
  amount: number;
  months: number;
  last_date: string;
  active: boolean;
  yearly: number;
};
export type Pending = {
  external_id: string;
  source: string;
  date: string;
  payee: string;
  narration: string;
  amount: string;
  currency: string;
  account: string;
  suggestions: { account: string; p: number }[];
};
export type Bank = {
  key: string;
  name: string;
  account: string;
  authorized: boolean;
  expired: boolean;
  valid_until: string | null;
  last_sync: string | null;
};
export type SyncState = {
  running: boolean;
  last: {
    started: string;
    finished: string;
    ok: boolean;
    result?: Record<string, unknown>;
    error?: string;
  } | null;
};

class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}/api${path}`, {
    headers: init?.body instanceof FormData ? undefined : { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
    } catch {
      /* no body */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json();
}

const qs = (params: Record<string, string | number | boolean | undefined | null>) => {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "" && v !== false) u.set(k, String(v));
  }
  const s = u.toString();
  return s ? `?${s}` : "";
};

type Span = { start?: string; end?: string };
const useSpanned = <T,>(key: string, path: string, span: Span | undefined, extra: Record<string, string | undefined> = {}) =>
  useQuery({
    queryKey: [key, span?.start, span?.end, extra],
    queryFn: () => api<T>(`${path}${qs({ start: span?.start, end: span?.end, ...extra })}`),
    enabled: !!span,
    placeholderData: keepPreviousData,
  });

export const useOverview = (span?: Span) => useSpanned<Overview>("overview", "/overview", span);
export const useCashflow = (span: Span | undefined, bucket: "month" | "quarter") =>
  useSpanned<CashflowBucket[]>("cashflow", "/cashflow", span, { bucket });
export const useCategories = (span: Span | undefined, compare = "prev") =>
  useSpanned<Category[]>("categories", "/categories", span, { compare });
export const useHoldings = (span?: Span) => useSpanned<Holdings>("holdings", "/holdings", span);
export const usePortfolioSeries = (span?: Span) => useSpanned<PortfolioPoint[]>("portfolio-series", "/portfolio/series", span);
export type TxnFilter = {
  start?: string;
  end?: string;
  account?: string;
  q?: string;
  auto?: boolean;
  limit?: number;
  offset?: number;
};
export const useTransactions = (f: TxnFilter, enabled = true) =>
  useQuery({
    queryKey: ["transactions", f],
    queryFn: () => api<TxnPage>(`/transactions${qs(f)}`),
    enabled,
    placeholderData: (prev) => prev,
  });
export const useRecentAuto = (days = 30) =>
  useQuery({ queryKey: ["recent-auto", days], queryFn: () => api<Txn[]>(`/transactions/recent-auto${qs({ days })}`) });
export const useSubscriptions = () =>
  useQuery({ queryKey: ["subscriptions"], queryFn: () => api<Subscription[]>("/subscriptions") });
export const useAccounts = () =>
  useQuery({ queryKey: ["accounts"], queryFn: () => api<string[]>("/accounts"), staleTime: 5 * 60_000 });
export const usePending = () => useQuery({ queryKey: ["pending"], queryFn: () => api<Pending[]>("/pending") });
export const useBanks = () => useQuery({ queryKey: ["banks"], queryFn: () => api<Bank[]>("/banks"), retry: false });
export const useSyncState = (poll: boolean) =>
  useQuery({
    queryKey: ["sync"],
    queryFn: () => api<SyncState>("/sync"),
    refetchInterval: poll ? 2000 : false,
  });

/** Invalidate everything derived from the ledger after a write. */
export function useLedgerWrite<V>(fn: (v: V) => Promise<unknown>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => qc.invalidateQueries(),
  });
}

export const recategorize = (id: string, account: string) =>
  api(`/transactions/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify({ account }) });
export const approvePending = (id: string, account: string) =>
  api(`/pending/${encodeURIComponent(id)}/approve`, { method: "POST", body: JSON.stringify({ account }) });
export const dismissPending = (id: string) =>
  api(`/pending/${encodeURIComponent(id)}/dismiss`, { method: "POST" });

// --- status / close / net worth / detail / rules ---------------------------

export type AccountStatus = {
  account: string;
  group: string | null;
  balance_eur: string;
  updates_via: "bank" | "wallet" | "indexa" | "csv" | "manual";
  updater: string | null;
  last_update: string | null;
  last_txn: string | null;
  balance_check: { date: string; amount: string; ok: boolean; error: string | null } | null;
  reconciled_30d: string;
  stale: boolean;
  stale_reason: string | null;
  status: "ok" | "warn" | "error";
};
export type Status = {
  accounts: AccountStatus[];
  summary: {
    date: string;
    accounts: { ok: number; warn: number; error: number };
    pending_reviews: number;
    banks_expiring: { key: string; name: string; valid_until: string; days: number }[];
    ledger_errors: number;
  };
};
export type CheckItem = { key: "stocks_csv" | "savings_csv" | "pending" | "balances" | "banks"; label: string; ok: boolean; detail: string };
export type CloseCategory = {
  account: string;
  amount: string;
  prev: string;
  vs_prev: string;
  avg6: string;
  vs_avg6: string;
  vs_avg6_pct: number | null;
};
export type CloseStats = {
  month: string;
  income: string;
  expenses: string;
  savings_rate: number | null;
  prev_savings_rate: number | null;
  income_by_account: Record<string, string>;
  top_categories: CloseCategory[];
  top_payees: { payee: string; amount: string }[];
  biggest_expenses: { id: string; date: string; payee: string; account: string; amount: string }[];
  avg_daily_spend: string;
  days: number;
  transactions: number;
  expense_transactions: number;
  new_recurring: string[];
  net_worth: { total: string; change: string; saved: string; contributions: string; market: string; groups: Record<string, string> };
  insights: string[];
};
export type DeductRow = { id: string; date: string; payee: string; amount: string };
export type Deductions = {
  deducted: (DeductRow & { base: string; iva: string; receipt: boolean })[];
  needs_receipt: DeductRow[];
  maybe: DeductRow[];
  base: string;
  iva: string;
};
export type Close = { month: string; checklist: CheckItem[]; stats: CloseStats; deductions: Deductions };
export type NetWorthMonth = {
  month: string;
  groups: Record<"cash" | "stocks" | "indexa" | "crypto" | "receivables", string>;
  total: string;
  change: string;
  saved: string;
  contributions: string;
  market: string;
  income: string;
  expenses: string;
};
export type Detail = {
  id: string;
  date: string;
  flag: string;
  payee: string | null;
  narration: string | null;
  tags: string[];
  links: string[];
  postings: { account: string; amount: string | null; currency: string | null; cost: string | null; price: string | null }[];
  meta: Record<string, string>;
  documents: string[];
  file: string;
  deductible: { on: boolean; pct: number; reason: string; vat: string | null; vat_rate: string | null; equipment: boolean; vat_pct?: number; iva_blocked?: boolean };
};
export type Rule = { match: string; payee?: string; account?: string; deductible?: boolean; deductible_pct?: number };
export type Quarter = {
  period: string;
  start: string;
  end: string;
  deadline: string;
  days_to_deadline: number;
  warnings: string[];
  modelo_303: { casillas: Record<string, string>; resultado: string; sentido: string };
  modelo_130: { casillas: Record<string, string>; resultado: string; sentido: string };
  payments: { id: string; date: string; amount: string; form: string; period: string | null }[];
  open_decisions: { id: string; date: string; amount: string; payee: string }[];
  show_card: boolean;
};
export type SavingsImport = {
  rows: number;
  statement_end: string;
  interest: { id: string; date: string; amount: string }[];
  imported: number;
  errors: string[];
  unmatched_transfers: { date: string; description: string; amount: string }[];
  balance: { date: string; amount: string; changed?: boolean; ok?: boolean };
  preview: string[];
};
export type StocksImport = { rows: number; imported: number; skipped: number; unsupported: string[]; errors: string[]; preview: string[] };

export const useStatus = () => useQuery({ queryKey: ["status"], queryFn: () => api<Status>("/status"), staleTime: 60_000 });
export const useClose = (month: string) =>
  useQuery({ queryKey: ["close", month], queryFn: () => api<Close>(`/close${qs({ month })}`), placeholderData: keepPreviousData });
export const useNetWorthMonths = (span?: Span & { months: number }) =>
  useQuery({
    queryKey: ["networth", span?.months, span?.end],
    queryFn: () => api<NetWorthMonth[]>(`/networth${qs({ months: span!.months, end: span!.end })}`),
    enabled: !!span,
    placeholderData: keepPreviousData,
  });
export const useDetail = (id: string | null) =>
  useQuery({ queryKey: ["detail", id], queryFn: () => api<Detail>(`/transactions/${encodeURIComponent(id!)}/detail`), enabled: !!id });
export const useQuarter = () => useQuery({ queryKey: ["quarter"], queryFn: () => api<Quarter>("/quarter"), staleTime: 60_000 });

export const updateDetail = (id: string, body: { payee?: string; narration?: string; note?: string }) =>
  api<Detail>(`/transactions/${encodeURIComponent(id)}/detail`, { method: "PATCH", body: JSON.stringify(body) });
const upload = <T,>(path: string, file: File) => {
  const fd = new FormData();
  fd.append("file", file);
  return api<T>(path, { method: "POST", body: fd });
};
export const attachDocument = (id: string, file: File) => upload<Detail>(`/transactions/${encodeURIComponent(id)}/attachment`, file);
export const addRule = (rule: Rule) => api<Rule>("/rules", { method: "POST", body: JSON.stringify(rule) });
export const setDeductible = (id: string, on: boolean, pct?: number) =>
  api<Detail>(`/transactions/${encodeURIComponent(id)}/deductible`, { method: "PATCH", body: JSON.stringify({ on, pct }) });
export const importSavings = (file: File, dryRun: boolean) => upload<SavingsImport>(`/import/savings${qs({ dry_run: dryRun })}`, file);
export const importStocks = (file: File) => upload<StocksImport>("/revolut/csv", file);
export const documentUrl = (rel: string) => `${BASE}/api/documents/${rel.split("/").map(encodeURIComponent).join("/")}`;
