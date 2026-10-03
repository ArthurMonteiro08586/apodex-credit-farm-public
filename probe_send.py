# -*- coding: utf-8 -*-
# Probe single send-code to check if IP rate-limit lifted
import json, time, urllib.request, urllib.error
import apodex_reg as ar
AUTH='https://auth.apodex.ai/api/auth'
mail=f'your+probe{int(time.time())%99999}@gmail.com'
body=json.dumps({'email':mail,'client_id':'apodex-web'}).encode()
req=urllib.request.Request(AUTH+'/passwordless/send-code',data=body,headers={'User-Agent':'Mozilla/5.0','Content-Type':'application/json'})
try:
    r=urllib.request.urlopen(req,timeout=30); print('SEND',r.status,r.read(200).decode()[:120])
except urllib.error.HTTPError as e:
    print('SEND FAIL',e.code,e.read(200).decode()[:160])
