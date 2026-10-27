"""Hand-calculated archived-ranking portfolio replays; fixtures are synthetic."""
from copy import deepcopy
import pandas as pd
import pytest

from app.analysis.screener_backtest import replay_ranked_portfolio,STATUS


def histories(count=10,closes=(11,12,13),opens=(10,11,12)):
    result={}
    index=pd.date_range('2024-01-02',periods=len(closes),freq='B',tz='UTC')
    for n in range(count):
        frame=pd.DataFrame({'Open':opens,'Close':closes},index=index)
        frame['Bar End']=index+pd.Timedelta(days=1)
        frame.attrs['currency']='USD'
        result[f'SYN{n}']=frame
    return result


def snapshot(published='2024-01-01T12:00:00Z',start=0,count=10,identity='archive1',**changes):
    return {'id':identity,'published_at':published,'membership_as_of':published,'horizon':'short_term','point_in_time':True,
            'rankings':[{'ticker':f'SYN{i}','rank':rank+1,'score':9-rank*.1,'currency':'USD'} for rank,i in enumerate(range(start,start+count))],**changes}


def config(**changes):return {'top_n':5,'starting_capital':10000,'commission_bps':0,'slippage_bps':0,'as_of':'2024-02-01T00:00:00Z',**changes}


@pytest.mark.parametrize('top_n',[5,10])
def test_equal_weight_top5_top10_reference_return_and_benchmarks(top_n):
    prices=histories()
    result=replay_ranked_portfolio([snapshot()],prices,config(top_n=top_n),{'QQQ':prices['SYN0'],'XLK':prices['SYN1']})
    assert result['status']!=STATUS
    assert result['metrics']['ending_equity']==pytest.approx(13000)
    assert result['metrics']['total_return']==pytest.approx(.3)
    assert result['metrics']['maximum_drawdown']==0
    assert result['rebalances'][0]['target_weight']==1/top_n
    buys=[trade for trade in result['trades'] if trade['side']=='buy']
    assert len(buys)==top_n
    assert all(trade['shares']==pytest.approx(1000/top_n) for trade in buys)
    assert result['benchmarks']['QQQ']['metrics']['total_return']==pytest.approx(.3)
    assert result['coverage']['point_in_time'] is True
    assert all(pd.Timestamp(trade['execution_time'])>pd.Timestamp(trade['published_at']) for trade in buys)


def test_commissions_and_slippage_hand_calculated_round_trip():
    prices=histories(closes=(10,10,10),opens=(10,10,10))
    result=replay_ranked_portfolio([snapshot()],prices,config(commission_bps=10,slippage_bps=20))
    expected=10000*(1-.002)*(1-.001)/((1+.002)*(1+.001))
    assert result['metrics']['ending_equity']==pytest.approx(expected)
    assert result['metrics']['commissions']>0 and result['metrics']['slippage_cost']>0
    assert result['metrics']['commissions']+result['metrics']['slippage_cost']==pytest.approx(10000-expected)


def test_periodic_rebalancing_is_net_trading_not_needless_full_liquidation():
    prices=histories(closes=(10,10,10),opens=(10,10,10))
    archives=[snapshot(),snapshot('2024-01-02T23:00:00Z',identity='archive2')]
    result=replay_ranked_portfolio(archives,prices,config(commission_bps=10,slippage_bps=20))
    assert len(result['rebalances'])==2
    assert result['rebalances'][1]['transaction_cost']==pytest.approx(0,abs=1e-8)
    assert result['rebalances'][1]['gross_turnover']==pytest.approx(0,abs=1e-8)
    expected=10000*(1-.002)*(1-.001)/((1+.002)*(1+.001))
    assert result['metrics']['ending_equity']==pytest.approx(expected)


def test_new_members_only_trade_after_their_ranking_publication():
    prices=histories(closes=(10,10,10),opens=(10,10,10))
    for i in range(5,10):
        prices[f'SYN{i}']['Open']=[10,30,30]
        prices[f'SYN{i}']['Close']=[30,30,30]
    archives=[snapshot(),snapshot('2024-01-02T23:00:00Z',start=5,count=5,identity='archive2')]
    result=replay_ranked_portfolio(archives,prices,config())
    assert result['metrics']['ending_equity']==pytest.approx(10000)  # The earlier 3x rise was never held.
    second_buys=[t for t in result['trades'] if t['side']=='buy' and t['snapshot_id']=='archive2']
    assert len(second_buys)==5 and all(t['reference_price']==30 for t in second_buys)


@pytest.mark.parametrize('change',[
    {'point_in_time':False},{'membership_as_of':'2024-01-03T00:00:00Z'},
    {'published_at':'2024-01-01'}, {'rankings':[]}, {'id':None},
])
def test_missing_point_in_time_membership_or_score_vintage_never_backfills(change):
    result=replay_ranked_portfolio([snapshot(**change)],histories(),config())
    assert result['status']==STATUS
    assert result['metrics']=={} and result['trades']==[]


def test_future_score_and_missing_prices_or_currency_fail_closed():
    archive=snapshot();archive['rankings'][0]['score_as_of']='2024-01-03T00:00:00Z'
    assert replay_ranked_portfolio([archive],histories(),config())['status']==STATUS
    prices=histories();prices.pop('SYN0')
    assert replay_ranked_portfolio([snapshot()],prices,config())['status']==STATUS
    archive=snapshot();archive['rankings'][0]['currency']='EUR'
    assert replay_ranked_portfolio([archive],histories(),config())['status']==STATUS
    prices=histories();prices['SYN0']=prices['SYN0'].iloc[1:]
    result=replay_ranked_portfolio([snapshot()],prices,config())
    assert result['status']==STATUS
    assert 'Missing historical session' in result['limitations'][0]


def test_no_archives_or_current_only_archives_do_not_invent_historical_rankings():
    assert replay_ranked_portfolio([],histories(),config())['status']==STATUS
    assert replay_ranked_portfolio([snapshot()],{},config())['status']==STATUS
    current=snapshot(published='2024-01-10T00:00:00Z')
    assert replay_ranked_portfolio([current],histories(),config())['status']==STATUS


def test_future_archives_and_bars_cannot_change_earlier_replay():
    prices=histories(closes=(11,12,13,14),opens=(10,11,12,13))
    settings=config(as_of='2024-01-05T00:00:00Z')
    baseline=replay_ranked_portfolio([snapshot()],prices,settings)
    modified=deepcopy(prices)
    for frame in modified.values():frame.loc[frame.index[-1],['Open','Close']]*=100
    future=snapshot('2024-01-20T00:00:00Z',identity='future',point_in_time=False)
    actual=replay_ranked_portfolio([snapshot(),future],modified,settings)
    assert actual==baseline


def test_missing_benchmark_is_not_fabricated_and_no_survivor_substitution():
    result=replay_ranked_portfolio([snapshot()],histories(),config())
    assert result['benchmarks']['QQQ']['status']==STATUS
    assert result['benchmarks']['QQQ']['metrics']=={}
    assert any('survivorship' in line for line in result['limitations'])


def test_request_start_end_aliases_select_only_the_requested_replay_period():
    result=replay_ranked_portfolio([snapshot()],histories(),config(start='2024-01-03',end='2024-01-04'))
    assert result['status']!=STATUS
    assert result['coverage']['replay_start']=='2024-01-03T00:00:00+00:00'
    assert result['coverage']['replay_end']=='2024-01-04T00:00:00+00:00'
    assert result['metrics']['ending_equity']==pytest.approx(10000*13/11)


def test_daily_availability_preserves_source_zone_before_utc_conversion():
    index=pd.date_range('2024-03-11',periods=4,freq='B',tz='America/New_York')
    source={}
    for n in range(5):
        source[f'SYN{n}']=pd.DataFrame({'Open':[10,11,12,13],'Close':[11,12,13,14]},index=index)
        source[f'SYN{n}'].attrs['currency']='USD'
    archive=snapshot(published='2024-03-10T12:00:00Z',count=5)
    result=replay_ranked_portfolio([archive],source,config(as_of='2024-03-14T02:00:00Z'))
    assert result['status']!=STATUS
    assert result['coverage']['sessions']==2
    assert result['coverage']['replay_end']=='2024-03-12T04:00:00+00:00'
    assert result['metrics']['ending_equity']==pytest.approx(12000)


def test_future_fetch_vintage_or_stale_ranked_rows_cannot_pass_provenance():
    stale=snapshot();stale['rankings'][0]['cache_stale']=True
    assert replay_ranked_portfolio([stale],histories(),config())['status']==STATUS
    future=snapshot();future['rankings'][0]['fetched_at']='2024-01-03T00:00:00Z'
    assert replay_ranked_portfolio([future],histories(),config())['status']==STATUS


def test_benchmark_currency_must_match_the_verified_portfolio_currency():
    prices=histories();benchmark=prices['SYN0'].copy();benchmark.attrs['currency']='EUR'
    result=replay_ranked_portfolio([snapshot()],prices,config(),{'QQQ':benchmark})
    assert result['status']!=STATUS
    assert result['benchmarks']['QQQ']['status']==STATUS
    assert result['benchmarks']['QQQ']['metrics']=={}
    benchmark.attrs.clear()
    result=replay_ranked_portfolio([snapshot()],prices,config(),{'QQQ':benchmark})
    assert result['benchmarks']['QQQ']['status']==STATUS
