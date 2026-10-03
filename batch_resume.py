# -*- coding: utf-8 -*-
# Resume batch to TARGET total accounts. Adaptive 429 backoff (IP-global limit).
# Loads existing accounts_web.json, appends new ones. Runs until TARGET reached.
import os
import json, time, os, urllib.request, urllib.error
import apodex_reg as ar

AUTH='https://auth.apodex.ai/api/auth'; WWW='https://www.apodex.ai'; UA='Mozilla/5.0'
TARGET = int(os.environ.get('TARGET','100'))
DBF='accounts_web.json'

def post_json(url, body, timeout=30):
    req=urllib.request.Request(url,data=json.dumps(body).encode(),headers={'User-Agent':UA,'Content-Type':'application/json'})
    return urllib.request.urlopen(req,timeout=timeout).read().decode()

def reg_one(idx):
    mail=f'your+apodexweb{int(time.time())}{idx:04d}@gmail.com'
    # send-code
    for attempt in range(3):
        try:
            post_json(AUTH+'/passwordless/send-code',{'email':mail,'client_id':'apodex-web'})
            break
        except urllib.error.HTTPError as e:
            if e.code==429:
                return None,'429'   # signal caller to backoff
            raise
    # poll OTP (read_otp handles IMAP internally)
    code=ar.read_otp(mail, timeout=150)
    if not code: return None,'no-code'
    # verify
    tok=None
    for vp in ['/v2/passwordless/verify-login','/passwordless/verify-code']:
        try:
            r=json.loads(post_json(AUTH+vp,{'email':mail,'code':code,'client_id':'apodex-web'}))
            tok=r.get('access_token') or r.get('data',{}).get('access_token')
            if tok: break
        except Exception: continue
    if not tok: return None,'no-tok'
    # balance
    bal=None; vip=None
    try:
        req=urllib.request.Request(WWW+'/api/vip/info',headers={'User-Agent':UA,'Authorization':'Bearer '+tok})
        vip=urllib.request.urlopen(req,timeout=20).read().decode()
        m=json.loads(vip); bal=m.get('data',{}).get('credit_balance')
    except Exception as e:
        vip=str(e)
    return {'email':mail,'ts':time.strftime('%Y-%m-%d %H:%M:%S'),'token':tok,'credit_balance':str(bal),'vip_info':vip},None

def main():
    db=json.load(open(DBF)) if os.path.exists(DBF) else []
    have=sum(1 for x in db if str(x.get('credit_balance'))=='300')
    print(f'start: total={len(db)} bal300={have} target={TARGET}',flush=True)
    backoff=60
    while len(db) < TARGET:
        rec,err = reg_one(len(db))
        if err=='429':
            print(f'[{len(db)}] 429 -> sleep {backoff}s',flush=True)
            time.sleep(backoff)
            backoff=min(backoff*2, 900)   # cap 15min
            continue
        if rec is None:
            print(f'[{len(db)}] fail:{err} -> sleep 15s',flush=True)
            time.sleep(15); continue
        backoff=60  # reset on success
        db.append(rec)
        with open(DBF,'w') as f: json.dump(db,f,indent=1)
        have=sum(1 for x in db if str(x.get('credit_balance'))=='300')
        print(f'[{len(db)}] OK bal={rec["credit_balance"]} total300={have}',flush=True)
        time.sleep(8)
    print(f'DONE total={len(db)}',flush=True)

if __name__=='__main__':
    main()
