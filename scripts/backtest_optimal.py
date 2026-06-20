import sys, os, json
sys.path.insert(0, 'scripts')
from crypto_trading import (
    sma, evaluate_trend_3d, compute_volume_score,
    compute_entry_v6_long, compute_entry_v6_short,
    resolve_action_v6, _entry_score_v7_long,
    get_coin_profile, compute_rsi, SHORT_ALLOWED,
)
from statistics import mean

SF=1.5; BASE=10000; ENTRY_MIN=65; MAX_POS_PCT=0.65; INITIAL=75
TP=[(7,0.07),(12,0.11),(20,0.20),(30,0.27)]
CACHE=os.path.join(os.path.dirname(os.path.abspath(__file__)), "_klines_12h_5y.json")
with open(CACHE) as f: _cache=json.load(f)
def fetch(s): return _cache.get(s+'_4000_1609434000000',[])
def aggr(c,n=3):
    r=[]
    for i in range(0,len(c)-n+1,n): b=c[i:i+n]; r.append({'close':b[-1]['close']})
    return r

PROFILES = {
    "ETH": {"lev": 2.0, "sl": 12, "cap": 1.9, "trail": 0.035, "cd": 0, "e_strong": 0.09, "e_weak": 0.07},
    "BNB": {"lev": 3.0, "sl": 12, "cap": 1.8, "trail": 0.065, "cd": 0, "e_strong": 0.07, "e_weak": 0.055},
    "TRX": {"lev": 2.5, "sl": 9,  "cap": 1.8, "trail": 0.065, "cd": 3, "e_strong": 0.07, "e_weak": 0.055},
}

print("="*95)
print("  OPTIMAL PROFILE BACKTEST — Yearly CAGR")
print("="*95)

all_results = {}
for coin in ["ETH","BNB","TRX"]:
    p = PROFILES[coin]
    prof = dict(get_coin_profile(coin))
    da = fetch(coin+"USDT")
    lev = p["lev"]; sl_val = p["sl"]; cm = p["cap"]; tr_rate = p["trail"]
    cd = p["cd"]; e_strong = p["e_strong"]; e_weak = p["e_weak"]
    max_ms = MAX_POS_PCT / lev; tc = BASE * cm

    entries = []; eq = 1.0; curve = []; trades = []; lei = -999
    yearly_eq = {}

    for idx in range(INITIAL, len(da)):
        ds=da[:idx+1]; ct=aggr(ds,3)
        if len(ct)<25: continue
        cc=ds[-1]['close']; cl=[c['close'] for c in ct]
        mf=sma(cl,10)[-1] or cl[-1]; mm=sma(cl,15)[-1] or cl[-1]; ms=sma(cl,30)[-1] or cl[-1]
        _,ts=evaluate_trend_3d(mf,mm,ms)
        c1=[c['close'] for c in ds]; v1=[c['volume'] for c in ds]
        ef=sma(c1,18)[-1] or c1[-1]; em=sma(c1,37)[-1] or c1[-1]; es=sma(c1,30)[-1] or c1[-1]
        ma7=sma(c1,int(7*SF))[-1] or c1[-1]; ma10=sma(c1,int(10*SF))[-1] or c1[-1]
        ma200=sma(c1,int(200*SF))[-1] or None
        vm2=sma(v1,int(20*SF))[-1] or v1[-1]
        v5a=sum(v1[-(int(6*SF)):-1])/(int(5*SF)) if len(v1)>=int(6*SF) else v1[-1]
        vs=compute_volume_score(v1[-1],vm2); rsi1=compute_rsi(c1,int(14*SF))
        dt=ds[-1]['open_time']
        ne=[]
        for ent in entries:
            ep=ent['ep']; mp=ent['mp']; tp_s=ent['tp']
            rem2=ent['rem']; hi=ent['hi']; tstop=ent['tstop']
            roi=((cc-ep)/ep*100)*mp*tc*lev/BASE
            if cc>hi: hi=cc; ent['hi']=hi
            rm=False
            if roi<=-sl_val: eq+=roi*rem2/100; trades.append({'t':'SL'}); rm=True
            elif tp_s<len(TP):
                trg,cpct=TP[tp_s]
                if roi>=trg:
                    cf=cpct*rem2; eq+=roi*cf/100; rem2-=cf
                    ent['rem']=rem2; ent['tp']=tp_s+1; trades.append({'t':'TP'})
                    if ent['tp']>=len(TP): ent['tstop']=cc*(1-tr_rate)
            if tp_s>=len(TP) and not rm:
                if tstop is None: tstop=cc*(1-tr_rate)
                tstop=max(tstop,hi*(1-tr_rate)); ent['tstop']=tstop
                if cc<=tstop: eq+=roi*rem2/100; trades.append({'t':'TRAIL'}); rm=True
            if not rm: ne.append(ent)
        entries=ne
        dep=sum(e['mp'] for e in entries)
        can=dep<max_ms and (idx-lei>=cd)
        if can:
            el=compute_entry_v6_long(ts,rsi1,cc,es,em,ef,vs,
                trend_min=prof['trend_min_long'],vol_min=prof['vol_min'],
                rsi_max=prof.get('rsi_max_long',90),ma7_1d=ma7,ma200_1d=ma200,
                last_volume=v1[-1],vol_5d_avg=v5a,
                use_ma200_filter=False,use_pullback_filter=False,
                use_volume_expan=False,min_entry_score=ENTRY_MIN)
            es_=compute_entry_v6_short(ts,rsi1,cc,es,em,ef,vs,
                trend_max=prof['trend_max_short'],vol_min=prof['vol_min'],
                rsi_min=prof.get('rsi_min_short',10)) if coin=='ETH' else False
            ps_,act=resolve_action_v6(ts,el,es_,'FLAT')
            if act in ('OPEN_LONG_ENTRY_1','OPEN_SHORT_ENTRY_1'):
                sc=_entry_score_v7_long(ts,cc,ma7,ma10,es,ma200,ef,em,vs,v1[-1],v5a,rsi1)
                mp=e_strong if sc>=ENTRY_MIN else e_weak
                if dep+mp<=max_ms+0.001:
                    entries.append({'ep':cc,'mp':mp,'tp':0,'rem':1.0,'hi':cc,'tstop':None})
                    lei=idx
        ureal=sum(((cc-e['ep'])/e['ep']*100)*e['mp']*tc*lev/BASE*e['rem']/100 for e in entries)
        total_eq = eq + ureal
        curve.append(total_eq)
        from datetime import datetime as dt_cls
        d = dt_cls.utcfromtimestamp(dt/1000)
        if d.month == 12:
            yearly_eq[d.year] = total_eq

    slc=sum(1 for t in trades if t['t']=='SL')
    tpc=sum(1 for t in trades if t['t'] in ('TP','TRAIL'))
    tot=slc+tpc; slr=slc/tot*100 if tot else 0
    peak=curve[0] if curve else eq; md=0
    for v in curve:
        if v>peak: peak=v
        dd=(peak-v)/peak*100
        if dd>md: md=dd
    years=len(curve)/2/365 if curve else 1
    teq=curve[-1] if curve else eq
    cagr=((teq**(1/years)-1)*100) if years>0 and teq>0 else 0

    all_results[coin] = dict(cagr=cagr, dd=md, slr=slr, tot=tot, final=teq*BASE, yearly=yearly_eq)

    print("%-6s L=%.1fx SL=%d%% Cap=%.1fx | CAGR=%+.1f%% DD=%.1f%% SLr=%.0f%% $%d->$%s" % (
        coin, lev, sl_val, cm, cagr, md, slr, BASE, '{:,.0f}'.format(teq*BASE)))

print()
print("="*95)
print("  YEARLY CAGR")
print("  %-6s" % "Coin", end="")
for y in range(2021,2026): print(" %9d" % y, end="")
print(" %8s %8s" % ("5Y", "DD"))
print("  "+"-"*70)
for coin in ["ETH","BNB","TRX"]:
    r = all_results[coin]
    print("  %-6s" % coin, end="")
    prev=1.0
    for y in range(2021,2026):
        ev = r['yearly'].get(y, prev)
        c = ((ev/prev)-1)*100
        print(" %+8.1f%%" % c, end="")
        prev=ev
    print(" %+7.1f%% %+7.1f%%" % (r['cagr'], r['dd']))

print()
total_final = sum(r['final'] for r in all_results.values())
avg_c = mean(r['cagr'] for r in all_results.values())
avg_d = mean(r['dd'] for r in all_results.values())
print("  PORTFOLIO | Avg CAGR=%+.1f%% DD=%.1f%% $%d->$%s" % (avg_c, avg_d, len(all_results)*BASE, '{:,.0f}'.format(total_final)))
