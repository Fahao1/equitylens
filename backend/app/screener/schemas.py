from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,model_validator
from app.schemas import QuantValuationAssumptions
from app.providers.yahoo import validate_ticker

Horizon=Literal['short_term','long_term']
SHORT_WEIGHTS={'technical_strength':.30,'trade_setup_quality':.25,'momentum_volume':.15,'news_catalysts':.15,'fundamentals_risk':.15}
LONG_WEIGHTS={'financial_quality_growth':.30,'valuation_attractiveness':.25,'growth_outlook':.20,'financial_resilience':.15,'technical_entry_timing':.10}


class ScreenFilters(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    industries:list[str]=Field(default_factory=list,max_length=50)
    exchanges:list[str]=Field(default_factory=list,max_length=20)
    countries:list[str]=Field(default_factory=list,max_length=20)
    include_international:bool=False
    market_cap_min:float=Field(1e9,ge=0,le=1e15)
    market_cap_max:float | None=Field(None,gt=0,le=1e15)
    average_volume_min:float=Field(100000,ge=0,le=1e12)
    profitable_only:bool=False
    min_revenue_growth:float | None=Field(None,ge=-1,le=100)
    max_forward_pe:float | None=Field(None,gt=0,le=10000)
    min_valuation:float | None=Field(None,ge=0,le=10)
    min_technical:float | None=Field(None,ge=0,le=10)
    min_overall:float | None=Field(None,ge=0,le=10)

    @model_validator(mode='after')
    def valid_ranges(self):
        if self.market_cap_max is not None and self.market_cap_max<self.market_cap_min:raise ValueError('Maximum market cap must be at least the minimum.')
        for values in (self.industries,self.exchanges,self.countries):
            if any(not v.strip() or len(v)>120 or any(ord(c)<32 for c in v) for v in values):raise ValueError('Filter labels must contain 1–120 ordinary characters.')
        return self


class ScreenRequest(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    horizon:Horizon='short_term'
    filters:ScreenFilters=Field(default_factory=ScreenFilters)
    weights:dict[str,float] | None=None
    capital:float=Field(10000,gt=0,le=1e12)
    risk_per_trade:float=Field(.01,gt=0,le=.05)
    risk_tolerance:Literal['low','medium','high']='medium'
    min_reward_risk:float=Field(2,ge=1,le=10)
    existing_shares:float=Field(0,ge=0,le=1e12)
    position_ticker:str | None=None
    capital_currency:str=Field('USD',pattern='^[A-Z]{3}$')
    cost_basis:float | None=Field(None,gt=0)
    commission_bps:float=Field(5,ge=0,le=100)
    slippage_bps:float=Field(5,ge=0,le=100)
    max_deep_analysis:int=Field(15,ge=1,le=50)
    auto_refresh:bool=True
    margin_of_safety:float=Field(.2,ge=0,le=.6)
    valuation_assumptions:QuantValuationAssumptions | None=None

    @model_validator(mode='after')
    def valid_weights(self):
        import math
        expected=SHORT_WEIGHTS if self.horizon=='short_term' else LONG_WEIGHTS
        if self.weights is not None and (set(self.weights)!=set(expected) or any(not math.isfinite(v) or not 0<=v<=1 for v in self.weights.values()) or abs(sum(self.weights.values())-1)>1e-6):
            raise ValueError('Provide every category for the selected horizon with fractional weights totaling 1.')
        if self.existing_shares and not self.position_ticker:raise ValueError('An existing position requires its ticker; it cannot be applied to every company.')
        if self.position_ticker:self.position_ticker=validate_ticker(self.position_ticker)
        return self


class ScreenResponse(BaseModel):
    model_config=ConfigDict(extra='allow')
    horizon:Horizon
    run_id:str | None=None
    as_of:str | None=None
    rankings:list[dict]=Field(default_factory=list)
    coverage:dict=Field(default_factory=dict)
    job:dict | None=None
    provider_errors:list[dict]=Field(default_factory=list)
    limitations:list[str]=Field(default_factory=list)


class ScreenerBacktestRequest(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    horizon:Horizon='long_term'
    top_n:Literal[5,10]=5
    starting_capital:float=Field(10000,gt=0,le=1e12)
    commission_bps:float=Field(5,ge=0,le=100)
    slippage_bps:float=Field(5,ge=0,le=100)
    start:str | None=None
    end:str | None=None
