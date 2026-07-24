from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import requests

REPO='obadiaha/polymarket-crypto-5m-15m'
REV='11793901f0ac89c5a6c51123a6ccd29a3aaf8f4c'
BASE=f'https://huggingface.co/datasets/{REPO}/resolve/{REV}'
FILES={
 'markets':('markets/all.parquet','896c68fa25b49b24e4f57b4e66e857ee94660f03aa6f5f1a3d7be3cd509c8c40'),
 'resolutions':('resolutions/all.parquet','d7715217e85da2e613ac6f765d272bc08b8d87b0f65a9a21bd86e64644729758'),
 'books_0310':('orderbooks/2026-03-10.parquet',None),
 'books_0312':('orderbooks/2026-03-12.parquet','2461fcc11cfe4d36c8ea1ee103c1892c19a882ee19e331f2b9faef9049dc37d8'),
}

def download(name,path,expected):
    target=Path(f'{name}.parquet')
    with requests.get(f'{BASE}/{path}',stream=True,timeout=300) as r:
        r.raise_for_status()
        with target.open('wb') as f:
            for block in r.iter_content(1<<20):
                if block:f.write(block)
    got=hashlib.sha256(target.read_bytes()).hexdigest()
    if expected: assert got==expected,(name,got,expected)
    return target,got

def main():
    hashes={};paths={}
    for name,(path,expected) in FILES.items():
        paths[name],hashes[name]=download(name,path,expected)
    markets=pd.read_parquet(paths['markets'])
    resolutions=pd.read_parquet(paths['resolutions'])
    books=pd.concat([pd.read_parquet(paths['books_0310']),pd.read_parquet(paths['books_0312'])],ignore_index=True)
    books=books[books.asset=='BTC'].copy()
    print('MARKETS HEAD\n',markets.head().to_string(index=False));print('MARKETS TAIL\n',markets.tail().to_string(index=False))
    print('RES HEAD\n',resolutions.head().to_string(index=False));print('RES TAIL\n',resolutions.tail().to_string(index=False))
    print('BOOKS HEAD\n',books.head().to_string(index=False))
    # Join candidates through exact market/question text and normalized strings.
    markets['key']=markets.market_id.astype(str)
    resolutions['key']=resolutions.market_id.astype(str)
    direct=resolutions.merge(markets[['key','question','start_time','end_time']],on='key',how='inner')
    print('direct merge',len(direct),'resolution rows',len(resolutions),'market rows',len(markets))
    book_ids=set(books.market_id.astype(str))
    res_book=resolutions[resolutions.market_id.astype(str).isin(book_ids)].copy()
    market_book=markets[markets.market_id.astype(str).isin(book_ids)].copy()
    print('book ids',len(book_ids),'res_book',len(res_book),'market_book',len(market_book))
    # Resolution rows can be keyed by question text while books use slugs. Parse epoch from slug and compare starts.
    books['epoch']=books.market_id.astype(str).str.extract(r'-(\d{10})$')[0].astype('Int64')
    books['duration']=np.where(books.market_id.astype(str).str.contains('15m'),'15m','5m')
    books['end_epoch']=books['epoch']+np.where(books.duration=='15m',900,300)
    # Inspect first-seen token order and final-token winner against any resolution match by time/question.
    first=(books.sort_values(['market_id','timestamp']).drop_duplicates(['market_id','token_id']).groupby('market_id').head(2))
    last=(books.sort_values(['market_id','timestamp']).groupby(['market_id','token_id'],as_index=False).tail(1))
    orientation=[]
    for mid,g in first.groupby('market_id'):
        ordered=g.sort_values('timestamp').token_id.astype(str).tolist()
        lg=last[last.market_id==mid].copy()
        if len(ordered)==2 and len(lg)>=2:
            lg['score']=lg.mid_price.fillna((lg.best_bid+lg.best_ask)/2)
            winner=str(lg.sort_values('score',ascending=False).iloc[0].token_id)
            orientation.append({'market_id':mid,'first_token':ordered[0],'second_token':ordered[1],'winner_token':winner,'first_is_winner':ordered[0]==winner,'winner_score':float(lg.score.max()),'loser_score':float(lg.score.min())})
    orientation=pd.DataFrame(orientation)
    output={
      'revision':REV,'hashes':hashes,
      'markets_rows':len(markets),'resolutions_rows':len(resolutions),'book_rows':len(books),'book_markets':len(book_ids),
      'direct_resolution_market_join':len(direct),'resolution_book_join':len(res_book),'market_book_join':len(market_book),
      'book_date_min':books.timestamp.min().isoformat(),'book_date_max':books.timestamp.max().isoformat(),
      'duration_counts':books.drop_duplicates('market_id').duration.value_counts().to_dict(),
      'first_token_winner_rate':float(orientation.first_is_winner.mean()) if len(orientation) else None,
      'orientation_rows':len(orientation),
      'orientation_confident':int(((orientation.winner_score>=.8)&(orientation.loser_score<=.2)).sum()) if len(orientation) else 0,
      'market_tail':json.loads(markets.tail(5).to_json(orient='records',date_format='iso')),
      'resolution_tail':json.loads(resolutions.tail(5).to_json(orient='records',date_format='iso')),
      'orientation_sample':orientation.head(20).to_dict('records'),
    }
    Path('obadiaha-semantics.json').write_text(json.dumps(output,indent=2))
    print(json.dumps(output,indent=2))

if __name__=='__main__':main()
