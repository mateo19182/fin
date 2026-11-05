import { useSearchParams } from "react-router-dom";

/** The open transaction detail lives in `?txn=<id>` so it survives navigation and Back closes it. */
export function useDetailParam() {
  const [sp, setSp] = useSearchParams();
  const id = sp.get("txn");
  const set = (v: string | null) => {
    const n = new URLSearchParams(sp);
    v ? n.set("txn", v) : n.delete("txn");
    setSp(n);
  };
  return { id, open: (txn: string) => set(txn), close: () => set(null) };
}

export const escapeRegex = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
