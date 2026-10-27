import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CalendarDays,
  Upload,
  Check,
  X,
  LoaderCircle,
  ChevronDown,
  Clock3,
} from "lucide-react";
import { api, post } from "./api";
import type { Bag, CalendarData, CalendarEvent } from "./types";
import {
  PageIntro,
  Empty,
  ErrorBox,
  Badge,
  SectionHeading,
  LinkOut,
  Limitations,
  label,
  dateTime,
  displayEventValue,
} from "./ui";
export default function CalendarPage({
  onToast,
}: {
  onToast: (text: string) => void;
}) {
  const [days, setDays] = useState(7),
    [country, setCountry] = useState(""),
    [impact, setImpact] = useState(""),
    [timezone, setTimezone] = useState(
      Intl.DateTimeFormat().resolvedOptions().timeZone || "America/Los_Angeles",
    ),
    [startDate, setStartDate] = useState(""),
    [endDate, setEndDate] = useState(""),
    [showImport, setShowImport] = useState(false),
    [format, setFormat] = useState("json"),
    [content, setContent] = useState(""),
    [sourceTimezone, setSourceTimezone] = useState("America/New_York"),
    [replaceExisting, setReplaceExisting] = useState(false),
    [now, setNow] = useState(Date.now());
  const client = useQueryClient();
  const calendar = useQuery({
    queryKey: ["calendar", days, timezone, startDate, endDate],
    queryFn: () =>
      api<CalendarData>(
        `/economic-calendar?days=${days}&timezone=${encodeURIComponent(timezone)}${startDate ? "&start_date=" + startDate : ""}${endDate ? "&end_date=" + endDate : ""}`,
      ),
  });
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => window.clearInterval(id);
  }, []);
  const imported = useMutation({
    mutationFn: () =>
      post<Bag>("/economic-calendar/import", {
        content,
        format,
        source_timezone: sourceTimezone,
        replace_existing: replaceExisting,
      }),
    onSuccess: (data) => {
      client.invalidateQueries({ queryKey: ["calendar"] });
      client.invalidateQueries({ queryKey: ["research"] });
      setShowImport(false);
      setContent("");
      onToast(
        `Calendar imported. ${data.count ?? data.imported ?? data.events?.length ?? "Available"} events processed.`,
      );
    },
    onError: (error) => onToast(error.message),
  });
  const allEvents = calendar.data?.events || [];
  const filtered = allEvents.filter(
    (e) =>
      (!country || e.currency === country || e.country === country) &&
      (!impact || e.impact?.toLowerCase() === impact.toLowerCase()),
  );
  const nextHigh = allEvents
    .filter(
      (e) =>
        String(e.impact).toLowerCase() === "high" &&
        e.scheduled_at &&
        new Date(e.scheduled_at).getTime() > now &&
        !/cancel/i.test(e.status || ""),
    )
    .sort((a, b) =>
      String(a.scheduled_at).localeCompare(String(b.scheduled_at)),
    )[0];
  const countdown = nextHigh
    ? Math.max(
        0,
        Math.floor((new Date(nextHigh.scheduled_at!).getTime() - now) / 60000),
      )
    : null;
  const groups = filtered.reduce<Record<string, CalendarEvent[]>>((acc, e) => {
    let day = "Time not specified";
    if (e.scheduled_at) {
      try {
        day = new Intl.DateTimeFormat("en-US", {
          weekday: "long",
          month: "long",
          day: "numeric",
          timeZone: timezone,
        }).format(new Date(e.scheduled_at));
      } catch {
        day = "Invalid date";
      }
    }
    (acc[day] ??= []).push(e);
    return acc;
  }, {});
  const countries = Array.from(
    new Set(allEvents.map((e) => e.currency || e.country).filter(Boolean)),
  ).sort();
  return (
    <>
      <PageIntro
        eyebrow="THE MARKET HAS A CALENDAR"
        title="Know what’s ahead"
        subtitle="Scheduled catalysts, expected impact and the limits of what we know."
      >
        <button
          className="button primary"
          onClick={() => setShowImport(!showImport)}
        >
          <Upload size={15} />
          Import calendar
        </button>
      </PageIntro>
      <div className="calendar-summary-grid">
        <section className="panel calendar-source">
          <span className="calendar-source-icon">
            <CalendarDays size={26} />
          </span>
          <div>
            <p className="eyebrow">ECONOMIC EVENT SOURCE</p>
            <h3>Forex Factory</h3>
            <p>
              Authorized export import <span>·</span> Source kept distinct from
              company news
            </p>
          </div>
          <LinkOut href="https://www.forexfactory.com/calendar">
            View source
          </LinkOut>
        </section>
        <section className="panel next-event">
          <div>
            <p className="eyebrow">
              <span className="amber-dot" />
              NEXT HIGH-IMPACT EVENT
            </p>
            <h3>{nextHigh?.title || "Calendar coverage needed"}</h3>
            <p>
              {nextHigh
                ? dateTime(nextHigh.scheduled_at, timezone)
                : "Import a current export to review scheduled catalysts."}
            </p>
          </div>
          {countdown != null && (
            <strong>
              {countdown >= 1440 ? `${Math.floor(countdown / 1440)}d ` : ""}
              {Math.floor((countdown % 1440) / 60)}h {countdown % 60}m
            </strong>
          )}
        </section>
      </div>
      {showImport && (
        <section className="panel import-panel">
          <SectionHeading
            eyebrow="BRING YOUR AUTHORIZED SOURCE FILE"
            title="Import a calendar export"
          >
            <button
              className="icon-button"
              onClick={() => setShowImport(false)}
              aria-label="Close import"
            >
              <X size={18} />
            </button>
          </SectionHeading>
          <p>
            Use a Forex Factory export you are authorized to use. Imports
            preserve source values and cannot infer missing actuals, release
            times or historical revisions.
          </p>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              imported.mutate();
            }}
          >
            <div className="form-grid">
              <label>
                Export format
                <select
                  value={format}
                  onChange={(e) => setFormat(e.target.value)}
                >
                  {["json", "csv", "xml", "ics"].map((f) => (
                    <option key={f} value={f}>
                      {f.toUpperCase()}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Source timezone (for naive times)
                <input
                  value={sourceTimezone}
                  onChange={(e) => setSourceTimezone(e.target.value)}
                  required
                />
              </label>
            </div>
            <label className="file-picker">
              <Upload size={18} />
              <span>Choose an exported calendar file</span>
              <input
                type="file"
                accept=".json,.csv,.xml,.ics"
                onChange={async (e) => {
                  const file = e.target.files?.[0];
                  if (!file) return;
                  if (file.size > 2_000_000) {
                    onToast(
                      "Please choose a calendar export smaller than 2 MB.",
                    );
                    return;
                  }
                  const extension = file.name.split(".").pop()?.toLowerCase();
                  if (
                    extension &&
                    ["json", "csv", "xml", "ics"].includes(extension)
                  )
                    setFormat(extension);
                  setContent(await file.text());
                }}
              />
            </label>
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={replaceExisting}
                onChange={(e) => setReplaceExisting(e.target.checked)}
              />
              <span>
                Replace previously imported calendar
                <small>
                  Use this for a refreshed export with rescheduled events. Prior
                  imported events are replaced; you can reload your original
                  file to restore its coverage.
                </small>
              </span>
            </label>
            <label>
              Or paste export contents
              <textarea
                value={content}
                onChange={(e) => setContent(e.target.value)}
                placeholder="Paste the source export contents here"
                rows={7}
                maxLength={2_000_000}
                required
              />
            </label>
            {imported.isError && <ErrorBox error={imported.error} />}
            <button
              className="button primary"
              disabled={imported.isPending || !content.trim()}
            >
              {imported.isPending ? (
                <LoaderCircle className="spin" size={15} />
              ) : (
                <Check size={15} />
              )}
              Validate & import
            </button>
          </form>
        </section>
      )}
      <section className="panel calendar-panel">
        <SectionHeading
          eyebrow="SCHEDULED EVENTS, IN YOUR TIMEZONE"
          title="Economic calendar"
        >
          <Badge>{label(calendar.data?.status || "Import required")}</Badge>
        </SectionHeading>
        <div className="calendar-filters">
          <label>
            Event window
            <select
              value={days}
              onChange={(e) => setDays(Number(e.target.value))}
            >
              <option value={1}>Next 24 hours</option>
              <option value={3}>Next 3 days</option>
              <option value={7}>Next 7 days</option>
              <option value={30}>Next 30 days</option>
            </select>
          </label>
          <label>
            Currency / country
            <select
              value={country}
              onChange={(e) => setCountry(e.target.value)}
            >
              <option value="">All regions</option>
              {countries.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>
          <label>
            Expected impact
            <select value={impact} onChange={(e) => setImpact(e.target.value)}>
              <option value="">All impacts</option>
              <option value="High">High</option>
              <option value="Medium">Medium</option>
              <option value="Low">Low</option>
            </select>
          </label>
          <label>
            Display timezone
            <select
              value={timezone}
              onChange={(e) => setTimezone(e.target.value)}
            >
              {Array.from(
                new Set([
                  timezone,
                  "America/Los_Angeles",
                  "America/New_York",
                  "Europe/London",
                  "Europe/Berlin",
                  "Asia/Tokyo",
                  "Asia/Shanghai",
                  "UTC",
                ]),
              ).map((z) => (
                <option key={z}>{z}</option>
              ))}
            </select>
          </label>
          <label>
            From date
            <input
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
            />
          </label>
          <label>
            Through date
            <input
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
            />
          </label>
        </div>
        {calendar.data?.coverage?.end &&
          new Date(calendar.data.coverage.end).getTime() < now && (
            <div className="notice warning">
              <Clock3 size={16} />
              <div>
                <strong>Imported calendar coverage has ended.</strong>
                <p>
                  The source file ends{" "}
                  {dateTime(calendar.data.coverage.end, timezone)}. Import a
                  current authorized export to assess upcoming event risk.
                </p>
              </div>
            </div>
          )}
        {calendar.isError && (
          <ErrorBox error={calendar.error} onRetry={() => calendar.refetch()} />
        )}
        {calendar.isLoading ? (
          <div className="loading-strip">
            <LoaderCircle size={16} className="spin" />
            Loading imported calendar…
          </div>
        ) : filtered.length ? (
          <div className="calendar-events">
            {Object.entries(groups).map(([day, events]) => (
              <div className="event-day" key={day}>
                <h3>
                  {day}
                  <span>{events.length} events</span>
                </h3>
                <div className="table-scroll">
                  <table className="calendar-table">
                    <thead>
                      <tr>
                        <th>Time / currency</th>
                        <th>Economic event</th>
                        <th>Impact</th>
                        <th>Previous</th>
                        <th>Forecast</th>
                        <th>Actual</th>
                        <th>Surprise</th>
                        <th>Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {events.map((e) => (
                        <tr
                          key={e.id}
                          className={
                            /cancel/i.test(e.status || "") ? "canceled" : ""
                          }
                        >
                          <td>
                            <strong>
                              {e.scheduled_at
                                ? new Intl.DateTimeFormat("en-US", {
                                    hour: "2-digit",
                                    minute: "2-digit",
                                    hour12: false,
                                    timeZone: timezone,
                                  }).format(new Date(e.scheduled_at))
                                : "TBD"}
                            </strong>
                            <span className="currency-code">
                              {e.currency || e.country || "—"}
                            </span>
                          </td>
                          <td className="event-name">
                            <LinkOut href={e.source_url}>{e.title}</LinkOut>
                            {e.revised_previous != null && (
                              <small>
                                Revised previous: {String(e.revised_previous)}
                              </small>
                            )}
                          </td>
                          <td>
                            <span
                              className={`impact-label ${String(e.impact).toLowerCase()}`}
                            >
                              <span>▰▰▰</span>
                              {e.impact || "Unknown"}
                            </span>
                          </td>
                          <td>{displayEventValue(e.previous)}</td>
                          <td>{displayEventValue(e.forecast)}</td>
                          <td>
                            <strong>{displayEventValue(e.actual)}</strong>
                          </td>
                          <td>
                            {displayEventValue(
                              e.economic_surprise ?? e.surprise,
                            )}
                          </td>
                          <td>
                            <Badge>{e.status || "scheduled"}</Badge>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <Empty
            title={
              allEvents.length
                ? "No events match these filters"
                : "Your calendar is ready for a source"
            }
            icon={<CalendarDays size={30} />}
          >
            {allEvents.length
              ? "Adjust the date, impact or region filters to view more events."
              : "Import a current Forex Factory export to see upcoming announcements. An empty calendar does not mean there are no market events."}
            {!allEvents.length && (
              <button
                className="button secondary"
                onClick={() => setShowImport(true)}
              >
                <Upload size={14} />
                Import calendar
              </button>
            )}
          </Empty>
        )}
        <div className="calendar-legend">
          <span>
            <i className="legend-square red-bg" />
            High impact
          </span>
          <span>
            <i className="legend-square amber-bg" />
            Medium impact
          </span>
          <span>
            <i className="legend-square gray-bg" />
            Low impact
          </span>
          <span className="muted">
            Numeric surprise = actual − forecast; a positive number is not
            necessarily bullish.
          </span>
        </div>
        <Limitations items={calendar.data?.limitations} />
        {calendar.data?.coverage && (
          <details className="limitations">
            <summary>
              Source coverage <ChevronDown size={13} />
            </summary>
            {typeof calendar.data.coverage === "string" ? (
              <p>{calendar.data.coverage}</p>
            ) : (
              <div className="coverage-details">
                <p>
                  Imported events:{" "}
                  {calendar.data.coverage.event_count ?? "Unavailable"}
                </p>
                <p>
                  Coverage begins:{" "}
                  {dateTime(calendar.data.coverage.start, timezone)}
                </p>
                <p>
                  Coverage ends:{" "}
                  {dateTime(calendar.data.coverage.end, timezone)}
                </p>
                <p>
                  Last imported:{" "}
                  {dateTime(calendar.data.coverage.last_imported_at, timezone)}
                </p>
                <p>Display timezone: {timezone}</p>
              </div>
            )}
          </details>
        )}
      </section>
    </>
  );
}
