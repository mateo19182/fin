from decimal import Decimal

from fin.sync import banks

# Sanitized Enable Banking samples (shape as returned by GET /accounts/{uid}/transactions).
CARD = {
    "entry_reference": "6ade19ed-0000-4000-8000-000000000001",
    "transaction_amount": {"currency": "EUR", "amount": "3.00"},
    "creditor": {"name": "Some Coffee Shop"},
    "debtor": {"name": "ACCOUNT HOLDER"},
    "bank_transaction_code": {"code": "CARD_PAYMENT", "sub_code": None},
    "credit_debit_indicator": "DBIT",
    "status": "PDNG",
    "booking_date": "2026-10-25",
    "value_date": None,
    "remittance_information": ["Some Coffee Shop"],
    "transaction_id": None,
}
INCOMING = {
    "entry_reference": "6ad32ecc-0000-4000-8000-000000000002",
    "transaction_amount": {"currency": "EUR", "amount": "500.00"},
    "creditor": {"name": "ACCOUNT HOLDER"},
    "debtor": {"name": "A Friend"},
    "bank_transaction_code": {"code": "TRANSFER"},
    "credit_debit_indicator": "CRDT",
    "status": "BOOK",
    "booking_date": "2026-10-17",
    "remittance_information": ["dinner Bizum payment from: A Friend"],
}
NO_ID = {
    "entry_reference": None,
    "transaction_amount": {"currency": "EUR", "amount": "12.30"},
    "creditor": None,
    "debtor": None,
    "credit_debit_indicator": None,
    "status": "BOOK",
    "booking_date": "2026-10-02",
    "remittance_information": ["TJ-SOME SHOP 12345"],
}


def test_card_payment_is_negative_and_payee_is_creditor():
    c = banks.convert(CARD, "revolut", "Assets:Bank:Revolut:Checking")
    assert c.amount == Decimal("-3.00") and c.currency == "EUR"
    assert c.payee == "Some Coffee Shop" and c.date.isoformat() == "2026-10-25"
    assert c.external_id == CARD["entry_reference"] and c.source == "revolut"
    assert c.raw["status"] == "PDNG"


def test_incoming_transfer_uses_debtor_and_remittance():
    c = banks.convert(INCOMING, "revolut", "Assets:Bank:Revolut:Checking")
    assert c.amount == Decimal("500.00") and c.payee == "A Friend"
    assert c.narration == "dinner Bizum payment from: A Friend"


def test_missing_id_gets_stable_hash_and_sign_is_kept():
    a = banks.convert(NO_ID, "caixa_rural", "Assets:Bank:CaixaRural:Checking")
    b = banks.convert(dict(NO_ID), "caixa_rural", "Assets:Bank:CaixaRural:Checking")
    assert a.external_id == b.external_id and a.external_id.startswith("caixa_rural:")
    assert a.payee == "TJ-SOME SHOP 12345" and a.amount == Decimal("12.30")


def test_zero_or_undated_rows_are_dropped():
    assert banks.convert({**CARD, "transaction_amount": {"amount": "0", "currency": "EUR"}},
                         "revolut", "x") is None
    assert banks.convert({**CARD, "booking_date": None}, "revolut", "x") is None


def test_auth_complete_accepts_redirect_url(monkeypatch, root):
    seen = {}

    def fake_call(method, path, **kw):
        seen.update(method=method, path=path, **kw)
        return {"session_id": "s", "accounts": [{"uid": "u"}],
                "access": {"valid_until": "2027-04-01T00:00:00Z"}}

    monkeypatch.setattr(banks, "_call", fake_call)
    out = banks.auth_complete("revolut", "https://example.com/cb?state=revolut&code=abc123")
    assert seen["json"] == {"code": "abc123"} and out["accounts"] == 1
    assert banks.status()[0]["authorized"] and banks.status()[0]["valid_until"] == "2027-04-01"
