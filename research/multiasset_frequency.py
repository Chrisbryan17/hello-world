from __future__ import annotations
import hashlib, json
from pathlib import Path
import requests
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

ASSETS=['btc','eth','sol','xrp','doge','bnb','hype']
REPO='kachoio/polymarket-5-minute-crypto-up-down-markets'
CLOCKS=[60,45,30,20]
C_GRID=[0.05,0.2,1.0]
COVERAGES=[0.01,0.05,0.10,0.25,0.50]
FAMILIES={
 'local':['mid_up','mom10','mom30','spread_up','spread_down','ask_sum','size_skew'],
 'btc_lead':['mid_up','mom10','mom30','spread_up','spread_down','ask_sum','size_skew','btc_mid_up','btc_mom10','btc_mom30','rel_btc'],
 'consensus':['mid_up','mom10','mom30','spread_up','spread_down','ask_sum','size_skew','consensus_mid','consensus_mom10','rel_consensus'],
 'full':['mid_up','mom10','mom30','spread_up','spread_down','ask_sum','size_skew','btc_mid_up','btc_mom10','btc_mom30','rel_btc','consensus_mid','consensus_mom10','rel_consensus'],
}
OUT=Path('results/multiasset_frequency')
DATA=Path('data')
OUT.mkdir(parents=True,exist_ok=True); DATA.mkdir(exist_ok=True)

def sha256(path):
 h=hashlib.sha256()
 with open(path,'rb') as f:
  for b in iter(lambda:f.read(1<<20),b''): h.update(b)
 return h.hexdigest()

def download(url,path):
 if path.exists(): return
 with requests.get(url,stream=True,timeout=120) as r:
  r.raise_for_status()
  with open(path,'wb') as f:
   for b in r.iter_content(1<<20):
    if b: f.write(b)

def cost(ask,slip=.01,coef=.07):
 q=np.clip(np.asarray(ask,dtype=float)+slip,.01,.99)
 return q+coef*q*(1-q)

def week_start(s):
 d=pd.to_datetime(s,utc=True)
 return (d-pd.to_timedelta((d.dt.dayofweek-1)%7,unit='D')).dt.floor('D')

def build_asset(asset,rev):
 mp=DATA/f'{asset}_markets.parquet'; tp=DATA/f'{asset}_ticks.parquet'
 base=f'https://huggingface.co/datasets/{REPO}/resolve/{rev}'
 download(f'{base}/{asset}_markets.parquet',mp); download(f'{base}/{asset}_ticks.parquet',tp)
 m=pd.read_parquet(mp,columns=['condition_id','market_start','market_end','outcome'])
 m=m[m.outcome.isin(['Up','Down'])].copy()
 m['market_start']=pd.to_datetime(m.market_start,utc=True)
 m['start_s']=(m.market_start.astype('int64')//10**9).astype('int64')
 start_map=pd.Series(m.start_s.values,index=m.condition_id).to_dict()
 cols=['condition_id','t','bu','au','bd','ad','sau','sad']
 t=pd.read_parquet(tp,columns=cols)
 t['rel']=t['t']-t['condition_id'].map(start_map)
 needed=sorted(set([300-c for c in CLOCKS]+[300-c-10 for c in CLOCKS]+[300-c-30 for c in CLOCKS]))
 t=t[t.rel.isin(needed)].copy()
 t['mid_up']=(t.bu+t.au)/2
 keep=['condition_id','rel','mid_up','bu','au','bd','ad','sau','sad']
 t=t[keep].drop_duplicates(['condition_id','rel'],keep='last')
 wide=t.pivot(index='condition_id',columns='rel')
 rows=[]; mm=m.set_index('condition_id')
 for clock in CLOCKS:
  r=300-clock; r10=r-10; r30=r-30
  required=[('mid_up',r),('mid_up',r10),('mid_up',r30),('bu',r),('au',r),('bd',r),('ad',r)]
  if any(x not in wide.columns for x in required): continue
  d=pd.DataFrame(index=wide.index)
  d['mid_up']=wide['mid_up',r]; d['mom10']=wide['mid_up',r]-wide['mid_up',r10]; d['mom30']=wide['mid_up',r]-wide['mid_up',r30]
  d['bu']=wide['bu',r]; d['au']=wide['au',r]; d['bd']=wide['bd',r]; d['ad']=wide['ad',r]
  d['sau']=wide['sau',r] if ('sau',r) in wide.columns else np.nan
  d['sad']=wide['sad',r] if ('sad',r) in wide.columns else np.nan
  d=d.join(mm[['market_start','outcome']],how='inner').dropna(subset=['mid_up','bu','au','bd','ad'])
  d['clock']=clock; d['asset']=asset; d['y']=(d.outcome=='Up').astype(int)
  d['spread_up']=d.au-d.bu; d['spread_down']=d.ad-d.bd; d['ask_sum']=d.au+d.ad
  d['size_skew']=np.log1p(d.sau.fillna(0))-np.log1p(d.sad.fillna(0))
  rows.append(d.reset_index())
 return pd.concat(rows,ignore_index=True)

def enrich(panel):
 btc=panel[panel.asset=='btc'][['market_start','clock','mid_up','mom10','mom30']].rename(columns={'mid_up':'btc_mid_up','mom10':'btc_mom10','mom30':'btc_mom30'})
 panel=panel.merge(btc,on=['market_start','clock'],how='left')
 g=panel.groupby(['market_start','clock'])
 panel['consensus_mid']=g.mid_up.transform('median'); panel['consensus_mom10']=g.mom10.transform('median')
 panel['rel_btc']=panel.mid_up-panel.btc_mid_up; panel['rel_consensus']=panel.mid_up-panel.consensus_mid
 panel['week_start']=week_start(panel.market_start); panel['hour']=panel.market_start.dt.floor('h')
 return panel.dropna(subset=['btc_mid_up','consensus_mid'])

def design(df,features,columns=None):
 x=df[features].copy(); dummies=pd.get_dummies(df.asset,prefix='asset',dtype=float)
 x=pd.concat([x.reset_index(drop=True),dummies.reset_index(drop=True)],axis=1)
 if columns is None: columns=x.columns.tolist()
 return x.reindex(columns=columns,fill_value=0.0),columns

def fit_predict(train,test,features,C):
 X,cols=design(train,features); Xt,_=design(test,features,cols)
 model=make_pipeline(StandardScaler(),LogisticRegression(C=C,max_iter=500))
 model.fit(X,train.y.values)
 return model.predict_proba(Xt)[:,1]

def select(df,p_up,coverage,slip=.01,coef=.07):
 z=df.copy(); z['p_up']=p_up
 cu=cost(z.au,slip,coef); cd=cost(z.ad,slip,coef)
 eu=z.p_up/cu; ed=(1-z.p_up)/cd
 z['side_up']=eu>=ed; z['score']=np.maximum(eu,ed)-1
 z['ask']=np.where(z.side_up,z.au,z.ad); z['ask_size']=np.where(z.side_up,z.sau,z.sad)
 z['won']=np.where(z.side_up,z.y==1,z.y==0)
 z['contract_multiple']=np.where(z.won,1/cost(z.ask,slip,coef),0.0)
 z=z.sort_values(['hour','score'],ascending=[True,False])
 z['hour_n']=z.groupby('hour').condition_id.transform('size')
 z['rank']=z.groupby('hour').cumcount()+1
 z['take_n']=np.ceil(z.hour_n*coverage).astype(int)
 return z[z['rank']<=z['take_n']].copy()

def metrics(trades):
 if trades.empty: return {'n':0,'arith':0,'win_rate':0}
 return {'n':int(len(trades)),'arith':float(trades.contract_multiple.mean()),'win_rate':float(trades.won.mean())}

def portfolio(trades,slip=.01,coef=.07):
 bank=1.0; peak=1.0; mdd=0.0
 for _,g in trades.sort_values('market_start').groupby('market_start'):
  mult=np.where(g.won,1/cost(g.ask,slip,coef),0.0)
  weights=np.zeros(len(g)); side=np.asarray(g.side_up)
  for val in [False,True]:
   idx=np.where(side==val)[0]
   if len(idx): weights[idx]=min(.20/len(idx),.12)
  gm=1-weights.sum()+float(np.dot(weights,mult))
  bank*=gm; peak=max(peak,bank); mdd=max(mdd,1-bank/peak)
 return {'terminal':float(bank),'mdd':float(mdd)}

def eligible_weeks(panel,min_starts=1600,min_asset_rows=1200):
 p=panel[panel.clock==60]
 starts=p.groupby('week_start').market_start.nunique()
 per_asset=p.groupby(['week_start','asset']).condition_id.size().unstack(fill_value=0).reindex(columns=ASSETS,fill_value=0)
 ok=(starts>=min_starts) & (per_asset.min(axis=1)>=min_asset_rows)
 return list(starts[ok].sort_index().index)

def run():
 info=requests.get(f'https://huggingface.co/api/datasets/{REPO}',timeout=60).json(); rev=info['sha']
 print('revision',rev)
 parts=[]; hashes={}
 for a in ASSETS:
  print('building',a,flush=True); parts.append(build_asset(a,rev))
  hashes[f'{a}_markets']=sha256(DATA/f'{a}_markets.parquet'); hashes[f'{a}_ticks']=sha256(DATA/f'{a}_ticks.parquet')
 panel=enrich(pd.concat(parts,ignore_index=True)); panel.to_parquet(OUT/'causal_panel.parquet',index=False)
 weeks=eligible_weeks(panel); print('eligible weeks',weeks); assert len(weeks)>=6, weeks
 tests=[]; choices=[]; selected_all=[]
 for fi in range(len(weeks)-2):
  va,vb,tw=weeks[fi:fi+3]; by_coverage={c:[] for c in COVERAGES}
  for family,features in FAMILIES.items():
   for clock in CLOCKS:
    tr_a=panel[(panel.week_start==va)&(panel.clock==clock)]
    tr_b=panel[(panel.week_start==vb)&(panel.clock==clock)]
    for C in C_GRID:
     p_b=fit_predict(tr_a,tr_b,features,C); p_a=fit_predict(tr_b,tr_a,features,C)
     for coverage in COVERAGES:
      vals=[metrics(select(tr_b,p_b,coverage))['arith'],metrics(select(tr_a,p_a,coverage))['arith']]
      by_coverage[coverage].append((min(vals),sum(vals)/2,family,clock,C,vals))
  for coverage in COVERAGES:
   candidates=by_coverage[coverage]
   candidates.sort(reverse=True,key=lambda x:(x[0],x[1],-len(FAMILIES[x[2]]),-x[3],-x[4]))
   best=candidates[0]; _,_,family,clock,C,_=best; features=FAMILIES[family]
   train=panel[(panel.week_start.isin([va,vb]))&(panel.clock==clock)]
   test=panel[(panel.week_start==tw)&(panel.clock==clock)]
   s=select(test,fit_predict(train,test,features,C),coverage)
   assert set(s.week_start.unique())=={tw}
   met=metrics(s); port=portfolio(s)
   tests.append({'coverage':coverage,'fold':fi+1,'val_a':str(va),'val_b':str(vb),'test_week':str(tw),'family':family,'clock':clock,'C':C,'val_worst':best[0],'val_mean':best[1],**met,**port})
   choices.append({'coverage':coverage,'fold':fi+1,'top_candidates':candidates[:10]})
   selected_all.append(s.assign(coverage=coverage,fold=fi+1,family=family,C=C,test_week=tw))
 tests=pd.DataFrame(tests); trades=pd.concat(selected_all,ignore_index=True)
 tests.to_csv(OUT/'fold_results.csv',index=False); trades.to_parquet(OUT/'selected_trades.parquet',index=False)
 (OUT/'candidate_choices.json').write_text(json.dumps(choices,default=str,indent=2))
 agg=[]
 for cov,g in tests.groupby('coverage'):
  tr=trades[trades.coverage==cov]
  elapsed=max(1,(tr.hour.max()-tr.hour.min()).total_seconds()/3600+1)
  base=portfolio(tr,.01,.07); slip2=portfolio(tr,.02,.07); zero=portfolio(tr,.01,0)
  cap=tr.ask_size.fillna(0)*tr.ask
  agg.append({'coverage':cov,'test_trades':len(tr),'trades_per_hour':len(tr)/elapsed,'worst_test_arith':g.arith.min(),'mean_test_arith':g.arith.mean(),'worst_test_win_rate':g.win_rate.min(),'mean_test_win_rate':g.win_rate.mean(),'base_terminal':base['terminal'],'base_mdd':base['mdd'],'slip2_terminal':slip2['terminal'],'slip2_mdd':slip2['mdd'],'zero_fee_terminal':zero['terminal'],'fok_ge_10':float((cap>=10).mean()),'fok_ge_25':float((cap>=25).mean()),'fok_ge_50':float((cap>=50).mean()),'median_top_ask_capacity':float(cap.median()),'quality_floor_pass':bool(g.arith.min()>=1.7563518376043876)})
 agg=pd.DataFrame(agg); agg.to_csv(OUT/'coverage_frontier.csv',index=False)
 trades.groupby(['coverage','asset']).agg(n=('won','size'),win_rate=('won','mean'),arith=('contract_multiple','mean'),median_capacity=('ask_size','median')).reset_index().to_csv(OUT/'asset_breakdown.csv',index=False)
 manifest={'dataset_repo':REPO,'dataset_revision':rev,'hashes':hashes,'weeks':[str(x) for x in weeks],'eligibility':{'min_unique_starts':1600,'min_rows_per_asset':1200},'quality_floor':1.7563518376043876,'selection':'two-week cross-fit validation, refit on both, one untouched next week','generated_utc':pd.Timestamp.now(tz='UTC').isoformat()}
 (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2))
 report=['# Multi-Asset Frequency Backtest','',f'Dataset revision: `{rev}`','','## Coverage frontier','',agg.to_markdown(index=False),'','## Fold results','',tests.to_markdown(index=False),'','## Interpretation','','A coverage row passes the frozen quality requirement only when every untouched test week has arithmetic contract multiple >= 1.7563518376043876. Portfolio results use a 40% total concurrent risk ceiling split into 20% Up and 20% Down buckets with a 12% per-position cap.','','The seven-asset corpus covers only 5-minute markets. Fifteen-minute and hourly transfer require separate historical datasets and are not inferred from this result.']
 (OUT/'REPORT.md').write_text('\n'.join(report))
 sums={p.name:sha256(p) for p in OUT.iterdir() if p.is_file()}; (OUT/'SHA256SUMS.json').write_text(json.dumps(sums,indent=2))
 print(agg.to_string(index=False)); print('DONE')
if __name__=='__main__': run()
