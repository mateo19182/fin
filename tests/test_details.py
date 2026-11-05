import pytest

from fin import details, ledger


def test_get(root):
    d = details.get("t-pepe-1")
    assert d["id"] == "t-pepe-1" and d["date"] == "2026-09-06" and d["payee"] == "Bar Pepe"
    assert d["meta"] == {"transaction_id": "t-pepe-1", "source": "revolut"}
    assert d["file"] == "transactions/banks/2026-09.beancount:31"
    assert d["postings"][0] == {"account": "Expenses:Food:Restaurant", "amount": "14.00",
                                "currency": "EUR", "cost": None, "price": None}
    assert d["documents"] == []
    with pytest.raises(KeyError):
        details.get("nope")


def test_update_text_and_note(root):
    d = details.update("t-pepe-1", payee="Pepe's Bar", narration="cañas", note="with Ana")
    assert (d["payee"], d["narration"], d["meta"]["note"]) == ("Pepe's Bar", "cañas", "with Ana")
    d = details.update("t-pepe-1", note="just me")  # replaces the existing note line in place
    assert d["meta"]["note"] == "just me" and d["payee"] == "Pepe's Bar"
    text = ledger.bank_file(ledger.load().find("t-pepe-1").date).read_text()
    assert text.count("note:") == 1 and 'Pepe\'s Bar" "cañas"' in text
    assert not ledger.load().errors
    # the untouched neighbours still resolve
    assert details.get("t-pepe-2")["payee"] == "Bar Pepe"


def test_update_sanitizes_text(root):
    d = details.update("t-pepe-1", payee='a" b\n2026-01-01 open Assets:Broken')
    assert d["payee"] == "a' b 2026-01-01 open Assets:Broken" and not ledger.load().errors


def test_attach(root):
    d = details.attach("t-pepe-1", "Receipt Bar Pepe (2).PDF", b"%PDF-1.4 fake")
    rel = d["documents"][0]
    assert rel == "2026/receipts/2026-09-06_bar-pepe.pdf"
    assert details.document_path(rel) == (root / "docs" / rel).resolve()
    assert details.document_path(rel).read_bytes() == b"%PDF-1.4 fake"
    d = details.attach("t-pepe-1", "Receipt Bar Pepe (2).PDF", b"second")
    assert d["documents"] == [rel, "2026/receipts/2026-09-06_bar-pepe-2.pdf"]
    assert d["meta"]["document_2"].endswith("-2.pdf")
    d = details.attach("t-pepe-1", "again.pdf", b"second")  # same bytes: no new file or meta
    assert len(d["documents"]) == 2
    assert not ledger.load().errors
    for bad in ("../config.toml", "/etc/passwd", "2026/../../ledger/main.beancount"):
        with pytest.raises(ValueError):
            details.document_path(bad)
