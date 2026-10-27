"""Synthetic fixtures test formats without redistributing Forex Factory data."""
import json
from datetime import datetime, timezone

import pytest

from app.analysis.macro import analyze_macro, economic_surprise
from app.providers.calendar import ForexFactoryCalendarProvider, parse_quantity

UTC = timezone.utc
provider = ForexFactoryCalendarProvider()


def fixture(**overrides):
    return {"title": "Synthetic CPI m/m", "country": "USD", "date": "2026-10-26T08:30:00-04:00", "last_updated": "2026-10-26T13:00:00Z", "impact": "High", "forecast": "0.2%", "previous": "0.3%", **overrides}


def test_json_normalizes_utc_and_preserves_missing_actual():
    event = provider.parse(json.dumps([fixture()]))[0]
    assert event["scheduled_at"] == "2026-10-26T12:30:00+00:00"
    assert event["forecast"] == "0.2%"
    assert event["quantities"]["forecast"]["value"] == .2
    assert event["actual"] is None
    assert event["status"] == "scheduled"
    assert event["country"] == "USD"


@pytest.mark.parametrize("raw,number,unit", [("123K", 123000, "number"), ("-1.2M", -1200000, "number"), ("2B", 2e9, "number"), ("3.1%", 3.1, "percent"), ("1,200", 1200, "number"), ("−3.2%", -3.2, "percent"), ("4.00-4.25%", None, None), ("N/A", None, None), ("1e999", None, None), ("3K%", None, None)])
def test_numeric_formats(raw, number, unit):
    assert parse_quantity(raw)["value"] == number
    assert parse_quantity(raw)["unit"] == unit


def test_csv_and_xml_formats():
    csv = "Name,Currency,Date,Time,Impact,Forecast,Previous,Actual\nSynthetic Payrolls,USD,10-26-2026,8:30am,High,100K,90K,110K\n"
    xml = "<weeklyevents><event><title>Synthetic Payrolls</title><country>USD</country><date><![CDATA[10-26-2026]]></date><time><![CDATA[8:30am]]></time><impact>High</impact><forecast>100K</forecast><previous>90K</previous><actual>110K</actual></event></weeklyevents>"
    a, b = provider.parse(csv, "csv")[0], provider.parse(xml, "xml")[0]
    assert a["scheduled_at"] == b["scheduled_at"] == "2026-10-26T12:30:00+00:00"
    assert a["quantities"]["actual"]["value"] == b["quantities"]["actual"]["value"] == 110000


def test_ics_tzid_and_folded_lines():
    data = "BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:test-only\nSUMMARY:Synthetic\n  CPI\nDTSTART;TZID=America/New_York:20261026T083000\nDESCRIPTION:Currency: USD\\nImpact: High\\nForecast: 0.2%\nEND:VEVENT\nEND:VCALENDAR"
    event = provider.parse(data, "ics")[0]
    assert event["title"] == "Synthetic CPI"
    assert event["scheduled_at"] == "2026-10-26T12:30:00+00:00"
    assert event["currency"] == "USD"
    assert event["forecast"] == "0.2%"


def test_all_day_and_tentative_have_no_invented_release_time():
    for time in ("All Day", "Tentative", ""):
        event = provider.parse(json.dumps([fixture(date="2026-10-26", time=time)]))[0]
        assert event["scheduled_at"] is None
        assert event["time_precision"] == "date"
    event = provider.parse("BEGIN:VCALENDAR\nBEGIN:VEVENT\nSUMMARY:Synthetic Holiday\nDTSTART;VALUE=DATE:20261026\nEND:VEVENT\nEND:VCALENDAR", "ics")[0]
    assert event["scheduled_at"] is None


@pytest.mark.parametrize("date", ["2026-11-01T01:30:00", "2026-03-08T02:30:00"])
def test_dst_rejects_ambiguous_or_nonexistent_times(date):
    with pytest.raises(ValueError, match="local time"):
        provider.parse(json.dumps([fixture(date=date)]))


def test_dst_explicit_offsets_are_not_ambiguous():
    before = provider.parse(json.dumps([fixture(date="2026-11-01T01:30:00-04:00")]))[0]
    after = provider.parse(json.dumps([fixture(date="2026-11-01T01:30:00-05:00")]))[0]
    assert before["scheduled_at"] == "2026-11-01T05:30:00+00:00"
    assert after["scheduled_at"] == "2026-11-01T06:30:00+00:00"


def test_dedup_latest_revision_and_status():
    old = fixture(actual="0.2%", last_updated="2026-10-26T13:00:00Z")
    revised = fixture(actual="0.4%", revised_previous="0.1%", status="revised", last_updated="2026-10-26T14:00:00Z")
    events = provider.parse(json.dumps([revised, old]))
    assert len(events) == 1
    assert events[0]["actual"] == "0.4%"
    assert events[0]["revised_previous"] == "0.1%"
    assert events[0]["status"] == "revised"


def test_surprise_units_and_direction_not_always_positive():
    event = provider.parse(json.dumps([fixture(actual="0.4%")]))[0]
    result = economic_surprise(event, now=datetime(2026, 10, 27, tzinfo=UTC))
    assert result["value"] == pytest.approx(.2)
    assert result["unit"] == "percentage points"
    assert result["interpretation"] == "bearish"
    payroll = provider.parse(json.dumps([fixture(title="Synthetic Non-Farm Payrolls", actual="120K", forecast="100K")]))[0]
    assert economic_surprise(payroll, now=datetime(2026, 10, 27, tzinfo=UTC))["interpretation"] == "mixed"


@pytest.mark.parametrize("status", ["canceled", "cancelled", "delayed", "postponed"])
def test_canceled_or_delayed_release_has_no_surprise(status):
    event = provider.parse(json.dumps([fixture(actual="0.4%", status=status)]))[0]
    assert economic_surprise(event, now=datetime(2026, 10, 27, tzinfo=UTC))["value"] is None


def test_future_actual_and_delayed_availability_cannot_affect_earlier_decisions():
    event = provider.parse(json.dumps([fixture(actual="0.4%", available_at="2026-10-27T12:00:00Z")]))[0]
    for now in (datetime(2026, 10, 25, tzinfo=UTC), datetime(2026, 10, 26, 14, tzinfo=UTC)):
        assert economic_surprise(event, now=now)["value"] is None
        result = analyze_macro([event], {"sector": "Technology"}, now=now)
        assert result["score"] is None
    assert economic_surprise(event, now=datetime(2026, 10, 28, tzinfo=UTC))["value"] is not None


def test_macro_missing_data_abstains_and_marks_hypotheses():
    empty = analyze_macro([], {}, now=datetime(2026, 10, 25, tzinfo=UTC))
    assert empty["score"] is None
    assert empty["outlook"] == "Insufficient Data"
    events = provider.parse(json.dumps([fixture()]))
    result = analyze_macro(events, {"sector": "Technology", "industry": "Semiconductors"}, now=datetime(2026, 10, 25, tzinfo=UTC))
    assert result["score"] is None
    assert result["event_risk"]["level"] == "elevated"
    assert result["stock_impacts"][0]["evidence_type"] == "hypothesis"
    assert "1" in result["windows"]


def test_parser_rejects_entity_xml_unsafe_url_large_content_and_bad_timezone():
    with pytest.raises(ValueError, match="entities"):
        provider.parse('<!DOCTYPE x [<!ENTITY x SYSTEM "file:///etc/passwd">]><weeklyevents/>', "xml")
    with pytest.raises(ValueError, match="2 MB"):
        provider.parse(" " * 2000001)
    with pytest.raises(ValueError, match="time zone"):
        provider.parse("[]", source_timezone="invalid/place")
    event = provider.parse(json.dumps([fixture(url="javascript:alert(1)")]))[0]
    assert event["source_url"] == "https://www.forexfactory.com/calendar"


def test_mismatched_units_no_surprise():
    event = provider.parse(json.dumps([fixture(actual="3", forecast="2%")]))[0]
    assert economic_surprise(event, now=datetime(2026, 10, 27, tzinfo=UTC))["value"] is None


def test_source_id_stays_stable_when_schedule_changes():
    a = provider.parse(json.dumps([fixture(id="licensed-event-1")]))[0]
    b = provider.parse(json.dumps([fixture(id="licensed-event-1", date="2026-10-27T08:30:00-04:00")]))[0]
    assert a["id"] == b["id"]
    assert a["source_id"] == "licensed-event-1"
    assert a["scheduled_date"] == "2026-10-26"


def test_invalid_date_is_rejected_even_without_release_time():
    with pytest.raises(ValueError, match="event date"):
        provider.parse(json.dumps([fixture(date="potato")]))


def test_future_revision_cannot_influence_earlier_research():
    event = provider.parse(json.dumps([fixture(actual="0.4%", status="revised", last_updated="2026-10-28T14:00:00Z", available_at="2026-10-26T12:30:00Z")]))[0]
    assert economic_surprise(event, now=datetime(2026, 10, 27, tzinfo=UTC))["value"] is None
    assert economic_surprise(event, now=datetime(2026, 10, 29, tzinfo=UTC))["value"] is not None


def test_macro_policy_for_banks_is_not_automatic_bearish_vote():
    event = provider.parse(json.dumps([fixture(actual="0.4%", last_updated="2026-10-26T13:00:00Z")]))[0]
    result = analyze_macro([event], {"sector": "Financial Services", "industry": "Banks - Diversified"}, now=datetime(2026, 10, 27, tzinfo=UTC))
    assert result["recent_events"][0]["surprise"]["interpretation"] == "mixed"
    assert result["score"] == 5


def test_normalized_surprise_requires_comparable_known_history():
    history = []
    for month in range(1, 11):
        history += provider.parse(json.dumps([fixture(id=f"old-{month}", date=f"2026-{month:02d}-01T12:30:00Z", actual=f"{month / 10}%", forecast="0.2%", available_at=f"2026-{month:02d}-01T12:30:00Z", last_updated=f"2026-{month:02d}-01T13:00:00Z")]))
    current = provider.parse(json.dumps([fixture(id="current", date="2026-11-01T12:30:00Z", actual="0.4%", available_at="2026-11-01T12:30:00Z", last_updated="2026-11-01T13:00:00Z")]))[0]
    import statistics
    expected = .2 / statistics.stdev([month / 10 - .2 for month in range(1, 11)])
    assert economic_surprise(current, history, now=datetime(2026, 11, 2, tzinfo=UTC))["normalized"] == pytest.approx(expected)
    assert economic_surprise(current, history[:9], now=datetime(2026, 11, 2, tzinfo=UTC))["normalized"] is None


def test_date_only_scheduled_at_does_not_invent_midnight():
    event = provider.parse(json.dumps([fixture(date=None, scheduled_at="2026-10-26")]))[0]
    assert event["scheduled_at"] is None
    assert event["scheduled_date"] == "2026-10-26"
