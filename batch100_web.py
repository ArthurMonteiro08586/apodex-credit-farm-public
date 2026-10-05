# -*- coding: utf-8 -*-
# Batch 100 consumer accounts (client_id=apodex-web) -> each gets 300 credits = $20 Welcome Bonus
import os
import json, time, urllib.request, urllib.error, sys
import apodex_reg as ar

AUTH = 'https://auth.apodex.ai/api/auth'
WWW = 'https://www.apodex.ai'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36'
OUT = 'accounts_web.json'
N = int(sys.argv[1]) if len(sys.argv) > 1 else 100

def load():
    try: return json.load(open(OUT))
    except Exception: return []

def save(db):
    json.dump(db, open(OUT, 'w'))

def jreq(url, method='GET', tok=None, body=None):
    h = {'User-Agent': UA, 'Content-Type': 'application/json'}
    if tok: h['Authorization'] = 'Bearer ' + tok
    req = urllib.request.Request(url, headers=h, method=method)
    try:
        r = urllib.request.urlopen(req, timeout=25)
        return r.status, r.read().decode()
    except urllib.error.HTTPError as ex:
        return ex.code, ex.read().decode()[:200]
    except Exception as ex:
        return 0, str(ex)

db = load()
done_emails = {x['email'] for x in db}
start = len(done_emails) + 10
print(f'starting at web{start}, target {N}')

for i in range(start, start + N):
    mail = os.environ.get('GMAIL_USER','your@gmail.com').replace('@', f'+apodexweb{i}@')
    if mail in done_emails: continue
    t0 = time.time()
    try:
        body = json.dumps({'email': mail, 'client_id': 'apodex-web'}).encode()
        req = urllib.request.Request(AUTH + '/passwordless/send-code', data=body,
            headers={'User-Agent': UA, 'Content-Type': 'application/json', 'Origin': WWW})
        urllib.request.urlopen(req, timeout=20)
    except urllib.error.HTTPError as ex:
        print(f'[{i}] send FAIL {ex.code} {ex.read().decode()[:80]}')
        if ex.code == 429: time.sleep(60); continue
        continue
    code = ar.read_otp(mail, timeout=150)
    if not code:
        print(f'[{i}] no OTP'); continue
    body = json.dumps({'email': mail, 'code': code, 'client_id': 'apodex-web'}).encode()
    req = urllib.request.Request(AUTH + '/v2/passwordless/verify-login', data=body,
        headers={'User-Agent': UA, 'Content-Type': 'application/json'})
    try:
        j = json.loads(urllib.request.urlopen(req, timeout=25).read().decode())
        tok = j['data']['access_token']
        rtok = j['data'].get('refresh_token')
    except Exception as e:
        print(f'[{i}] verify FAIL {e}'); continue
    # check balance
    st, resp = jreq(WWW + '/api/vip/info', tok=tok)
    bal = '?'
    if st == 200:
        try:
            d = json.loads(resp)['data']
            bal = d.get('credit_balance')
            packs = d.get('credit_packs', [])
        except Exception: packs = []
    rec = {'email': mail, 'ts': time.strftime('%Y-%m-%d %H:%M:%S'), 'token': tok,
           'refresh_token': rtok, 'credit_balance': bal, 'vip_info': resp[:400] if st == 200 else f'HTTP{st}'}
    db.append(rec); save(db)
    print(f'[{i}] OK bal={bal} ({time.time()-t0:.0f}s) total={len(db)}')
    time.sleep(2)

print('DONE total:', len(db))
