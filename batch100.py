import os
# -*- coding: utf-8 -*-
# Apodex batch autoreg: N accounts, pure API, adaptive rate-limit backoff.
import json, sys, time, base64, re, random, urllib.request, urllib.error
import apodex_reg as ar

AUTH="https://auth.apodex.ai"; PLAT="https://platform.apodex.ai"
OUT="accounts.json"; LOG="batch100.log"

def log(msg):
    line=f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    open(LOG,"a",encoding="utf-8").write(line+"\n")

def api(url, payload=None, token=None, method=None):
    h=dict(ar.HDRS)
    if token: h["Authorization"]="Bearer "+token
    data=json.dumps(payload).encode() if payload is not None else None
    req=urllib.request.Request(url,data=data,headers=h,method=method or ("POST" if data else "GET"))
    try:
        with urllib.request.urlopen(req,timeout=30) as r: return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try: b=json.loads(e.read().decode())
        except Exception: b={}
        return e.code, b
    except Exception as e:
        return -1, {"err":str(e)}

def load_db():
    try: return json.load(open(OUT,encoding="utf-8"))
    except Exception: return []

def save_db(db):
    json.dump(db,open(OUT,"w",encoding="utf-8"),indent=1)

def reg_one(alias):
    st,r=api(f"{AUTH}/api/auth/passwordless/send-code",{"email":alias})
    if st==429: return "429", None
    if st!=200: return f"send{st}", str(r)[:100]
    code=ar.read_otp(alias,timeout=150)
    if not code: return "otp_timeout", None
    st,r=api(f"{AUTH}/api/auth/v2/passwordless/verify-login",{"email":alias,"code":code,"client_id":"apodex-platform-web"})
    if st!=200 or "data" not in r: return f"verify{st}", str(r)[:100]
    d=r["data"]; tok=d["access_token"]
    st,r=api(f"{PLAT}/v1/api-keys",{"name":f"eni-{int(time.time())%100000}"},tok)
    key=None
    if st in (200,201):
        mm=re.search(r"sk-[A-Za-z0-9_\-]+={0,2}",json.dumps(r))
        if mm: key=mm.group(0)
    rec={"email":alias,"key_b64":base64.b64encode(key.encode()).decode() if key else None,
         "access_token":tok,"refresh_token":d.get("refresh_token"),
         "user_id":d.get("user",{}).get("id"),"ts":time.strftime("%F %T"),"via":"api-batch"}
    return ("ok" if key else "nokey"), rec

def main():
    start=int(sys.argv[1]); n=int(sys.argv[2])
    delay=8.0; rate_hits=0; done=0
    for i in range(start, start+n):
        alias=os.environ.get('GMAIL_USER','your@gmail.com').replace('@', f'+apodex{i}@')
        db=load_db()
        if any(x.get("email")==alias and x.get("key_b64") for x in db):
            log(f"skip {alias} (exists)"); done+=1; continue
        for attempt in range(6):
            status,rec=reg_one(alias)
            if status=="429":
                rate_hits+=1
                wait=min(60*rate_hits,900)+random.uniform(0,20)
                log(f"429 on {alias} hit#{rate_hits} -> sleep {int(wait)}s")
                time.sleep(wait); continue
            if status in ("ok","nokey"):
                db=[x for x in db if x.get("email")!=alias]+[rec]
                save_db(db)
                if status=="ok": done+=1
                log(f"{status.upper()} {alias} (total ok: {done})")
                break
            log(f"FAIL {alias} {status} {rec or ''}")
            time.sleep(10)
        else:
            log(f"GIVEUP {alias}")
        # adaptive delay
        if rate_hits>=3: delay=max(delay,45)
        time.sleep(delay+random.uniform(0,4))
    log(f"BATCH DONE: {done} keys -> {OUT}")

if __name__=="__main__":
    main()
