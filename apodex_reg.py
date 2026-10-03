# -*- coding: utf-8 -*-
"""Apodex full autoreg: send-code -> Gmail IMAP OTP -> verify-login -> tokens -> API key creation."""
import os
import imaplib, email, re, json, sys, time, os
import urllib.request, urllib.error

AUTH = "https://auth.apodex.ai"
PLATFORM = "https://platform.apodex.ai"
CLIENT_ID = "apodex-platform-web"
GMAIL = (os.environ.get("GMAIL_USER","your@gmail.com"), os.environ.get("GMAIL_APP_PASS","your-app-password"))
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "accounts.json")

HDRS = {
    "Content-Type": "application/json",
    "Accept-Language": "en",
    "Origin": PLATFORM,
    "Referer": PLATFORM + "/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
}

def post(url, payload, token=None):
    h = dict(HDRS)
    if token: h["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=h, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try: body = json.loads(e.read().decode())
        except Exception: body = {}
        return e.code, body

def get(url, token=None):
    h = dict(HDRS)
    if token: h["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:500]

def read_otp(alias_email, timeout=120):
    pat = re.compile(r"verification code is (\d{6})")
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            m = imaplib.IMAP4_SSL("imap.gmail.com", 993)
            m.login(*GMAIL)
            m.select("INBOX")
            typ, data = m.search(None, '(UNSEEN FROM "noreply@apodex.ai")')
            ids = data[0].split()
            for mid in ids:
                typ, msg = m.fetch(mid, "(RFC822)")
                em = email.message_from_bytes(msg[0][1])
                if alias_email.lower() not in json.dumps(em.get("To","")).lower():
                    # To header may be encoded; also check body
                    raw = msg[0][1].decode("utf-8","ignore")
                    if alias_email.lower() not in raw.lower():
                        continue
                subj = em.get("Subject","")
                body = ""
                if em.is_multipart():
                    for p in em.walk():
                        if p.get_content_type() == "text/plain":
                            body = p.get_payload(decode=True).decode("utf-8","ignore"); break
                else:
                    body = em.get_payload(decode=True).decode("utf-8","ignore")
                mm = pat.search(subj) or pat.search(body) or re.search(r"\b(\d{6})\b", body)
                if mm:
                    m.store(mid, "+FLAGS", "\\Seen")
                    m.logout()
                    return mm.group(1)
            m.logout()
        except Exception as e:
            print("  imap retry:", e)
        time.sleep(5)
    return None

def register(alias):
    print(f"[1] send-code {alias}")
    st, r = post(f"{AUTH}/api/auth/passwordless/send-code", {"email": alias})
    print("   ->", st, str(r)[:150])
    if st != 200: return None
    print("[2] wait OTP...")
    code = read_otp(alias)
    if not code:
        print("   TIMEOUT no OTP"); return None
    print("   code:", code)
    print("[3] verify-login")
    st, r = post(f"{AUTH}/api/auth/v2/passwordless/verify-login",
                 {"email": alias, "code": code, "client_id": CLIENT_ID})
    if st != 200 or "data" not in r:
        print("   FAIL", st, str(r)[:200]); return None
    d = r["data"]
    print("   OK user:", d.get("user",{}).get("id"), "new_user:", d.get("is_new_user"))
    return d

def save(alias, tok):
    rec = {"email": alias, "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
           "access_token": tok.get("access_token"), "refresh_token": tok.get("refresh_token"),
           "expires_in": tok.get("expires_in"), "user_id": tok.get("user",{}).get("id")}
    db = []
    if os.path.exists(OUT):
        try: db = json.load(open(OUT, encoding="utf-8"))
        except Exception: db = []
    db = [x for x in db if x.get("email") != alias] + [rec]
    json.dump(db, open(OUT, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print("[saved]", OUT, f"({len(db)} accounts)")

if __name__ == "__main__":
    aliases = sys.argv[1:] or [os.environ.get("GMAIL_USER","your@gmail.com").replace("@","+apodex100@")]
    for a in aliases:
        tok = register(a)
        if tok: save(a, tok)
        time.sleep(2)
