import { Clock3, LoaderCircle, RefreshCw } from "lucide-react";
import { dateTime } from "./ui";
import { ApiError } from "./api";
import type { DataSectionStatus } from "./types";
export default function DataStatus({
  label,
  status,
  loading = false,
  error,
  onRetry,
}: {
  label: string;
  status?: DataSectionStatus;
  loading?: boolean;
  error?: unknown;
  onRetry?: () => void;
}) {
  const failure = status?.error;
  const text =
    failure?.message || (error instanceof Error ? error.message : "");
  const retryable =
    failure?.retryable ?? (!(error instanceof ApiError) || error.retryable);
  const cached = status?.status === "cached" || status?.cache_stale;
  const name =
    status?.status === "not_applicable"
      ? "Not applicable"
      : cached
        ? "Cached data"
        : loading && !status
          ? "Loading"
          : status?.status === "error" || error
            ? "Could not update"
            : status?.status === "unavailable"
              ? "Unavailable"
              : status?.status === "partial"
                ? "Partially available"
                : status
                  ? "Available"
                  : "Awaiting source";
  return (
    <div
      className={`data-status ${cached ? "cached" : failure || error ? "failed" : ""}`}
      role={failure || error ? "status" : undefined}
      aria-label={`${label} data status`}
    >
      {loading && !status ? (
        <LoaderCircle size={11} className="spin" />
      ) : (
        <Clock3 size={11} />
      )}
      <span>
        <strong>
          {label}: {name}
        </strong>
        {status?.fetched_at && <> · Updated {dateTime(status.fetched_at)}</>}
        {status?.cache_stale && (
          <> · Source refresh failed; this snapshot may be stale</>
        )}
        {text && <span className="data-status-message">{text}</span>}
      </span>
      {(failure || error || status?.status === "unavailable") &&
        retryable &&
        onRetry && (
          <button type="button" className="text-button" onClick={onRetry}>
            <RefreshCw size={10} />
            Retry
          </button>
        )}
    </div>
  );
}
