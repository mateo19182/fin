# fin

Self-hosted personal finance on a plain-text [Beancount](https://beancount.github.io/) ledger.
Bank sync, transaction review, net worth and spending dashboards, investments, receipt imports,
and Spanish tax estimates. Python CLI and API, React web UI, optional Claude categorisation.

This public repository contains application code and synthetic test fixtures. Keep your
ledger, documents, credentials and bank sessions private. These paths are gitignored.
The app has no authentication: run it on localhost or a private tailnet.

## Run

Requires Python 3.12+, uv and Node.js/npm. PDF imports also require `pdftotext`.

```sh
cp config.toml.example config.toml
cp -r examples/ledger ledger
uv sync
cd web && npm ci && npm run build && cd ..
uv run fin serve
```

Open http://127.0.0.1:8742. Configure your accounts, bank connections and optional API keys
in `config.toml`. The example ledger has no transactions. Add account declarations for any
additional accounts you use. `uv run fin --help` lists the CLI commands; the web Guide explains
the workflows. `FIN_ROOT` selects an alternative directory for configuration and private data.

## Private data and backups

`ledger/` contains your accounts, transactions, prices and categorisation rules; `data/`
contains SQLite state and bank sessions; `docs/` holds documents organised by year and kind.
Back these up separately with a private backup system. Automatic Git commits and pushes are
**disabled by default**. The optional `[git] enabled = true` setting is only for a separately
configured private checkout tracking its ledger. Never enable it against this public origin.

## Features and configuration

- Enable Banking, Indexa and on-chain wallet sync; Revolut investment and savings imports.
- Rules and history-based categorisation, optional Claude assistance, review queue.
- Net worth, spending, holdings, recurring payments and monthly close.
- Payslip, invoice and receipt imports; Spanish IRPF and quarterly tax estimates.
- Optional notifications via an installed Hermes CLI. Nothing sends until invoked or scheduled.

The tax helpers are estimates for review, not filing software. The PDF parsers depend on
statement layouts and may need adaptation for your providers. Example employer/client aliases
in `fin/renta/payslips.py` and `fin/renta/invoices.py` should be adapted to your ledger.
Systemd unit templates in `deploy/` assume `~/projects/personal/fin`; review paths and schedules
before installing them. No services are installed automatically.

## Development

```sh
uv run pytest -q
uv run ruff check
cd web && npm run build
```

Tests use temporary roots and synthetic fixtures. The source was exported without the private
repository's Git history, ledger, documents, secrets or personal agent workflow.
