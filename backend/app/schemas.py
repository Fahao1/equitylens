from enum import Enum
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator
from app.providers.yahoo import validate_ticker


class Horizon(str, Enum):
    short = "short"
    swing = "swing"
    long = "long"


class Weights(BaseModel):
    financial: float = Field(.25, ge=0, le=1)
    valuation: float = Field(.20, ge=0, le=1)
    technical: float = Field(.20, ge=0, le=1)
    news: float = Field(.10, ge=0, le=1)
    macro: float = Field(.10, ge=0, le=1)
    risk: float = Field(.15, ge=0, le=1)

    @model_validator(mode="after")
    def total(self):
        if abs(sum(self.model_dump().values()) - 1) > 1e-6:
            raise ValueError("Scoring weights must sum to 1 (100%).")
        return self


class TradeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    horizon: Horizon = Horizon.swing
    risk_tolerance: Literal["low", "medium", "high"] = "medium"
    capital: float = Field(10000, gt=0, le=1e12)
    risk_per_trade: float = Field(.01, gt=0, le=.05)
    min_reward_risk: float = Field(2, ge=1, le=10)
    existing_shares: float = Field(0, ge=0, le=1e12)
    cost_basis: float | None = Field(None, gt=0)
    weights: Weights = Field(default_factory=Weights)
    commission_bps: float = Field(5, ge=0, le=100)
    slippage_bps: float = Field(5, ge=0, le=100)


class BacktestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    ticker: str
    period: Literal["1y", "5y", "max"] = "5y"
    starting_capital: float = Field(10000, gt=0, le=1e12)
    commission_bps: float = Field(5, ge=0, le=100)
    slippage_bps: float = Field(5, ge=0, le=100)
    risk_per_trade: float = Field(.01, gt=0, le=.05)
    fast_period: int = Field(20, ge=2, le=200)
    slow_period: int = Field(50, ge=3, le=500)
    benchmark_ticker: str = "SPY"
    strategy: Literal['sma','all','trend_following','breakout','mean_reversion','fundamental_value'] = 'sma'
    horizon: Horizon = Horizon.swing
    max_holding_bars: int = Field(20, ge=1, le=252)
    min_samples: int = Field(30, ge=30, le=1000)

    @field_validator("ticker", "benchmark_ticker")
    @classmethod
    def ticker_valid(cls, v):
        return validate_ticker(v)

    @model_validator(mode="after")
    def windows(self):
        if self.fast_period >= self.slow_period:
            raise ValueError("Fast average must be shorter than slow average.")
        return self


class TickerRequest(BaseModel):
    ticker: str

    @field_validator("ticker")
    @classmethod
    def ticker_valid(cls, v):
        return validate_ticker(v)


class CalendarImport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=2, max_length=2_000_000)
    format: Literal["json", "csv", "xml", "ics"] = "json"
    source_timezone: str = Field("America/New_York", max_length=64)
    replace_existing: bool = False


class CategoryResult(BaseModel):
    model_config = ConfigDict(extra="allow")
    score: float | None = Field(None, ge=0, le=10)
    confidence: float = Field(0, ge=0, le=1)
    signals: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class JsonResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class ResearchResponse(BaseModel):
    ticker: str
    as_of: str
    overview: dict[str, JsonValue]
    history: dict[str, JsonValue]
    technical: CategoryResult
    fundamentals: CategoryResult
    valuation: CategoryResult
    news: CategoryResult
    macro: CategoryResult
    risk: CategoryResult
    score: dict[str, JsonValue]
    trade_plan: dict[str, JsonValue]
    report: dict[str, JsonValue]
    data_quality: dict[str, JsonValue]
    quant_core: dict[str, JsonValue] | None = None

class DCFAssumptions(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    growth: float = Field(.05, ge=-.3, le=.3)
    discount_rate: float = Field(.10, gt=.01, le=.4)
    terminal_growth: float = Field(.02, ge=-.05, le=.05)
    years: int = Field(5, ge=1, le=20)
    base_fcf: float | None = Field(None, gt=0)
    shares: float | None = Field(None, gt=0)

    @model_validator(mode="after")
    def discount(self):
        if self.discount_rate - .01 <= self.terminal_growth:
            raise ValueError("All scenarios require discount rate above terminal growth, including optimistic discount rate minus 1%.")
        return self


class CalendarResponse(BaseModel):
    events: list[dict[str, JsonValue]]
    source: str
    status: str
    coverage: dict[str, JsonValue]
    limitations: list[str]


class HistoryResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    prices: list[dict[str, JsonValue]]
    source: str
    interval: str
    period: str


class SearchMatch(BaseModel):
    symbol: str
    name: str | None = None
    exchange: str | None = None
    asset_type: str | None = None


class SearchResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    query: str
    results: list[SearchMatch]
    source: str
    fetched_at: str | None = None
    cache_stale: bool = False
    cache_age_seconds: int = 0


class QuantValuationAssumptions(DCFAssumptions):
    enable_dcf: bool = False
    earnings_multiples: tuple[float,float,float] | None = None
    fcf_yields: tuple[float,float,float] | None = None

    @model_validator(mode='after')
    def ordered_scenarios(self):
        import math
        if self.earnings_multiples is not None and (not all(math.isfinite(v) and 0<v<=100 for v in self.earnings_multiples) or list(self.earnings_multiples)!=sorted(self.earnings_multiples)):
            raise ValueError('Earnings multiples must be positive ordered bear/base/bull values <=100.')
        if self.fcf_yields is not None and (not all(math.isfinite(v) and 0<v<=1 for v in self.fcf_yields) or list(self.fcf_yields)!=sorted(self.fcf_yields,reverse=True)):
            raise ValueError('FCF yields must be fractions in descending bear/base/bull order.')
        return self


class QuantRequest(TradeRequest):
    benchmark_ticker: str = 'SPY'
    min_samples: int = Field(30, ge=30, le=1000)
    max_holding_bars: int | None = Field(None, ge=1, le=252)
    margin_of_safety: float = Field(.2, ge=0, le=.6)
    valuation_assumptions: QuantValuationAssumptions | None = None
    peer_tickers: list[str] = Field(default_factory=list, max_length=5)

    @field_validator('benchmark_ticker')
    @classmethod
    def benchmark_valid(cls,value):return validate_ticker(value)

    @field_validator('peer_tickers')
    @classmethod
    def peers_valid(cls,values):return list(dict.fromkeys(validate_ticker(value) for value in values))
