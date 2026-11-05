// es-ES skips the separator on 4-digit numbers (4023 €); force it for consistency.
const grouping = { useGrouping: "always" } as unknown as Intl.NumberFormatOptions;
const eur = new Intl.NumberFormat("es-ES", { style: "currency", currency: "EUR", ...grouping });
const eur0 = new Intl.NumberFormat("es-ES", {
  style: "currency",
  currency: "EUR",
  maximumFractionDigits: 0,
  ...grouping,
});
const num = new Intl.NumberFormat("es-ES", { maximumFractionDigits: 2 });

export const fmtEur = (n: number | null | undefined, opts?: { round?: boolean; sign?: boolean }) => {
  if (n === null || n === undefined) return "—";
  const s = (opts?.round ? eur0 : eur).format(n);
  return opts?.sign && n > 0 ? `+${s}` : s;
};

export const fmtPct = (n: number | null | undefined, sign = true) => {
  if (n === null || n === undefined) return "—";
  const s = `${num.format(Math.abs(n))} %`;
  return n < 0 ? `−${s}` : sign && n > 0 ? `+${s}` : s;
};

export const fmtUnits = (n: number) =>
  new Intl.NumberFormat("es-ES", { maximumFractionDigits: n < 1 ? 6 : n < 100 ? 4 : 2 }).format(n);

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const MONTHS_LONG = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

/** "2026-09" -> "Sep" ; with year -> "Sep 26" */
export const fmtMonth = (ym: string, withYear = false) => {
  const [y, m] = ym.split("-").map(Number);
  return withYear ? `${MONTHS[m - 1]} ${String(y).slice(2)}` : MONTHS[m - 1];
};
export const fmtMonthLong = (ym: string) => {
  const [y, m] = ym.split("-").map(Number);
  return `${MONTHS_LONG[m - 1]} ${y}`;
};

/** "2026-09-08" -> "8 Sep" ; with year -> "8 Sep 2026" */
export const fmtDate = (iso: string, withYear = false) => {
  const [y, m, d] = iso.split("-").map(Number);
  return `${d} ${MONTHS[m - 1]}${withYear ? ` ${y}` : ""}`;
};

/** Month-aligned period: "October 2026", "Aug – Oct 2026", "Nov 25 – Oct 26" */
export const fmtPeriod = (start: string, end: string) => {
  const a = start.slice(0, 7), b = end.slice(0, 7);
  if (a === b) return fmtMonthLong(a);
  const [ya, ma] = a.split("-").map(Number);
  const [yb, mb] = b.split("-").map(Number);
  return ya === yb ? `${MONTHS[ma - 1]} – ${MONTHS[mb - 1]} ${ya}` : `${fmtMonth(a, true)} – ${fmtMonth(b, true)}`;
};

/** Cash-flow bucket: "2026-03" -> "Mar" / "Mar 26"; "2026-Q1" -> "Q1 26" */
export const fmtBucket = (p: string, withYear = false) =>
  p.includes("Q") ? `Q${p.slice(-1)} ${p.slice(2, 4)}` : fmtMonth(p, withYear);
export const fmtBucketLong = (p: string) => (p.includes("Q") ? `Q${p.slice(-1)} ${p.slice(0, 4)}` : fmtMonthLong(p));

export const fmtDateTime = (iso: string | null | undefined) => {
  if (!iso) return "—";
  const d = new Date(iso);
  return isNaN(d.getTime())
    ? iso
    : d.toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
};

export const thisMonth = () => new Date().toISOString().slice(0, 7);
export const monthRange = (ym: string): [string, string] => {
  const [y, m] = ym.split("-").map(Number);
  const last = new Date(Date.UTC(y, m, 0)).getUTCDate();
  return [`${ym}-01`, `${ym}-${String(last).padStart(2, "0")}`];
};
export const shiftMonth = (ym: string, delta: number) => {
  const [y, m] = ym.split("-").map(Number);
  const d = new Date(Date.UTC(y, m - 1 + delta, 1));
  return d.toISOString().slice(0, 7);
};

/** "Expenses:Food:Groceries" -> "Groceries"; "Expenses:Food" -> "Food" */
export const leaf = (account: string) => account.split(":").slice(-1)[0];
/** "Expenses:Food:Groceries" -> "Food · Groceries" */
export const shortAccount = (account: string) => {
  const parts = account.split(":");
  return parts.length <= 1 ? account : parts.slice(1).join(" · ");
};
