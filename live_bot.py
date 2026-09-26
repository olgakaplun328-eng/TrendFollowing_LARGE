
import os, time, logging, requests
import pandas as pd
import numpy as np
from telegram_config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log=logging.getLogger("adaptive-small")
URL="https://api.mexc.com/api/v3/klines"
TF=os.getenv("SIGNAL_TIMEFRAME","15m")
POLL=int(os.getenv("POLL_SECONDS","60"))
LIMIT=int(os.getenv("KLINE_LIMIT","250"))
SYMBOLS=[x.strip().upper() for x in os.getenv("SYMBOLS","BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT,DOGEUSDT,TRXUSDT,TAOUSDT").split(",") if x.strip()]
TP=float(os.getenv("TP_PCT","0.006"))       # 0.6%
SL=float(os.getenv("SL_PCT","0.0045"))      # 0.45%
MIN_VOL=float(os.getenv("MIN_VOL_RATIO","1.10"))

s=requests.Session(); s.headers["User-Agent"]="AdaptiveMomentum-Small/1.0"
last={}

def ema(x,n): return x.ewm(span=n,adjust=False).mean()
def rsi(x,n=14):
    d=x.diff(); up=d.clip(lower=0); dn=-d.clip(upper=0)
    au=up.ewm(alpha=1/n,adjust=False).mean(); ad=dn.ewm(alpha=1/n,adjust=False).mean()
    rs=au/ad.replace(0,np.nan)
    return 100-(100/(1+rs))
def atr(df,n=14):
    pc=df.close.shift(1)
    tr=pd.concat([(df.high-df.low),(df.high-pc).abs(),(df.low-pc).abs()],axis=1).max(axis=1)
    return tr.ewm(alpha=1/n,adjust=False).mean()
def adx(df,n=14):
    up=df.high.diff(); dn=-df.low.diff()
    plus=np.where((up>dn)&(up>0),up,0.0); minus=np.where((dn>up)&(dn>0),dn,0.0)
    a=atr(df,n)
    pdi=100*pd.Series(plus,index=df.index).ewm(alpha=1/n,adjust=False).mean()/a.replace(0,np.nan)
    mdi=100*pd.Series(minus,index=df.index).ewm(alpha=1/n,adjust=False).mean()/a.replace(0,np.nan)
    dx=100*(pdi-mdi).abs()/(pdi+mdi).replace(0,np.nan)
    return dx.ewm(alpha=1/n,adjust=False).mean(),pdi,mdi
def fetch(sym):
    r=s.get(URL,params={"symbol":sym,"interval":TF,"limit":LIMIT},timeout=15); r.raise_for_status()
    d=r.json()
    if not isinstance(d,list) or len(d)<80: raise RuntimeError("bad kline response")
    df=pd.DataFrame(d,columns=["time","open","high","low","close","volume","ct","qv","trades","tb","tq","ignore"])
    for c in ["open","high","low","close","volume"]: df[c]=pd.to_numeric(df[c],errors="coerce")
    df["time"]=pd.to_datetime(df.time,unit="ms",utc=True)
    return df.iloc[:-1].copy()

def signal(df):
    c=df.close; v=df.volume
    ef=ema(c,9); es=ema(c,30); r=rsi(c); a,pdi,mdi=adx(df)
    macd=ema(c,12)-ema(c,26); ms=ema(macd,9)
    vs=v.rolling(20).mean(); vr=v/vs
    bbmid=c.rolling(20).mean(); std=c.rolling(20).std()
    lower=bbmid-2*std
    vwap=(c*v).cumsum()/v.cumsum()
    i=-1
    long1=ef.iloc[i]>es.iloc[i] and a.iloc[i]>25 and r.iloc[i]<45 and r.iloc[i]>r.iloc[i-1] and vr.iloc[i]>1.2 and c.iloc[i]<lower.iloc[i]*1.02 and pdi.iloc[i]>mdi.iloc[i] and c.iloc[i]>vwap.iloc[i]*0.995
    long2=ef.iloc[i]>ema(c,21).iloc[i] and macd.iloc[i]>ms.iloc[i] and macd.iloc[i]>0 and r.iloc[i]<45 and a.iloc[i]>20 and vr.iloc[i]>1.3 and c.iloc[i]>vwap.iloc[i]*0.995
    long3=r.iloc[i]<30 and a.iloc[i]>25 and ((c.iloc[i]-c.rolling(20).min().iloc[i])/(c.rolling(20).max().iloc[i]-c.rolling(20).min().iloc[i] or 1)<0.2) and vr.iloc[i]>1.1 and c.iloc[i]>vwap.iloc[i]*0.995
    short1=ef.iloc[i]<es.iloc[i] and a.iloc[i]>25 and r.iloc[i]>55 and r.iloc[i]<r.iloc[i-1] and vr.iloc[i]>1.2 and c.iloc[i]> (bbmid+2*std).iloc[i]*0.98 and mdi.iloc[i]>pdi.iloc[i] and c.iloc[i]<vwap.iloc[i]*1.005
    short2=ef.iloc[i]<ema(c,21).iloc[i] and macd.iloc[i]<ms.iloc[i] and macd.iloc[i]<0 and r.iloc[i]>55 and a.iloc[i]>20 and vr.iloc[i]>1.3 and c.iloc[i]<vwap.iloc[i]*1.005
    short3=r.iloc[i]>70 and a.iloc[i]>25 and ((c.rolling(20).max().iloc[i]-c.iloc[i])/(c.rolling(20).max().iloc[i]-c.rolling(20).min().iloc[i] or 1)<0.2) and vr.iloc[i]>1.1 and c.iloc[i]<vwap.iloc[i]*1.005
    if sum([long1,long2,long3])>=1 and sum([short1,short2,short3])==0: return "LONG", [x for x,b in [("ADX+RSI",long1),("EMA+MACD",long2),("Oversold",long3)] if b]
    if sum([short1,short2,short3])>=1 and sum([long1,long2,long3])==0: return "SHORT", [x for x,b in [("ADX+RSI",short1),("EMA+MACD",short2),("Overbought",short3)] if b]
    return None,[]

def send(text):
    u=f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    s.post(u,data={"chat_id":TELEGRAM_CHAT_ID,"text":text},timeout=15).raise_for_status()

def scan():
    n=0
    for sym in SYMBOLS:
        try:
            df=fetch(sym); candle=str(df.iloc[-1].time); side,reasons=signal(df)
            if not side: continue
            key=f"{sym}:{candle}:{side}"
            if last.get(sym)==key: continue
            entry=float(df.iloc[-1].close)
            sl=entry*(1-SL if side=="LONG" else 1+SL)
            tp=entry*(1+TP if side=="LONG" else 1-TP)
            text=(f"🎯 ADAPTIVE MOMENTUM — SMALL MOVE\n\n"
                  f"{'🟢' if side=='LONG' else '🔴'} {side} {sym}\n"
                  f"Entry: {entry:.8g}\nSL: {sl:.8g} ({SL*100:.2f}%)\nTP: {tp:.8g} ({TP*100:.2f}%)\n"
                  f"RR: 1:{TP/SL:.2f}\nReasons: {', '.join(reasons)}\n"
                  f"TF: {TF} | alert-only")
            send(text); last[sym]=key; n+=1
            log.info("SIGNAL %s %s",side,sym)
        except Exception as e: log.warning("%s | %s",sym,e)
        time.sleep(.25)
    return n

while True:
    t=time.time()
    try: log.info("scan complete | signals=%d",scan())
    except Exception as e: log.exception("scan failed: %s",e)
    time.sleep(max(1,POLL-(time.time()-t)))
