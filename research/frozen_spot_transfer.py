from __future__ import annotations
import hashlib, json, math
from pathlib import Path
import requests
import numpy as np
import pandas as pd
from honest_backtest import Signal, Decision, run_signal, leaderboard_row
from honest_backtest.adapters.parquet_pm import load_corpus

REPO='kinzikdza/polymarket-updown-microstructure'
SOURCE_SHA='eb4e9fc794c059dd9bef69c98eb4d34e70a5bd83'
QUALITY_FLOOR=1.7563518376043876
CONVERT={
 'book_snapshots':'https://huggingface.co/datasets/kinzikdza/polymarket-updown-microstructure/resolve/refs%2Fconvert%2Fparquet/book_snapshots/train/0000.parquet',
 'pm_trades':'https://huggingface.co/datasets/kinzikdza/polymarket-updown-microstructure/resolve/refs%2Fconvert%2Fparquet/pm_trades/train/0000.parquet',
 'slots':'https://huggingface.co/datasets/kinzikdza/polymarket-updown-microstructure/resolve/refs%2Fconvert%2Fparquet/slots/train/0000.parquet',
}
OUT=Path('results/frozen_spot_transfer'); DATA=Path('data/kinzik')
OUT.mkdir(parents=True,exist_ok=True); DATA.mkdir(parents=True,exist_ok=True)

def sha256(path):
 h=hashlib.sha256()
 with open(path,'rb') as f:
  for b in iter(lambda:f.read(1<<20),b''): h.update(b)
 return h.hexdigest()

def download(url,path):
 if path.exists(): return
 with requests.get(url,stream=True,timeout=180) as r:
  r.raise_for_status()
  with open(path,'wb') as f:
   for b in r.iter_content(1<<20):
    if b: f.write(b)

def all_in_cost(ask,slippage=.01,fee_coef=.07):
 q=float(np.clip(ask+slippage,.01,.99))
 return q+fee_coef*q*(1-q),q

def row_cost(df):
 q=np.clip(pd.to_numeric(df['fill_px'],errors='coerce').astype(float),.01,.99)
 fee=pd.to_numeric(df.get('fee_rate',.07),errors='coerce').fillna(.07).astype(float)
 return q+fee*q*(1-q)

class SpotDislocation(Signal):
 mode='taker'; coins=('btc','eth','sol','xrp'); durations=('5m','15m'); once=True
 def __init__(self,name,anchor='strike',window_s=40,mom_bps=.20,max_cost=.50,slippage=.01,size=20.0):
  self.name=name; self.family='spot_dislocation_transfer'; self.anchor=anchor
  self.window_s=window_s; self.mom_bps=mom_bps; self.max_cost=max_cost
  self.slippage=slippage; self.size=size
 def decide(self,ctx,i):
  s2c=int(ctx.s2c[i])
  if s2c<0 or s2c>self.window_s or not ctx.book_ok(i): return None
  spot=float(ctx.spot[i])
  anchor=float(ctx.meta.strike if self.anchor=='strike' else ctx.meta.spot_at_open)
  if not np.isfinite(spot) or not np.isfinite(anchor) or spot<=0 or anchor<=0: return None
  buy_yes=spot>=anchor; sign=1.0 if buy_yes else -1.0
  dist=sign*math.log(spot/anchor)*1e4
  mom=sign*ctx.spot_ret_bps(i,1)
  vol=ctx.realized_vol_persec(i,10)*1e4
  ask=float(ctx.ask(i,buy_yes))
  if not (0<ask<1): return None
  total,limit_px=all_in_cost(ask,self.slippage,.07)
  if dist<0 or dist/max(vol,1e-9)<0 or mom<self.mom_bps or total>self.max_cost: return None
  return Decision(i=i,ts_ms=int(ctx.ts[i]),token_yes=bool(buy_yes),action='taker',target_px=limit_px,size=self.size,tag=f'dist={dist:.4f}|mom1={mom:.4f}|vol={vol:.4f}|s2c={s2c}')

def safe_json(x):
 if x is None or isinstance(x,(str,bool,int,float)): return x
 if isinstance(x,np.integer): return int(x)
 if isinstance(x,np.floating): return float(x)
 if isinstance(x,np.ndarray): return x.tolist()
 if isinstance(x,pd.Timestamp): return x.isoformat()
 if isinstance(x,dict): return {str(k):safe_json(v) for k,v in x.items()}
 if isinstance(x,(list,tuple)): return [safe_json(v) for v in x]
 raise TypeError(type(x).__name__)

def lens_metrics(rdf,mask,calendar_hours):
 g=rdf.loc[mask].copy()
 if g.empty:
  return {'n':0,'per_hour':0.0,'win_rate':None,'avg_fill_px':None,'avg_all_in_cost':None,'arithmetic_multiple':None,'worst_week_arithmetic':None,'worst_week_n':0,'net_edge_per_share':None}
 cost=row_cost(g)
 mult=np.where(g['won'].astype(bool),1.0/cost,0.0)
 g['_cost']=cost; g['_multiple']=mult
 weekly=g.groupby('week').agg(n=('cid','size'),arithmetic=('_multiple','mean'),win_rate=('won','mean'),avg_cost=('_cost','mean')).reset_index()
 worst=weekly.sort_values(['arithmetic','week']).iloc[0]
 return {
  'n':int(len(g)),
  'per_hour':float(len(g)/calendar_hours),
  'win_rate':float(g['won'].mean()),
  'avg_fill_px':float(g['fill_px'].mean()),
  'avg_all_in_cost':float(cost.mean()),
  'arithmetic_multiple':float(np.mean(mult)),
  'worst_week_arithmetic':float(worst['arithmetic']),
  'worst_week_n':int(worst['n']),
  'net_edge_per_share':float((g['won'].astype(float)-cost).mean()),
 }

def breakdown(rdf,mask):
 g=rdf.loc[mask].copy()
 if g.empty: return []
 g['_cost']=row_cost(g); g['_multiple']=np.where(g['won'].astype(bool),1.0/g['_cost'],0.0)
 out=g.groupby(['coin','dur']).agg(n=('cid','size'),win_rate=('won','mean'),avg_cost=('_cost','mean'),arithmetic_multiple=('_multiple','mean'),median_honest_shares=('honest_sz','median')).reset_index()
 return out.to_dict('records')

def main():
 hashes={}
 for name,url in CONVERT.items():
  p=DATA/f'{name}.parquet'; download(url,p); hashes[name]=sha256(p)
 print('downloaded',hashes,flush=True)
 ctxs=list(load_corpus(DATA,coins=('btc','eth','sol','xrp'),durations=('5m','15m')))
 print('contexts',len(ctxs),flush=True)
 slots=pd.DataFrame([{'condition_id':c.meta.condition_id,'coin':c.meta.coin,'duration':c.meta.duration,'open_ts':c.meta.open_ts,'close_ts':c.meta.close_ts,'resolved_side':c.meta.resolved_side,'snapshots':c.n,'has_tape':c.has_tape} for c in ctxs])
 slots['close_dt']=pd.to_datetime(slots.close_ts,unit='s',utc=True); slots['hour']=slots.close_dt.dt.floor('h'); slots['week']=slots.close_dt.dt.tz_localize(None).dt.to_period('W-MON').astype(str)
 slots.to_csv(OUT/'corpus_inventory.csv',index=False)
 calendar_hours=max(1.0,(slots['close_dt'].max()-slots['close_dt'].min()).total_seconds()/3600.0)
 specs=[
  ('frozen_strike_40s_s5','strike',40,.20,.50,5.0,'exact_liquidity_sensitivity'),
  ('frozen_strike_40s_s10','strike',40,.20,.50,10.0,'exact_liquidity_sensitivity'),
  ('frozen_strike_40s_s20','strike',40,.20,.50,20.0,'exact_frozen_structure'),
  ('frozen_strike_40s_s40','strike',40,.20,.50,40.0,'exact_liquidity_sensitivity'),
  ('oracle_aligned_open_40s_s20','open',40,.20,.50,20.0,'diagnostic_anchor'),
  ('oracle_aligned_open_120s_s20','open',120,.20,.50,20.0,'diagnostic_window'),
  ('oracle_aligned_open_300s_s20','open',300,.20,.50,20.0,'diagnostic_window'),
 ]
 summaries=[]
 for name,anchor,window,mom,max_cost,size,label in specs:
  print('running',name,flush=True)
  sig=SpotDislocation(name,anchor,window,mom,max_cost,.01,size)
  recs=run_signal(sig,ctxs,latency_ms=1000,tape_window_ms=1500)
  row=leaderboard_row(sig.name,sig.family,sig.mode,recs)
  rdf=pd.DataFrame(recs)
  if not rdf.empty:
   rdf['dt']=pd.to_datetime(rdf['ts_ms'],unit='ms',utc=True)
   rdf['week']=rdf['dt'].dt.tz_localize(None).dt.to_period('W-MON').astype(str)
  rdf.to_csv(OUT/f'{name}_records.csv',index=False)
  (OUT/f'{name}_leaderboard.json').write_text(json.dumps(row,indent=2,default=safe_json,allow_nan=True))
  print(name,'records',len(rdf),'columns',rdf.columns.tolist(),flush=True)
  paper=rdf['crossable'].astype(bool) if not rdf.empty else pd.Series([],dtype=bool)
  persist=(rdf['persisted'].astype(bool)&rdf['persist_known'].astype(bool)) if not rdf.empty else pd.Series([],dtype=bool)
  fillable=rdf['fillable'].astype(bool) if not rdf.empty else pd.Series([],dtype=bool)
  entry={
   'name':name,'label':label,'anchor':anchor,'window_s':window,'mom_bps':mom,'max_cost':max_cost,'requested_shares':size,
   'eligible_markets':int(len(slots)),'eligible_markets_per_hour':float(len(slots)/calendar_hours),
   'decision_coverage':float(len(rdf)/len(slots)) if len(slots) else 0.0,
   'paper':lens_metrics(rdf,paper,calendar_hours),
   'persist':lens_metrics(rdf,persist,calendar_hours),
   'fillable':lens_metrics(rdf,fillable,calendar_hours),
   'fillable_breakdown':breakdown(rdf,fillable),
   'persist_breakdown':breakdown(rdf,persist),
   'leaderboard':safe_json(row),
  }
  fw=entry['fillable']['worst_week_arithmetic']
  entry['quality_floor_pass']=bool(fw is not None and fw>=QUALITY_FLOOR)
  summaries.append(entry)
 flat=[]
 for s in summaries:
  r={k:v for k,v in s.items() if k not in ('paper','persist','fillable','fillable_breakdown','persist_breakdown','leaderboard')}
  for lens in ('paper','persist','fillable'):
   for k,v in s[lens].items(): r[f'{lens}_{k}']=v
  flat.append(r)
 pd.DataFrame(flat).to_csv(OUT/'summary.csv',index=False)
 (OUT/'summary.json').write_text(json.dumps(summaries,indent=2,default=safe_json,allow_nan=True))
 manifest={'source_repo':REPO,'source_sha':SOURCE_SHA,'convert_urls':CONVERT,'file_sha256':hashes,'contexts':len(ctxs),'date_min':slots.close_dt.min().isoformat(),'date_max':slots.close_dt.max().isoformat(),'calendar_hours':calendar_hours,'specs':specs,'execution':{'latency_ms':1000,'tape_window_ms':1500,'slippage':.01},'quality_floor_raw_contract_arithmetic':QUALITY_FLOOR}
 (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2,default=safe_json))
 display=pd.DataFrame(flat)
 cols=['name','requested_shares','decision_coverage','paper_per_hour','persist_per_hour','fillable_per_hour','fillable_n','fillable_win_rate','fillable_arithmetic_multiple','fillable_worst_week_arithmetic','fillable_worst_week_n','quality_floor_pass']
 report=['# Frozen Spot-Dislocation Independent Transfer','',f'Contexts: {len(ctxs):,} from {manifest["date_min"]} to {manifest["date_max"]}.','','## Frequency and quality','',display[cols].to_markdown(index=False),'','The `frozen_strike_40s_s20` row is the exact structural transfer: strike anchor, final 40 seconds, signed one-second spot momentum >=0.20 bps, all-in cost <=0.50, first decision per market, 1-cent taker tolerance. Share-size variants change only the executable-liquidity requirement. Open-anchor and wider-window rows are diagnostics, not frozen-policy claims. Honest persistence requires a known one-second-persistent book; fillable requires real-trade corroboration within 1.5 seconds and sufficient observed shares.']
 (OUT/'REPORT.md').write_text('\n'.join(report))
 sums={p.name:sha256(p) for p in OUT.iterdir() if p.is_file()}; (OUT/'SHA256SUMS.json').write_text(json.dumps(sums,indent=2))
 print(display[cols].to_string(index=False)); print('DONE',flush=True)
if __name__=='__main__': main()
