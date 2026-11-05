"""Short Telegram notes via `hermes send`. Dry-run prints instead of sending."""

import os
import subprocess
from datetime import date, timedelta

from fin import config, store
from fin.sync import banks


def send(text: str, dry_run: bool = False) -> bool:
    if dry_run or os.environ.get("FIN_NOTIFY_DRY_RUN") == "1":
        print("--- notify (dry-run) ---\n" + text + "\n---")
        return True
    target = config.section("notify").get("target", "telegram")
    subprocess.run(["hermes", "send", "-q", "--to", target, text], check=True, timeout=60)
    return True


def _fmt_amount(row: dict) -> str:
    return f"{float(row['amount']):+.2f} {row['currency']}"


def pending_text(rows: list[dict], booked: int = 0) -> str:
    lines = [f"Finance: {len(rows)} to review" + (f", {booked} auto-booked" if booked else "")]
    for i, r in enumerate(rows, 1):
        tops = " / ".join(s["account"].split(":", 1)[-1] for s in r.get("suggestions", [])[:2])
        lines.append(f"{i}. {r['date'][5:]} {r['payee'][:28]} {_fmt_amount(r)} → {tops or '?'}"
                     f" [{store.short_id(r['id'])}]")
    lines.append(f"Reply here (e.g. '1 food, 2 travel') or open {config.web_url('/review')}")
    return "\n".join(lines)


def expiry_text(dry_run: bool = False) -> str | None:
    today = date.today()
    notified = store.get("expiry_notified", {})
    lines = []
    for b in banks.status():
        if not b["valid_until"]:
            continue
        until = date.fromisoformat(b["valid_until"])
        if until > today + timedelta(days=7) or notified.get(b["key"]) == today.isoformat():
            continue
        state = "expired" if b["expired"] else f"expires {until}"
        lines.append(f"Bank {b['name']}: session {state}. Run `fin bank-auth {b['key']}`.")
        notified[b["key"]] = today.isoformat()
    if lines and not dry_run:
        store.put("expiry_notified", notified)
    return "\n".join(lines) or None


def after_sync(result: dict, dry_run: bool = False) -> str | None:
    """One message at most: new pending items, bank sessions expiring, errors."""
    parts = []
    pend = result.get("ingest", {}).get("pending", [])
    if pend:
        parts.append(pending_text(pend, len(result["ingest"].get("booked", []))))
    if exp := expiry_text(dry_run):
        parts.append(exp)
    if result.get("errors"):
        parts.append("Sync errors: " + "; ".join(result["errors"])[:500])
    if not parts:
        return None
    text = "\n\n".join(parts)
    send(text, dry_run)
    if pend and not dry_run:
        store.mark_notified([p["id"] for p in pend])
    return text
