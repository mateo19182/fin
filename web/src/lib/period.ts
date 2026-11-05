import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { api } from "./api";

export const PRESETS = [
  ["1m", "1M"],
  ["3m", "3M"],
  ["6m", "6M"],
  ["ytd", "YTD"],
  ["1y", "1Y"],
  ["all", "All"],
] as const;

export type Span = { start: string; end: string };
export type Period = Span & { range: string; months: number; prev: Span | null; yoy: Span | null };

const CUSTOM = /^\d{4}-\d{2}\.\.\d{4}-\d{2}$/;
export const isCustom = (r: string) => CUSTOM.test(r);
const isRange = (r: string) => PRESETS.some(([k]) => k === r) || isCustom(r);

/** Period selection kept in `?range=` (preset or "YYYY-MM..YYYY-MM"), resolved to dates by the API. */
export function usePeriod(fallback: string) {
  const [sp, setSp] = useSearchParams();
  const raw = sp.get("range") ?? "";
  const range = isRange(raw) ? raw : fallback;
  const q = useQuery({
    queryKey: ["period", range],
    queryFn: () => api<Period>(`/period?range=${encodeURIComponent(range)}`),
    staleTime: 10 * 60_000,
    placeholderData: (prev) => prev,
  });
  const setRange = (r: string) => {
    const n = new URLSearchParams(sp);
    n.set("range", r);
    setSp(n, { replace: true });
  };
  return { range, setRange, period: q.data, error: q.error };
}
