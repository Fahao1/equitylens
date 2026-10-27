import type { ReactNode } from "react";
import {
  CircleHelp,
  Layers3,
  RefreshCw,
  ExternalLink,
  ChevronDown,
} from "lucide-react";
import { safeUrl, ApiError } from "./api";
import type { Bag } from "./types";
export const num = (v: unknown, digits = 2) =>
  v != null && Number.isFinite(Number(v))
    ? Number(v).toLocaleString("en-US", {
        maximumFractionDigits: digits,
        minimumFractionDigits: digits,
      })
    : "—";
export const compact = (v: unknown) =>
  v != null && Number.isFinite(Number(v))
    ? Intl.NumberFormat("en-US", {
        notation: "compact",
        maximumFractionDigits: 2,
      }).format(Number(v))
    : "—";
export const pct = (v: unknown) =>
  v == null ? "—" : `${num(Number(v) * 100, 1)}%`;
export const label = (v: string) =>
  v.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
export const dateTime = (v: unknown, timezone?: string) => {
  if (!v) return "Not available";
  try {
    return new Intl.DateTimeFormat("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "numeric",
      minute: "2-digit",
      timeZone: timezone,
      timeZoneName: "short",
    }).format(new Date(String(v)));
  } catch {
    return String(v);
  }
};
export const dateOnly = (v: unknown) => {
  if (!v) return "—";
  try {
    return new Intl.DateTimeFormat("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
      timeZone: "UTC",
    }).format(new Date(String(v)));
  } catch {
    return String(v);
  }
};
export const strings = (value: any): string[] =>
  Array.isArray(value)
    ? value.map((v) =>
        typeof v === "string"
          ? v
          : typeof v?.explanation === "string"
            ? v.explanation
            : typeof v?.message === "string"
              ? v.message
              : typeof v?.text === "string"
                ? v.text
                : JSON.stringify(v),
      )
    : value
      ? [typeof value === "string" ? value : JSON.stringify(value)]
      : [];
export const currencySymbol = (code?: string) => {
  if (!code) return "";
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: code,
      maximumFractionDigits: 0,
    })
      .format(0)
      .replace(/[\d\s,.]/g, "");
  } catch {
    return code;
  }
};
export const scoreColor = (value: number | null | undefined) =>
  value == null
    ? "muted"
    : value >= 6.5
      ? "green"
      : value <= 3.5
        ? "red"
        : "amber";
export function IconBox({ children }: { children: ReactNode }) {
  return <span className="icon-box">{children}</span>;
}
export function Empty({
  title,
  children,
  icon = <Layers3 size={25} />,
}: {
  title: string;
  children?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <div className="empty">
      <div className="empty-icon">{icon}</div>
      <h3>{title}</h3>
      <div>{children}</div>
    </div>
  );
}
export function ErrorBox({
  error,
  onRetry,
}: {
  error: unknown;
  onRetry?: () => void;
}) {
  return (
    <div role="alert" className="notice error">
      <CircleHelp size={18} />
      <div>
        <strong>We couldn’t retrieve this data.</strong>
        <p>{error instanceof Error ? error.message : String(error)}</p>
      </div>
      {onRetry && (!(error instanceof ApiError) || error.retryable) && (
        <button className="button quiet small" onClick={onRetry}>
          Try again <RefreshCw size={13} />
        </button>
      )}
    </div>
  );
}
export function Badge({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: string;
}) {
  return <span className={`badge ${tone.toLowerCase()}`}>{children}</span>;
}
export function SectionHeading({
  eyebrow,
  title,
  children,
}: {
  eyebrow?: string;
  title: string;
  children?: ReactNode;
}) {
  return (
    <div className="section-heading">
      <div>
        {eyebrow && <p className="eyebrow">{eyebrow}</p>}
        <h2>{title}</h2>
      </div>
      {children}
    </div>
  );
}
export function LinkOut({
  href,
  children,
}: {
  href: unknown;
  children: ReactNode;
}) {
  const url = safeUrl(href);
  return url ? (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      className="source-link"
    >
      {children}
      <ExternalLink size={12} />
    </a>
  ) : (
    <span>{children}</span>
  );
}
export function Evidence({
  items,
  empty = "No evidence available.",
}: {
  items: any;
  empty?: string;
}) {
  const values = strings(items);
  return values.length ? (
    <ul className="evidence-list">
      {values.map((x, i) => (
        <li key={i}>
          <span className="evidence-dot" />
          {x}
        </li>
      ))}
    </ul>
  ) : (
    <p className="muted small-text">{empty}</p>
  );
}
export function Limitations({ items }: { items: any }) {
  const list = strings(items);
  return list.length ? (
    <details className="limitations">
      <summary>
        <CircleHelp size={14} />
        {list.length} data {list.length === 1 ? "limitation" : "limitations"}
        <ChevronDown size={14} />
      </summary>
      <Evidence items={list} />
    </details>
  ) : null;
}
export function MetricGrid({ metrics }: { metrics: Bag }) {
  return (
    <div className="metric-grid">
      {Object.entries(metrics || {}).map(([key, value]) => (
        <div className="metric-cell" key={key}>
          <span>{label(key)}</span>
          <strong
            className={
              value != null && typeof value !== "number"
                ? "metric-text"
                : undefined
            }
          >
            {typeof value === "number"
              ? /margin|yield|growth|return_on|roe$|roa$|roic$|total_return|annualized_return|maximum_drawdown|buy_and_hold_return|benchmark_return|win_rate|dividend_fcf_payout|revenue_consistency|share_dilution|rd_to_revenue|effective_tax_rate|terminal_value_share|discount_rate/.test(
                  key,
                )
                ? pct(value)
                : Math.abs(value) >= 1e6
                  ? compact(value)
                  : num(value, /number_of_trades|^years$/.test(key) ? 0 : 2)
              : value == null
                ? "—"
                : Array.isArray(value)
                  ? value.join(", ")
                  : typeof value === "object"
                    ? JSON.stringify(value)
                    : String(value)}
          </strong>
        </div>
      ))}
    </div>
  );
}
export function InlineMarkdown({ text }: { text: string }) {
  return (
    <>
      {text.split(/(\[[^\]]+\]\(https?:\/\/[^)]+\))/g).map((part, index) => {
        const match = part.match(/^\[([^\]]+)\]\((https?:\/\/[^)]+)\)$/);
        return match ? (
          <a
            key={index}
            href={safeUrl(match[2])}
            target="_blank"
            rel="noopener noreferrer"
          >
            {match[1]}
          </a>
        ) : (
          part.replace(/\*\*/g, "")
        );
      })}
    </>
  );
}
export function Markdown({ text }: { text: string }) {
  return (
    <article className="report-markdown">
      {(text || "").split("\n").map((line, i) =>
        line.startsWith("### ") ? (
          <h3 key={i}>
            <InlineMarkdown text={line.slice(4)} />
          </h3>
        ) : line.startsWith("## ") ? (
          <h2 key={i}>
            <InlineMarkdown text={line.slice(3)} />
          </h2>
        ) : line.startsWith("# ") ? (
          <h1 key={i}>
            <InlineMarkdown text={line.slice(2)} />
          </h1>
        ) : line.startsWith("- ") ? (
          <p className="report-bullet" key={i}>
            • <InlineMarkdown text={line.slice(2)} />
          </p>
        ) : line.trim() ? (
          <p key={i}>
            <InlineMarkdown text={line} />
          </p>
        ) : (
          <br key={i} />
        ),
      )}
    </article>
  );
}

export function ScoreRing({
  value,
  large = false,
}: {
  value: number | null | undefined;
  large?: boolean;
}) {
  const v = value == null ? 0 : Math.max(0, Math.min(10, value));
  return (
    <div
      className={`score-ring ${large ? "large" : ""} ${scoreColor(value)}`}
      style={{ "--progress": `${v * 10}%` } as React.CSSProperties}
    >
      <div>
        <strong>{value == null ? "—" : num(value, 1)}</strong>
        <span>/10</span>
      </div>
    </div>
  );
}

export function PageIntro({
  eyebrow,
  title,
  subtitle,
  children,
}: {
  eyebrow: string;
  title: string;
  subtitle: string;
  children?: ReactNode;
}) {
  return (
    <div className="page-title-row">
      <div>
        <p className="eyebrow">
          <span className="tiny-line" />
          {eyebrow}
        </p>
        <h1>
          {title}
          <span className="green">.</span>
        </h1>
        <p className="subtitle">{subtitle}</p>
      </div>
      {children}
    </div>
  );
}
export function DataTable({ rows }: { rows: Bag[] }) {
  const keys = Array.from(new Set(rows.flatMap((r) => Object.keys(r)))).filter(
    (k) => !["values", "source"].includes(k),
  );
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            {keys.map((k) => (
              <th key={k}>{label(k)}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              {keys.map((k) => (
                <td key={k}>
                  {r[k] == null
                    ? "—"
                    : typeof r[k] === "number"
                      ? /margin|growth|yield|^return$|surprisePercent|total_return|maximum_drawdown|win_rate/.test(
                          k,
                        )
                        ? pct(r[k])
                        : Math.abs(r[k]) > 1e6
                          ? compact(r[k])
                          : num(r[k])
                      : typeof r[k] === "object"
                        ? JSON.stringify(r[k])
                        : String(r[k])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
export function download(filename: string, content: string) {
  const url = URL.createObjectURL(
    new Blob([content], { type: "text/markdown;charset=utf-8" }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}
export function displayEventValue(value: any): string {
  if (value == null || value === "") return "—";
  if (typeof value === "object")
    return displayEventValue(value.raw ?? value.value);
  return String(value);
}
