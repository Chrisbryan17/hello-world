from __future__ import annotations
import hashlib, json, math
from pathlib import Path
import requests
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

REPO='aliplayer1/polymarket-crypto-updown'
REV='ba1ad37cbcdd720cced20f1cdc97c2cf347cad6c'
BASE=f'https://huggingface.co/datasets/{REPO}/resolve/{REV}'
QUALITY_FLOOR=1.7563518376043876
FILES={
 'markets':'data/markets.parquet',
 'spot':'data/spot_prices/part-0.parquet',
 'btc_ticks':'data/ticks/crypto=BTC/timeframe=1-hour/part-0.parquet',
 'eth_ticks':'data/ticks/crypto=ETH/timeframe=1-hour/part-0.parquet',
 'btc_orderbook':'data/orderbook/crypto=BTC/timeframe=1-hour/part-0.parquet',
 'eth_orderbook':'data/orderbook/crypto=ETH/timeframe=1-hour/part-0.parquet',
}
EXPECTED={
 'markets':'2cf01fea1659cc96193f2437e8b95a05429ad6bede359fe5d0193974c154219f',
 'spot':'ac35074bc847e6e9e9634be17a6d4f87bedd49954ec5912a00320e003be7e6c6',
 'btc_ticks':'b326f9001fbbccc22bc65a17bdb5afdc20852f11c030ec0194b9edeaff201337',
 'eth_ticks':'e89356c4266f22016065fa812912552cc962d3a1190fccf0a7d6b0fe78d5d2f6',
 'btc_orderbook':'91ee5bbd323b73b4acf3730d432e4cd00f2707dcbc81b47e40429ad7c74a6064',
 'eth_orderbook':'db0b523ed06960b67c08dbf3cf78a7e6a5024ffcd9a7fd077cd23f58e12ec6bb',
}
OUT=Path('results/hourly_orderbook_transfer'); DATA=Path('data/hourly_orderbook')
OUT.mkdir(parents=True,exist_ok=True); DATA.mkdir(parents=True,exist_ok=True)

def sha256(path:Path)->str:
 h=hashlib.sha256()
 with open(path,'rb') as f:
  for b in iter(lambda:f.read(1<<20),b''): h.update(b)
 return h.hexdigest()

def download(name,rel):
 p=DATA/f'{name}.parquet'
 if not p.exists():
  print('download',name,rel,flush=True)
  with requests.get(f'{BASE}/{rel}',stream=True,timeout=300) as r:
   r.raise_for_status()
   with open(p,'wb') as f:
    for b in r.iter_content(1<<20):
     if b:f.write(b)
 got=sha256(p)
 exp=EXPECTED.get(name)
 if exp and got!=exp: raise RuntimeError(f'hash mismatch {name}: {got} != {exp}')
 return p,got

def fee_cost(px):
 q=np.clip(np.asarray(px,dtype=float),.01,.99)
 return q+.07*q*(1-q)

def week_start(ts_s):
 d=pd.to_datetime(ts_s,unit='s',utc=True)
 return (d-pd.to_timedelta((d.dt.dayofweek-1)%7,unit='D')).dt.floor('D')

def choose_col(names,*candidates):
 low={n.lower():n for n in names}
 for c in candidates:
  if c.lower() in low:return low[c.lower()]
 raise KeyError(f'missing columns {candidates}; have {names}')

def stream_spot(path,min_ms,max_ms):
 pf=pq.ParquetFile(path); parts=[]
 cols=['ts_ms','symbol','price','source']
 for rg in range(pf.num_row_groups):
  d=pf.read_row_group(rg,columns=cols).to_pandas()
  sym=d.symbol.astype(str).str.lower(); src=d.source.astype(str).str.lower()
  m=(d.ts_ms.between(min_ms,max_ms))&(src=='binance')&sym.isin(['btcusdt','ethusdt'])
  if m.any():parts.append(d.loc[m,cols])
 out=pd.concat(parts,ignore_index=True).sort_values(['symbol','ts_ms']) if parts else pd.DataFrame(columns=cols)
 print('spot rows',len(out),flush=True);return out

def stream_ticks(path,market_ids,min_ms,max_ms):
 pf=pq.ParquetFile(path); names=pf.schema_arrow.names
 cols=[choose_col(names,'market_id'),choose_col(names,'timestamp_ms'),choose_col(names,'outcome'),choose_col(names,'side'),choose_col(names,'price'),choose_col(names,'size_usdc')]
 parts=[]
 for rg in range(pf.num_row_groups):
  d=pf.read_row_group(rg,columns=cols).to_pandas();d.columns=['market_id','timestamp_ms','outcome','side','price','size_usdc']
  m=d.market_id.astype(str).isin(market_ids)&d.timestamp_ms.between(min_ms,max_ms)&(d.side.astype(str).str.upper()=='BUY')&d.price.between(.01,.99)&(d.size_usdc>0)
  if m.any():parts.append(d.loc[m])
 out=pd.concat(parts,ignore_index=True).sort_values(['market_id','timestamp_ms']) if parts else pd.DataFrame(columns=['market_id','timestamp_ms','outcome','side','price','size_usdc'])
 print(path.name,'tick rows',len(out),flush=True);return out

def stream_orderbook(path,market_ids,meta_map,min_ms,max_ms,max_window_s=480):
 pf=pq.ParquetFile(path); names=pf.schema_arrow.names
 print(path.name,'schema',names,flush=True)
 c_mid=choose_col(names,'market_id');c_ts=choose_col(names,'timestamp_ms','timestamp');c_out=choose_col(names,'outcome');c_bid=choose_col(names,'best_bid','bid');c_ask=choose_col(names,'best_ask','ask');c_bs=choose_col(names,'bid_size','best_bid_size');c_as=choose_col(names,'ask_size','best_ask_size')
 cols=[c_mid,c_ts,c_out,c_bid,c_ask,c_bs,c_as];parts=[]
 for rg in range(pf.num_row_groups):
  d=pf.read_row_group(rg,columns=cols).to_pandas();d.columns=['market_id','timestamp_ms','outcome','best_bid','best_ask','bid_size','ask_size']
  d['market_id']=d.market_id.astype(str)
  if d.timestamp_ms.max()<10**12:d['timestamp_ms']=(d.timestamp_ms.astype('int64')*1000)
  d=d[d.market_id.isin(market_ids)&d.timestamp_ms.between(min_ms,max_ms)]
  if d.empty:continue
  end=d.market_id.map({k:int(v['end_ts']*1000) for k,v in meta_map.items()})
  m=(d.timestamp_ms>=end-max_window_s*1000)&(d.timestamp_ms<=end)
  d=d[m]
  if not d.empty:parts.append(d)
 out=pd.concat(parts,ignore_index=True) if parts else pd.DataFrame(columns=['market_id','timestamp_ms','outcome','best_bid','best_ask','bid_size','ask_size'])
 out=out.dropna(subset=['market_id','timestamp_ms','outcome']).sort_values(['market_id','timestamp_ms','outcome'])
 print(path.name,'filtered orderbook rows',len(out),flush=True);return out

def asof_values(query_ms,source_ms,values,max_gap_ms):
 idx=np.searchsorted(source_ms,query_ms,side='right')-1
 out=np.full(len(query_ms),np.nan);gap=np.full(len(query_ms),np.inf)
 ok=idx>=0;out[ok]=values[idx[ok]];gap[ok]=query_ms[ok]-source_ms[idx[ok]];out[gap>max_gap_ms]=np.nan
 return out,gap

def build_wide(ob,markets):
 d=ob.copy();o=d.outcome.astype(str).str.lower();d['is_up']=o.str.startswith('up')|o.str.startswith('yes')
 d=d[d.outcome.notna()]
 d=d.drop_duplicates(['market_id','timestamp_ms','is_up'],keep='last')
 w=d.pivot(index=['market_id','timestamp_ms'],columns='is_up',values=['best_bid','best_ask','bid_size','ask_size'])
 def grab(field,side):
  return w[(field,side)] if (field,side) in w.columns else pd.Series(np.nan,index=w.index)
 out=pd.DataFrame(index=w.index)
 for field,prefix in [('best_bid','bid'),('best_ask','ask'),('bid_size','bid_size'),('ask_size','ask_size')]:
  out[f'up_{prefix}']=grab(field,True);out[f'down_{prefix}']=grab(field,False)
 out=out.reset_index().merge(markets[['market_id','crypto','resolution','open_ts','end_ts','week_start']],on='market_id',how='inner')
 out['s2c']=(out.end_ts*1000-out.timestamp_ms)/1000.0
 return out.sort_values(['market_id','timestamp_ms'])

def attach_spot_features(wide,spot,markets,specs):
 results=[]
 for asset in ['BTC','ETH']:
  d=wide[wide.crypto==asset].copy();s=spot[spot.symbol.astype(str).str.lower()==asset.lower()+'usdt'].sort_values('ts_ms')
  st=s.ts_ms.to_numpy();sv=s.price.to_numpy()
  ma=markets[markets.crypto==asset].copy();q=(ma.open_ts.astype('int64')*1000).to_numpy();ma['open_spot'],ma['open_gap']=asof_values(q,st,sv,5000);ma=ma[ma.open_spot.notna()]
  d=d.merge(ma[['market_id','open_spot']],on='market_id',how='inner')
  curq=d.timestamp_ms.astype('int64').to_numpy();d['spot'],d['spot_gap']=asof_values(curq,st,sv,2000)
  for name,window,lookback,threshold in specs:
   x=d[(d.s2c>=0)&(d.s2c<=window)&d.spot.notna()].copy();prevq=x.timestamp_ms.astype('int64').to_numpy()-lookback*1000;x['prev_spot'],x['prev_gap']=asof_values(prevq,st,sv,2000);x=x[x.prev_spot.notna()]
   x['side_up']=x.spot>=x.open_spot;sign=np.where(x.side_up,1.0,-1.0)
   x['dist_bps']=sign*np.log(x.spot/x.open_spot)*1e4;x['mom_bps']=sign*np.log(x.spot/x.prev_spot)*1e4
   x['side_ask']=np.where(x.side_up,x.up_ask,x.down_ask);x['side_ask_size']=np.where(x.side_up,x.up_ask_size,x.down_ask_size)
   x['side_bid']=np.where(x.side_up,x.up_bid,x.down_bid)
   x['target_px']=np.clip(x.side_ask+.01,.01,.99);x['all_in']=fee_cost(x.target_px)
   book_ok=(x.up_bid>0)&(x.up_ask>x.up_bid)&(x.up_ask<1)&(x.down_bid>=0)&(x.down_ask>x.down_bid)&(x.down_ask<1)
   sig=x[book_ok&(x.dist_bps>=0)&(x.mom_bps>=threshold)&x.side_ask.between(.01,.99)&(x.all_in<=.50)].sort_values(['market_id','timestamp_ms']).drop_duplicates('market_id',keep='first').copy()
   sig['spec']=name;sig['window_s']=window;sig['lookback_s']=lookback;sig['mom_threshold']=threshold;results.append(sig)
 return pd.concat(results,ignore_index=True) if results else pd.DataFrame()

def execute(signals,wide,ticks,shares,tape_window_ms=1500,latency_ms=1000,max_gap_ms=4000):
 rows=[];books={mid:g.sort_values('timestamp_ms') for mid,g in wide.groupby('market_id',sort=False)};tapes={mid:g.sort_values('timestamp_ms') for mid,g in ticks.groupby('market_id',sort=False)}
 for s in signals.itertuples(index=False):
  b=books.get(s.market_id);arr=int(s.timestamp_ms+latency_ms)
  if b is None:continue
  k=int(np.searchsorted(b.timestamp_ms.to_numpy(),arr,side='left'))
  if k>=len(b) or int(b.iloc[k].timestamp_ms)-arr>max_gap_ms:continue
  br=b.iloc[k];ask=float(br.up_ask if s.side_up else br.down_ask);ask_size=float(br.up_ask_size if s.side_up else br.down_ask_size)
  if not(np.isfinite(ask) and np.isfinite(ask_size) and ask<=s.target_px+1e-9 and ask_size>=shares):continue
  t=tapes.get(s.market_id);tape_shares=0.0
  if t is not None:
   outcome='Up' if s.side_up else 'Down';q=t[(t.timestamp_ms>=s.timestamp_ms)&(t.timestamp_ms<=s.timestamp_ms+tape_window_ms)&(t.outcome.astype(str).str.lower()==outcome.lower())&(t.price<=s.target_px+1e-9)]
   tape_shares=float((q.size_usdc/q.price.clip(lower=.01)).sum())
  if tape_shares<shares:continue
  won=bool((int(s.resolution)==1)==bool(s.side_up));rows.append({'market_id':s.market_id,'crypto':s.crypto,'spec':s.spec,'week_start':s.week_start,'signal_ts_ms':int(s.timestamp_ms),'s2c':float(s.s2c),'side_up':bool(s.side_up),'won':won,'decision_ask':float(s.side_ask),'arrival_ask':ask,'arrival_ask_size':ask_size,'tape_shares':tape_shares,'fill_px':ask,'target_px':float(s.target_px),'requested_shares':shares,'dist_bps':float(s.dist_bps),'mom_bps':float(s.mom_bps)})
 return pd.DataFrame(rows)

def metrics(fills,hours):
 if fills.empty:return {'n':0,'per_hour':0.0,'win_rate':None,'arith':None,'net_per_share':None}
 d=fills.copy();d['cost']=fee_cost(d.fill_px);d['mult']=np.where(d.won,1/d.cost,0.0)
 return {'n':int(len(d)),'per_hour':float(len(d)/hours),'win_rate':float(d.won.mean()),'arith':float(d.mult.mean()),'net_per_share':float((d.won.astype(float)-d.cost).mean())}

def main():
 paths={};hashes={}
 for n,r in FILES.items():paths[n],hashes[n]=download(n,r)
 m=pd.read_parquet(paths['markets']);m=m[(m.crypto.isin(['BTC','ETH']))&(m.timeframe=='1-hour')&(m.resolution.isin([0,1]))].drop_duplicates('market_id').copy();m['open_ts']=m.end_ts-3600;m['week_start']=week_start(m.end_ts)
 ids=set(m.market_id.astype(str));meta={str(r.market_id):r._asdict() for r in m.itertuples(index=False)};min_ms=int((m.open_ts.min()-60)*1000);max_ms=int(m.end_ts.max()*1000)
 spot=stream_spot(paths['spot'],min_ms,max_ms)
 ticks=pd.concat([stream_ticks(paths['btc_ticks'],ids,min_ms,max_ms),stream_ticks(paths['eth_ticks'],ids,min_ms,max_ms)],ignore_index=True)
 ob=pd.concat([stream_orderbook(paths['btc_orderbook'],ids,meta,min_ms,max_ms),stream_orderbook(paths['eth_orderbook'],ids,meta,min_ms,max_ms)],ignore_index=True)
 wide=build_wide(ob,m);wide.to_parquet(OUT/'hourly_topbook_last480s.parquet',index=False)
 specs=[('exact_40s_1s',40,1,.20),('scaled_480s_12s',480,12,.20*math.sqrt(12)),('scaled_480s_60s',480,60,.20*math.sqrt(60))]
 sig=attach_spot_features(wide,spot,m,specs);sig.to_parquet(OUT/'signals.parquet',index=False);print('signals',sig.groupby(['spec','crypto']).size().to_dict() if not sig.empty else {},flush=True)
 weeks=sorted(m.week_start.unique());rows=[];fills_all=[];hours_total=max(1.0,(m.end_ts.max()-m.end_ts.min())/3600+1);eligible_per_hour=len(m)/hours_total;half=.5*eligible_per_hour
 for spec,window,lookback,thr in specs:
  ss=sig[sig.spec==spec] if not sig.empty else sig
  for shares in [1.0,5.0,10.0,20.0]:
   f=execute(ss,wide,ticks,shares);fills_all.append(f)
   total=metrics(f,hours_total);rec={'spec':spec,'window_s':window,'lookback_s':lookback,'mom_threshold':thr,'requested_shares':shares,'eligible_markets':len(m),'eligible_per_hour':eligible_per_hour,'half_market_target_per_hour':half,'signals':len(ss),'signal_coverage':len(ss)/len(m),**{f'total_{k}':v for k,v in total.items()}}
   week_results=[]
   for wk in weeks:
    mm=m[m.week_start==wk];h=max(1.0,(mm.end_ts.max()-mm.end_ts.min())/3600+1);fw=f[f.week_start==wk] if not f.empty else f;met=metrics(fw,h);week_results.append({'week':str(wk),**met})
   rec['weeks_json']=json.dumps(week_results);valid=[x['arith'] for x in week_results if x['arith'] is not None];rec['worst_week_arith']=min(valid) if valid else None;rec['week_count_with_fills']=sum(x['n']>0 for x in week_results);rec['quality_floor_pass']=bool(rec['week_count_with_fills']>=2 and rec['worst_week_arith']>=QUALITY_FLOOR);rec['half_market_frequency_pass']=bool(total['per_hour']>=half);rec['joint_pass']=bool(rec['quality_floor_pass'] and rec['half_market_frequency_pass']);rows.append(rec)
 fills=pd.concat(fills_all,ignore_index=True) if fills_all else pd.DataFrame();fills.to_parquet(OUT/'fills.parquet',index=False)
 summary=pd.DataFrame(rows);summary.to_csv(OUT/'summary.csv',index=False)
 manifest={'repo':REPO,'revision':REV,'file_sha256':hashes,'resolved_markets':len(m),'date_min':pd.to_datetime(m.end_ts.min(),unit='s',utc=True).isoformat(),'date_max':pd.to_datetime(m.end_ts.max(),unit='s',utc=True).isoformat(),'eligible_per_hour':eligible_per_hour,'half_market_target_per_hour':half,'quality_floor':QUALITY_FLOOR,'execution':'actual top-of-book arrival after 1s; ask and displayed shares within limit; actual BUY tape volume within 1.5s covers requested shares'};(OUT/'manifest.json').write_text(json.dumps(manifest,indent=2))
 cols=['spec','requested_shares','signals','signal_coverage','total_n','total_per_hour','total_win_rate','total_arith','worst_week_arith','week_count_with_fills','quality_floor_pass','half_market_frequency_pass','joint_pass'];(OUT/'REPORT.md').write_text('\n'.join(['# Hourly Order-Book Spot-Dislocation Transfer','',summary[cols].to_markdown(index=False),'','This replay uses actual BTC/ETH hourly top-of-book asks and sizes, a one-second arrival delay, the frozen one-cent limit, actual subsequent BUY tape, and the same <=0.50 all-in cost cap. The 480-second rows are predeclared horizon adapters, not tuned winners.']))
 sums={p.name:sha256(p) for p in OUT.iterdir() if p.is_file()};(OUT/'SHA256SUMS.json').write_text(json.dumps(sums,indent=2));print(summary[cols].to_string(index=False));print('DONE')
if __name__=='__main__':main()
