# -*- coding: utf-8 -*-
# Capture the REAL chat request the web app makes: Playwright + consumer token in localStorage.
import json, asyncio, sys

async def main():
    from playwright.async_api import async_playwright
    rec = json.load(open('bridge_tok.json'))
    tok = rec['token']

    captured = []

    async with async_playwright() as p:
        br = await p.chromium.launch(headless=True)
        ctx = await br.new_context(user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36')
        pg = await ctx.new_page()

        async def on_request(req):
            u = req.url
            if any(k in u for k in ['/api/', 'think.apodex', 'chat', 'completions', 'research']) and 'assets' not in u and '_next' not in u:
                entry = {'url': u, 'method': req.method}
                try:
                    pd = req.post_data
                    if pd: entry['body'] = pd[:2000]
                except Exception: pass
                try: entry['headers'] = {k: v for k, v in (await req.all_headers()).items() if k.lower() in ('authorization','content-type','accept','origin','referer','x-client-id','x-org-id','apodex-client')}
                except Exception: pass
                captured.append(entry)

        async def on_response(resp):
            u = resp.url
            if any(k in u for k in ['chat', 'completions', 'research', 'message']) and 'assets' not in u and '_next' not in u:
                try:
                    body = await resp.text()
                    print(f'RESP {resp.status} {u[:120]}: {body[:400]!r}', flush=True)
                except Exception:
                    print(f'RESP {resp.status} {u[:120]} (no body)', flush=True)

        pg.on('request', on_request)
        pg.on('response', on_response)

        # seed token: visit www first
        await pg.goto('https://www.apodex.ai/', wait_until='domcontentloaded', timeout=60000)
        await pg.evaluate(f"""() => {{
            const tok = {json.dumps(tok)};
            const rt = {json.dumps(rec.get('refresh_token') or '')};
            const st = {{token: tok, expiresAt: Date.now() + 3600*1000, refreshToken: rt || null, lastSeenVersion: null}};
            localStorage.setItem('mirage-auth-store', JSON.stringify({{state: st, version: 0}}));
            document.cookie = 'apx-signed-in=1; path=/; max-age=31536000; SameSite=Lax';
        }}""")
        print('token seeded, goto /chat', flush=True)
        await pg.goto('https://www.apodex.ai/chat', wait_until='networkidle', timeout=90000)
        await pg.wait_for_timeout(3000)
        print('URL now:', pg.url, flush=True)
        # dump page text to see if logged in
        txt = await pg.evaluate("() => document.body.innerText.slice(0, 300)")
        print('PAGE:', txt.replace(chr(10),' | ')[:250], flush=True)

        # try to send a message
        sent = False
        for sel in ['textarea', 'div[contenteditable="true"]', 'input[type="text"]']:
            try:
                el = pg.locator(sel).first
                if await el.count() > 0:
                    await el.fill('What is 2+2? One word answer.') if sel != 'div[contenteditable="true"]' else await el.type('What is 2+2? One word answer.')
                    sent = True
                    print('filled', sel, flush=True)
                    break
            except Exception as e:
                print('sel fail', sel, str(e)[:60], flush=True)
        if sent:
            await pg.keyboard.press('Enter')
            await pg.wait_for_timeout(25000)

        json.dump(captured, open('chat_capture.json', 'w'), indent=1)
        print('captured', len(captured), 'requests -> chat_capture.json', flush=True)
        await br.close()

asyncio.run(main())
