# -*- coding: utf-8 -*-
import os
import json, time, urllib.request, urllib.error
import apodex_reg as ar
AUTH="https://auth.apodex.ai/api"; PLAT="https://platform.apodex.ai"; WWW="https://www.apodex.ai"
ALIAS=os.environ.get("GMAIL_USER","your@gmail.com").replace("@","+apodexweb10@")
H={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36','Content-Type':'application/json','Accept-Language':'en'}
def call(url,payload=None,tok=None,full=False):
    h=dict(H)
    if tok: h['Authorization']='Bearer '+tok
    data=json.dumps(payload).encode() if payload else None
    req=urllib.request.Request(url,data=data,headers=h,method='POST' if data else 'GET')
    try:
        with urllib.request.urlopen(req,timeout=30) as r:
            t=r.read().decode('utf-8','ignore')
            return r.status, (t if full else t[:700])
    except urllib.error.HTTPError as e:
        try: b=e.read().decode()[:250]
        except: b=''
        return e.code, b
    except Exception as e: return -1, str(e)[:150]
def log(*a):
    s=f"[{time.strftime('%H:%M:%S')}] "+' '.join(str(x) for x in a)
    print(s,flush=True); open('web_probe.log','a',encoding='utf-8').write(s+'\n')

for attempt in range(10):
    st,r=call(f"{AUTH}/auth/passwordless/send-code",{"email":ALIAS})
    log('send',attempt,st,str(r)[:80])
    if st==200: break
    time.sleep(75)
else:
    raise SystemExit('send never ok')
code=ar.read_otp(ALIAS,timeout=180)
log('OTP',code)
if not code: raise SystemExit('no otp')
st,r=call(f"{AUTH}/auth/v2/passwordless/verify-login",{"email":ALIAS,"code":code,"client_id":"apodex-web"},full=True)
log('verify apodex-web status',st,'len',len(r))
tok=None
if st==200:
    d=json.loads(r)
    data=d.get('data',d)
    tok=data.get('access_token'); rtok=data.get('refresh_token')
    log('is_new_user',data.get('is_new_user'),'user_id',(data.get('user') or {}).get('id'))
    json.dump({'email':ALIAS,'access_token':tok,'refresh_token':rtok,'client':'apodex-web','ts':time.strftime('%F %T')},open('web_acc10.json','w'))
time.sleep(4)
if tok:
    log('WWW /api/vip/info:',call(f"{WWW}/api/vip/info",None,tok))
    log('WWW /api/vip/credit-transactions:',call(f"{WWW}/api/vip/credit-transactions",{"page":1,"page_size":20},tok))
    log('WWW /api/auth/projects:',call(f"{WWW}/api/auth/projects",None,tok))
    log('PLAT credit-grants:',call(f"{PLAT}/v1/user/credit-grants",None,tok))
    log('PLAT account:',call(f"{PLAT}/v1/user/account",None,tok))
else:
    log('NO TOKEN')
log('DONE')
