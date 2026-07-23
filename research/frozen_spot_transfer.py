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
 if isinstance(x,(np.integer,)): return int(x)
 if isinstance(x,(np.floating,)): return float(x)
 if isinstance(x,np.ndarray): return x.tolist()
 if isinstance(x,(pd.Timestamp,)): return x.isoformat()
 raise TypeError(type(x).__name__)

def main():
 hashes={}
 for name,url in CONVERT.items():
  p=DATA/f'{name}.parquet'; download(url,p); hashes[name]=sha256(p)
 print('downloaded',hashes,flush=True)
 ctxs=list(load_corpus(DATA,coins=('btc','eth','sol','xrp'),durations=('5m','15m')))
 print('contexts',len(ctxs),flush=True)
 slots=pd.DataFrame([{'condition_id':c.meta.condition_id,'coin':c.meta.coin,'duration':c.meta.duration,'open_ts':c.meta.open_ts,'close_ts':c.meta.close_ts,'resolved_side':c.meta.resolved_side,'snapshots':c.n,'has_tape':c.has_tape} for c in ctxs])
 slots['close_dt']=pd.to_datetime(slots.close_ts,unit='s',utc=True); slots['hour']=slots.close_dt.dt.floor('h'); slots['week']=slots.close_dt.dt.to_period('W-MON').astype(str)
 slots.to_csv(OUT/'corpus_inventory.csv',index=False)
 specs=[
  ('frozen_strike_40s','strike',40,.20,.50),
  ('oracle_aligned_open_40s','open',40,.20,.50),
  ('oracle_aligned_open_120s','open',120,.20,.50),
  ('oracle_aligned_open_300s','open',300,.20,.50),
 ]
 summaries=[]
 for name,anchor,window,mom,max_cost in specs:
  print('running',name,flush=True)
  sig=SpotDislocation(name,anchor,window,mom,max_cost,.01,20.0)
  recs=run_signal(sig,ctxs,latency_ms=1000,tape_window_ms=1500)
  row=leaderboard_row(sig.name,sig.family,sig.mode,recs)
  rdf=pd.DataFrame(recs)
  rdf.to_csv(OUT/f'{name}_records.csv',index=False)
  (OUT/f'{name}_leaderboard.json').write_text(json.dumps(row,indent=2,default=safe_json))
  print(name,'records',len(rdf),'columns',rdf.columns.tolist(),flush=True)
  entry={'name':name,'anchor':anchor,'window_s':window,'mom_bps':mom,'max_cost':max_cost,'decisions':len(rdf)}
  for k,v in row.items():
   if isinstance(v,(str,bool,int,float,np.integer,np.floating)) or v is None: entry[k]=safe_json(v) if not isinstance(v,(str,bool)) and v is not None else v
  if not rdf.empty:
   # Dynamic schema-safe metrics.
   for col in ['filled','paper_filled','persist_filled','tape_filled','won','fill_px','target_px','edge_real','paper_edge','ghost_gap']:
    if col in rdf:
     s=pd.to_numeric(rdf[col],errors='coerce')
     entry[f'{col}_mean']=float(s.mean())
     entry[f'{col}_sum']=float(s.sum())
   for col in ['coin','duration','week','fill_lens','status']:
    if col in rdf: entry[f'by_{col}']=rdf[col].astype(str).value_counts().to_dict()
  summaries.append(entry)
 pd.DataFrame(summaries).to_csv(OUT/'summary.csv',index=False)
 (OUT/'summary.json').write_text(json.dumps(summaries,indent=2,default=safe_json))
 manifest={'source_repo':REPO,'source_sha':SOURCE_SHA,'convert_urls':CONVERT,'file_sha256':hashes,'contexts':len(ctxs),'date_min':slots.close_dt.min().isoformat(),'date_max':slots.close_dt.max().isoformat(),'specs':specs,'execution':{'latency_ms':1000,'tape_window_ms':1500,'slippage':.01,'shares':20.0},'quality_floor_raw_contract_arithmetic':1.7563518376043876}
 (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2))
 report=['# Frozen Spot-Dislocation Independent Transfer','',f'Contexts: {len(ctxs):,} from {manifest["date_min"]} to {manifest["date_max"]}.','','## Summary','',pd.DataFrame(summaries).to_markdown(index=False),'','The frozen row is the verbatim structural transfer: strike anchor, final 40 seconds, signed one-second spot momentum >=0.20 bps, all-in cost <=0.50, first decision per market, 1-cent taker tolerance. The open-anchor rows are explicitly labeled diagnostics because the independent corpus documents a spot-versus-oracle level offset. Honest grades use one-second book persistence and a 1.5-second real-trade corroboration window.']
 (OUT/'REPORT.md').write_text('\n'.join(report))
 sums={p.name:sha256(p) for p in OUT.iterdir() if p.is_file()}; (OUT/'SHA256SUMS.json').write_text(json.dumps(sums,indent=2))
 print(pd.DataFrame(summaries).to_string(index=False)); print('DONE',flush=True)
if __name__=='__main__': main()
