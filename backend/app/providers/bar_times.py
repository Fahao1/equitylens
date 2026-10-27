"""Conservative candle completion without inventing exchange holiday schedules."""
from datetime import datetime,timezone,timedelta
from zoneinfo import ZoneInfo
import pandas as pd


def bar_availability(frame):
    """Knowledge time for completed daily OHLC; session labels are not release times."""
    if 'Bar End' in frame:
        return pd.DatetimeIndex(pd.to_datetime(frame['Bar End'],utc=True,errors='coerce'))
    index=pd.DatetimeIndex(frame.index)
    if index.tz is None:index=index.tz_localize('UTC')
    return (index.normalize()+pd.DateOffset(days=1)).tz_convert('UTC')


def completed_bars(frame,interval='1d',exchange_timezone='UTC',as_of=None):
    if frame.empty:
        return frame.copy()
    now=pd.Timestamp(as_of or datetime.now(timezone.utc))
    if now.tzinfo is None:now=now.tz_localize('UTC')
    zone=ZoneInfo(exchange_timezone or 'UTC')
    result=frame.copy().sort_index()
    local=result.index.tz_convert(zone) if result.index.tz else result.index.tz_localize(zone)
    if 'Bar End' not in result:
        if interval=='1d':
            ends=[pd.Timestamp(t.date()+timedelta(days=1),tz=zone) for t in local]
        elif interval=='1wk':
            ends=[pd.Timestamp(t.date()+timedelta(days=7-t.weekday()),tz=zone) for t in local]
        else:
            duration={'15m':15,'1h':60,'4h':240}[interval]
            ends=local+pd.Timedelta(minutes=duration)
        result['Bar End']=pd.to_datetime(ends,utc=True)
    ends=pd.to_datetime(result['Bar End'],utc=True,errors='coerce')
    return result.loc[ends.notna() & (ends<=now)].copy()


def derived_weekly(daily,exchange_timezone='UTC'):
    if daily.empty:return daily.copy()
    zone=ZoneInfo(exchange_timezone or 'UTC')
    local=daily.index.tz_convert(zone) if daily.index.tz else daily.index.tz_localize(zone)
    groups=[t.date()-timedelta(days=t.weekday()) for t in local]
    result=daily.groupby(groups).agg({'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'})
    result.index=pd.DatetimeIndex([pd.Timestamp(day,tz=zone) for day in result.index])
    result['Bar End']=pd.to_datetime([t+pd.DateOffset(days=7) for t in result.index],utc=True)
    return result


def derived_four_hour(hourly,exchange_timezone='UTC',session_open=None):
    if hourly.empty:return hourly.copy()
    zone=ZoneInfo(exchange_timezone or 'UTC')
    data=hourly.copy();local=data.index.tz_convert(zone) if data.index.tz else data.index.tz_localize(zone)
    output=[]
    for _,group in data.groupby(local.date):
        if session_open:
            first=group.index[0].tz_convert(zone)
            anchor=pd.Timestamp(f'{first.date()} {session_open}',tz=zone).tz_convert(group.index.tz)
        else:
            anchor=group.index[0]
        buckets=((group.index-anchor).total_seconds()//(4*3600)).astype(int)
        for bucket,items in group.groupby(buckets):
            start=anchor+pd.Timedelta(hours=4*int(bucket))
            if items.index[0]!=start or any((items.index[n]-items.index[n-1]).total_seconds()!=3600 for n in range(1,len(items))):
                continue
            # A nominal four-hour window must have elapsed even if a session is shorter.
            output.append({'date':start,'Open':items.Open.iloc[0],'High':items.High.max(),'Low':items.Low.min(),
                           'Close':items.Close.iloc[-1],'Volume':items.Volume.sum(min_count=1),'Bar End':start+pd.Timedelta(hours=4)})
    return pd.DataFrame(output).set_index('date')
