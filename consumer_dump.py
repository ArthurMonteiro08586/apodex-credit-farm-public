# -*- coding: utf-8 -*-
# Fresh consumer reg -> full vip info + credit transactions dump
import os
import json, time, re, urllib.request, urllib.error
import apodex_reg as ar
AUTH='https://auth.apodex.ai/api/auth'; WWW='https://www.apodex.ai'; UA='Mozilla/5.0'

def jreq(url, method='GET', tok=None):
    h={'User-Agent':UA,'Content-Type':'application/json'}
    if tok: h['Authorization']='Bearer '+tok
    req=urllib.request.Request(url,headers=h,method=method)
    try:
        r=urllib.request.urlopen(req,timeout=25); return r.status, r.read().decode()
    except urllib.error.HTTPError as ex: return ex.code, ex.read().decode()[:300]
    except Exception as ex: return 0, str(ex)

mail=os.environ.get('GMAIL_USER','your@gmail.com').replace('@', f'+apodexweb{int(time.time())%10000}@')
print('mail:', mail)
body=json.dumps({'email':mail,'client_id':'apodex-web'}).encode()
req=urllib.request.Request(AUTH+'/passwordless/send-code',data=body,headers={'User-Agent':UA,'Content-Type':'application/json','Origin':WWW})
print('send:', urllib.request.urlopen(req,timeout=20).status)
code=ar.read_otp(mail, timeout=180)
print('code:', code)
body=json.dumps({'email':mail,'code':code,'client_id':'apodex-web'}).encode()
tok=None
for vp in ['/v2/passwordless/verify-login','/passwordless/verify-code']:
    req=urllib.request.Request(AUTH+vp,data=body,headers={'User-Agent':UA,'Content-Type':'application/json'})
    try:
        j=json.loads(urllib.request.urlopen(req,timeout=25).read().decode())
        tok=j['data']['access_token']; print('verify via',vp); break
    except urllib.error.HTTPError as ex:
        print(vp,'->',ex.code,ex.read().decode()[:120])
json.dump({'email':mail,'token':tok,'ts':time.time()},open('consumer_fresh.json','w'))
print('=== /api/vip/info ===')
print(jreq(WWW+'/api/vip/info',tok=tok))
print('=== /api/vip/credit-transactions ===')
print(jreq(WWW+'/api/vip/credit-transactions',tok=tok))
print('=== /api/vip/balance ===')
print(jreq(WWW+'/api/vip/balance',tok=tok))
print('=== /api/vip/credits ===')
print(jreq(WWW+'/api/vip/credits',tok=tok))
