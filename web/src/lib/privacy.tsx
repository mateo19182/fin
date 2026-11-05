import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

const KEY = "fin.private";
const Ctx = createContext<{ on: boolean; toggle: () => void }>({ on: false, toggle: () => {} });

export function PrivacyProvider({ children }: { children: ReactNode }) {
  const [on, setOn] = useState(() => {
    try {
      return localStorage.getItem(KEY) === "1";
    } catch {
      return false;
    }
  });
  useEffect(() => {
    document.documentElement.dataset.private = on ? "1" : "0";
    try {
      localStorage.setItem(KEY, on ? "1" : "0");
    } catch {
      /* ignore */
    }
  }, [on]);
  return <Ctx.Provider value={{ on, toggle: () => setOn((v) => !v) }}>{children}</Ctx.Provider>;
}

export const usePrivacy = () => useContext(Ctx);
