# -*- coding: utf-8 -*-
"""Apodex AUTOREG v2: Playwright UI login (email+OTP) -> console -> Create API Key -> capture FULL key.
Usage: python apodex_full.py N   (registers your+apodexR{N}@gmail.com, N=timestamp-based if omitted)
No secrets hardcoded except IMAP (own mailbox). Output: accounts.json (local, gitignored)."""
import os
import json, time, re, imaplib, email, sys, os, random

GMAIL_USER = os.environ.get("APODEX_IMAP_USER", "your@gmail.com")
GMAIL_PASS = os.environ.get("APODEX_IMAP_PASS", "your-app-password")
BASE_ALIAS = "your+apodex"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "accounts.json")

def read_otp(alias, timeout=120):
    """Code lives in SUBJECT: 'Your Apodex verification code is NNNNNN'."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            m = imaplib.IMAP4_SSL("imap.gmail.com", 993)
            m.login(GMAIL_USER, GMAIL_PASS)
            m.select("INBOX")
            typ, data = m.search(None, '(UNSEEN FROM "noreply@apodex.ai")')
            for mid in data[0].split():
                typ, msg = m.fetch(mid, "(RFC822)")
                em = email.message_from_bytes(msg[0][1])
                to = str(em.get("To", ""))
                subj = str(em.get("Subject", ""))
                if alias.lower() not in to.lower():
                    continue
                mm = re.search(r"verification code is (\d{6})", subj)
                if not mm:
                    # decode subject if needed
                    from email.header import decode_header, make_header
                    subj = str(make_header(decode_header(subj)))
                    mm = re.search(r"verification code is (\d{6})", subj)
                if mm:
                    m.store(mid, "+FLAGS", "\Seen")
                    m.logout()
                    return mm.group(1)
            m.logout()
        except Exception as e:
            print("  imap retry:", e)
        time.sleep(4)
    return None

def register_one(pg, alias, log=print):
    """Full UI flow on an existing page. Returns dict or None."""
    pg.goto("https://platform.apodex.ai/login", wait_until="networkidle", timeout=90000)
    pg.fill('input[type="email"], input[name="email"]', alias)
    pg.get_by_role("button", name=re.compile("send code", re.I)).click()
    pg.wait_for_timeout(2000)
    log(f"[{alias}] code sent, reading OTP...")
    code = read_otp(alias)
    if not code:
        log(f"[{alias}] OTP TIMEOUT"); return None
    log(f"[{alias}] OTP {code}, verifying...")
    otp = pg.locator('input[name="code"], input[type="text"], input[inputmode]').first
    otp.fill(code)
    pg.get_by_role("button", name=re.compile("sign in|verify", re.I)).click()
    pg.wait_for_timeout(5000)
    if "login" in pg.url:
        log(f"[{alias}] LOGIN FAILED url={pg.url} body={pg.evaluate('document.body.innerText')[:200]}")
        return None
    # grab tokens
    tok = pg.evaluate("() => ({access: localStorage.getItem('apodex_auth_token') || localStorage.getItem('apodex_pp_access_token'), refresh: localStorage.getItem('apodex_pp_refresh_token'), cookies: document.cookie})")
    log(f"[{alias}] logged in -> {pg.url}")
    # console: create API key
    pg.goto("https://platform.apodex.ai/console/api-keys", wait_until="networkidle", timeout=90000)
    pg.wait_for_timeout(2000)
    pg.get_by_role("button", name=re.compile("create new key|create key|new key", re.I)).click()
    pg.wait_for_timeout(1000)
    name = f"eni-{int(time.time())%100000}"
    try:
        pg.locator('input').first.fill(name)
    except Exception:
        pass
    pg.get_by_role("button", name=re.compile("^create api key$|create", re.I)).click()
    pg.wait_for_timeout(3000)
    # full key appears in a textbox/input once
    full = None
    for sel in ['input[readonly]', 'textarea', 'input', '[role="textbox"]']:
        try:
            vals = pg.evaluate(f"() => Array.from(document.querySelectorAll('{sel}')).map(e => e.value ?? e.textContent).filter(v => v && /sk-[A-Za-z0-9_\-]{{20,}}=?/.test(v))")
            if vals:
                mm = re.search(r"sk-[A-Za-z0-9_\-]+=?", vals[0])
                if mm: full = mm.group(0); break
        except Exception:
            pass
    if not full:
        bodytxt = pg.evaluate("document.body.innerText")
        mm = re.search(r"sk-[A-Za-z0-9_\-]{20,}=?", bodytxt)
        if mm: full = mm.group(0)
    if not full:
        log(f"[{alias}] KEY NOT FOUND. body: {pg.evaluate('document.body.innerText')[:400]}")
        return {"email": alias, "key": None, "tokens": tok}
    log(f"[{alias}] FULL KEY captured: {full[:12]}...{full[-6:]} (len {len(full)})")
    return {"email": alias, "key": full, "tokens": tok, "ts": time.strftime("%Y-%m-%d %H:%M:%S")}

def save(rec):
    db = []
    if os.path.exists(OUT):
        try: db = json.load(open(OUT, encoding="utf-8"))
        except Exception: db = []
    db = [x for x in db if x.get("email") != rec.get("email")] + [rec]
    json.dump(db, open(OUT, "w", encoding="utf-8"), indent=1, ensure_ascii=False)

def main():
    from playwright.sync_api import sync_playwright
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    start = int(sys.argv[2]) if len(sys.argv) > 2 else random.randint(200, 999)
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        ctx = b.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36", locale="en-US")
        pg = ctx.new_page()
        ok = 0
        for i in range(start, start + n):
            alias = f"{BASE_ALIAS}{i}@gmail.com"
            try:
                rec = register_one(pg, alias)
                if rec and rec.get("key"): ok += 1
                if rec: save(rec)
            except Exception as e:
                print(f"[{alias}] ERROR: {e}")
            time.sleep(random.uniform(2, 5))
        print(f"DONE: {ok}/{n} keys captured -> {OUT}")
        b.close()

if __name__ == "__main__":
    main()
