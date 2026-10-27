"""Small transactional persistence layer, shared by SQLite and PostgreSQL."""
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from sqlalchemy import JSON, DateTime, String, Text, create_engine, select, delete
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def utcnow():
    return datetime.now(timezone.utc)


def utc_iso(stamp):
    return (stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp.astimezone(timezone.utc)).isoformat()


class Base(DeclarativeBase):
    pass


class Cache(Base):
    __tablename__ = "provider_cache"
    key: Mapped[str] = mapped_column(String(160), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Watch(Base):
    __tablename__ = "watchlist"
    ticker: Mapped[str] = mapped_column(String(32), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Report(Base):
    __tablename__ = "reports"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    markdown: Mapped[str] = mapped_column(Text)


class CalendarEvent(Base):
    __tablename__ = "calendar_events"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)


class ScreeningRun(Base):
    __tablename__ = 'screening_runs'
    id: Mapped[str] = mapped_column(String(40),primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=utcnow,index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),nullable=True)
    status: Mapped[str] = mapped_column(String(24))
    payload: Mapped[dict] = mapped_column(JSON)


class Store:
    def __init__(self, url: str):
        if url.startswith("sqlite:///") and ":memory:" not in url:
            Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        kwargs = {"connect_args": {"check_same_thread": False, "timeout": 30}} if url.startswith("sqlite") else {"pool_pre_ping": True}
        if ":memory:" in url:
            from sqlalchemy.pool import StaticPool
            kwargs["poolclass"] = StaticPool
        self.engine = create_engine(url, **kwargs)
        self.session = sessionmaker(self.engine, expire_on_commit=False)
        self.lock = Lock()
        Base.metadata.create_all(self.engine)

    def cache_get(self, key: str):
        with self.session() as s:
            item = s.get(Cache, key)
            if item is None:
                return None
            updated = item.updated_at.replace(tzinfo=timezone.utc) if item.updated_at.tzinfo is None else item.updated_at
            return {"value": item.value, "updated_at": updated, "age": (utcnow() - updated).total_seconds()}

    def cache_set(self, key: str, value: dict):
        with self.lock, self.session.begin() as s:
            s.merge(Cache(key=key, value=value, updated_at=utcnow()))

    def watchlist(self):
        with self.session() as s:
            return [{"ticker": w.ticker, "created_at": utc_iso(w.created_at)} for w in s.scalars(select(Watch).order_by(Watch.created_at.desc()))]

    def add_watch(self, ticker: str):
        with self.lock, self.session.begin() as s:
            if s.get(Watch, ticker) is None:
                s.add(Watch(ticker=ticker))

    def remove_watch(self, ticker: str):
        with self.lock, self.session.begin() as s:
            s.execute(delete(Watch).where(Watch.ticker == ticker))

    def save_report(self, ticker: str, markdown: str):
        from uuid import uuid4
        with self.session.begin() as s:
            report = Report(id=str(uuid4()), ticker=ticker, created_at=utcnow(), markdown=markdown)
            s.add(report)
        return {"id": report.id, "ticker": ticker, "created_at": utc_iso(report.created_at), "markdown": markdown}

    def reports(self):
        with self.session() as s:
            return [{"id": r.id, "ticker": r.ticker, "created_at": utc_iso(r.created_at), "markdown": r.markdown} for r in s.scalars(select(Report).order_by(Report.created_at.desc()).limit(100))]

    def import_events(self, events: list[dict], replace_existing: bool = False):
        imported = 0
        with self.lock, self.session.begin() as s:
            if replace_existing:
                s.execute(delete(CalendarEvent))
            for event in events:
                existing = s.get(CalendarEvent, event["id"])
                if existing and existing.payload.get("last_updated", "") > event.get("last_updated", ""):
                    continue
                s.merge(CalendarEvent(id=event["id"], payload=event))
                imported += 1
        return imported

    def events(self):
        with self.session() as s:
            return [e.payload for e in s.scalars(select(CalendarEvent))]

    def save_screening(self,run_id,payload,status,published=False):
        with self.lock,self.session.begin() as s:
            row=s.get(ScreeningRun,run_id)
            if row is None:
                row=ScreeningRun(id=run_id,status=status,payload=payload)
                s.add(row)
            else:row.payload,row.status=payload,status
            if published:row.published_at=utcnow()

    def screening_runs(self,published_only=False,limit=100):
        with self.session() as s:
            query=select(ScreeningRun).order_by(ScreeningRun.created_at.desc()).limit(limit)
            if published_only:query=query.where(ScreeningRun.published_at.is_not(None))
            return [{'id':r.id,'created_at':utc_iso(r.created_at),'published_at':utc_iso(r.published_at) if r.published_at else None,'status':r.status,'payload':r.payload} for r in s.scalars(query)]
