"""Small SQLite store for app state that does not belong in the ledger:
the review queue of uncertain transactions and key/value sync state."""

import json
import sqlite3
from datetime import date
from decimal import Decimal

from fin.config import data_dir
from fin.models import Candidate

SCHEMA = """
create table if not exists pending (
    external_id text primary key,
    source text not null,
    date text not null,
    payee text not null,
    narration text not null,
    amount text not null,
    currency text not null,
    account text not null,
    suggestions text not null default '[]',  -- [{"account": ..., "p": 0.4}, ...]
    raw text not null default '{}',
    created_at text not null default (datetime('now')),
    notified integer not null default 0
);
create table if not exists kv (key text primary key, value text not null);
"""


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(data_dir() / "fin.db")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def add_pending(c: Candidate, suggestions: list[dict]) -> None:
    with db() as conn:
        conn.execute(
            "insert or replace into pending"
            " (external_id, source, date, payee, narration, amount, currency, account,"
            "  suggestions, raw) values (?,?,?,?,?,?,?,?,?,?)",
            (c.external_id, c.source, c.date.isoformat(), c.payee, c.narration, str(c.amount),
             c.currency, c.account, json.dumps(suggestions), json.dumps(c.raw, default=str)),
        )


def short_id(external_id: str) -> str:
    """Prefix shown to people; wallet ids share their first chars, so keep them whole."""
    return external_id if external_id.startswith("wallet:") else external_id[:13]


def pending_ids() -> set[str]:
    with db() as conn:
        return {r[0] for r in conn.execute("select external_id from pending")}


def list_pending() -> list[dict]:
    with db() as conn:
        rows = conn.execute("select * from pending order by date desc").fetchall()
    return [{**dict(r), "suggestions": json.loads(r["suggestions"]), "raw": json.loads(r["raw"])}
            for r in rows]


def get_candidate(external_id: str) -> Candidate | None:
    with db() as conn:
        r = conn.execute("select * from pending where external_id=?", (external_id,)).fetchone()
    if r is None:
        return None
    return Candidate(r["source"], r["external_id"], date.fromisoformat(r["date"]), r["payee"],
                     r["narration"], Decimal(r["amount"]), r["currency"], r["account"],
                     json.loads(r["raw"]))


def remove_pending(external_id: str) -> None:
    with db() as conn:
        conn.execute("delete from pending where external_id=?", (external_id,))


def mark_notified(ids: list[str]) -> None:
    with db() as conn:
        conn.executemany("update pending set notified=1 where external_id=?", [(i,) for i in ids])


def get(key: str, default=None):
    with db() as conn:
        r = conn.execute("select value from kv where key=?", (key,)).fetchone()
    return json.loads(r[0]) if r else default


def put(key: str, value) -> None:
    with db() as conn:
        conn.execute("insert or replace into kv values (?,?)",
                     (key, json.dumps(value, default=str)))
