from datetime import date
from decimal import Decimal

from fin import ingest, ledger, store
from fin.models import Candidate

BANK = "Assets:Bank:Revolut:Checking"


def cand(ext, payee, amount, **raw):
    return Candidate("revolut", ext, date(2026, 10, 2), payee, payee, Decimal(amount), "EUR",
                     BANK, raw)


def test_ingest_dedupes_autobooks_and_queues(root):
    cands = [cand("t-merc-1", "Mercadona", "-23.40"),  # already in ledger
             cand("n-1", "Mercadona", "-12.00"),
             cand("n-2", "Unknown Place", "-7.50", status="PDNG"),
             cand("n-2", "Unknown Place", "-7.50")]  # same id twice in one fetch
    res = ingest.ingest(cands, dry_run=True)
    assert res["skipped"] == 2 and [b["id"] for b in res["booked"]] == ["n-1"]
    assert [p["id"] for p in res["pending"]] == ["n-2"]
    assert ledger.load().find("n-1") is None and not store.pending_ids()

    res = ingest.ingest(cands)
    t = ledger.load().find("n-1")
    assert t.meta["auto"] == "history" and t.meta["source"] == "revolut"
    assert {p.account for p in t.postings} == {"Expenses:Food:Groceries", BANK}
    assert store.pending_ids() == {"n-2"}
    assert res["booked"][0]["account"] == "Expenses:Food:Groceries"

    again = ingest.ingest(cands)
    assert again["skipped"] == 4 and not again["booked"] and not again["pending"]


def test_hand_written_entry_counts_as_duplicate(root):
    f = ledger.ledger_file().parent / "transactions" / "banks" / "2026-10.beancount"
    f.write_text('2026-10-02 * "Manual" "typed by hand"\n'
                 "  Expenses:Software      9.99 EUR\n  Assets:Bank:Revolut:Checking  -9.99 EUR\n")
    res = ingest.ingest([cand("n-3", "Something", "-9.99")], dry_run=True)
    assert res["skipped"] == 1


def test_approve_dismiss_recategorize(root):
    ingest.ingest([cand("p-1", "Mystery Shop", "-20.00"), cand("p-2", "Other", "-1.00")])
    assert store.pending_ids() == {"p-1", "p-2"}

    ingest.approve("p-1", "Expenses:Entertainment")
    t = ledger.load().find("p-1")
    assert t.flag == "*" and "auto" not in t.meta
    assert {p.account for p in t.postings} == {"Expenses:Entertainment", BANK}
    assert store.pending_ids() == {"p-2"}

    ingest.dismiss("p-2")
    assert not store.pending_ids()
    assert ingest.ingest([cand("p-2", "Other", "-1.00")])["skipped"] == 1

    r = ingest.recategorize("p-1", "Expenses:Software")
    assert r == {"id": "p-1", "from": "Expenses:Entertainment", "to": "Expenses:Software"}
    assert "Expenses:Software" in {p.account for p in ledger.load().find("p-1").postings}


def test_approve_rejects_unknown_account(root):
    ingest.ingest([cand("p-3", "Shop", "-2.00")])
    try:
        ingest.approve("p-3", "Expenses:Typo")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")
    assert store.pending_ids() == {"p-3"}


def test_pending_flag_and_indexa_units(root):
    ingest.ingest([cand("p-4", "Cafe", "-2.00", status="PDNG")])
    ingest.approve("p-4", "Expenses:Food:Restaurant")
    assert ledger.load().find("p-4").flag == "!"

    ingest.ingest([cand("p-5", "Indexa Capital", "-500.00")])
    ingest.approve("p-5", "Assets:Investment:Indexa")
    t = ledger.load().find("p-5")
    pos = next(p for p in t.postings if p.account == "Assets:Investment:Indexa")
    assert pos.units.number == Decimal("500.00") and pos.units.currency == "INDEXA"
    assert pos.cost.number == Decimal("1") and pos.cost.currency == "EUR"


def test_same_row_resent_with_a_bank_id_is_not_booked_twice(root):
    caixa = "Assets:Bank:CaixaRural:Checking"
    ledger.ensure_open(caixa, "EUR")

    def tgss(ext, day=30):
        return Candidate("caixa_rural", ext, date(2026, 10, day), "TGSS", "RCBO.TGSS. COTIZACION",
                         Decimal("-88.56"), "EUR", caixa, {})
    first = ingest.ingest([tgss("caixa_rural:77adcddab986538f")])  # day 1: no bank id, hashed
    assert len(first["booked"]) + len(first["pending"]) == 1
    res = ingest.ingest([tgss("2026-10-30.0")])  # day 2: same row, now with the bank's id
    assert res["skipped"] == 1 and not res["booked"] and not res["pending"]
    # two real identical charges in one fetch carry the same kind of id: both kept
    res = ingest.ingest([tgss("2026-10-31.0", 31), tgss("2026-10-31.1", 31)], dry_run=True)
    assert res["skipped"] == 0 and len(res["booked"]) + len(res["pending"]) == 2
