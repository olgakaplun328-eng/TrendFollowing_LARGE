
import os,time,logging,requests
import pandas as pd, numpy as np
from telegram_config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
logging.basicConfig(level=logging.INFO,format="%(asctime)s | %(levelname)s | %(message)s")
log=logging.getLogger("trend-large")
URL="https://api.mexc.com/api/v3/klines"
POLL=int(os.getenv("POLL_SECONDS","60")); LIMIT=int(os.getenv("KLINE_LIMIT","250"))
SYMBOLS=[x.strip().upper() for x in os.getenv("SYMBOLS","BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT,DOGEUSDT,TRXUSDT,TAOUSDT").split(",") if x.strip()]
TP=float(os.getenv("TP_PCT","0.018")); SL=float(os.getenv("SL_PCT","0.009"))
s=requests.Session(); s.headers["User-Agent"]="TrendFollowing-Large/1.0"; last={}
def ema(x,n): return x.ewm(span=n,adjust=False).mean()
def obv(df): return (np.sign(df.close.diff()).fillna(0)*df.volume).cumsum()
def fetch(sym,tf,limit=250):
    # MEXC Spot API uses 60m for the hourly interval.
    api_tf = "60m" if tf == "1h" else tf
    r=s.get(URL,params={"symbol":sym,"interval":api_tf,"limit":limit},timeout=15); r.raise_for_status()
    d=r.json()
    rows = d if isinstance(d, list) else []
    vals = []
    for row in rows:
        if isinstance(row, (list, tuple)) and len(row) >= 6:
            vals.append(list(row[:8]) + [None] * max(0, 8-len(row[:8])))
    df=pd.DataFrame(vals, columns=["time","open","high","low","close","volume","ct","qv"])
    for c in ["open","high","low","close","volume"]: df[c]=pd.to_numeric(df[c],errors="coerce")
    df["time"]=pd.to_datetime(df.time,unit="ms",utc=True); return df.iloc[:-1].copy()
def sig(sym):
    df=fetch(sym,"5m"); h=fetch(sym,"1h",200)
    c=df.close; e20=ema(c,20); o=obv(df); he50=ema(h.close,50)
    # Use last closed candles; require actual crossover, not merely above/below.
    long5=e20.iloc[-1]>e20.iloc[-2] and c.iloc[-1]>e20.iloc[-1] and c.iloc[-2]<=e20.iloc[-2] and o.iloc[-1]>o.iloc[-2]
    short5=e20.iloc[-1]<e20.iloc[-2] and c.iloc[-1]<e20.iloc[-1] and c.iloc[-2]>=e20.iloc[-2] and o.iloc[-1]<o.iloc[-2]
    long1=h.close.iloc[-1]>he50.iloc[-1]; short1=h.close.iloc[-1]<he50.iloc[-1]
    if long5 and long1:return "LONG",["5m EMA20 breakout","5m OBV rising","1h EMA50 trend"]
    if short5 and short1:return "SHORT",["5m EMA20 breakdown","5m OBV falling","1h EMA50 trend"]
    return None,[]
def send(t):
    u=f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"; s.post(u,data={"chat_id":TELEGRAM_CHAT_ID,"text":t},timeout=15).raise_for_status()
def scan():
    n=0
    for sym in SYMBOLS:
        try:
            df=fetch(sym,"5m"); side,reasons=sig(sym)
            if not side:continue
            candle=str(df.iloc[-1].time); key=f"{sym}:{candle}:{side}"
            if last.get(sym)==key:continue
            entry=float(df.iloc[-1].close); sl=entry*(1-SL if side=="LONG" else 1+SL); tp=entry*(1+TP if side=="LONG" else 1-TP)
            text=(f"🎯 TREND FOLLOWING — LARGE MOVE\n\n"
                  f"{'🟢' if side=='LONG' else '🔴'} {side} {sym}\nEntry: {entry:.8g}\nSL: {sl:.8g} ({SL*100:.2f}%)\n"
                  f"TP: {tp:.8g} ({TP*100:.2f}%)\nRR: 1:{TP/SL:.2f}\nReasons: {', '.join(reasons)}\nTF: 5m + 1h | alert-only")
            send(text);last[sym]=key;n+=1;log.info("SIGNAL %s %s",side,sym)
        except Exception as e:log.warning("%s | %s",sym,e)
        time.sleep(.25)
    return n
while True:
    t=time.time()
    try:log.info("scan complete | signals=%d",scan())
    except Exception as e:log.exception("scan failed: %s",e)
    time.sleep(max(1,POLL-(time.time()-t)))
