#!/usr/bin/env python3
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import argparse, json, re
import numpy as np, pandas as pd
from huggingface_hub import hf_hub_download, list_repo_files

REPO='trentmkelly/polymarket_crypto_derivatives'
PAT=re.compile(r'btc5m_market(\d+)_(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})_all')

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--shard',type=int,default=0);ap.add_argument('--shards',type=int,default=64);args=ap.parse_args()
    files=sorted(p for p in list_repo_files(REPO,repo_type='dataset') if p.startswith('btc5m_') and p.endswith('/steps.parquet'))
    selected=[p for i,p in enumerate(files) if i%args.shards==args.shard]
    def dl(p):return p,hf_hub_download(REPO,p,repo_type='dataset')
    with ThreadPoolExecutor(max_workers=8) as ex: local=list(ex.map(dl,selected))
    counts={k:0 for k in ['episodes','starts_2s','binance_open_2s','chainlink_open_2s','has_sane_preclose','terminal_confident','entry10_100','entry20_100','entry60_100']}
    rows=[]
    for rp,lp in local:
        counts['episodes']+=1
        m=PAT.fullmatch(Path(rp).parent.name);start=datetime.strptime(m.group(2),'%Y-%m-%d_%H-%M-%S').replace(tzinfo=timezone.utc);sm=int(start.timestamp()*1000)
        d=pd.read_parquet(lp).sort_values('ts');first=int(d.ts.min());last=int(d.ts.max())
        min_prog=float(d.progress.min());max_prog=float(d.progress.max())
        starts=first<=sm+2000
        counts['starts_2s']+=int(starts)
        b=d[['ts','binance_price']].dropna();c=d[['ts','chainlink_price']].dropna()
        bopen=(len(b)>0 and int(b.ts.min())<=sm+2000);copen=(len(c)>0 and int(c.ts.min())<=sm+2000)
        counts['binance_open_2s']+=int(bopen);counts['chainlink_open_2s']+=int(copen)
        sane=(d.up_best_bid.gt(0)&d.up_best_ask.gt(d.up_best_bid)&d.up_best_ask.lt(1)&d.down_best_bid.gt(0)&d.down_best_ask.gt(d.down_best_bid)&d.down_best_ask.lt(1))
        g=d[sane&d.ts.between(sm+270000,sm+302000)]
        has_final=not g.empty;counts['has_sane_preclose']+=int(has_final)
        conf=False;upm=dnm=np.nan;final_off=np.nan
        if has_final:
            r=g.iloc[-1];upm=.5*(float(r.up_best_bid)+float(r.up_best_ask));dnm=.5*(float(r.down_best_bid)+float(r.down_best_ask));final_off=(int(r.ts)-sm)/1000;conf=max(upm,dnm)>=.85 and abs(upm-dnm)>=.70
        counts['terminal_confident']+=int(conf)
        entry={}
        for obs in [10,20,60]:
            q=d[d.ts.between(sm+obs*1000+100,sm+obs*1000+400)]
            ok=bool(len(q) and ((q.up_best_bid>0)&(q.up_best_ask>q.up_best_bid)&(q.up_best_ask<1)&(q.down_best_bid>0)&(q.down_best_ask>q.down_best_bid)&(q.down_best_ask<1)).any())
            counts[f'entry{obs}_100']+=int(ok);entry[obs]=ok
        rows.append({'episode':Path(rp).parent.name,'first_offset_s':(first-sm)/1000,'last_offset_s':(last-sm)/1000,'min_progress':min_prog,'max_progress':max_prog,'binance_first_offset_s':((int(b.ts.min())-sm)/1000 if len(b) else None),'chainlink_first_offset_s':((int(c.ts.min())-sm)/1000 if len(c) else None),'sane_preclose':has_final,'final_offset_s':final_off,'terminal_up_mid':upm,'terminal_down_mid':dnm,'terminal_confident':conf,**{f'entry{obs}':v for obs,v in entry.items()}})
    out=pd.DataFrame(rows)
    report={'counts':counts,'numeric_summary':out.describe(include='all').to_dict(),'examples':out.head(25).to_dict(orient='records')}
    Path('trent_coverage_diagnostic.json').write_text(json.dumps(report,indent=2,default=str));out.to_csv('trent_coverage_diagnostic.csv',index=False);print(json.dumps(counts,indent=2))
if __name__=='__main__':main()
