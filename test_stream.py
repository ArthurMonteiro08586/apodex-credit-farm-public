# -*- coding: utf-8 -*-
# Pure-HTTP replay of web-app chat: POST /api/chat/stream with own uuids. Dump ALL SSE events.
import json, uuid, urllib.request, time

rec = json.load(open('bridge_tok.json'))
TOK = rec['token']
W = 'https://www.apodex.ai'

def stream_chat(query, mode='standard', caps=None, timeout=600):
    chat_id = str(uuid.uuid4())
    msg_id = str(uuid.uuid4())
    body = json.dumps({
        'messages': [{'role': 'user', 'content': query}],
        'chat_id': chat_id, 'message_id': msg_id,
        'mode': mode, 'version': '1.1',
        'enabled_capabilities': caps or [],
    }).encode()
    req = urllib.request.Request(W + '/api/chat/stream', data=body, method='POST', headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36',
        'Authorization': 'Bearer ' + TOK,
        'Content-Type': 'application/json',
        'Accept': '*/*',
        'Origin': W,
        'Referer': W + '/chat/' + chat_id,
    })
    t0 = time.time()
    events = {}
    last = []
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        print('HTTP', resp.status, resp.headers.get('content-type'))
        cur_event = None
        for raw in resp:
            line = raw.decode('utf-8','replace').rstrip('\n')
            if line.startswith('event: '):
                cur_event = line[7:].strip()
                events[cur_event] = events.get(cur_event, 0) + 1
            elif line.startswith('data: ') and cur_event:
                last.append((cur_event, line[6:]))
    print('elapsed %.1fs, events:' % (time.time()-t0), json.dumps(events, indent=1))
    # show unique event types with sample payloads
    shown = set()
    for ev, d in last:
        if ev not in shown:
            shown.add(ev)
            print(f'--- {ev}: {d[:300]}')
    return chat_id, events, last

if __name__ == '__main__':
    cid, ev, last = stream_chat('What is the capital of France? One sentence.')
