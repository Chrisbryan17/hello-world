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
OUT=Path('results/hourly_spot_transfer'); DATA=Path('data/aliplayer_hourly')
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

def week(s):
 return pd.to_datetime(s,unit='s',utc=True).dt.tz_localize(None).dt.to_period('W-MON').astype(str)

def attach_spot_times(df,spot,lookback_s):
 t=(df.timestamp.astype('int64')*1000).to_numpy(); st=spot.ts_ms.to_numpy(); sp=spot.price.to_numpy()
 idx=np.searchsorted(st,t,side='right')-1; ok=idx>=0
 cur=np.full(len(df),np.nan); cur_gap=np.full(len(df),np.inf)
 cur[ok]=sp[idx[ok]]; cur_gap[ok]=t[ok]-st[idx[ok]]
 pt=t-lookback_s*1000; j=np.searchsorted(st,pt,side='right')-1; okj=j>=0
 prev=np.full(len(df),np.nan); prev_gap=np.full(len(df),np.inf)
 prev[okj]=sp[j[okj]]; prev_gap[okj]=pt[okj]-st[j[okj]]
 return cur,prev,cur_gap,prev_gap

def open_spot(markets,spot):
 t=(markets.window_open_ts.astype('int64')*1000).to_numpy(); st=spot.ts_ms.to_numpy(); sp=spot.price.to_numpy()
 i=np.searchsorted(st,t,side='right')-1; ok=i>=0
 v=np.full(len(markets),np.nan); gap=np.full(len(markets),np.inf)
 v[ok]=sp[i[ok]]; gap[ok]=t[ok]-st[i[ok]]
 return v,gap

def execute(signals,ticks,dollars,tape_window_s):
 rows=[]
 groups={mid:g.sort_values('timestamp_ms') for mid,g in ticks.groupby('market_id',sort=False)}
 for s in signals.itertuples(index=False):
  g=groups.get(s.market_id)
  if g is None: continue
  lo=int(s.timestamp*1000+1000); hi=int(s.timestamp*1000+tape_window_s*1000)
  side='Up' if s.side_up else 'Down'
  q=g[(g.timestamp_ms>=lo)&(g.timestamp_ms<=hi)&(g.side=='BUY')&(g.outcome==side)&(g.price<=s.target_px+1e-9)&(g.size_usdc>=dollars)]
  if q.empty: continue
  x=q.iloc[0]
  rows.append({'market_id':s.market_id,'crypto':s.crypto,'signal_ts':int(s.timestamp),'fill_ts_ms':int(x.timestamp_ms),'side_up':bool(s.side_up),'won':bool((s.resolution==1)==s.side_up),'reference_px':float(s.side_px),'target_px':float(s.target_px),'fill_px':float(x.price),'size_usdc':float(x.size_usdc),'end_ts':int(s.end_ts),'s2c':int(s.end_ts-s.timestamp),'dist_bps':float(s.dist_bps),'mom_bps':float(s.mom_bps),'window_s':int(s.window_s),'lookback_s':int(s.lookback_s),'tape_window_s':int(tape_window_s),'requested_usdc':float(dollars)})
 return pd.DataFrame(rows)

def metrics(fills,eligible_hours,eligible_markets):
 if fills.empty:return {'n':0,'per_hour':0.0,'market_coverage':0.0,'week_count':0,'win_rate':None,'arithmetic_multiple':None,'worst_week_arithmetic':None,'worst_week_n':0,'net_edge_per_dollar':None}
 d=fills.copy(); d['all_in_cost']=cost(d.fill_px); d['multiple']=np.where(d.won,1/d.all_in_cost,0.0); d['week']=week(d.end_ts)
 w=d.groupby('week').agg(n=('market_id','size'),arith=('multiple','mean')).reset_index(); worst=w.sort_values(['arith','week']).iloc[0]
 return {'n':int(len(d)),'per_hour':float(len(d)/eligible_hours),'market_coverage':float(len(d)/eligible_markets),'week_count':int(len(w)),'win_rate':float(d.won.mean()),'arithmetic_multiple':float(d.multiple.mean()),'worst_week_arithmetic':float(worst.arith),'worst_week_n':int(worst.n),'net_edge_per_dollar':float((d.won.astype(float)-d.all_in_cost).mean())}

def main():
 hashes={}
 for name,rel in FILES.items():
  p=DATA/f'{name}.parquet'; print('download',name,flush=True); download(rel,p); hashes[name]=sha256(p)
 m=pd.read_parquet(DATA/'markets.parquet')
 m=m[(m.crypto.isin(['BTC','ETH']))&(m.timeframe=='1-hour')&(m.resolution.isin([0,1]))].copy()
 m['window_open_ts']=m.end_ts-3600; m=m.drop_duplicates('market_id').sort_values('end_ts')
 print('resolved hourly markets',len(m),m.end_ts.min(),m.end_ts.max(),flush=True)
 spot=pd.read_parquet(DATA/'spot.parquet'); spot=spot[(spot.source=='binance')&spot.symbol.str.lower().isin(['btcusdt','ethusdt'])].copy(); spot=spot.sort_values('ts_ms')
 prices=[]; ticks=[]
 for asset in ['btc','eth']:
  p=pd.read_parquet(DATA/f'{asset}_prices.parquet'); p['crypto']=asset.upper(); prices.append(p)
  t=pd.read_parquet(DATA/f'{asset}_ticks.parquet'); t=t[(t.timestamp_ms>0)&t.market_id.notna()&t.price.between(.01,.99)&(t.side=='BUY')].copy(); t['crypto']=asset.upper(); ticks.append(t)
 prices=pd.concat(prices,ignore_index=True); ticks=pd.concat(ticks,ignore_index=True)
 prices=prices.merge(m[['market_id','crypto','resolution','window_open_ts','end_ts']],on=['market_id','crypto'],how='inner')
 prices=prices[(prices.timestamp>=prices.window_open_ts)&(prices.timestamp<=prices.end_ts)].sort_values(['crypto','timestamp'])
 ticks=ticks.merge(m[['market_id','end_ts']],on='market_id',how='inner'); ticks=ticks[(ticks.timestamp_ms>=((ticks.end_ts-3600)*1000))&(ticks.timestamp_ms<=ticks.end_ts*1000)]
 eligible_hours=max(1.0,(m.end_ts.max()-m.end_ts.min())/3600.0); eligible_per_hour=len(m)/eligible_hours; half_target=.5*eligible_per_hour
 print('prices',len(prices),'ticks',len(ticks),'eligible/hour',eligible_per_hour,flush=True)
 specs=[
  ('exact_40s_1s',40,1,.20,'exact_structural_transfer'),
  ('scaled_480s_12s',480,12,.20*math.sqrt(12),'fractional_horizon_adapter'),
  ('scaled_480s_60s',480,60,.20*math.sqrt(60),'slower_momentum_diagnostic'),
 ]
 signal_parts=[]
 for asset in ['BTC','ETH']:
  pa=prices[prices.crypto==asset].copy(); sa=spot[spot.symbol.str.lower()==asset.lower()+'usdt'][['ts_ms','price']].sort_values('ts_ms').reset_index(drop=True)
  ma=m[m.crypto==asset].copy(); op,gap=open_spot(ma,sa); ma['open_spot']=op; ma['open_gap_ms']=gap; ma=ma[(ma.open_gap_ms<=5000)&ma.open_spot.notna()]
  pa=pa.merge(ma[['market_id','open_spot']],on='market_id',how='inner')
  for name,window_s,lookback_s,threshold,label in specs:
   d=pa[(pa.end_ts-pa.timestamp>=0)&(pa.end_ts-pa.timestamp<=window_s)].copy()
   cur,prev,cgap,pgap=attach_spot_times(d,sa,lookback_s); d['spot']=cur; d['prev_spot']=prev; d['spot_gap_ms']=cgap; d['prev_gap_ms']=pgap
   d=d[(d.spot_gap_ms<=2000)&(d.prev_gap_ms<=2000)&d.spot.notna()&d.prev_spot.notna()]
   d['side_up']=d.spot>=d.open_spot; sign=np.where(d.side_up,1.0,-1.0)
   d['dist_bps']=sign*np.log(d.spot/d.open_spot)*1e4; d['mom_bps']=sign*np.log(d.spot/d.prev_spot)*1e4
   d['side_px']=np.where(d.side_up,d.up_price,d.down_price); d['target_px']=np.clip(d.side_px+.01,.01,.99)
   d=d[(d.dist_bps>=0)&(d.mom_bps>=threshold)&(cost(d.target_px)<=.50)&d.side_px.between(.01,.99)]
   d=d.sort_values(['market_id','timestamp']).drop_duplicates('market_id',keep='first')
   d['spec']=name; d['label']=label; d['window_s']=window_s; d['lookback_s']=lookback_s; d['mom_threshold']=threshold
   signal_parts.append(d)
 signals=pd.concat(signal_parts,ignore_index=True) if signal_parts else pd.DataFrame()
 signals.to_parquet(OUT/'signals.parquet',index=False); print('signals',signals.groupby(['spec','crypto']).size().to_dict(),flush=True)
 summaries=[]; allfills=[]
 for name,window_s,lookback_s,threshold,label in specs:
  sig=signals[signals.spec==name]
  for dollars in [5.0,10.0,20.0]:
   for tw in [5,30]:
    f=execute(sig,ticks,dollars,tw); f['spec']=name; f['label']=label; allfills.append(f)
    met=metrics(f,eligible_hours,len(m)); q=bool(met['worst_week_arithmetic'] is not None and met['worst_week_arithmetic']>=QUALITY_FLOOR and met['week_count']>=4); freq=bool(met['per_hour']>=half_target)
    summaries.append({'spec':name,'label':label,'window_s':window_s,'lookback_s':lookback_s,'mom_threshold_bps':threshold,'requested_usdc':dollars,'tape_window_s':tw,'eligible_markets':len(m),'eligible_markets_per_hour':eligible_per_hour,'target_half_markets_per_hour':half_target,'signals':len(sig),'signal_coverage':len(sig)/len(m),**met,'quality_floor_pass':q,'half_market_frequency_pass':freq,'joint_pass':bool(q and freq)})
 fills=pd.concat(allfills,ignore_index=True) if allfills else pd.DataFrame(); fills.to_parquet(OUT/'fills.parquet',index=False)
 summary=pd.DataFrame(summaries); summary.to_csv(OUT/'summary.csv',index=False)
 manifest={'repo':REPO,'revision':REV,'file_sha256':hashes,'resolved_hourly_markets':len(m),'date_min':pd.to_datetime(m.end_ts.min(),unit='s',utc=True).isoformat(),'date_max':pd.to_datetime(m.end_ts.max(),unit='s',utc=True).isoformat(),'eligible_markets_per_hour':eligible_per_hour,'target_half_markets_per_hour':half_target,'quality_floor':QUALITY_FLOOR,'execution':'signal on causal CLOB price history + Binance spot; entry only when a later actual BUY fill of requested USDC occurs at or below target'}
 (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2))
 cols=['spec','requested_usdc','tape_window_s','signals','signal_coverage','n','per_hour','win_rate','arithmetic_multiple','worst_week_arithmetic','worst_week_n','quality_floor_pass','half_market_frequency_pass','joint_pass']
 (OUT/'REPORT.md').write_text('\n'.join(['# BTC/ETH Hourly Spot-Dislocation Transfer','',summary[cols].to_markdown(index=False),'','Exact 40-second/1-second is a structural transfer. The 480-second/12-second row preserves the original fractions of the market horizon and square-root-of-time momentum threshold; it is a predeclared horizon adapter, not a selected optimum. Entries require a subsequent real BUY fill with sufficient USDC size at or below the one-cent limit.']))
 sums={p.name:sha256(p) for p in OUT.iterdir() if p.is_file()}; (OUT/'SHA256SUMS.json').write_text(json.dumps(sums,indent=2))
 print(summary[cols].to_string(index=False));print('DONE',flush=True)
if __name__=='__main__':main()
