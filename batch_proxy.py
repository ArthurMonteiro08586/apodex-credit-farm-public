# -*- coding: utf-8 -*-
# Proxy-rotated batch: consumer accounts (client_id=apodex-web) -> 300 credits ($20)
# 429 is IP-based (proven by probe_proxy.py). Rotates proxies; parks limited ones.
import json, time, sqlite3, sys, urllib.request, urllib.error
import apodex_reg as ar
import os as _os
PROXY_TXT = _os.environ.get('APODEX_PROXY_TXT', 'live_http_proxies.txt')
PROXY_DB  = _os.environ.get('APODEX_PROXY_DB', 'proxies.db')  # optional: sqlite pool table(proxy, alive)


AUTH = 'https://auth.apodex.ai/api/auth'
WWW = 'https://www.apodex.ai'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36'
OUT = 'accounts_web.json'
TARGET = int(sys.argv[1]) if len(sys.argv) > 1 else 100
PARK_S = 180  # park a proxy after 429

def load_pool():
    pool = []
    try:
        for l in open(PROXY_TXT):
            p = l.split()[0].strip()
            if p: pool.append(p if p.startswith('http') else 'http://' + p)
    except Exception: pass
    try:
        c = sqlite3.connect(f'file:{PROXY_DB}?mode=ro', uri=True)
        for (purl,) in c.execute("SELECT proxy FROM pool WHERE alive=1"):
            if purl: pool.append(purl if purl.startswith('http') else 'http://' + purl)
        c.close()
    except Exception as e:
        print('db err', e)
    # dedupe preserve order
    seen = set(); out = []
    for p in pool:
        if p not in seen:
            seen.add(p); out.append(p)
    return out

def load():
    try: return json.load(open(OUT))
    except Exception: return []

def save(db):
    import os
    tmp = OUT + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(db, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, OUT)

def preq(url, proxy, method='GET', tok=None, body=None, timeout=25):
    h = {'User-Agent': UA, 'Content-Type': 'application/json'}
    if tok: h['Authorization'] = 'Bearer ' + tok
    if method == 'POST' and body is None: body = b''
    req = urllib.request.Request(url, headers=h, method=method, data=body)
    op = urllib.request.build_opener(urllib.request.ProxyHandler({'http': proxy, 'https': proxy}))
    try:
        r = op.open(req, timeout=timeout)
        return r.status, r.read().decode()
    except urllib.error.HTTPError as ex:
        try: return ex.code, ex.read().decode()[:300]
        except Exception: return ex.code, ''
    except Exception as ex:
        return 0, str(ex)[:100]

pool = load_pool()
print(f'pool: {len(pool)} proxies')
db = load()
done = {x['email'] for x in db}
maxi = 0
for e in done:
    if '+apodexweb' in e:
        try: maxi = max(maxi, int(e.split('+apodexweb')[1].split('@')[0]))
        except Exception: pass
print(f'have {len(db)} accounts, next index {maxi+1}, target {TARGET}')

state = {p: {'dead': False, 'parked_until': 0, 'used': 0} for p in pool}
pi = 0

def next_proxy():
    global pi
    now = time.time()
    for _ in range(len(pool)):
        p = pool[pi % len(pool)]; pi += 1
        s = state[p]
        if not s['dead'] and s['parked_until'] <= now:
            return p
    # all parked -> earliest release
    cand = [p for p in pool if not state[p]['dead']]
    if not cand: return None
    return min(cand, key=lambda p: state[p]['parked_until'])

def reg_one(mail):
    p = next_proxy()
    if not p:
        wait = min(state[q]['parked_until'] for q in pool if not state[q]['dead']) - time.time()
        print(f'all proxies parked, sleep {wait:.0f}s'); time.sleep(max(wait, 5) + 2)
        p = next_proxy()
        if not p: return False
    body = json.dumps({'email': mail, 'client_id': 'apodex-web'}).encode()
    st, resp = preq(AUTH + '/passwordless/send-code', p, 'POST', body=body, timeout=20)
    if st == 429:
        state[p]['parked_until'] = time.time() + PARK_S
        print(f'  {p} -> 429, parked {PARK_S}s')
        return False
    if st != 200:
        state[p]['dead'] = True
        print(f'  {p} -> send fail {st} {resp[:60]}, dead')
        return False
    code = ar.read_otp(mail, timeout=150)
    if not code:
        print(f'  {mail}: no OTP (send ok via {p})')
        return False
    body = json.dumps({'email': mail, 'code': code, 'client_id': 'apodex-web'}).encode()
    st, resp = preq(AUTH + '/v2/passwordless/verify-login', p, 'POST', body=body)
    if st != 200:
        # retry verify without proxy (verify not rate limited)
        try:
            req = urllib.request.Request(AUTH + '/v2/passwordless/verify-login', data=body,
                headers={'User-Agent': UA, 'Content-Type': 'application/json'})
            st, resp = urllib.request.urlopen(req, timeout=25).status, None
            resp = json.dumps({'direct': True})
        except urllib.error.HTTPError as ex:
            st, resp = ex.code, ex.read().decode()[:200]
        except Exception as ex:
            st, resp = 0, str(ex)[:100]
        if st != 200:
            print(f'  verify fail {st} {str(resp)[:80]}')
            return False
    try:
        if isinstance(resp, str) and resp.startswith('{'):
            j = json.loads(resp)
        else:
            j = json.loads(resp) if isinstance(resp, str) else {}
        tok = j['data']['access_token']; rtok = j['data'].get('refresh_token')
    except Exception:
        # direct path returned None resp; re-verify directly
        try:
            req = urllib.request.Request(AUTH + '/v2/passwordless/verify-login', data=body,
                headers={'User-Agent': UA, 'Content-Type': 'application/json'})
            j = json.loads(urllib.request.urlopen(req, timeout=25).read().decode())
            tok = j['data']['access_token']; rtok = j['data'].get('refresh_token')
        except Exception as e:
            print(f'  verify parse fail {e}')
            return False
    st2, resp2 = preq(WWW + '/api/vip/info', p, tok=tok)
    bal = '?'
    if st2 == 200:
        try: bal = json.loads(resp2)['data'].get('credit_balance')
        except Exception: pass
    elif st2 == 0:
        try:
            req = urllib.request.Request(WWW + '/api/vip/info', headers={'User-Agent': UA, 'Authorization': 'Bearer ' + tok})
            resp2 = urllib.request.urlopen(req, timeout=25).read().decode()
            bal = json.loads(resp2)['data'].get('credit_balance')
        except Exception: pass
    state[p]['used'] += 1
    rec = {'email': mail, 'ts': time.strftime('%Y-%m-%d %H:%M:%S'), 'token': tok,
           'refresh_token': rtok, 'credit_balance': bal, 'proxy': p,
           'vip_info': str(resp2)[:400]}
    db.append(rec); save(db)
    print(f'OK {mail} bal={bal} via {p} total={len(db)}/{TARGET}')
    return True

i = maxi + 1
guard = 0
while len(db) < TARGET and guard < TARGET * 40:
    guard += 1
    mail = os.environ.get('GMAIL_USER','your@gmail.com').replace('@', f'+apodexweb{i}@')
    i += 1
    if mail in done: continue
    t0 = time.time()
    try:
        reg_one(mail)
    except Exception as e:
        print(f'  exc {e}')
    alive = sum(1 for p in pool if not state[p]['dead'])
    if alive < 3:
        print(f'only {alive} proxies alive, sleep 120'); time.sleep(120)
    time.sleep(1.5)

print(f'DONE total={len(db)} bal300={sum(1 for x in db if str(x.get("credit_balance"))=="300")}')