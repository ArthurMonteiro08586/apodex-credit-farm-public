import os
# -*- coding: utf-8 -*-
# Probe send-code via free proxies from pool — is 429 IP-based?
import json, time, urllib.request, urllib.error
AUTH='https://auth.apodex.ai/api/auth'
raw=[l.split()[0] for l in open(os.environ.get('APODEX_PROXY_TXT', 'live_http_proxies.txt')) if l.strip()]
proxies=[p if p.startswith('http') else 'http://'+p for p in raw][:15]
print('proxy pool:',len(proxies))
ok=0
for px in proxies:
    if not px.startswith('http'): px='http://'+px
    mail=f'proxyprobe{int(time.time())}@gmail.com'
    body=json.dumps({'email':mail,'client_id':'apodex-web'}).encode()
    req=urllib.request.Request(AUTH+'/passwordless/send-code',data=body,headers={'Content-Type':'application/json','User-Agent':'Mozilla/5.0'})
    op=urllib.request.build_opener(urllib.request.ProxyHandler({'http':px,'https':px}))
    t0=time.time()
    try:
        r=op.open(req,timeout=15); dt=time.time()-t0
        print('PROXY OK',px,r.status,f'{dt:.1f}s'); ok+=1
    except urllib.error.HTTPError as e:
        dt=time.time()-t0
        b=e.read().decode()[:100]
        print('PROXY',px,'HTTP',e.code,f'{dt:.1f}s',b)
        if e.code!=429 and 'timeout' not in b.lower(): ok+=0
    except Exception as e:
        print('PROXY',px,'ERR',type(e).__name__,str(e)[:60])
    if ok>=2: break
print('reachable(non-429):',ok)