from __future__ import annotations
import hashlib,json,math
from pathlib import Path
import requests
import numpy as np
import pandas as pd

REPO='aliplayer1/polymarket-crypto-updown'
REV='ba1ad37cbcdd720cced20f1cdc97c2cf347cad6c'
QUALITY_FLOOR=1.7563518376043876
BASE=f'https://huggingface.co/datasets/{REPO}/resolve/{REV}'
FILES={
 'markets':'data/markets.parquet',
 'btc_prices':'data/prices/crypto=BTC/timeframe=1-hour/part-0.parquet',
 'eth_prices':'data/prices/crypto=ETH/timeframe=1-hour/part-0.parquet',
 'btc_ticks':'data/ticks/crypto=BTC/timeframe=1-hour/part-0.parquet',
 'eth_ticks':'data/ticks/crypto=ETH/timeframe=1-hour/part-0.parquet',
 'spot':'data/spot_prices/part-0.parquet',
}
OUT=Path('results/hourly_cost_frontier'); DATA=Path('data/aliplayer_hourly')
OUT.mkdir(parents=True,exist_ok=True); DATA.mkdir(parents=True,exist_ok=True)

def sha256(p):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for b in iter(lambda:f.read(1<<20),b''): h.update(b)
 return h.hexdigest()

def download(rel,p):
 if p.exists(): return
 with requests.get(f'{BASE}/{rel}',stream=True,timeout=180) as r:
  r.raise_for_status()
  with open(p,'wb') as f:
   for b in r.iter_content(1<<20):
    if b:f.write(b)

def cost(px):
 q=np.clip(np.asarray(px,dtype=float),.01,.99)
 return q+.07*q*(1-q)

def week_start(ts):
 d=pd.to_datetime(ts,unit='s',utc=True)
 return (d-pd.to_timedelta((d.dt.dayofweek-1)%7,unit='D')).dt.floor('D')

def asof_values(query_ms, source_ms, source_values, max_gap_ms):
 idx=np.searchsorted(source_ms,query_ms,side='right')-1
 out=np.full(len(query_ms),np.nan); gap=np.full(len(query_ms),np.inf)
 ok=idx>=0
 out[ok]=source_values[idx[ok]]; gap[ok]=query_ms[ok]-source_ms[idx[ok]]
 out[gap>max_gap_ms]=np.nan
 return out,gap

def execute(signals,ticks,dollars=5.0,window_s=30):
 rows=[]
 groups={mid:g.sort_values('timestamp_ms') for mid,g in ticks.groupby('market_id',sort=False)}
 for s in signals.itertuples(index=False):
  g=groups.get(s.market_id)
  if g is None: continue
  lo=int(s.timestamp*1000+1000); hi=int(s.timestamp*1000+window_s*1000)
  outcome='Up' if s.side_up else 'Down'
  q=g[(g.timestamp_ms>=lo)&(g.timestamp_ms<=hi)&(g.side=='BUY')&(g.outcome==outcome)&(g.price<=s.target_px+1e-9)&(g.size_usdc>=dollars)]
  if q.empty: continue
  x=q.iloc[0]
  rows.append({'market_id':s.market_id,'crypto':s.crypto,'end_ts':int(s.end_ts),'signal_ts':int(s.timestamp),'fill_ts_ms':int(x.timestamp_ms),'resolution':int(s.resolution),'side_up':bool(s.side_up),'won':bool((s.resolution==1)==s.side_up),'fill_px':float(x.price),'target_px':float(s.target_px),'size_usdc':float(x.size_usdc),'spec':s.spec,'cost_cap':float(s.cost_cap)})
 return pd.DataFrame(rows)

def metric(df,hours):
 if df.empty:return {'n':0,'per_hour':0.0,'win_rate':None,'arith':None,'net_edge':None}
 d=df.copy(); d['all_in']=cost(d.fill_px); d['multiple']=np.where(d.won,1/d.all_in,0.0)
 return {'n':int(len(d)),'per_hour':float(len(d)/hours),'win_rate':float(d.won.mean()),'arith':float(d.multiple.mean()),'net_edge':float((d.won.astype(float)-d.all_in).mean())}

def main():
 hashes={}
 for name,rel in FILES.items():
  p=DATA/f'{name}.parquet'; download(rel,p); hashes[name]=sha256(p)
 m=pd.read_parquet(DATA/'markets.parquet')
 m=m[(m.crypto.isin(['BTC','ETH']))&(m.timeframe=='1-hour')&(m.resolution.isin([0,1]))].drop_duplicates('market_id').copy()
 m['open_ts']=m.end_ts-3600; m['week_start']=week_start(m.end_ts)
 weeks=sorted(m.week_start.unique())
 assert len(weeks)>=2,weeks
 val_week,test_week=weeks[-2],weeks[-1]
 m=m[m.week_start.isin([val_week,test_week])].copy()
 spot=pd.read_parquet(DATA/'spot.parquet')
 spot=spot[(spot.source=='binance')&spot.symbol.str.lower().isin(['btcusdt','ethusdt'])].copy()
 prices=[];ticks=[]
 for a in ['btc','eth']:
  p=pd.read_parquet(DATA/f'{a}_prices.parquet');p['crypto']=a.upper();prices.append(p)
  t=pd.read_parquet(DATA/f'{a}_ticks.parquet');t=t[(t.timestamp_ms>0)&t.market_id.notna()&t.price.between(.01,.99)&(t.side=='BUY')].copy();t['crypto']=a.upper();ticks.append(t)
 prices=pd.concat(prices,ignore_index=True).merge(m[['market_id','crypto','resolution','open_ts','end_ts','week_start']],on=['market_id','crypto'],how='inner')
 prices=prices[(prices.timestamp>=prices.open_ts)&(prices.timestamp<=prices.end_ts)].sort_values(['crypto','timestamp'])
 ticks=pd.concat(ticks,ignore_index=True).merge(m[['market_id','end_ts','week_start']],on='market_id',how='inner')
 specs=[('exact_40s_1s',40,1,.20),('scaled_480s_12s',480,12,.20*math.sqrt(12)),('scaled_480s_60s',480,60,.20*math.sqrt(60))]
 caps=[.50,.55,.60,.65,.70,.80]
 stages=[];signal_parts=[]
 for asset in ['BTC','ETH']:
  pa=prices[prices.crypto==asset].copy()
  sa=spot[spot.symbol.str.lower()==asset.lower()+'usdt'][['ts_ms','price']].sort_values('ts_ms')
  st=sa.ts_ms.to_numpy();sv=sa.price.to_numpy()
  ma=m[m.crypto==asset].copy()
  open_q=(ma.open_ts.astype('int64')*1000).to_numpy();ma['open_spot'],ma['open_gap']=asof_values(open_q,st,sv,5000)
  ma=ma[ma.open_spot.notna()]
  pa=pa.merge(ma[['market_id','open_spot']],on='market_id',how='inner')
  for spec,window,lb,thr in specs:
   d0=pa[(pa.end_ts-pa.timestamp>=0)&(pa.end_ts-pa.timestamp<=window)].copy()
   cur_q=(d0.timestamp.astype('int64')*1000).to_numpy(); prev_q=cur_q-lb*1000
   d0['spot'],d0['spot_gap']=asof_values(cur_q,st,sv,2000);d0['prev_spot'],d0['prev_gap']=asof_values(prev_q,st,sv,2000)
   d1=d0[d0.spot.notna()&d0.prev_spot.notna()].copy()
   d1['side_up']=d1.spot>=d1.open_spot;sign=np.where(d1.side_up,1.0,-1.0)
   d1['dist_bps']=sign*np.log(d1.spot/d1.open_spot)*1e4;d1['mom_bps']=sign*np.log(d1.spot/d1.prev_spot)*1e4
   d1['side_px']=np.where(d1.side_up,d1.up_price,d1.down_price);d1['target_px']=np.clip(d1.side_px+.01,.01,.99);d1['all_in']=cost(d1.target_px)
   d2=d1[(d1.dist_bps>=0)&(d1.mom_bps>=thr)&d1.side_px.between(.01,.99)].copy()
   qtiles=d2.side_px.quantile([0,.1,.25,.5,.75,.9,1]).to_dict() if len(d2) else {}
   for cap in caps:
    s=d2[d2.all_in<=cap].sort_values(['market_id','timestamp']).drop_duplicates('market_id',keep='first').copy()
    s['spec']=spec;s['cost_cap']=cap;signal_parts.append(s)
    stages.append({'asset':asset,'spec':spec,'window_rows':len(d0),'spot_rows':len(d1),'momentum_rows':len(d2),'cost_cap':cap,'signals':len(s),'side_px_quantiles':json.dumps(qtiles)})
 signals=pd.concat(signal_parts,ignore_index=True) if signal_parts else pd.DataFrame()
 stage=pd.DataFrame(stages);stage.to_csv(OUT/'stage_counts.csv',index=False)
 allrows=[];fills_all=[]
 for spec,window,lb,thr in specs:
  for cap in caps:
   s=signals[(signals.spec==spec)&(signals.cost_cap==cap)]
   f=execute(s,ticks,5.0,30);fills_all.append(f)
   for label,wk in [('validation',val_week),('test',test_week)]:
    sm=s[s.week_start==wk]
    if not f.empty:
     fw=week_start(f.end_ts)
     fm=f[fw==wk]
    else:
     fm=f
    hours=max(1.0,(m.loc[m.week_start==wk,'end_ts'].max()-m.loc[m.week_start==wk,'end_ts'].min())/3600+1)
    allrows.append({'spec':spec,'window_s':window,'lookback_s':lb,'mom_threshold':thr,'cost_cap':cap,'split':label,'week_start':str(wk),'eligible_markets':int((m.week_start==wk).sum()),'signals':len(sm),'signal_coverage':len(sm)/max(1,(m.week_start==wk).sum()),**metric(fm,hours)})
 results=pd.DataFrame(allrows);results.to_csv(OUT/'frontier.csv',index=False)
 fills=pd.concat(fills_all,ignore_index=True) if fills_all else pd.DataFrame();fills.to_parquet(OUT/'fills.parquet',index=False)
 val=results[results.split=='validation'].copy();eligible=val[(val.n>=10)&(val.arith>=QUALITY_FLOOR)].sort_values(['per_hour','arith'],ascending=False)
 selection=None
 if not eligible.empty:
  b=eligible.iloc[0];selection={'spec':b.spec,'cost_cap':float(b.cost_cap),'validation':b.to_dict()}
  test=results[(results.split=='test')&(results.spec==b.spec)&(results.cost_cap==b.cost_cap)].iloc[0]
  selection['test']=test.to_dict();selection['test_quality_pass']=bool(test.n>=10 and test.arith>=QUALITY_FLOOR)
 (OUT/'selection.json').write_text(json.dumps(selection,indent=2,default=str))
 manifest={'repo':REPO,'revision':REV,'hashes':hashes,'validation_week':str(val_week),'test_week':str(test_week),'quality_floor':QUALITY_FLOOR,'candidate_grid':{'specs':specs,'cost_caps':caps,'requested_usdc':5,'tape_window_s':30},'selection_rule':'highest validation fills/hour subject to n>=10 and arithmetic>=quality floor; apply once to untouched next week'}
 (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2,default=str))
 report=['# Hourly Cost-Cap Frontier','',f'Validation week: `{val_week}`; untouched test week: `{test_week}`.','','## Stage counts','',stage.drop(columns=['side_px_quantiles']).to_markdown(index=False),'','## Validation/test frontier','',results.to_markdown(index=False),'','## Frozen selection','',json.dumps(selection,indent=2,default=str)]
 (OUT/'REPORT.md').write_text('\n'.join(report))
 sums={p.name:sha256(p) for p in OUT.iterdir() if p.is_file()};(OUT/'SHA256SUMS.json').write_text(json.dumps(sums,indent=2))
 print(stage.drop(columns=['side_px_quantiles']).to_string(index=False));print(results.to_string(index=False));print('selection',selection);print('DONE')
if __name__=='__main__':main()
