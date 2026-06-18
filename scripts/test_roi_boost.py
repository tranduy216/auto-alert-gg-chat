#!/usr/bin/env python3
"""Test ROI boost strategies: score=1 rule, alt coins, capital allocation."""

import os, sys
from datetime import datetime, timedelta
from statistics import mean, stdev

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import requests as req_lib

from crypto_trading import (
    sma, compute_rsi, evaluate_trend_3d, trend_strength,
    compute_volume_score, _aggregate_daily_to_3d,
    get_coin_profile,
    SHORT_ALLOWED,
    SHORT_COOLDOWN_LOSSES, SHORT_COOLDOWN_DAYS,
    LONG_COOLDOWN_LOSSES, LONG_COOLDOWN_DAYS,
)

BINANCE_MAX_LIMIT = 1000
MIN_3D_PERIODS = 25
_cache = {}

def fetch(symbol, limit=1000, st=None):
    key = (symbol, limit, st)
    if key in _cache: return _cache[key]
    candles = []; remaining = limit; cur = st
    while remaining > 0:
        take = min(remaining, BINANCE_MAX_LIMIT)
        p = {"symbol": symbol, "interval": "1d", "limit": take + 50}
        if cur: p["startTime"] = cur
        r = req_lib.get("https://api.binance.com/api/v3/klines", params=p, timeout=15)
        r.raise_for_status()
        batch = [{"open_time": k[0], "open": float(k[1]), "high": float(k[2]),
                  "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])} for k in r.json()]
        if len(batch) <= 1: break
        candles.extend(batch); remaining -= len(batch)
        cur = batch[-1]["open_time"] + 1
        if len(candles) >= limit: break
    r = candles[:limit]; _cache[key] = r; return r

PERIODS = {
    "2021_2023": (int(datetime(2021,1,1).timestamp()*1000), BINANCE_MAX_LIMIT, "2021–2023"),
    "2024_2026": (int(datetime(2024,1,1).timestamp()*1000), BINANCE_MAX_LIMIT, "2024–2026"),
    "2021_2026": (int(datetime(2021,1,1).timestamp()*1000), 2000, "2021–2026"),
}

COIN_MAP = {
    "ETH":"ETHUSDT","BNB":"BNBUSDT","PAXG":"PAXGUSDT","TRX":"TRXUSDT",
    "SOL":"SOLUSDT","BTC":"BTCUSDT",
    "LINK":"LINKUSDT","ADA":"ADAUSDT","MATIC":"MATICUSDT",
    "AVAX":"AVAXUSDT","DOT":"DOTUSDT","XRP":"XRPUSDT","ARB":"ARBUSDT",
}

def entry_long(ts, rsi, close, ma20, ms, mf, vs, t_min=0, v_min=0.3):
    if ts < t_min: return False
    if mf is not None and mf < ms: return False
    if close < ma20 or close < ms: return False
    return vs >= v_min

def entry_short(ts, rsi, close, ma20, ms, mf, vs, t_max=-3, v_min=0.3):
    if ts > t_max: return False
    if mf is not None and mf > ms: return False
    if close > ma20 or close > ms: return False
    return vs >= v_min

def exit_v6(ps, ep, cp, rsz, m7, m20, ts, tv, rsi3, ts_, he,
            ml=0.06, tr=0.80, hs=0.75):
    if ps=="FLAT" or ep is None or ep<=0: return ("HOLD",0,"",ts_,he)
    il=ps.startswith("LONG")
    pnl=((cp-ep)/ep*100)if il else((ep-cp)/ep*100)
    bp=max(he or ep,cp)if il else min(he or ep,cp)
    ns=ts_
    if ns is None: ns=round(ep*(tr if il else(2-tr)),2)
    if il:
        if bp>(he or ep):
            tb=bp*tr
            if tb>ns: ns=round(tb,2)
    else:
        if bp<(he or ep):
            tb=bp*(2-tr)
            if tb<ns: ns=round(tb,2)
    if pnl<=-ml*100: return("EXIT_ALL",1,f"ML{ml*100:.0f}%",ns,bp)
    hl=round(ep*(hs if il else(2-hs)),2)
    if il:
        if cp<=max(ns or 0,hl): return("EXIT_ALL",1,"STOP",ns,bp)
    else:
        if cp>=min(ns or 999999,hl): return("EXIT_ALL",1,"STOP",ns,bp)
    if il and m7<m20: return("EXIT_ALL",1,"MA7<MA20",ns,bp)
    if not il and m7>m20: return("EXIT_ALL",1,"MA7>MA20",ns,bp)
    if il and tv<-0.3: return("EXIT_ALL",1,f"SCORE{tv:.1f}",ns,bp)
    if not il and tv>0.3: return("EXIT_ALL",1,f"SCORE{tv:.1f}",ns,bp)
    return("HOLD",0,"",ns,bp)

def bt(coin, da, tml=0, tms=-3, vm=0.3, ml=0.06, tr=0.80, hs=0.75, lev=2.5,
       cap_pct=0.10, long_only=False, short_only=False):
    prof = get_coin_profile(coin)
    first=datetime.utcfromtimestamp(da[0]["open_time"]/1000).strftime("%Y-%m-%d")
    last=datetime.utcfromtimestamp(da[-1]["open_time"]/1000).strftime("%Y-%m-%d")
    st={"ps":"FLAT","ep":None,"rsz":1.0,"ts":None,"he":None,"sls":0,"scu":None,"lls":0,"lcu":None}
    trades=[];eq=[1.0]
    ID=MIN_3D_PERIODS*3
    short_ok=coin in SHORT_ALLOWED and not long_only
    long_ok=not short_only

    for di in range(ID, len(da)):
        ds=da[:di+1];c3d=_aggregate_daily_to_3d(ds)
        if len(c3d)<MIN_3D_PERIODS: continue
        cc=ds[-1]["close"];c3c=[c["close"] for c in c3d]
        m7=(sma(c3c,7)[-1]or c3c[-1]);m10=(sma(c3c,10)[-1]or c3c[-1])
        m20=(sma(c3c,20)[-1]or c3c[-1]);_,ts=evaluate_trend_3d(m7,m10,m20)
        tv=trend_strength(ts);rsi3=compute_rsi(c3c,14)
        c1c=[c["close"] for c in ds];h1=[c["high"] for c in ds]
        l1=[c["low"] for c in ds];v1=[c["volume"] for c in ds]
        ma20_1d=(sma(c1c,20)[-1]or c1c[-1]);ma50_1d=(sma(c1c,50)[-1]or c1c[-1])
        mf=(sma(c1c,12)[-1]or None);ms=sma(c1c,25)[-1]or ma50_1d
        vm20=(sma(v1,20)[-1]or v1[-1]);vs=compute_volume_score(v1[-1],vm20)
        rsi1=compute_rsi(c1c,14);r10l=min(l1[-10:])if len(l1)>=10 else cc*.95
        r10h=max(h1[-10:])if len(h1)>=10 else cc*1.05
        dt=ds[-1]["open_time"]
        ds_=datetime.utcfromtimestamp(dt/1000).strftime("%Y-%m-%d")if isinstance(dt,int) else str(dt)
        pps=st["ps"];ep=st["ep"];rsz=st["rsz"];ts_=st.get("ts");he=st.get("he")

        if pps=="FLAT":
            _la=True
            if st.get("lcu"):
                cd=st["lcu"]
                if isinstance(cd,str) and dt and isinstance(dt,int):
                    if dt<int(datetime.fromisoformat(cd).timestamp()*1000): _la=False
                elif isinstance(cd,(int,float)) and isinstance(dt,int):
                    if dt<cd: _la=False
            el=entry_long(ts,rsi1,cc,ma20_1d,ms,mf,vs,tml,vm)if _la and long_ok else False
            _sa=short_ok
            if _sa and st.get("scu"):
                cd=st["scu"]
                if isinstance(cd,str) and dt and isinstance(dt,int):
                    if dt<int(datetime.fromisoformat(cd).timestamp()*1000): _sa=False
                elif isinstance(cd,(int,float)) and isinstance(dt,int):
                    if dt<cd: _sa=False
            es=entry_short(ts,rsi1,cc,ma20_1d,ms,mf,vs,tms,vm)if _sa else False
            if el:
                pps="LONG_ENTRY_1";ep=cc;rsz=1.0;ts_=None;he=None
                trades.append({"d":ds_,"t":"LONG_OPEN","p":cc,"r":f"TS={ts}"})
            elif es:
                pps="SHORT_ENTRY_1";ep=cc;rsz=1.0;ts_=None;he=None
                trades.append({"d":ds_,"t":"SHORT_OPEN","p":cc,"r":f"TS={ts}"})
            st.update({"ps":pps,"ep":ep,"rsz":rsz,"ts":ts_,"he":he})
        else:
            il=pps.startswith("LONG")
            pnl=((cc-ep)/ep*100if il else(ep-cc)/ep*100)if ep and ep>0 else 0
            ea,rp,er,nts,nhe=exit_v6(pps,ep,cc,rsz,m7,m20,ts,tv,rsi3,ts_,he,ml,tr,hs)
            ts_=nts;he=nhe
            if ea=="HOLD": pps=pps
            else:
                if ea=="EXIT_ALL":
                    trades.append({"d":ds_,"t":"CLOSE","p":cc,"s":rsz,"pnl":round(pnl,2),"r":er})
                    if "SHORT" in pps:
                        sls=st.get("sls",0)
                        if pnl>0: st["sls"]=0;st["scu"]=None
                        else:sls+=1;st["sls"]=sls
                        if sls>=SHORT_COOLDOWN_LOSSES:st["scu"]=(datetime.utcfromtimestamp(dt/1000)+timedelta(days=SHORT_COOLDOWN_DAYS)).isoformat()
                    else:
                        lls=st.get("lls",0)
                        if pnl>0: st["lls"]=0;st["lcu"]=None
                        else:lls+=1;st["lls"]=lls
                        if lls>=LONG_COOLDOWN_LOSSES:st["lcu"]=(datetime.utcfromtimestamp(dt/1000)+timedelta(days=LONG_COOLDOWN_DAYS)).isoformat()
                    pps="FLAT";rsz=0.0;ep=None
            st.update({"ps":pps,"ep":ep,"rsz":rsz,"ts":ts_,"he":he})
        if st["ps"]!="FLAT" and st["ep"] and st["rsz"]>0:
            _il=st["ps"].startswith("LONG")
            upnl=((cc-st["ep"])/st["ep"]*100 if _il else(st["ep"]-cc)/st["ep"]*100)
            eq.append(1.0+upnl/100*st["rsz"]*lev* (1/cap_pct if cap_pct!=0.10 else 1))
        else: eq.append(1.0)
    return {"coin":coin,"trades":trades,"eq":eq,"period":f"{first}→{last}"}

def metrics(r):
    closes=[t for t in r["trades"] if t["t"]=="CLOSE"]
    if not closes: return {"coin":r["coin"],"n":0,"pnl":0,"msg":"No trades","period":r["period"]}
    pnls=[t["pnl"] for t in closes];wins=[p for p in pnls if p>0];losses=[p for p in pnls if p<=0]
    tp=sum(pnls);wr=len(wins)/len(closes)*100;aw=mean(wins)if wins else 0;al=mean(losses)if losses else 0
    pf=abs(sum(wins)/sum(losses))if sum(losses)!=0 else float("inf")
    eq=r["eq"];peak=eq[0];mdd=0
    for v in eq:
        if v>peak:peak=v
        dd=(peak-v)/peak*100
        if dd>mdd: mdd=dd
    rets=[(eq[i]-eq[i-1])/eq[i-1] for i in range(1,len(eq)) if eq[i-1]>0]
    sh=0
    if len(rets)>1 and stdev(rets)>0: sh=(mean(rets)/stdev(rets))*(365**0.5)
    return {"coin":r["coin"],"n":len(closes),"pnl":round(tp,2),"wr":round(wr,1),
            "aw":round(aw,2),"al":round(al,2),"pf":round(pf,2),"mdd":round(mdd,2),"sh":round(sh,2),"period":r["period"]}

def print_m(m):
    if m.get("msg"): print(f"  {m['coin']:7s} | {m['msg']}"); return
    print(f"  {m['coin']:7s} | Trades={m['n']:3d} | PnL={m['pnl']:+8.2f}% | WR={m['wr']:4.0f}% | PF={m['pf']:<6.2f} | DD={m['mdd']:5.1f}% | S={m['sh']:.2f}")

def run_portfolio(coins, da_cache, label, tml=0, tms=-3, vm=0.3, ml=0.06, tr=0.80, hs=0.75, lev=2.5, cap_pct=0.10):
    print(f"\n  {label}")
    print(f"  {'─'*65}")
    pnls=[];wrs=[];pfs=[];dds=[];shs=[];nts=[]
    for coin in coins:
        da=da_cache[coin]
        r=bt(coin,da,tml,tms,vm,ml,tr,hs,lev,cap_pct);m=metrics(r)
        print_m(m)
        if not m.get("msg"):
            pnls.append(m["pnl"]);wrs.append(m["wr"]);pfs.append(m["pf"])
            dds.append(m["mdd"]);shs.append(m["sh"]);nts.append(m["n"])
    avg_pnl=sum(pnls);avg_wr=mean(wrs);avg_pf=mean(pfs);avg_dd=mean(dds);avg_sh=mean(shs);tot_nt=sum(nts)
    print(f"  {'─'*65}")
    print(f"  PORTFOLIO | PnL={avg_pnl:+8.2f}% | WR={avg_wr:4.0f}% | PF={avg_pf:.2f} | DD={avg_dd:5.1f}% | S={avg_sh:.2f} | Trades={tot_nt}")
    n=len(pnls)
    initial=10000; capital_per=initial/n
    final=sum(capital_per*(1+p/100) for p in pnls)
    cagr=(final/initial)**(1/5.5)-1
    print(f"  10K→${final:,.0f} (CAGR: {cagr*100:.1f}%/năm)")
    return final, cagr

def main():
    print("="*70)
    print("  ROI BOOST STRATEGIES")
    print("="*70)

    CORE=["ETH","BNB","PAXG","TRX","SOL"]
    ALT_CANDIDATES=["LINK","ADA","MATIC","AVAX","DOT","XRP","ARB"]
    CORE_MAP={c:COIN_MAP[c] for c in CORE}
    ALT_MAP={c:COIN_MAP[c] for c in ALT_CANDIDATES}

    # Fetch all data for 2024-2026
    st24, lim24, lbl24 = PERIODS["2024_2026"]
    print(f"\nFetching 2024-2026 data...")
    da_cache={}
    for coin,sym in {**CORE_MAP,**ALT_MAP}.items():
        try:
            raw=fetch(sym,lim24,st24);da=raw[:lim24]
            da_cache[coin]=da
            print(f"  {coin}: {len(da)} candles")
        except Exception as e:
            print(f"  {coin}: SKIP ({e})")

    # === 1. Score=1 impact on current portfolio
    print(f"\n{'='*70}")
    print(f"  TEST: SCORE=1 RULE IMPACT")
    print(f"  So sánh T0 (bao gồm score=1 mới) vs before (không có score=1)")
    print(f"{'='*70}")
    coins_avail=[c for c in CORE if c in da_cache]

    run_portfolio(coins_avail, da_cache, "T0 (có score=1) — config hiện tại", tml=0)
    run_portfolio(coins_avail, da_cache, "T1 (chặn score=1, chỉ 2,3) — so sánh", tml=1)

    # === 2. Alternative coins screening
    print(f"\n{'='*70}")
    print(f"  TEST: ALTERNATIVE COINS (2024-2026)")
    print(f"  Tìm coin thay SOL, dạng BNB/ETH")
    print(f"{'='*70}")
    alt_avail=[c for c in ALT_CANDIDATES if c in da_cache]
    for coin in alt_avail:
        r=bt(coin,da_cache[coin],tml=0);m=metrics(r)
        print_m(m)

    # === 3. Build optimal portfolio
    print(f"\n{'='*70}")
    print(f"  TEST: OPTIMAL PORTFOLIO (2024-2026)")
    print(f"{'='*70}")

    # Screen alt coins for best performers
    alt_results=[]
    for coin in alt_avail:
        r=bt(coin,da_cache[coin],tml=0);m=metrics(r)
        if not m.get("msg") and m["pf"]>=1.0:
            alt_results.append((coin,m["pnl"],m["pf"],m["mdd"],m["sh"]))
    alt_results.sort(key=lambda x: x[1]+x[2]*5-x[3]*0.5, reverse=True)
    print(f"  Top alt coins (PnL+PF*5-DD*0.5 score):")
    for coin,pnl,pf,mdd,sh in alt_results[:5]:
        print(f"    {coin}: PnL={pnl:+.1f}% PF={pf:.2f} DD={mdd:.1f}% S={sh:.2f}")

    # Test candidate portfolios
    candidates=[
        ("Current SOL", coins_avail),
        ("SOL→LINK", ["ETH","BNB","PAXG","TRX","LINK"]),
        ("SOL→ADA", ["ETH","BNB","PAXG","TRX","ADA"]),
        ("SOL→AVAX", ["ETH","BNB","PAXG","TRX","AVAX"]),
        ("SOL→XRP", ["ETH","BNB","PAXG","TRX","XRP"]),
        ("SOL→DOT", ["ETH","BNB","PAXG","TRX","DOT"]),
        ("SOL→ARB", ["ETH","BNB","PAXG","TRX","ARB"]),
        ("SOL→MATIC", ["ETH","BNB","PAXG","TRX","MATIC"]),
    ]
    best_final=0; best_label=""; best_coins=[]
    for label,clist in candidates:
        avail=[c for c in clist if c in da_cache]
        final,cagr=run_portfolio(avail, da_cache, label, tml=0)
        if final>best_final: best_final=final;best_label=label;best_coins=avail

    print(f"\n  ★ BEST: {best_label} → ${best_final:,.0f}")

    # === 4. Full period with best coin list
    print(f"\n{'='*70}")
    print(f"  TEST: FULL PERIOD 2021-2026 — {best_label}")
    print(f"{'='*70}")
    st21, lim21, lbl21 = PERIODS["2021_2026"]
    # Fetch full data
    for coin in best_coins:
        if coin not in _cache:
            try:
                raw=fetch(COIN_MAP[coin],lim21,st21)
                da_cache[coin]=raw[:lim21]
            except: pass

    run_portfolio(best_coins, da_cache, f"{best_label} — T0 cap=10%", tml=0, cap_pct=0.10)
    run_portfolio(best_coins, da_cache, f"{best_label} — T0 cap=12%", tml=0, cap_pct=0.12)
    run_portfolio(best_coins, da_cache, f"{best_label} — T0 cap=15%", tml=0, cap_pct=0.15)

    # === 5. Full period with optimized config
    print(f"\n{'='*70}")
    print(f"  FINAL OPTIMIZED CONFIG")
    print(f"{'='*70}")
    da_cache_full={}
    for coin in best_coins:
        sym=COIN_MAP[coin]
        try:
            raw=fetch(sym,2000,st21)
            da_cache_full[coin]=raw[:2000]
        except: pass

    configs=[
        ("T0 cap10%", 0, 0.10),
        ("T0 cap12%", 0, 0.12),
        ("T0 cap15%", 0, 0.15),
        ("T0 cap12% lev3x", 0, 0.12),
    ]

    for label, tml, cap in configs:
        lev=3.0 if "3x" in label else 2.5
        run_portfolio(best_coins, da_cache_full, f"2021-2026 {label}", tml=tml, cap_pct=cap, lev=lev)

if __name__=="__main__":
    main()
