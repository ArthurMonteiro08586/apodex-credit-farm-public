# -*- coding: utf-8 -*-
"""
apodex_bridge.py — OpenAI-compatible bridge over Apodex consumer web chat.

Spends the 300-credit ($20) Welcome Bonus of farmed consumer accounts
(www.apodex.ai, client_id=apodex-web) through the SAME SSE endpoint the web
app uses:  POST /api/chat/stream

Front:  POST /v1/chat/completions  (OpenAI format, stream + non-stream)
        GET  /v1/models
        GET  /healthz               (pool stats)
Back:   accounts_web.json pool, per-account credit tracking via /api/vip/info,
        auto-rotate on exhaustion/401, optional per-request proxy.

Modes:  "standard" = fast chat (swarm agents, ~10s)
        "pro"      = deep research (long, tool-using; spends more credits)
Model mapping (request "model"):
        apodex-web          -> standard
        apodex-web-pro      -> pro
        anything else       -> standard (override with ?mode=pro or body {"apodex_mode":"pro"})

Run:    python apodex_bridge.py            (0.0.0.0:8420, pool accounts_web.json)
Env:    BRIDGE_PORT, BRIDGE_POOL (path), BRIDGE_AUTH (optional Bearer for the front)
"""
import json, os, sys, time, uuid, threading, urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
POOL_PATH = os.environ.get('BRIDGE_POOL', os.path.join(HERE, 'accounts_web.json'))
PORT = int(os.environ.get('BRIDGE_PORT', '8420'))
FRONT_AUTH = os.environ.get('BRIDGE_AUTH', '')  # if set, require Bearer on front
WWW = 'https://www.apodex.ai'
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36')
BAL_FLOOR = 5          # retire account below this credit balance
REFRESH_EVERY = 2400   # re-check balance every N seconds per account

# ---------------------------------------------------------------- pool -----
class Account:
    __slots__ = ('email', 'token', 'refresh_token', 'balance', 'last_bal_check',
                 'dead', 'in_use', 'used_count', 'proxy')
    def __init__(self, rec):
        self.email = rec.get('email', '?')
        self.token = rec.get('token') or rec.get('access_token')
        self.refresh_token = rec.get('refresh_token')
        self.balance = None
        self.last_bal_check = 0
        self.dead = False
        self.in_use = False
        self.used_count = 0
        self.proxy = rec.get('proxy')

class Pool:
    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self.accounts = []
        self.load()

    def load(self):
        try:
            db = json.load(open(self.path, encoding='utf-8'))
            self._mtime = os.path.getmtime(self.path)
        except Exception as e:
            print('[pool] load fail:', e); db = []
        self.accounts = [Account(x) for x in db if (x.get('token') or x.get('access_token'))]
        print(f'[pool] {len(self.accounts)} accounts from {os.path.basename(self.path)}')

    def _check_balance(self, acc):
        req = urllib.request.Request(WWW + '/api/vip/info', headers={
            'User-Agent': UA, 'Authorization': 'Bearer ' + acc.token})
        try:
            j = json.loads(urllib.request.urlopen(req, timeout=25).read())
            acc.balance = int(j['data'].get('credit_balance', 0))
            acc.last_bal_check = time.time()
            return True
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                acc.dead = True
                print(f'[pool] {acc.email}: token dead ({e.code})')
            return False
        except Exception as e:
            print(f'[pool] balance check fail {acc.email}: {str(e)[:80]}')
            return False

    def acquire(self, exclude=None):
        """Pick a live account with credits. Blocks briefly if all busy."""
        exclude = exclude or set()
        for _ in range(120):
            with self.lock:
                cands = [a for a in self.accounts if not a.dead and not a.in_use and a.email not in exclude]
                # prefer known-good balance, then unknown
                cands.sort(key=lambda a: (a.balance is not None and a.balance < BAL_FLOOR,
                                          -(a.balance or 0)))
                for a in cands:
                    if a.balance is not None and a.balance < BAL_FLOOR:
                        continue
                    a.in_use = True
                    return a
            time.sleep(1)
        return None

    def maybe_reload(self):
        """Hot-reload pool file (bridge_reauth.py rewrites it)."""
        try:
            mtime = os.path.getmtime(self.path)
        except OSError:
            return
        if mtime > getattr(self, '_mtime', 0):
            self._mtime = mtime
            with self.lock:
                by_email = {a.email: a for a in self.accounts}
                try:
                    db = json.load(open(self.path, encoding='utf-8'))
                except Exception:
                    return
                new = []
                for rec in db:
                    if not (rec.get('token') or rec.get('access_token')):
                        continue
                    old = by_email.get(rec.get('email'))
                    tok = rec.get('token') or rec.get('access_token')
                    if old and old.token == tok:
                        new.append(old)
                    else:
                        a = Account(rec)
                        new.append(a)
                self.accounts = new
                print(f'[pool] reloaded: {len(new)} accounts')

    def release(self, acc, spent=None):
        with self.lock:
            acc.in_use = False
            acc.used_count += 1
            if spent is not None and acc.balance is not None:
                acc.balance = max(0, acc.balance - spent)
            if acc.balance is not None and acc.balance < BAL_FLOOR:
                acc.dead = True
                print(f'[pool] {acc.email}: exhausted (bal={acc.balance}), retired')

    def refresh_balance(self, acc):
        if time.time() - acc.last_bal_check > REFRESH_EVERY:
            self._check_balance(acc)

    def stats(self):
        with self.lock:
            alive = [a for a in self.accounts if not a.dead]
            known = [a.balance for a in alive if a.balance is not None]
            return {'total': len(self.accounts), 'alive': len(alive),
                    'dead': len(self.accounts) - len(alive),
                    'credits_known': sum(known), 'accounts_balance_known': len(known),
                    'busy': sum(1 for a in self.accounts if a.in_use)}

# ---------------------------------------------------------------- chat -----
def stream_web_chat(acc, messages, mode='standard', capabilities=None, timeout=1800):
    """Replay the web app's POST /api/chat/stream. Yields (event, data_dict)."""
    chat_id = str(uuid.uuid4())
    msg_id = str(uuid.uuid4())
    body = json.dumps({
        'messages': messages, 'chat_id': chat_id, 'message_id': msg_id,
        'mode': mode, 'version': '1.1',
        'enabled_capabilities': capabilities or [],
    }).encode()
    req = urllib.request.Request(WWW + '/api/chat/stream', data=body, method='POST', headers={
        'User-Agent': UA, 'Authorization': 'Bearer ' + acc.token,
        'Content-Type': 'application/json', 'Accept': '*/*',
        'Origin': WWW, 'Referer': f'{WWW}/chat/{chat_id}',
    })
    opener = urllib.request.build_opener()
    if acc.proxy and os.environ.get('BRIDGE_USE_PROXY'):
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({'http': acc.proxy, 'https': acc.proxy}))
    resp = opener.open(req, timeout=timeout)
    cur = None
    for raw in resp:
        line = raw.decode('utf-8', 'replace').rstrip('\r\n')
        if line.startswith('event: '):
            cur = line[7:].strip()
        elif line.startswith('data: ') and cur:
            try:
                yield cur, json.loads(line[6:])
            except Exception:
                yield cur, {'raw': line[6:]}
    resp.close()

def convert_messages(oai_messages):
    """OpenAI messages -> apodex web messages (system folded into first user msg)."""
    out, sys_txt = [], []
    for m in oai_messages:
        role, content = m.get('role', 'user'), m.get('content', '')
        if isinstance(content, list):  # vision-style parts -> text only
            content = ' '.join(p.get('text', '') for p in content if isinstance(p, dict))
        if role == 'system':
            sys_txt.append(content)
        else:
            out.append({'role': role, 'content': content})
    if sys_txt and out:
        out[0]['content'] = '\n\n'.join(sys_txt) + '\n\n' + out[0]['content']
    elif sys_txt:
        out.append({'role': 'user', 'content': '\n\n'.join(sys_txt)})
    return out or [{'role': 'user', 'content': ''}]

def run_completion(pool, body):
    """One OpenAI-shaped completion with account rotation on 401/429."""
    messages = convert_messages(body.get('messages') or [])
    model = body.get('model', 'apodex-web')
    mode = body.get('apodex_mode') or ('pro' if 'pro' in str(model).lower() else 'standard')
    if mode not in ('standard', 'pro'):
        mode = 'standard'
    max_tries = int(os.environ.get('BRIDGE_MAX_TRIES', '8'))
    excluded = set()
    last_err = None
    for attempt in range(max_tries):
        pool.maybe_reload()
        acc = pool.acquire(exclude=excluded)
        if not acc:
            raise BridgeError(503, 'no live accounts in pool (run bridge_reauth.py)')
        pool.refresh_balance(acc)
        try:
            text, meta = _one_try(pool, acc, messages, mode, body)
            return text, meta
        except BridgeError as e:
            last_err = e
            excluded.add(acc.email)
            if e.code in (401, 403):
                acc.dead = True
                print(f'[bridge] {acc.email}: dead ({e.code}), rotating')
            elif e.code == 429:
                print(f'[bridge] {acc.email}: 429, rotating (attempt {attempt+1})')
                time.sleep(float(os.environ.get('BRIDGE_429_SLEEP', '3')))
            else:
                raise
            continue
    raise last_err or BridgeError(502, 'all attempts failed')

def _one_try(pool, acc, messages, mode, body):
    t0 = time.time()
    answer_parts, reasoning_len, tools = [], 0, 0
    final = None
    try:
        for ev, d in stream_web_chat(acc, messages, mode=mode):
            if ev == 'message':
                delta = d.get('delta') or {}
                if 'content' in delta and delta['content']:
                    answer_parts.append(delta['content'])
                if 'reasoning_content' in delta:
                    reasoning_len += len(delta['reasoning_content'] or '')
                if delta.get('tool_calls'):
                    tools += 1
            elif ev == 'final_answer':
                final = d.get('content')
            elif ev == 'error':
                raise BridgeError(502, 'upstream error: ' + json.dumps(d)[:200])
        text = final if final else ''.join(answer_parts)
        if not text:
            raise BridgeError(502, 'empty answer from upstream')
        meta = {'account': acc.email, 'mode': mode, 'elapsed': round(time.time() - t0, 1),
                'reasoning_chars': reasoning_len, 'tool_calls': tools}
        return text, meta
    except urllib.error.HTTPError as e:
        raise BridgeError(e.code, 'upstream HTTP %s' % e.code)
    finally:
        pool.release(acc)

class BridgeError(Exception):
    def __init__(self, code, msg):
        super().__init__(msg); self.code = code; self.msg = msg

# ---------------------------------------------------------------- http -----
POOL = Pool(POOL_PATH)

class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *args):
        sys.stderr.write('[%s] %s\n' % (time.strftime('%H:%M:%S'), fmt % args))

    def _send(self, code, obj, ctype='application/json'):
        data = json.dumps(obj).encode() if not isinstance(obj, bytes) else obj
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Headers', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
        self.send_header('Content-Length', '0')
        self.end_headers()

    def do_GET(self):
        if self.path.startswith('/healthz'):
            self._send(200, POOL.stats())
        elif self.path.startswith('/v1/models'):
            self._send(200, {'object': 'list', 'data': [
                {'id': 'apodex-web', 'object': 'model', 'owned_by': 'apodex-bridge',
                 'description': 'Apodex consumer swarm chat (standard mode, spends welcome credits)'},
                {'id': 'apodex-web-pro', 'object': 'model', 'owned_by': 'apodex-bridge',
                 'description': 'Apodex PRO deep research (long-running, spends more credits)'},
            ]})
        else:
            self._send(404, {'error': 'not found'})

    def do_POST(self):
        if FRONT_AUTH:
            h = self.headers.get('Authorization', '')
            if h != 'Bearer ' + FRONT_AUTH:
                self._send(401, {'error': {'message': 'invalid bridge auth'}}); return
        if not self.path.startswith('/v1/chat/completions'):
            self._send(404, {'error': 'not found'}); return
        n = int(self.headers.get('Content-Length', 0))
        try:
            body = json.loads(self.rfile.read(n) or b'{}')
        except Exception:
            self._send(400, {'error': {'message': 'bad json'}}); return
        try:
            text, meta = run_completion(POOL, body)
        except BridgeError as e:
            self._send(e.code, {'error': {'message': e.msg, 'type': 'bridge_error'}}); return
        except Exception as e:
            self._send(500, {'error': {'message': str(e)[:200], 'type': 'bridge_error'}}); return
        cid = 'chatcmpl-' + uuid.uuid4().hex[:24]
        now = int(time.time())
        if body.get('stream'):
            # emulate OpenAI SSE: content in one chunk (web SSE deltas already coalesced)
            chunks = [
                {'id': cid, 'object': 'chat.completion.chunk', 'created': now,
                 'model': body.get('model', 'apodex-web'),
                 'choices': [{'index': 0, 'delta': {'role': 'assistant', 'content': ''}, 'finish_reason': None}]},
                {'id': cid, 'object': 'chat.completion.chunk', 'created': now,
                 'model': body.get('model', 'apodex-web'),
                 'choices': [{'index': 0, 'delta': {'content': text}, 'finish_reason': None}]},
                {'id': cid, 'object': 'chat.completion.chunk', 'created': now,
                 'model': body.get('model', 'apodex-web'),
                 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]},
            ]
            payload = ''.join('data: ' + json.dumps(c) + '\n\n' for c in chunks) + 'data: [DONE]\n\n'
            self._send(200, payload.encode(), 'text/event-stream')
        else:
            self._send(200, {
                'id': cid, 'object': 'chat.completion', 'created': now,
                'model': body.get('model', 'apodex-web'),
                'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': text},
                             'finish_reason': 'stop'}],
                'usage': {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0},
                'apodex_bridge': meta,
            })

def main():
    srv = ThreadingHTTPServer(('0.0.0.0', PORT), Handler)
    print(f'[bridge] OpenAI-compatible on http://0.0.0.0:{PORT}/v1  (pool: {len(POOL.accounts)} accounts)')
    print('[bridge] models: apodex-web (standard), apodex-web-pro (deep research)')
    srv.serve_forever()

if __name__ == '__main__':
    main()
