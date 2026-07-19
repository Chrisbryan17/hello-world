#!/usr/bin/env python3
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import argparse, json, random, re, time
import numpy as np, pandas as pd
from huggingface_hub import hf_hub_download, list_repo_files

REPO='trentmkelly/polymarket_crypto_derivatives'
LATS=(100,250,500,1000)
PAT=re.compile(r'btc5m_market(\d+)_(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})_all')

def first_after(ts,target,max_gap=300):
    i=int(np.searchsorted(ts,target,side='left'))
    return i if i<len(ts) and ts[i]-target<=max_gap else -1

def terminal_label(d,sm):
    sane=(d.up_best_bid.gt(0)&d.up_best_ask.gt(d.up_best_bid)&d.up_best_ask.lt(1)&d.down_best_bid.gt(0)&d.down_best_ask.gt(d.down_best_bid)&d.down_best_ask.lt(1))
    g=d[sane&d.ts.between(sm+270000,sm+302000)]
    if g.empty:return None
    r=g.iloc[-1];u=.5*(float(r.up_best_bid)+float(r.up_best_ask));v=.5*(float(r.down_best_bid)+float(r.down_best_ask))
    if max(u,v)<.85 or abs(u-v)<.70:return None
    return int(u>=v),int(r.ts),u,v

def compact(lp,rp):
    m=PAT.fullmatch(Path(rp).parent.name)
    if not m:return []
    mid,ss=m.groups();start=datetime.strptime(ss,'%Y-%m-%d_%H-%M-%S').replace(tzinfo=timezone.utc);sm=int(start.timestamp()*1000)
    d=pd.read_parquet(lp).sort_values('ts');lab=terminal_label(d,sm)
    if lab is None:return []
    y,lts,tu,td=lab;ts=d.ts.to_numpy(np.int64);rows=[]
    for lat in LATS:
        target=sm+60000+lat;i=first_after(ts,target,300)
        if i<0:continue
        r=d.iloc[i];vals=[r.up_best_bid,r.up_best_ask,r.down_best_bid,r.down_best_ask,r.up_bid_size_total,r.up_ask_size_total,r.down_bid_size_total,r.down_ask_size_total]
        if not all(np.isfinite(vals)):continue
        ub,ua,db,da,ubs,uas,dbs,das=map(float,vals)
        if not(0<ub<ua<1 and 0<db<da<1):continue
        rows.append({'episode':Path(rp).parent.name,'market_id':mid,'market_start':start.isoformat(),'market_start_s':int(start.timestamp()),'y':y,'label_ts':lts,'terminal_up_mid':tu,'terminal_down_mid':td,'latency_ms':lat,'entry_ts':int(r.ts),'entry_gap_ms':int(r.ts-target),'up_bid':ub,'up_ask':ua,'down_bid':db,'down_ask':da,'up_bid_size':ubs,'up_ask_size':uas,'down_bid_size':dbs,'down_ask_size':das,'up_imbalance':float(r.up_imbalance),'down_imbalance':float(r.down_imbalance)})
    return rows

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--shard',type=int,required=True);ap.add_argument('--shards',type=int,default=16);ap.add_argument('--workers',type=int,default=8);a=ap.parse_args()
    files=sorted(p for p in list_repo_files(REPO,repo_type='dataset') if p.startswith('btc5m_') and p.endswith('/steps.parquet'));sel=[p for i,p in enumerate(files) if i%a.shards==a.shard]
    def dl(p):
        err=None
        for k in range(6):
            try:return p,hf_hub_download(REPO,p,repo_type='dataset'),None
            except Exception as e:err=repr(e);time.sleep(min(8,.5*2**k)+random.random())
        return p,None,err
    with ThreadPoolExecutor(max_workers=a.workers) as ex:got=list(ex.map(dl,sel))
    rows=[];missing=[];fail={}
    for rp,lp,err in got:
        if lp is None:missing.append({'path':rp,'error':err});continue
        try:rows.extend(compact(lp,rp))
        except Exception as e:fail[type(e).__name__]=fail.get(type(e).__name__,0)+1
    out=pd.DataFrame(rows);pq=f'trent_btc60_books_shard_{a.shard:02d}.parquet';mf=f'trent_btc60_manifest_shard_{a.shard:02d}.json'
    if len(out):out.to_parquet(pq,index=False,compression='zstd')
    man={'all':len(files),'shard':a.shard,'selected':len(sel),'downloaded':len(got)-len(missing),'missing':missing,'rows':len(out),'markets':int(out.episode.nunique()) if len(out) else 0,'failures':fail,'latency_counts':out.latency_ms.value_counts().sort_index().to_dict() if len(out) else {}}
    Path(mf).write_text(json.dumps(man,indent=2));print(json.dumps(man,indent=2))
if __name__=='__main__':main()
