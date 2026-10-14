import { useEffect, useState, type DragEvent } from "react";
import { FileSpreadsheet, FileUp, RefreshCw, Trash2, X } from "lucide-react";
import { ApiError, api } from "../api";
import type {
  AccountSummary,
  BrokerImportPreview,
  BrokerTransactionRecord,
} from "../types";

interface BrokerActivityDialogProps {
  account: AccountSummary;
  onClose: () => void;
  onImported: () => Promise<void>;
}

function money(value: string | null, currency: string): string {
  if (value === null || !Number.isFinite(Number(value))) return "—";
  return `${currency} ${new Intl.NumberFormat("en-GB", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(Number(value))}`;
}

function dateTime(value: string | null): string {
  return value ? value.replace("T", " ").slice(0, 16) : "—";
}

function taxLabel(status: string): string {
  switch (status) {
    case "country_rule_estimate":
      return "Country-rule estimate";
    case "manual_override":
      return "Manual rate";
    case "legacy_assumption":
      return "Legacy estimate";
    case "tax_exempt":
      return "Tax-exempt";
    default:
      return "Not estimated";
  }
}

function transactionLabel(
  transaction: Pick<BrokerTransactionRecord, "event_type">,
): string {
  return transaction.event_type === "closed_position" ? "Closed position" : "Cash operation";
}

function pricePair(
  transaction: Pick<BrokerTransactionRecord, "open_price" | "close_price" | "currency_code">,
): string {
  if (transaction.open_price === null || transaction.close_price === null) return "—";
  return `${money(transaction.open_price, transaction.currency_code)} → ${money(
    transaction.close_price,
    transaction.currency_code,
  )}`;
}

function charges(
  transaction: Pick<
    BrokerTransactionRecord,
    "commission" | "swap" | "taxes" | "currency_code"
  >,
): string {
  const items = [
    transaction.commission === null
      ? null
      : `Commission ${money(transaction.commission, transaction.currency_code)}`,
    transaction.swap === null
      ? null
      : `Swap ${money(transaction.swap, transaction.currency_code)}`,
    transaction.taxes === null
      ? null
      : `Tax ${money(transaction.taxes, transaction.currency_code)}`,
  ].filter((item): item is string => item !== null);
  return items.join(" · ") || "—";
}

export function BrokerActivityDialog({
  account,
  onClose,
  onImported,
}: BrokerActivityDialogProps) {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<BrokerImportPreview | null>(null);
  const [stocksEtfsOnly, setStocksEtfsOnly] = useState(false);
  const [transactions, setTransactions] = useState<BrokerTransactionRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [busy, setBusy] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [deletingBatchId, setDeletingBatchId] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  async function loadHistory(offset = 0, append = false) {
    setLoadingHistory(true);
    setError("");
    try {
      const result = await api.brokerTransactions(account.id, offset, 100);
      setTransactions((current) =>
        append ? [...current, ...result.transactions] : result.transactions,
      );
      setTotal(result.total);
    } catch (cause) {
      setError(
        cause instanceof ApiError ? cause.message : "Broker transaction history could not be loaded.",
      );
    } finally {
      setLoadingHistory(false);
    }
  }

  useEffect(() => {
    void loadHistory();
  }, [account.id]);

  function chooseFile(nextFile: File | undefined) {
    if (!nextFile) return;
    const suffix = nextFile.name.split(".").pop()?.toLowerCase();
    if (!suffix || !["xlsx", "csv", "zip"].includes(suffix)) {
      setError("Choose an XTB .xlsx, .csv, or .zip transaction report.");
      return;
    }
    setFile(nextFile);
    setPreview(null);
    setMessage("");
    setError("");
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    chooseFile(event.dataTransfer.files[0]);
  }

  async function previewFile() {
    if (!file) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const result = await api.previewBrokerImport(account.id, file, stocksEtfsOnly);
      setPreview(result);
    } catch (cause) {
      setPreview(null);
      setError(cause instanceof ApiError ? cause.message : "The broker report could not be previewed.");
    } finally {
      setBusy(false);
    }
  }

  async function importFile() {
    if (!file || !preview) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const result = await api.importBrokerHistory(
        account.id,
        file,
        stocksEtfsOnly,
        preview.content_sha256,
      );
      setMessage(
        result.imported_count > 0
          ? `Imported ${result.imported_count} record(s); ${result.duplicate_count} duplicate record(s) were skipped.`
          : `No new rows imported; ${result.duplicate_count} duplicate record(s) were skipped.`,
      );
      setFile(null);
      setPreview(null);
      await onImported();
      await loadHistory();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "The broker report could not be imported.");
    } finally {
      setBusy(false);
    }
  }

  async function removeImport(batchId: string) {
    if (
      !window.confirm(
        "Remove all imported history rows from this file?\n\nThis only deletes imported history. It does not change account balances or holdings.",
      )
    ) {
      return;
    }
    setDeletingBatchId(batchId);
    setError("");
    setMessage("");
    try {
      await api.deleteBrokerImport(account.id, batchId);
      await loadHistory();
      setMessage("Imported history batch removed.");
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "The import could not be removed.");
    } finally {
      setDeletingBatchId(null);
    }
  }

  const visibleBatchesById = new Map<string, BrokerTransactionRecord>();
  for (const transaction of transactions) {
    visibleBatchesById.set(transaction.import_batch_id, transaction);
  }
  const visibleBatches = [...visibleBatchesById.values()];

  return (
    <div
      className="modal-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section
        className="modal-card broker-activity-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="broker-activity-title"
      >
        <div className="modal-heading">
          <div>
            <div className="eyebrow">XTB · imported history</div>
            <h2 id="broker-activity-title">{account.display_name} activity</h2>
          </div>
          <button className="icon-button" type="button" aria-label="Close" onClick={onClose}>
            <X size={19} />
          </button>
        </div>
        <p className="modal-intro">
          Export Closed Positions and Cash Operations from xStation Account History using the
          full date range, then drop the .xlsx, .csv, or .zip report here. Import each XTB
          account separately. Daily and quarterly PDF statements are not complete trade-history
          exports.
        </p>
        <div
          className={`broker-import-dropzone${dragging ? " is-dragging" : ""}`}
          onDragEnter={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragOver={(event) => event.preventDefault()}
          onDragLeave={(event) => {
            if (event.target === event.currentTarget) setDragging(false);
          }}
          onDrop={onDrop}
        >
          <FileUp size={24} aria-hidden="true" />
          <strong>{file ? file.name : "Drop an XTB report here"}</strong>
          <small>or choose an .xlsx, .csv, or .zip file (maximum 25 MB)</small>
          <label className="button button-secondary button-small">
            Choose report
            <input
              className="broker-import-file-input"
              type="file"
              accept=".xlsx,.csv,.zip"
              onChange={(event) => chooseFile(event.target.files?.[0])}
            />
          </label>
        </div>
        <label className="broker-import-scope">
          <input
            type="checkbox"
            checked={stocksEtfsOnly}
            onChange={(event) => {
              setStocksEtfsOnly(event.target.checked);
              setPreview(null);
            }}
          />
          <span>
            This report contains only real stocks/ETFs, not CFDs, forex, or other products.
            <small>
              Required before showing a tax estimate from reported profit. Estimates remain
              approximations and do not aggregate annual gains/losses or tax lots.
            </small>
          </span>
        </label>
        <div className="broker-import-actions">
          <span className="broker-import-privacy">
            The app does not retain the source file after processing; it stores normalized
            transaction fields only. Import will not change current balances or holdings.
          </span>
          <button
            className="button button-secondary"
            type="button"
            disabled={!file || busy}
            onClick={() => void previewFile()}
          >
            <FileSpreadsheet size={15} /> {busy && !preview ? "Reading…" : "Preview"}
          </button>
          <button
            className="button button-primary"
            type="button"
            disabled={!preview || busy}
            onClick={() => void importFile()}
          >
            {busy && preview ? "Importing…" : "Import history"}
          </button>
        </div>
        {preview && (
          <section className="broker-import-preview">
            <div className="broker-import-summary">
              <strong>{preview.transaction_count} record(s) found</strong>
              <span>
                {preview.closed_position_count} closed position(s) ·{" "}
                {preview.cash_operation_count} cash operation(s) ·{" "}
                {preview.duplicate_count} duplicate(s)
              </span>
            </div>
            {preview.warnings.map((warning) => (
              <small className="broker-import-warning" key={warning}>{warning}</small>
            ))}
            <div className="table-scroll broker-import-table">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Record</th>
                    <th>Instrument / details</th>
                    <th className="align-right">Quantity</th>
                    <th className="align-right">Open → close</th>
                    <th className="align-right">Reported P&amp;L / amount</th>
                    <th>Fees / tax in report</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.sample.map((transaction) => (
                    <tr key={`${transaction.row_number}-${transaction.event_at}`}>
                      <td>{dateTime(transaction.event_at)}</td>
                      <td>{transactionLabel(transaction)}</td>
                      <td>{transaction.symbol ?? transaction.description ?? "—"}</td>
                      <td className="align-right tabular">
                        {transaction.quantity ?? "—"}
                      </td>
                      <td className="align-right tabular">{pricePair(transaction)}</td>
                      <td className="align-right tabular">
                        {money(
                          transaction.reported_profit ?? transaction.amount,
                          transaction.currency_code,
                        )}
                      </td>
                      <td className="muted-cell">{charges(transaction)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}
        {message && <div className="market-feedback" role="status">{message}</div>}
        {error && <div className="inline-error" role="alert">{error}</div>}
        <section className="broker-history-section">
          <div className="panel-heading">
            <div>
              <div className="eyebrow">Stored statement rows</div>
              <h3>{total} transaction record(s)</h3>
            </div>
            <button
              className="button button-quiet button-small"
              type="button"
              onClick={() => void loadHistory()}
              disabled={loadingHistory}
            >
              <RefreshCw size={13} /> Refresh
            </button>
          </div>
          {visibleBatches.length > 0 && (
            <div className="broker-import-batches">
              {visibleBatches.map((transaction) => (
                <span key={transaction.import_batch_id}>
                  Imported file · {transaction.import_batch_id.slice(0, 8)}
                  <button
                    className="button button-quiet button-small"
                    type="button"
                    onClick={() => void removeImport(transaction.import_batch_id)}
                    disabled={deletingBatchId === transaction.import_batch_id}
                    title="Remove all history rows from this import"
                  >
                    <Trash2 size={12} />
                    {deletingBatchId === transaction.import_batch_id ? "Removing…" : "Remove"}
                  </button>
                </span>
              ))}
            </div>
          )}
          {transactions.length > 0 ? (
            <>
              <div className="table-scroll broker-import-table">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Date</th>
                      <th>Record</th>
                      <th>Instrument / details</th>
                      <th className="align-right">Quantity</th>
                      <th className="align-right">Open → close</th>
                      <th className="align-right">Reported P&amp;L / amount</th>
                      <th>Fees / tax in report</th>
                      <th className="align-right">Tax estimate</th>
                    </tr>
                  </thead>
                  <tbody>
                    {transactions.map((transaction) => (
                      <tr key={transaction.id}>
                        <td>
                          {dateTime(transaction.event_at)}
                          {transaction.opened_at && (
                            <small className="quote-timestamp">
                              Opened {dateTime(transaction.opened_at)}
                            </small>
                          )}
                        </td>
                        <td>{transactionLabel(transaction)}</td>
                        <td>
                          {transaction.symbol ?? transaction.description ?? "—"}
                          {transaction.direction && (
                            <small className="quote-timestamp">
                              {transaction.direction} · {transaction.currency_code}
                            </small>
                          )}
                        </td>
                        <td className="align-right tabular">{transaction.quantity ?? "—"}</td>
                        <td className="align-right tabular">{pricePair(transaction)}</td>
                        <td className="align-right tabular">
                          {money(
                            transaction.reported_profit ?? transaction.amount,
                            transaction.currency_code,
                          )}
                          {transaction.balance_after !== null && (
                            <small className="quote-timestamp">
                              Balance {money(transaction.balance_after, transaction.currency_code)}
                            </small>
                          )}
                        </td>
                        <td className="muted-cell">{charges(transaction)}</td>
                        <td
                          className="align-right tabular"
                          title={transaction.tax_estimate_warnings.join(" ")}
                        >
                          {transaction.estimated_tax === null
                            ? taxLabel(transaction.estimated_tax_status)
                            : `${money(transaction.estimated_tax, transaction.currency_code)} · ${taxLabel(transaction.estimated_tax_status)}`}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {transactions.length < total && (
                <button
                  className="button button-secondary button-small broker-load-more"
                  type="button"
                  onClick={() => void loadHistory(transactions.length, true)}
                  disabled={loadingHistory}
                >
                  {loadingHistory ? "Loading…" : "Load more"}
                </button>
              )}
            </>
          ) : (
            <p className="quiet-copy">
              {loadingHistory
                ? "Loading imported activity…"
                : "No broker history imported for this account yet."}
            </p>
          )}
        </section>
        <div className="modal-actions">
          <button className="button button-secondary" type="button" onClick={onClose}>
            Close
          </button>
        </div>
      </section>
    </div>
  );
}
