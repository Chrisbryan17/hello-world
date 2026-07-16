#!/usr/bin/env python3
import json, re, time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote
import requests

WALLET='0xd02b6d910a38479c3125308fc4737a46509cd6df'
DATA='https://data-api.polymarket.com'
GAMMA='https://gamma-api.polymarket.com'
OUT=Path('output'); OUT.mkdir(exist_ok=True)
s=requests.Session(); s.headers['User-Agent']='monthly-backtest-extractor/1.0'
request_count=0

def get(url, params=None):
    global request_count
    delay=1
    for i in range(8):
        try:
            request_count+=1
            r=s.get(url,params=params,timeout=60)
            if r.status_code in (429,500,502,503,504): raise RuntimeError(f'{r.status_code} {r.text[:200]}')
            r.raise_for_status(); return r.json()
        except Exception:
            if i==7: raise
            time.sleep(delay); delay=min(delay*2,20)

def key(x):
    return (x.get('transactionHash'),x.get('asset'),x.get('timestamp'),x.get('side'),x.get('size'),x.get('price'),x.get('conditionId'))

def is_btc(x):
    return str(x.get('title','')).startswith('Bitcoin Up or Down -') and re.search(r'btc-updown-(5m|15m)-\d{10}$',str(x.get('slug','')))

def fetch_interval(a,b,depth=0):
    page=get(DATA+'/trades',{'user':WALLET,'limit':1000,'offset':0,'takerOnly':'false','start':a,'end':b})
    print('SLICE',datetime.fromtimestamp(a,timezone.utc).isoformat(),datetime.fromtimestamp(b,timezone.utc).isoformat(),'DEPTH',depth,'ROWS',len(page),flush=True)
    if len(page)<1000:
        return page
    if a>=b:
        raise RuntimeError(f'one-second interval still capped at 1000: {a}')
    mid=(a+b)//2
    return fetch_interval(a,mid,depth+1)+fetch_interval(mid+1,b,depth+1)

end=int(time.time()); start=end-30*86400
rows=[]
cur=datetime.fromtimestamp(start,timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0)
last=datetime.fromtimestamp(end,timezone.utc)
while cur<=last:
    a=max(start,int(cur.timestamp())); b=min(end,int((cur+timedelta(days=1)).timestamp())-1)
    if a<=b:
        day_rows=fetch_interval(a,b)
        print('DAY_TOTAL',cur.date(),'ROWS',len(day_rows),flush=True)
        rows.extend(day_rows)
    cur+=timedelta(days=1)
uniq={key(x):x for x in rows}
trades=sorted([x for x in uniq.values() if start<=int(x.get('timestamp',0))<=end and is_btc(x)],key=lambda x:(int(x.get('timestamp',0)),str(x.get('transactionHash','')),str(x.get('asset',''))))
print('BTC_TRADES',len(trades),'REQUESTS',request_count,flush=True)

closed=[]; offset=0
while True:
    page=get(DATA+'/closed-positions',{'user':WALLET,'title':'Bitcoin Up or Down','limit':50,'offset':offset,'sortBy':'TIMESTAMP','sortDirection':'DESC'})
    if not page: break
    closed.extend(page)
    oldest=min(int(x.get('timestamp',0)) for x in page)
    print('CLOSED',offset,len(page),oldest,flush=True)
    offset+=len(page)
    if len(page)<50 or oldest<start-3*86400: break

winners={}
for x in closed:
    cid=str(x.get('conditionId','')); o=str(x.get('outcome','')); op=str(x.get('oppositeOutcome','')); p=float(x.get('curPrice',0) or 0)
    if cid and p>=.999 and o: winners[cid]=o
    elif cid and p<=.001 and op: winners.setdefault(cid,op)
slug={str(x.get('conditionId')):str(x.get('slug','')) for x in trades}
gamma=[]
missing=sorted(set(slug)-set(winners))
for n,cid in enumerate(missing,1):
    try:
        m=get(GAMMA+'/markets/slug/'+quote(slug[cid],safe=''))
        if not isinstance(m,dict) or not m: continue
        gamma.append(m)
        outs=m.get('outcomes',[]); prices=m.get('outcomePrices',[])
        if isinstance(outs,str): outs=json.loads(outs)
        if isinstance(prices,str): prices=json.loads(prices)
        vals=[float(v) for v in prices]
        if vals:
            i=max(range(len(vals)),key=vals.__getitem__)
            if vals[i]>=.99: winners[cid]=str(outs[i])
    except Exception as e:
        print('GAMMA_WARN',cid,slug[cid],repr(e),flush=True)
    if n%50==0: time.sleep(1)

(OUT/'trades.json').write_text(json.dumps(trades,indent=2),encoding='utf-8')
(OUT/'closed_positions.json').write_text(json.dumps(closed,indent=2),encoding='utf-8')
(OUT/'gamma_markets.json').write_text(json.dumps(gamma,indent=2),encoding='utf-8')
(OUT/'resolutions.json').write_text(json.dumps(winners,indent=2),encoding='utf-8')
meta={'wallet':WALLET,'start_epoch':start,'end_epoch':end,'generated_utc':datetime.fromtimestamp(end,timezone.utc).isoformat(),'trade_count':len(trades),'condition_count':len(set(str(x.get('conditionId')) for x in trades)),'resolved_count':len(set(str(x.get('conditionId')) for x in trades)&set(winners)),'request_count':request_count,'unresolved_condition_ids':sorted(set(slug)-set(winners))}
(OUT/'metadata.json').write_text(json.dumps(meta,indent=2),encoding='utf-8')
print('META',json.dumps(meta),flush=True)
