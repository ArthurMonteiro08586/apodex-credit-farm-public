# -*- coding: utf-8 -*-
# bridge_reauth.py — re-login dead pool accounts via passwordless OTP (same emails, credits persist).
# Proxy-rotated send-code (429 = per-IP), IMAP OTP read, verify-login -> fresh token+refresh.
# Usage: python bridge_reauth.py [N]  (N = accounts to revive, default all dead)
import os, json, time, sys, sqlite3, threading, urllib.request, urllib.error
os.environ.setdefault('GMAIL_USER', 'your@gmail.com')        # your IMAP mailbox
os.environ.setdefault('GMAIL_APP_PASS', 'your-app-password')  # Gmail app password
import apodex_reg as ar

AUTH = 'https://auth.apodex.ai/api/auth'
WWW = 'https://www.apodex.ai'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36'
OUT = 'accounts_web.json'
LOCK = threading.Lock()
PARK_S = 180

def load_pool_proxies():
    pool = []
    try:
        for l in open('C:/Users/User/tmp/live_http_proxies.txt'):
            p = l.split()[0].strip()
            if p: pool.append(p if p.startswith('http') else 'http://' + p)
    except Exception: pass
    try:
        c = sqlite3.connect('file:C:/Users/User/Desktop/proxy_bot/proxies.db?mode=ro', uri=True)
        for (purl,) in c.execute("SELECT proxy FROM pool WHERE alive=1"):
            if purl: pool.append(purl if purl.startswith('http') else 'http://' + purl)
        c.close()
    except Exception: pass
    seen = set(); out = []
    for p in pool:
        if p not in seen: seen.add(p); out.append(p)
    return out

def preq(url, proxy, method='GET', tok=None, body=None, timeout=25):
    h = {'User-Agent': UA, 'Content-Type': 'application/json'}
    if tok: h['Authorization'] = 'Bearer ' + tok
    data = body.encode() if isinstance(body, str) else (json.dumps(body).encode() if body is not None else None)
    if method == 'POST' and data is None: data = b''
    req = urllib.request.Request(url, headers=h, method=method, data=data)
    op = urllib.request.build_opener(urllib.request.ProxyHandler({'http': proxy, 'https': proxy})) if proxy else urllib.request.build_opener()
    try:
        with op.open(req, timeout=timeout) as r:
            return r.status, r.read().decode('utf-8','replace')
    except urllib.error.HTTPError as e:
        try: return e.code, e.read().decode('utf-8','replace')[:300]
        except Exception: return e.code, ''
    except Exception as e:
        return 0, str(e)[:100]

class ProxyRot:
    def __init__(self, pool):
        self.pool = pool
        self.state = {p: {'dead': False, 'parked_until': 0} for p in pool}
        self.i = 0
    def next(self):
        now = time.time()
        for _ in range(len(self.pool)):
            p = self.pool[self.i % len(self.pool)]; self.i += 1
            s = self.state[p]
            if not s['dead'] and s['parked_until'] <= now: return p
        return None
    def park(self, p, secs=PARK_S): self.state[p]['parked_until'] = time.time() + secs
    def kill(self, p): self.state[p]['dead'] = True
    def alive(self): return sum(1 for p in self.pool if not self.state[p]['dead'])

def token_alive(tok):
    if not tok: return False
    req = urllib.request.Request(WWW + '/api/vip/info', headers={'User-Agent': UA, 'Authorization': 'Bearer ' + tok})
    try:
        urllib.request.urlopen(req, timeout=20); return True
    except Exception:
        return False

def reauth_one(acc, rot):
    mail = acc['email']
    # send-code via rotating proxies
    for attempt in range(6):
        p = rot.next()
        if not p:
            print('  all proxies parked, sleep 60'); time.sleep(60); continue
        st, resp = preq(AUTH + '/passwordless/send-code', p, 'POST',
                        body={'email': mail, 'client_id': 'apodex-web'})
        if st == 200: break
        if st == 429:
            rot.park(p); continue
        rot.kill(p)
    else:
        print(f'  {mail}: send-code never ok'); return False
    code = ar.read_otp(mail, timeout=150)
    if not code:
        print(f'  {mail}: no OTP'); return False
    # verify (direct ok — verify not rate limited)
    st, resp = preq(AUTH + '/v2/passwordless/verify-login', None, 'POST',
                    body={'email': mail, 'code': code, 'client_id': 'apodex-web'})
    if st != 200:
        print(f'  {mail}: verify {st} {resp[:80]}'); return False
    try:
        j = json.loads(resp)
        tok = j['data']['access_token']; rtok = j['data'].get('refresh_token')
    except Exception as e:
        print(f'  {mail}: parse {e}'); return False
    # balance check + save atomically
    st2, r2 = preq(WWW + '/api/vip/info', None, tok=tok)
    bal = '?'
    if st2 == 200:
        try: bal = json.loads(r2)['data'].get('credit_balance')
        except Exception: pass
    with LOCK:
        db = json.load(open(OUT, encoding='utf-8'))
        for x in db:
            if x['email'] == mail:
                x['token'] = tok; x['refresh_token'] = rtok
                x['credit_balance'] = bal; x['reauth_ts'] = time.strftime('%F %T')
                break
        tmp = OUT + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(db, f); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, OUT)
    print(f'REVIVED {mail} bal={bal}')
    return True

def main():
    n_want = int(sys.argv[1]) if len(sys.argv) > 1 else 10**9
    db = json.load(open(OUT, encoding='utf-8'))
    rot = ProxyRot(load_pool_proxies())
    print('proxy pool:', len(rot.pool))
    # find dead accounts (token not alive)
    dead = [x for x in db if not token_alive(x.get('token'))]
    print('dead accounts:', len(dead))
    revived = 0
    for acc in dead:
        if revived >= n_want: break
        if rot.alive() < 3:
            print('proxy pool exhausted, sleep 120'); time.sleep(120)
        try:
            if reauth_one(acc, rot): revived += 1
        except Exception as e:
            print('  exc', str(e)[:100])
        time.sleep(1.0)
    print(f'DONE revived={revived}')

if __name__ == '__main__':
    main()
