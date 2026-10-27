"""Import authorized Forex Factory weekly exports; deliberately no web scraper.

The interface can be replaced by another licensed calendar provider. Importing a file
is not a grant of rights to republish its contents.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
from datetime import datetime, timezone
from typing import Protocol
from urllib.parse import urlparse
from xml.etree import ElementTree
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

UTC = timezone.utc
MAX_BYTES = 2_000_000
MAX_EVENTS = 10_000
SOURCE_URL = "https://www.forexfactory.com/calendar"


class CalendarProvider(Protocol):
    def parse(self, content: str, format: str = "json", source_timezone: str = "America/New_York") -> list[dict]: ...


def parse_quantity(value: object) -> dict:
    """Percentages stay in percentage points; K/M/B/T expand into base units."""
    raw = "" if value is None else str(value).strip()
    normalized = raw.replace("−", "-").replace(",", "").replace(" ", "")
    match = re.fullmatch(r"([+-]?(?:\d+(?:\.\d*)?|\.\d+))([KMBT])?(%)?", normalized, re.I)
    if not match or (match.group(2) and match.group(3)):
        return {"raw": raw, "value": None, "unit": None}
    number = float(match.group(1)) * {None: 1, "K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}[match.group(2).upper() if match.group(2) else None]
    if not math.isfinite(number):
        return {"raw": raw, "value": None, "unit": None}
    return {"raw": raw, "value": number, "unit": "percent" if match.group(3) else "number"}


def _localize(naive: datetime, zone: ZoneInfo) -> datetime:
    possibilities = []
    for fold in (0, 1):
        candidate = naive.replace(tzinfo=zone, fold=fold)
        if candidate.astimezone(UTC).astimezone(zone).replace(tzinfo=None) == naive:
            possibilities.append(candidate)
    if not possibilities:
        raise ValueError(f"Nonexistent local time {naive.isoformat()} in {zone.key}; supply an explicit UTC offset")
    if len({item.utcoffset() for item in possibilities}) > 1:
        raise ValueError(f"Ambiguous local time {naive.isoformat()} in {zone.key}; supply an explicit UTC offset")
    return possibilities[0]


def parse_timestamp(value: object, source_timezone: str = "America/New_York") -> str | None:
    if value is None or str(value).strip() == "":
        return None
    raw = str(value).strip()
    try:
        zone = ZoneInfo(source_timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("Unknown source time zone") from exc
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        dt = None
        for pattern in ("%m-%d-%Y %I:%M%p", "%m/%d/%Y %I:%M%p", "%Y-%m-%d %H:%M", "%m-%d-%Y %H:%M", "%m/%d/%Y %H:%M", "%Y%m%dT%H%M%SZ", "%Y%m%dT%H%M%S"):
            try:
                dt = datetime.strptime(raw, pattern)
                if pattern.endswith("Z"):
                    dt = dt.replace(tzinfo=UTC)
                break
            except ValueError:
                continue
        if dt is None:
            raise ValueError(f"Unrecognized event timestamp: {raw[:80]}")
    if dt.tzinfo is None:
        dt = _localize(dt, zone)
    return dt.astimezone(UTC).isoformat()


def _clean_keys(record: dict) -> dict:
    return {re.sub(r"[^a-z0-9]", "", str(key).lower()): value for key, value in record.items()}


def _ics(content: str) -> list[dict]:
    # RFC 5545 line unfolding. Do not interpret escaped content as HTML.
    lines = re.sub(r"\r?\n[ \t]", "", content).splitlines()
    records, current = [], None
    for line in lines:
        if line.strip() == "BEGIN:VEVENT":
            current = {}
        elif line.strip() == "END:VEVENT":
            if current is not None:
                records.append(current)
            current = None
        elif current is not None and ":" in line:
            property_, value = line.split(":", 1)
            parts = property_.split(";")
            name = parts[0].upper()
            params = dict(part.split("=", 1) for part in parts[1:] if "=" in part)
            value = value.replace("\\n", "\n").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")
            if name == "DTSTART":
                if params.get("VALUE") == "DATE" or re.fullmatch(r"\d{8}", value):
                    current["date"] = datetime.strptime(value, "%Y%m%d").date().isoformat()
                    current["time"] = "All Day"
                else:
                    current["scheduled_at"] = value
                    if "TZID" in params:
                        current["source_timezone"] = params["TZID"].strip('"')
            elif name == "SUMMARY":
                current["title"] = value
            elif name == "UID":
                current["source_id"] = value
            elif name == "URL":
                current["source_url"] = value
            elif name == "LAST-MODIFIED":
                current["last_updated"] = value
            elif name == "STATUS":
                current["status"] = value
            elif name == "DESCRIPTION":
                current["description"] = value
                for detail in value.splitlines():
                    match = re.match(r"(Currency|Country|Impact|Forecast|Previous|Actual|Revised Previous)\s*:\s*(.*)", detail, re.I)
                    if match:
                        current[match.group(1).lower().replace(" ", "_")] = match.group(2)
            elif name in {"CATEGORIES", "X-IMPACT", "X-CURRENCY", "X-COUNTRY"}:
                key = {"CATEGORIES": "impact", "X-IMPACT": "impact", "X-CURRENCY": "currency", "X-COUNTRY": "country"}[name]
                current[key] = value
    if current is not None:
        raise ValueError("Unclosed ICS event")
    return records


def _safe_url(value: object) -> str:
    candidate = str(value or "")
    parts = urlparse(candidate)
    if parts.scheme in {"https", "http"} and parts.netloc and not parts.username and not parts.password:
        return candidate
    return SOURCE_URL


class ForexFactoryCalendarProvider:
    name = "Forex Factory (authorized file import)"

    def parse(self, content: str, format: str = "json", source_timezone: str = "America/New_York") -> list[dict]:
        if len(content.encode("utf-8")) > MAX_BYTES:
            raise ValueError("Calendar file exceeds 2 MB")
        try:
            ZoneInfo(source_timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Unknown source time zone") from exc
        format = format.lower().lstrip(".")
        if format == "json":
            parsed = json.loads(content)
            records = parsed.get("events") if isinstance(parsed, dict) else parsed
        elif format == "csv":
            records = list(csv.DictReader(io.StringIO(content.lstrip("\ufeff"))))
        elif format == "xml":
            if re.search(r"<!\s*(?:DOCTYPE|ENTITY)", content, re.I):
                raise ValueError("XML document types and entities are not allowed")
            root = ElementTree.fromstring(content)
            records = [{child.tag: child.text or "" for child in event} for event in root.findall(".//event")]
        elif format == "ics":
            if "BEGIN:VCALENDAR" not in content:
                raise ValueError("Invalid ICS calendar")
            records = _ics(content)
        else:
            raise ValueError("Use json, csv, xml or ics")
        if not isinstance(records, list) or len(records) > MAX_EVENTS:
            raise ValueError("Expected a list of at most 10000 events")
        now = datetime.now(UTC).isoformat()
        unique = {}
        for position, record in enumerate(records):
            if not isinstance(record, dict):
                raise ValueError(f"Event {position + 1} must be an object")
            item = _clean_keys(record)
            title = str(item.get("title") or item.get("name") or item.get("event") or "").strip()
            if not title or len(title) > 500:
                raise ValueError(f"Event {position + 1} needs a title of 1–500 characters")
            zone = str(item.get("sourcetimezone") or source_timezone)
            date = str(item.get("date") or "").strip()
            time = str(item.get("time") or "").strip()
            timestamp = item.get("scheduledat") or item.get("datetime")
            precision = "time"
            if timestamp and re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(timestamp).strip()):
                date = str(timestamp).strip()
                scheduled = None
                precision = "date"
            elif timestamp:
                scheduled = parse_timestamp(timestamp, zone)
            elif date and ("T" in date or re.search(r"\d:\d", date)):
                scheduled = parse_timestamp(date, zone)
            elif date and time and time.lower() not in {"all day", "tentative", "tba", "unknown"}:
                scheduled = parse_timestamp(f"{date} {time}", zone)
            else:
                scheduled = None
                precision = "date" if date else "unknown"
            impact_raw = str(item.get("impact") or "Unknown").strip().lower()
            impact = "High" if "high" in impact_raw else "Medium" if "med" in impact_raw else "Low" if "low" in impact_raw else "Non-Economic" if any(x in impact_raw for x in ("holiday", "non-economic")) else "Unknown"
            currency = str(item.get("currency") or item.get("country") or "").upper().strip()
            country = str(item.get("country") or currency).upper().strip()
            status_raw = str(item.get("status") or "").lower().strip()
            quantities = {key: parse_quantity(item.get(re.sub(r"[^a-z0-9]", "", key))) for key in ("forecast", "previous", "actual", "revised_previous")}
            if status_raw in {"cancelled", "canceled"}:
                status = "canceled"
            elif status_raw in {"delayed", "postponed"}:
                status = "delayed"
            elif status_raw == "revised":
                status = "revised"
            elif quantities["actual"]["value"] is not None:
                status = "released"
            else:
                status = "scheduled"
            source_id = str(item.get("sourceid") or item.get("id") or "") or None
            identity = f"forexfactory|{source_id}" if source_id else "|".join((title.casefold(), currency, scheduled or date))
            if scheduled:
                scheduled_date = datetime.fromisoformat(scheduled).astimezone(ZoneInfo(zone)).date().isoformat()
            elif date:
                parsed_date = None
                for pattern in ("%Y-%m-%d", "%m-%d-%Y", "%m/%d/%Y", "%Y%m%d"):
                    try:
                        parsed_date = datetime.strptime(date, pattern).date().isoformat()
                        break
                    except ValueError:
                        continue
                if parsed_date is None:
                    raise ValueError(f"Unrecognized event date: {date[:80]}")
                scheduled_date = parsed_date
            else:
                scheduled_date = None
            event = {
                "id": hashlib.sha256(identity.encode()).hexdigest()[:24],
                "source_id": source_id,
                "title": title, "country": country, "currency": currency,
                "scheduled_at": scheduled, "scheduled_date": scheduled_date,
                "time_precision": precision, "source_timezone": zone,
                "impact": impact, "status": status,
                "source_url": _safe_url(item.get("sourceurl") or item.get("url")),
                "description": str(item.get("description") or "")[:10000] or None,
                "last_updated": parse_timestamp(item.get("lastupdated"), zone) or now,
                "available_at": parse_timestamp(item.get("availableat") or item.get("releasedat"), zone),
                "imported_at": now, "source": self.name,
                "quantities": quantities,
                **{key: value["raw"] or None for key, value in quantities.items()},
            }
            if event["id"] not in unique or event["last_updated"] >= unique[event["id"]]["last_updated"]:
                unique[event["id"]] = event
        return sorted(unique.values(), key=lambda row: (row["scheduled_at"] or row["scheduled_date"] or "9999", row["title"]))
