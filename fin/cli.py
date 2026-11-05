"""`fin` command line. Prefer --json outputs for agents."""

import argparse
import json
import sys
from pathlib import Path


def _out(data, as_json: bool, text=None):
    if as_json:
        print(json.dumps(data, indent=1, default=str))
    else:
        print(text if text is not None else json.dumps(data, indent=1, default=str))


def cmd_sync(a):
    from fin import sync

    r = sync.run(a.source or None, dry_run=a.dry_run)
    ing = r["ingest"]
    summary = (f"since {r['since']}: {ing['total']} fetched, {ing['skipped']} known, "
               f"{len(ing['booked'])} booked, {len(ing['pending'])} pending"
               + (f", errors: {'; '.join(r['errors'])}" if r["errors"] else ""))
    _out(r, a.json, summary)


def cmd_pending(a):
    from fin import store

    rows = store.list_pending()
    text = "\n".join(f"{store.short_id(r['external_id'])}  {r['date']}  {r['payee'][:30]:<30} "
                     f"{float(r['amount']):>9.2f} {r['currency']}  "
                     + " / ".join(s["account"] for s in r["suggestions"][:2]) for r in rows)
    _out(rows, a.json, text or "nothing pending")


def cmd_approve(a):
    from fin import ingest

    _out(ingest.approve(a.id, a.account), a.json, f"booked → {a.account}")


def cmd_dismiss(a):
    from fin import ingest

    _out(ingest.dismiss(a.id), a.json, "dismissed")


def cmd_recat(a):
    from fin import ingest

    r = ingest.recategorize(a.id, a.account)
    _out(r, a.json, f"{r['from']} → {r['to']}")


def cmd_accounts(a):
    from fin import ledger

    accounts = ledger.load().accounts()
    _out(accounts, a.json, "\n".join(accounts))


def cmd_query(a):
    from beanquery import query

    from fin import ledger

    lg = ledger.load()
    cols, rows = query.run_query(lg.entries, lg.options, a.bql, numberify=True)
    names = [c.name for c in cols]
    if a.json:
        print(json.dumps([dict(zip(names, r, strict=True)) for r in rows], default=str))
    else:
        print("  ".join(names))
        for r in rows:
            print("  ".join(str(v) for v in r))


def cmd_import_revolut(a):
    from fin.sync import revolut_invest

    text = Path(a.file).read_text() if a.file != "-" else sys.stdin.read()
    r = revolut_invest.import_csv(text, dry_run=a.dry_run)
    if not a.dry_run and a.file != "-":
        r["archived"] = str(revolut_invest.archive(Path(a.file).read_bytes()))
    msg = (f"{r['rows']} rows: {r['imported']} imported, {r['skipped']} already in ledger, "
           f"{len(r['unsupported'])} unsupported, {len(r['errors'])} errors")
    if a.dry_run:
        msg += "\n\n" + "\n".join(r["preview"])
    _out(r, a.json, msg + ("\n" + "\n".join(r["unsupported"] + r["errors"]) if not a.json else ""))


def cmd_banks(a):
    from fin.sync import banks

    rows = banks.status()
    lines = []
    for b in rows:
        state = "ok" if b["authorized"] else "EXPIRED" if b["expired"] else "not authorized"
        lines.append(f"{b['key']:<14}{b['name']:<22}{state:<16}until {b['valid_until'] or '-'}"
                     f"  last sync {b['last_sync'] or '-'}")
    _out(rows, a.json, "\n".join(lines))


def cmd_bank_auth(a):
    from fin.sync import banks

    url = banks.auth_start(a.key)
    _out({"url": url}, a.json,
         f"Open and authorize, then run: fin bank-complete {a.key} <redirected URL>\n{url}")


def cmd_bank_complete(a):
    from fin.sync import banks

    _out(banks.auth_complete(a.key, a.url), a.json, "session saved")


def cmd_report(a):
    from fin import report

    print(report.send_monthly(a.month) if a.send else report.monthly(a.month))


def cmd_status(a):
    from fin import status

    rows, s = status.accounts_status(), status.summary()
    _out({"accounts": rows, "summary": s}, a.json, status.text(rows, s))


def cmd_import_savings(a):
    from fin.sync import revolut_savings

    text = Path(a.file).read_text() if a.file != "-" else sys.stdin.read()
    r = revolut_savings.import_csv(text, dry_run=a.dry_run)
    if not a.dry_run and a.file != "-":
        r["archived"] = str(revolut_savings.archive(Path(a.file).read_bytes()))
    msg = (f"{r['rows']} rows to {r['statement_end']}: {len(r['interest'])} interest months"
           f"{' would be' if a.dry_run else ''} booked, balance {r['balance']['amount']} EUR"
           f" at {r['balance']['date']}, {len(r['unmatched_transfers'])} unmatched transfers")
    for i in r["interest"]:
        msg += f"\n  {i['date']} {i['amount']:>8} EUR  {i['id']}"
    for u in r["unmatched_transfers"]:
        msg += f"\n  MISSING {u['date']} {u['amount']:>9} EUR  {u['description']}"
    msg += "".join(f"\n  ERROR {e}" for e in r["errors"])
    _out(r, a.json, msg)


def cmd_rule(a):
    from fin import payees

    if a.action == "add":
        if not a.match:
            raise ValueError("usage: fin rule add <regex> [--payee NAME] [--account ACCOUNT]")
        r = payees.add_rule(a.match, a.payee, a.account)
        _out(r, a.json, f"added rule {r}")
    else:
        rules = payees.list_rules()
        _out(rules, a.json, "\n".join(
            f"{r['match']:<40} {r.get('payee', '-'):<24} {r.get('account', '-')}"
            for r in rules) or "no rules")


def cmd_close(a):
    from fin import close

    s, items = close.stats(a.month), close.checklist(a.month)
    _out({"stats": s, "checklist": items}, a.json, close.text(s, items))


def cmd_import_payslip(a):
    from fin import ledger
    from fin.renta import payslips

    parsed = payslips.parse(a.file)
    r = payslips.book(parsed, dry_run=a.dry_run)
    if not a.dry_run:
        r["archived"] = str(payslips.archive(a.file, parsed))
        ledger.commit(f"payslip: {r['employer']} {r['month']}")
    msg = (f"{r['employer']} {r['month']}: gross {r['gross']} -> net {r['net']} "
           f"({'would rewrite' if a.dry_run else 'rewrote'} {r['id']})\n\n{r['after']}")
    _out(r, a.json, msg)


def cmd_import_invoice(a):
    from fin.renta import invoices

    parsed = invoices.parse(a.file)
    r = invoices.book(parsed, dry_run=a.dry_run)
    if not a.dry_run:
        r["archived"] = str(invoices.archive(a.file, parsed))
    msg = f"{'already booked' if r['already_booked'] else 'booked'} {r['id']}\n{r['preview']}"
    msg += (f"receipt {r['receipt']['date']} {r['receipt']['id']}: {r['receipt']['from']} -> "
            f"{r['receipt']['to']}" if r["receipt"] else "no receipt in the ledger yet")
    _out(r, a.json, msg)


def cmd_renta(a):
    from fin.renta import report

    r = report.renta(a.year)
    if a.detail:
        _out(report.detail(r, a.detail), True)
        return
    _out(r, a.json, report.text(r))


def cmd_receipt(a):
    from fin import receipts

    r = receipts.receipt(a.file, a.txn, dry_run=a.dry_run)
    _out(r, a.json, receipts.summary(r))


def cmd_deductible(a):
    from fin import activity

    r = activity.set_deductible(a.id, a.state == "on", a.pct,
                                True if a.equipment else None)
    _out(r, a.json, f"{a.id}: deductible {'on' if r['on'] else 'off'}"
         + (f" {r['pct']}%" if r["on"] else ""))


def cmd_deductible_payee(a):
    from fin import activity

    r = activity.set_payee_deductible(a.payee, a.state == "on", a.pct, a.vat)
    _out(r, a.json, f"rule {r}")


def cmd_quarter(a):
    from fin.renta import quarterly

    r = quarterly.quarter(a.q)
    _out(r, a.json, quarterly.text(r))


def cmd_tax_payment(a):
    from fin.renta import quarterly

    r = quarterly.book_tax_payment(a.id, a.form, a.period)
    _out(r, a.json, f"{a.id}: {r['form']} {r['period']} → {r['account']}")


def cmd_digest(a):
    from fin import digest

    d = digest.digest()
    if a.send:
        sent = digest.send()
        _out({**d, "sent": sent is not None}, a.json,
             digest.text(d) if sent else "nothing notable, not sent")
    else:
        note = "" if d["notable"] else "\n(not notable: would not send)"
        _out(d, a.json, digest.text(d) + note)


def cmd_serve(a):
    from fin import api

    api.serve(port=a.port)


def main(argv=None):
    p = argparse.ArgumentParser(prog="fin", description="Personal finance on a beancount ledger")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, fn, **kw):
        sp = sub.add_parser(name, **kw)
        sp.add_argument("--json", action="store_true")
        sp.set_defaults(fn=fn)
        return sp

    s = add("sync", cmd_sync, help="fetch banks/prices/indexa/wallets, ingest, notify")
    s.add_argument("--source", action="append", choices=["banks", "prices", "indexa", "wallets"])
    s.add_argument("--dry-run", action="store_true")
    add("pending", cmd_pending, help="list items waiting for review")
    s = add("approve", cmd_approve, help="book a pending item")
    s.add_argument("id")
    s.add_argument("account")
    add("dismiss", cmd_dismiss, help="drop a pending item for good").add_argument("id")
    s = add("recat", cmd_recat, help="move a booked entry to another account")
    s.add_argument("id")
    s.add_argument("account")
    add("accounts", cmd_accounts, help="open accounts")
    add("query", cmd_query, help="run a BQL query").add_argument("bql")
    s = add("import-revolut", cmd_import_revolut, help="import a Revolut Invest CSV statement")
    s.add_argument("file")
    s.add_argument("--dry-run", action="store_true")
    add("banks", cmd_banks, help="bank session status")
    add("bank-auth", cmd_bank_auth, help="start bank authorization").add_argument("key")
    s = add("bank-complete", cmd_bank_complete, help="finish bank authorization")
    s.add_argument("key")
    s.add_argument("url", help="redirected URL or bare code")
    s = add("report", cmd_report, help="monthly plain-text report")
    s.add_argument("--month")
    s.add_argument("--send", action="store_true")
    add("serve", cmd_serve, help="run the web API").add_argument("--port", type=int)
    add("status", cmd_status, help="per-account freshness and reconciliation")
    s = add("import-savings", cmd_import_savings, help="import a Revolut savings statement CSV")
    s.add_argument("file")
    s.add_argument("--dry-run", action="store_true")
    s = add("rule", cmd_rule, help="payee/category rules (ledger/rules.toml)")
    s.add_argument("action", choices=["add", "list"])
    s.add_argument("match", nargs="?", help="regex searched in payee, bank text and narration")
    s.add_argument("--payee")
    s.add_argument("--account")
    s = add("close", cmd_close, help="monthly close: checklist and stats (default: last month)")
    s.add_argument("--month")
    s = add("renta", cmd_renta, help="IRPF estimate for a tax year (never final)")
    s.add_argument("--year", type=int, default=2026)
    s.add_argument("--detail", metavar="SECTION",
                   help="one section as JSON: trabajo, actividad, ahorro, base, cuota, "
                        "pagos_a_cuenta, resultado, modelo_720")
    s = add("import-payslip", cmd_import_payslip, help="book a payslip PDF in the gross shape")
    s.add_argument("file")
    s.add_argument("--dry-run", action="store_true")
    s = add("import-invoice", cmd_import_invoice, help="book an issued invoice PDF (autónomo)")
    s.add_argument("file")
    s.add_argument("--dry-run", action="store_true")
    s = add("receipt", cmd_receipt, help="attach an expense receipt (file or folder) to its txn")
    s.add_argument("file")
    s.add_argument("--txn", help="entry id to attach to instead of matching")
    s.add_argument("--dry-run", action="store_true")
    s = add("deductible", cmd_deductible, help="mark an entry (not) deductible for the activity")
    s.add_argument("id")
    s.add_argument("state", choices=["on", "off"])
    s.add_argument("--pct", type=int)
    s.add_argument("--equipment", action="store_true", help="amortise instead of expensing")
    s = add("deductible-payee", cmd_deductible_payee, help="rule: payee (not) deductible")
    s.add_argument("payee")
    s.add_argument("state", choices=["on", "off"])
    s.add_argument("--pct", type=int)
    s.add_argument("--vat", choices=["es", "eu", "non_eu", "oss"])
    s = add("quarter", cmd_quarter, help="303/130 figures per casilla (default: last quarter)")
    s.add_argument("--q", metavar="PERIOD", help="e.g. 2026-3T")
    s = add("tax-payment", cmd_tax_payment, help="classify an AEAT payment as 303 or 130")
    s.add_argument("id")
    s.add_argument("form", choices=["303", "130"])
    s.add_argument("period", help="e.g. 2026-3T")
    s = add("digest", cmd_digest, help="weekly digest (--send: Telegram when notable)")
    s.add_argument("--send", action="store_true")

    a = p.parse_args(argv)
    try:
        a.fn(a)
    except (KeyError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
