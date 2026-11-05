import { Link } from "react-router-dom";
import type { ReactNode } from "react";
import { PageTitle } from "../components/ui";

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-3">
      <h2 className="text-base font-semibold tracking-tight">{title}</h2>
      {children}
    </section>
  );
}

function List({ items }: { items: ReactNode[] }) {
  return (
    <ul className="flex flex-col gap-1.5 text-sm leading-6">
      {items.map((x, i) => (
        <li key={i} className="flex gap-2.5">
          <span className="mt-[11px] h-1 w-1 shrink-0 rounded-full bg-muted" aria-hidden />
          <span className="min-w-0">{x}</span>
        </li>
      ))}
    </ul>
  );
}

function Step({ when, children }: { when: string; children: ReactNode }) {
  return (
    <div className="grid gap-x-4 gap-y-1 sm:grid-cols-[8rem_1fr]">
      <div className="text-sm font-medium">{when}</div>
      <div className="text-sm leading-6 text-muted">{children}</div>
    </div>
  );
}

const Code = ({ children }: { children: ReactNode }) => <code className="rounded bg-line/60 px-1 py-0.5 text-[0.85em]">{children}</code>;
const To = ({ to, children }: { to: string; children: ReactNode }) => <Link to={to} className="text-accent hover:underline">{children}</Link>;

export function Guide() {
  return (
    <div className="flex max-w-2xl flex-col gap-10">
      <div>
        <PageTitle>Guide</PageTitle>
        <p className="-mt-3 text-sm leading-6 text-muted">
          How the money tracking works, what runs on its own and what is left for you to do.
        </p>
      </div>

      <Section title="What it is">
        <p className="text-sm leading-6">
          A plain-text <strong className="font-medium">beancount</strong> ledger in a private git repo, updated every day from the banks,
          the broker and the wallets. Three ways in: this web app, Hermes on Telegram, and the <Code>fin</Code> command line on the server.
          Every change to the ledger is a git commit, so anything can be reverted.
        </p>
      </Section>

      <Section title="What runs automatically">
        <div className="flex flex-col gap-4">
          <Step when="Daily, 08:30">
            Sync: Revolut and Caixa Rural (Enable Banking), Indexa valuation, BTC / LTC / ETH / Base wallets, market prices. New bank
            movements are categorised by your rules first, then by history; what is not clear lands in <To to="/review">Review</To> and a
            Telegram message lists it. Then alerts: duplicate charge, unusually big spend, new subscription, subscription price rise, bank
            session about to expire.
          </Step>
          <Step when="Sunday, 19:00">Weekly digest, only when something is notable: spend well above or below the 8-week average, an alert, pending reviews or a tax deadline within two weeks.</Step>
          <Step when="1st of the month">Monthly report on Telegram with the month's figures and the to-do list for the <To to="/close">Close</To>.</Step>
          <Step when="~10 days before a 303 deadline">A reminder with our own 303 figure, to compare with the gestor's.</Step>
        </div>
      </Section>

      <Section title="How to use it">
        <div className="flex flex-col gap-4">
          <Step when="Weekly">
            A glance at the <To to="/">Overview</To>, then clear <To to="/review">Review</To>: pick a category, or reply to the Telegram list
            (e.g. "1 restaurant, 2 travel, 3 skip").
          </Step>
          <Step when="Monthly">
            Drop the Revolut brokerage statement CSV, the Revolut savings statement CSV and any invoices you issued (the Example
            payslip only when it changes) into the documents inbox, from the laptop, the phone or by sending them to Hermes, then ask
            Hermes (or Claude) to process them. Or upload the two CSVs on the <To to="/close">Close</To> page. Then check the Close
            checklist is all green.
          </Step>
          <Step when="Any time">
            Work receipts (photo or PDF) go to the inbox too; when processed, each is matched to its bank charge and attached. Ask Hermes questions: e.g. "how
            much did I spend on food in September?", "is everything up to date?", "what does the 3T 303 look like?", "always book Vast.ai as
            Software".
          </Step>
          <Step when="Quarterly">Compare the gestor's 303 with the figures on the <To to="/close">Close</To> page (shown when a quarter ends or a deadline is near).</Step>
        </div>
      </Section>

      <Section title="Where things are">
        <List
          items={[
            <><To to="/">Overview</To> — net worth, this period's income / spending / saved, top spending.</>,
            <><To to="/review">Review</To> — movements waiting for a category, and what was booked automatically in the last 30 days.</>,
            <><To to="/transactions">Transactions</To> — everything, by month, category, account or search; tap one to edit, attach a file or mark it deductible.</>,
            <><To to="/spending">Spending</To> — cash flow, categories over a period, subscriptions.</>,
            <><To to="/portfolio">Portfolio</To> — Revolut, Indexa and crypto positions and returns.</>,
            <><To to="/close">Close</To> — the month's checklist and summary; quarterly 303 when relevant.</>,
            <><To to="/sources">Sources</To> — account health, bank connections, manual sync, CSV imports.</>,
            <>
              Every document under <Code>misc/finance</Code> (Syncthing, backed up weekly): <Code>&lt;year&gt;/payslips</Code>,{" "}
              <Code>invoices-issued</Code>, <Code>receipts</Code>, <Code>taxes</Code>, <Code>statements</Code>, plus{" "}
              <Code>permanent</Code> for contracts, RETA and W-8BEN.
            </>,
            <>
              <Code>misc/finance/inbox</Code> — drop anything there (or send it to Hermes, which saves it there). Nothing happens until you
              ask Hermes or Claude to process it: they look at each file, import it and move it to its folder, and ask when unsure.
            </>,
            <>The ledger itself lives in git: <Code>ledger/</Code> in the finance repo.</>,
          ]}
        />
      </Section>

      <Section title="Access and privacy">
        <List
          items={[
            <>The web app is reachable only inside the tailnet and has no login: anyone on the tailnet can use it.</>,
            <>Hermes can read and change the ledger. Every change is a git commit and can be reverted.</>,
            <>The GitHub repo is private but contains the full ledger.</>,
            <>Bank keys, API tokens and bank sessions live only on the server, in <Code>config.toml</Code> and <Code>data/secrets</Code>; they are not in git.</>,
          ]}
        />
      </Section>
    </div>
  );
}
