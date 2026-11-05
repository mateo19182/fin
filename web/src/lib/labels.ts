/** Human names for sync sources and importers (meta `source`, status `updater`). */
export const SOURCE: Record<string, string> = {
  revolut: "Revolut",
  caixa_rural: "Caixa Rural",
  revolut_invest: "Revolut Invest",
  revolut_savings_csv: "Revolut savings CSV",
  savings_csv: "savings statement",
  invoice_pdf: "Invoice",
  wallet: "Wallet",
  indexa: "Indexa",
};
export const sourceLabel = (s: string | null | undefined, fallback = "Manual entry") => (s ? SOURCE[s] ?? s : fallback);
