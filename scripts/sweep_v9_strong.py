#!/usr/bin/env python3
"""v9 sweep: strong-only entry (score>=65) + cooldown 1/3/5/7 bars"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crypto_trading import (
    sma, evaluate_trend_3d, compute_volume_score,
    compute_entry_v6_long, compute_entry_v6_short,
    resolve_action_v6, _entry_score_v7_long,
    get_coin_profile, SHORT_ALLOWED, compute_rsi,
)

SF=1.5; BASE=10000; TOTAL=BASE*1.8
COINS=['ETH','BNB','TRX']; SYM={c:f'{c}USDT' for c in COINS}
def lev(c): return 3.0 if c=='ETH' else 2.5
def tr_r(c): return 0.035 if c=='ETH' else 0.065
def esz(c,s): return (0.09 if s else 0.07) if c=='ETH' else (0.07 if s else 0.055)
TP=[(7,0.07),(12,0.11),(20,0.20),(30,0.27)]; INITIAL=75
CACHE=os.path.join(os.path.dirname(os.path.abspath(__file__)), '_klines_12h_5y.json')
with open(CACHE) as f: _cache=json.load(f)
def fetch(s): return _cache.get(f'{s}_4000_1609434000000',[])
def aggr(c,n=3):
    r=[]
    for i in range(0,len(c)-n+1,n): b=c[i:i+n]; r.append({'close':b[-1]['close']})
    return r

def bt(coin, sl_roi, cd_bars):
    prof=dict(get_coin_profile(coin)); lv=lev(coin); trr=tr_r(coin)
    entries=[]; eq=1.0; curve=[]; trades=[]; last_entry_idx=-999
    da=fetch(SYM[coin])
    for idx in range(INITIAL,len(da)):
        ds=da[:idx+1]; ct=aggr(ds,3)
        if len(ct)<25: continue
        cc=ds[-1]['close']; cl=[c['close'] for c in ct]
        mf=sma(cl,10)[-1] or cl[-1]; mm=sma(cl,15)[-1] or cl[-1]; ms=sma(cl,30)[-1] or cl[-1]
        _,ts=evaluate_trend_3d(mf,mm,ms)
        c1=[c['close'] for c in ds]; v1=[c['volume'] for c in ds]
        ef=sma(c1,18)[-1] or c1[-1]; em=sma(c1,37)[-1] or c1[-1]; es=sma(c1,30)[-1] or c1[-1]
        ma7=sma(c1,int(7*SF))[-1] or c1[-1]; ma10=sma(c1,int(10*SF))[-1] or c1[-1]
        ma200=sma(c1,int(200*SF))[-1] or None
        vm=sma(v1,int(20*SF))[-1] or v1[-1]
        v5a=sum(v1[-(int(6*SF)):-1])/(int(5*SF)) if len(v1)>=int(6*SF) else v1[-1]
        vs=compute_volume_score(v1[-1],vm); rsi1=compute_rsi(c1,int(14*SF))
        new_entries=[]
        for ent in entries:
            ep=ent['ep']; mp=ent['mp']; tp_s=ent['tp']; rem=ent['rem']
            hi=ent['hi']; tstop=ent['tstop']
            roi=((cc-ep)/ep*100)*mp*TOTAL*lv/BASE
            if cc>hi: hi=cc; ent['hi']=hi
            rm=False
            if roi<=-sl_roi: eq+=roi*rem/100; trades.append({'t':'SL'}); rm=True
            elif tp_s<len(TP):
                trg,cpct=TP[tp_s]
                if roi>=trg:
                    cf=cpct*rem; eq+=roi*cf/100; rem-=cf
                    ent['rem']=rem; ent['tp']=tp_s+1; trades.append({'t':'TP'})
                    if ent['tp']>=len(TP): ent['tstop']=cc*(1-trr)
            if tp_s>=len(TP) and not rm:
                if tstop is None: tstop=cc*(1-trr)
                tstop=max(tstop,hi*(1-trr)); ent['tstop']=tstop
                if cc<=tstop: eq+=roi*rem/100; trades.append({'t':'TRAIL'}); rm=True
            if not rm: new_entries.append(ent)
        entries=new_entries
        dep=sum(e['mp'] for e in entries)
        can_enter = dep < 14400/TOTAL and (idx - last_entry_idx >= cd_bars)
        if can_enter:
            el=compute_entry_v6_long(ts,rsi1,cc,es,em,ef,vs,
                trend_min=prof['trend_min_long'],vol_min=prof['vol_min'],
                rsi_max=prof.get('rsi_max_long',90),ma7_1d=ma7,ma200_1d=ma200,
                last_volume=v1[-1],vol_5d_avg=v5a,
                use_ma200_filter=False,use_pullback_filter=False,
                use_volume_expan=False,min_entry_score=65)  # STRONG ONLY
            es_=compute_entry_v6_short(ts,rsi1,cc,es,em,ef,vs,
                trend_max=prof['trend_max_short'],vol_min=prof['vol_min'],
                rsi_min=prof.get('rsi_min_short',10)) if coin in SHORT_ALLOWED else False
            ps_,act=resolve_action_v6(ts,el,es_,'FLAT')
            if act in ('OPEN_LONG_ENTRY_1','OPEN_SHORT_ENTRY_1'):
                sc=_entry_score_v7_long(ts,cc,ma7,ma10,es,ma200,ef,em,vs,v1[-1],v5a,rsi1)
                if sc >= 65:  # double-check strong
                    mp=esz(coin,True)  # always strong size
                else:
                    mp=esz(coin,False)
                if dep+mp<=14400/TOTAL+0.001:
                    entries.append({'ep':cc,'mp':mp,'tp':0,'rem':1.0,'hi':cc,'tstop':None})
                    last_entry_idx=idx
        ureal=sum(((cc-e['ep'])/e['ep']*100)*e['mp']*TOTAL*lv/BASE*e['rem']/100 for e in entries)
        curve.append(eq+ureal)
    slc=sum(1 for t in trades if t['t']=='SL')
    tpc=sum(1 for t in trades if t['t'] in ('TP','TRAIL'))
    tot=slc+tpc
    slr=slc/tot*100 if tot else 0
    peak=curve[0] if curve else eq; md=0
    for v in curve:
        if v>peak: peak=v
        dd=(peak-v)/peak*100
        if dd>md: md=dd
    years=len(curve)/2/365 if curve else 1
    teq=curve[-1] if curve else eq
    cagr=((teq**(1/years)-1)*100) if years>0 and teq>0 else 0
    return cagr,md,slc,tpc,tot,slr,teq

SL_MAP = {"ETH": [7,9,12], "BNB": [9,12,15], "TRX": [9,12,15]}
COOLDOWNS = [0,1,3,5,7]

print(f"{'='*105}")
print(f"  v9: STRONG-ONLY (score>=65) + Cooldown sweep | SL rate cang thap cang tot")
print(f"{'='*105}")

for coin in COINS:
    print(f"\n  {coin} (lev={lev(coin)}x, trail={tr_r(coin)*100:.1f}%):")
    print(f"  {'SL%':>6} {'cd=0':>18} {'cd=1':>18} {'cd=3':>18} {'cd=5':>18} {'cd=7':>18}")
    print(f"  {'─'*95}")
    for sl in SL_MAP[coin]:
        row = f"  {sl:>5.0f}% "
        best_c = -999; best_cd = 0
        for cd in COOLDOWNS:
            c,d,slc,tpc,tot,slr,teq = bt(coin, sl, cd)
            final = teq*BASE
            row += f"C={c:+5.1f} SL={slr:.0f}% "
            if c > best_c: best_c = c; best_cd = cd
        print(row)
    print(f"  Best: SL={SL_MAP[coin][0]}%, cd={best_cd}b")
