import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { FileText, Download, ArrowRight, ArrowUpRight } from "lucide-react";
import { api } from "./api";
import type { Bag } from "./types";
import {
  PageIntro,
  Empty,
  ErrorBox,
  Badge,
  SectionHeading,
  Markdown,
  dateTime,
  download,
} from "./ui";
export default function ReportsPage({
  openStock,
}: {
  openStock: (ticker: string) => void;
}) {
  const reports = useQuery({
      queryKey: ["reports"],
      queryFn: () => api<{ items: Bag[] }>("/reports"),
    }),
    [selected, setSelected] = useState<Bag | null>(null);
  return (
    <>
      <PageIntro
        eyebrow="YOUR RESEARCH, WITH A PAPER TRAIL"
        title="Saved research"
        subtitle="Keep the evidence and assumptions behind a decision, as they were recorded."
      />
      {reports.isError && <ErrorBox error={reports.error} />}
      <section className="panel">
        <SectionHeading
          title={
            selected
              ? `${selected.ticker} research report`
              : "Your research library"
          }
        >
          {selected && (
            <button
              className="button secondary small"
              onClick={() => setSelected(null)}
            >
              Back to library
            </button>
          )}
        </SectionHeading>
        {selected ? (
          <>
            <div className="report-toolbar">
              <span>Saved {dateTime(selected.created_at)}</span>
              <div className="action-group">
                <button
                  className="button secondary small"
                  onClick={() =>
                    download(
                      `${selected.ticker}-research.md`,
                      selected.markdown || selected.report?.markdown || "",
                    )
                  }
                >
                  <Download size={14} />
                  Export
                </button>
                <button
                  className="button primary small"
                  onClick={() => openStock(selected.ticker)}
                >
                  Refresh research <ArrowUpRight size={14} />
                </button>
              </div>
            </div>
            <Markdown
              text={
                selected.markdown ||
                selected.report?.markdown ||
                "No report content was saved."
              }
            />
          </>
        ) : reports.data?.items?.length ? (
          <div className="report-grid">
            {reports.data.items.map((report) => (
              <button
                className="report-card"
                key={report.id}
                onClick={() => setSelected(report)}
              >
                <FileText size={24} />
                <Badge>Research snapshot</Badge>
                <h3>{report.ticker}</h3>
                <p>{dateTime(report.created_at)}</p>
                <span>
                  Open saved report <ArrowRight size={14} />
                </span>
              </button>
            ))}
          </div>
        ) : (
          <Empty
            title="Build a library of conviction"
            icon={<FileText size={28} />}
          >
            Open a stock’s Research report tab and save a snapshot. Reports
            retain their original date and data limitations.
          </Empty>
        )}
      </section>
    </>
  );
}
