import { NavLink, Outlet } from "react-router-dom";
import { usePending, useStatus } from "../lib/api";
import { usePrivacy } from "../lib/privacy";
import { DetailSheet } from "./DetailSheet";

// `Close` and `Guide` are reached from Overview / Sources on phones: the bottom bar holds six.
const NAV = [
  { to: "/", label: "Overview", icon: "M4 19h16M6 15l4-5 4 3 4-6" },
  { to: "/review", label: "Review", icon: "M5 12l4 4L19 6" },
  { to: "/transactions", label: "Transactions", icon: "M4 7h16M4 12h16M4 17h10" },
  { to: "/spending", label: "Spending", icon: "M5 20V9m7 11V4m7 16v-7" },
  { to: "/portfolio", label: "Portfolio", icon: "M12 3a9 9 0 1 0 9 9h-9z M14 3a7 7 0 0 1 7 7h-7z" },
  { to: "/close", label: "Close", icon: "M12 3a9 9 0 1 1 0 18 9 9 0 0 1 0-18zm-3 9 2 2 4-4", mobile: false },
  { to: "/sources", label: "Sources", icon: "M12 4v16m-8-8h16" },
  { to: "/guide", label: "Guide", icon: "M4 5h6a2 2 0 0 1 2 2v13a2 2 0 0 0-2-2H4zM20 5h-6a2 2 0 0 0-2 2v13a2 2 0 0 1 2-2h6z", mobile: false },
];

function Icon({ d }: { d: string }) {
  return (
    <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d={d} />
    </svg>
  );
}

function Eye({ off }: { off: boolean }) {
  return (
    <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12z" />
      <circle cx="12" cy="12" r="3" />
      {off && <path d="M4 4l16 16" />}
    </svg>
  );
}

export function Layout() {
  const { on, toggle } = usePrivacy();
  const { data: pending } = usePending();
  const { data: status } = useStatus();
  const badge = pending?.length ?? 0;
  const issues = status ? status.summary.accounts.warn + status.summary.accounts.error : 0;
  const issueTone = status && status.summary.accounts.error > 0 ? "bg-neg" : "bg-warn";

  const link = (mobile: boolean) =>
    NAV.filter((n) => !mobile || n.mobile !== false).map((n) => (
      <NavLink
        key={n.to}
        to={n.to}
        end={n.to === "/"}
        className={({ isActive }) =>
          mobile
            ? `relative flex flex-1 flex-col items-center gap-0.5 py-2 text-[10px] ${isActive ? "text-accent" : "text-muted"}`
            : `relative flex items-center gap-3 rounded-lg px-3 py-2 text-sm ${
                isActive ? "bg-accent-soft font-medium text-accent" : "text-muted hover:text-text"
              }`
        }
      >
        <Icon d={n.icon} />
        <span>{n.label}</span>
        {n.to === "/review" && badge > 0 && (
          <span
            className={`rounded-full bg-accent px-1.5 text-[10px] font-semibold leading-4 text-white ${
              mobile ? "absolute left-1/2 top-1 ml-1.5" : "ml-auto"
            }`}
          >
            {badge}
          </span>
        )}
        {n.to === "/sources" && issues > 0 && (
          <span
            title={`${issues} account${issues === 1 ? "" : "s"} need attention`}
            className={`h-2 w-2 rounded-full ${issueTone} ${mobile ? "absolute left-1/2 top-2 ml-2.5" : "ml-auto"}`}
          />
        )}
      </NavLink>
    ));

  const eye = (
    <button
      type="button"
      onClick={toggle}
      title={on ? "Show amounts" : "Hide amounts"}
      className="rounded-lg p-2 text-muted hover:bg-line/60 hover:text-text"
    >
      <Eye off={on} />
    </button>
  );

  return (
    <div className="mx-auto flex min-h-dvh max-w-6xl">
      <aside className="sticky top-0 hidden h-dvh w-52 shrink-0 flex-col gap-1 border-r border-line px-3 py-6 md:flex">
        <div className="mb-6 flex items-center justify-between px-3">
          <span className="text-lg font-semibold tracking-tight">fin</span>
          {eye}
        </div>
        {link(false)}
      </aside>
      <header className="fixed inset-x-0 top-0 z-10 flex h-12 items-center justify-between border-b border-line bg-bg/90 px-4 backdrop-blur md:hidden">
        <span className="text-base font-semibold tracking-tight">fin</span>
        {eye}
      </header>
      <main className="min-w-0 flex-1 px-4 pb-24 pt-16 md:px-10 md:pb-10 md:pt-8">
        <Outlet />
      </main>
      <nav className="fixed inset-x-0 bottom-0 z-10 flex border-t border-line bg-surface/95 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden">
        {link(true)}
      </nav>
      <DetailSheet />
    </div>
  );
}
