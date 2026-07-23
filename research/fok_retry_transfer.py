from __future__ import annotations
import hashlib,json,math
from pathlib import Path
import requests
import numpy as np
import pandas as pd
from honest_backtest.adapters.parquet_pm import load_corpus

REPO='kinzikdza/polymarket-updown-microstructure'
SOURCE_SHA='eb4e9fc794c059dd9bef69c98eb4d34e70a5bd83'
QUALITY_FLOOR=1.7563518376043876
URLS={
 'book_snapshots':'https://huggingface.co/datasets/kinzikdza/polymarket-updown-microstructure/resolve/refs%2Fconvert%2Fparquet/book_snapshots/train/0000.parquet',
 'pm_trades':'https://huggingface.co/datasets/kinzikdza/polymarket-updown-microstructure/resolve/refs%2Fconvert%2Fparquet/pm_trades/train/0000.parquet',
 'slots':'https://huggingface.co/datasets/kinzikdza/polymarket-updown-microstructure/resolve/refs%2Fconvert%2Fparquet/slots/train/0000.parquet',
}
OUT=Path('results/fok_retry_transfer');DATA=Path('data/kinzik')
OUT.mkdir(parents=True,exist_ok=True);DATA.mkdir(parents=True,exist_ok=True)

def sha256(p):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for b in iter(lambda:f.read(1<<20),b''):h.update(b)
 return h.hexdigest()

def download(url,p):
 if p.exists():return
 with requests.get(url,stream=True,timeout=180) as r:
  r.raise_for_status()
  with open(p,'wb') as f:
   for b in r.iter_content(1<<20):
    if b:f.write(b)

def fee_cost(px):
 q=float(np.clip(px,.01,.99));return q+.07*q*(1-q)

def find_signal(ctx):
 for i in range(ctx.n):
  s2c=int(ctx.s2c[i])
  if s2c<0 or s2c>40 or not ctx.book_ok(i):continue
  spot=float(ctx.spot[i]);anchor=float(ctx.meta.strike)
  if not(np.isfinite(spot) and np.isfinite(anchor) and spot>0 and anchor>0):continue
  yes=spot>=anchor;sign=1.0 if yes else -1.0
  dist=sign*math.log(spot/anchor)*1e4;mom=sign*ctx.spot_ret_bps(i,1);vol=ctx.realized_vol_persec(i,10)*1e4
  ask=float(ctx.ask(i,yes));limit=float(np.clip(ask+.01,.01,.99))
  if dist>=0 and dist/max(vol,1e-9)>=0 and mom>=.20 and fee_cost(limit)<=.50:
   return {'i':i,'ts_ms':int(ctx.ts[i]),'yes':yes,'limit':limit,'decision_ask':ask,'s2c':s2c,'dist':dist,'mom':mom}
 return None

def try_fill(ctx,sig,shares,retry_s):
 start=sig['ts_ms']+1000;stop=sig['ts_ms']+int(retry_s*1000)
 for attempt in range(start,stop+1,1000):
  k=int(np.searchsorted(ctx.ts,attempt,side='left'))
  if k>=ctx.n or int(ctx.ts[k])-attempt>4000:continue
  ask=float(ctx.ask(k,sig['yes']));ask_sz=float(ctx.ask_sz(k,sig['yes'])) if np.isfinite(ctx.ask_sz(k,sig['yes'])) else 0.0
  if not(np.isfinite(ask) and ask<=sig['limit']+1e-9 and ask_sz>=shares):continue
  m=((ctx.tr_yes==sig['yes'])&ctx.tr_buy&(ctx.tr_px<=sig['limit']+1e-9)&(ctx.tr_ts>=attempt)&(ctx.tr_ts<=attempt+1500))
  tape=float(ctx.tr_sz[m].sum())
  if tape>=shares:
   return {'fill_ts_ms':int(ctx.ts[k]),'fill_px':ask,'ask_size':ask_sz,'tape_shares':tape,'attempt_delay_s':(attempt-sig['ts_ms'])/1000}
 return None

def metrics(d,hours):
 if d.empty:return {'n':0,'per_hour':0.0,'win_rate':None,'arith':None,'worst_week':None,'worst_week_n':0,'weeks':0,'net_per_share':None}
 x=d.copy();x['cost']=x.fill_px.map(fee_cost);x['mult']=np.where(x.won,1/x.cost,0.0)
 w=x.groupby('week').agg(n=('cid','size'),arith=('mult','mean'))
 return {'n':int(len(x)),'per_hour':float(len(x)/hours),'win_rate':float(x.won.mean()),'arith':float(x.mult.mean()),'worst_week':float(w.arith.min()),'worst_week_n':int(w.loc[w.arith.idxmin(),'n']),'weeks':int(len(w)),'net_per_share':float((x.won.astype(float)-x.cost).mean())}

def main():
 hashes={}
 for n,u in URLS.items():
  p=DATA/f'{n}.parquet';download(u,p);hashes[n]=sha256(p)
 ctxs=list(load_corpus(DATA,coins=('btc','eth','sol','xrp'),durations=('5m','15m')))
 starts=[];decisions=[]
 for ctx in ctxs:
  starts.append(ctx.meta.close_ts)
  s=find_signal(ctx)
  if s is None:continue
  decisions.append((ctx,s))
 print('contexts',len(ctxs),'signals',len(decisions),flush=True)
 hours=(max(starts)-min(starts))/3600 if starts else 1
 rows=[];fills=[]
 for retry_s in [1.5,5,15,30]:
  for shares in [1.0,5.0,10.0]:
   rec=[]
   for ctx,s in decisions:
    f=try_fill(ctx,s,shares,retry_s)
    if f is None:continue
    dt=pd.to_datetime(s['ts_ms'],unit='ms',utc=True);wk=str(dt.tz_localize(None).to_period('W-MON'))
    rec.append({'cid':ctx.meta.condition_id,'coin':ctx.meta.coin,'dur':ctx.meta.duration,'week':wk,'won':bool(ctx.meta.resolved_yes==s['yes']),'requested_shares':shares,'retry_s':retry_s,**s,**f})
   d=pd.DataFrame(rec);fills.append(d)
   met=metrics(d,hours);quality=bool(met['weeks']>=4 and met['worst_week'] is not None and met['worst_week']>=QUALITY_FLOOR)
   rows.append({'retry_s':retry_s,'requested_shares':shares,'signals':len(decisions),'decision_per_hour':len(decisions)/hours,**met,'quality_floor_pass':quality})
 out=pd.DataFrame(rows);out.to_csv(OUT/'summary.csv',index=False)
 fd=pd.concat(fills,ignore_index=True) if fills else pd.DataFrame();fd.to_parquet(OUT/'fills.parquet',index=False)
 manifest={'repo':REPO,'source_sha':SOURCE_SHA,'hashes':hashes,'contexts':len(ctxs),'signals':len(decisions),'hours':hours,'quality_floor':QUALITY_FLOOR,'retry_definition':'same frozen signal and limit; IOC/FOK attempt every second starting +1s; each accepted only if arrival ask/size and 1.5s qualifying tape cover full order'};(OUT/'manifest.json').write_text(json.dumps(manifest,indent=2))
 (OUT/'REPORT.md').write_text('\n'.join(['# Frozen FOK Retry Frontier','',out.to_markdown(index=False),'','Retrying changes only execution timing. The signal, side, one-cent limit, fee cap, and first signal per market remain frozen.']))
 sums={p.name:sha256(p) for p in OUT.iterdir() if p.is_file()};(OUT/'SHA256SUMS.json').write_text(json.dumps(sums,indent=2));print(out.to_string(index=False));print('DONE')
if __name__=='__main__':main()
