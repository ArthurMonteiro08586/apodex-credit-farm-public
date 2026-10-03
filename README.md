# Apodex $20 Credit Farm

Массовая регистрация аккаунтов на Apodex (apodex.ai) с автоматическим получением **$20 promotional credits** (300 кредитов, "Welcome Bonus", expiry +30 дней) на каждый аккаунт.

## Как это работает

Apodex — два раздельных продукта с общим auth (auth.apodex.ai, passwordless email OTP):

| Продукт | client_id | Домен | $20 бонус |
|---------|-----------|-------|-----------|
| **Consumer** (Deep Research чат, ASR, memory, web report) | `apodex-web` | www.apodex.ai | **ДА — 300 credits = $20** |
| Developer platform (API console) | `apodex-platform-web` | platform.apodex.ai | НЕТ (balance 0) |

Ключевой инсайт: промо-кредиты капают только на **consumer**-аккаунты. Курс: **15 credits = $1**, welcome pack = 300 credits = **$20.00**, `kind:"promotion"`, `remark:"Welcome Bonus"`, expiry ~30 дней.

## Флоу (10 сек на аккаунт)

1. `POST auth.apodex.ai/api/auth/passwordless/send-code` `{email, client_id:"apodex-web"}`
2. OTP 6 цифр из письма `noreply@apodex.ai` (Gmail IMAP, `+alias` трюк — один ящик, бесконечно аккаунтов)
3. `POST .../v2/passwordless/verify-login` `{email, code, client_id:"apodex-web"}` → `access_token` + `refresh_token`
4. Проверка: `GET www.apodex.ai/api/vip/info` → `credit_balance: "300"`, `credit_packs[0].remark: "Welcome Bonus"`

## Файлы

- `batch100_web.py N` — основной батч: N consumer-аккаунтов → `accounts_web.json` (token + баланс каждого)
- `apodex_reg.py` — ядро: send-code / IMAP OTP reader / verify / save
- `consumer_dump.py` — пробник: свежий акк + полный дамп `/api/vip/info`, `/api/vip/plans`, `/api/config`
- `web_reg10.py` — разведка web-клиента
- `batch100.py` — platform-батч (API-ключи, но БЕЗ $20; оставлен для сравнения)

## Что даёт consumer-аккаунт

300 кредитов тратятся в research-чате www.apodex.ai: Deep Research, Pro Mode, ASR, web report, memory service, file upload (Excel/PPT). Список фич: `/api/config` → `model_config`.

## Rate limits

- send-code: глобальный ~1 запрос/минуту на 429 (`PASSWORDLESS_SEND_RATE_LIMITED`, `expires_in:95`) — батч спит и ретраит
- OTP письмо приходит 10-90 сек
- Gmail `+alias` — Apodex НЕ нормализует алиасы, каждый `+tag` = новый аккаунт

## Запуск

```
python batch100_web.py 100
```

Результат в `accounts_web.json`: email, access_token, refresh_token, credit_balance, vip_info на каждый акк.

## 429 rate-limit = IP-based → proxy-ротация (КЛЮЧЕВОЕ)

`send-code` имеет ГЛОБАЛЬНЫЙ IP-лимит (`PASSWORDLESS_SEND_RATE_LIMITED`, "too frequent").
Пробой (`probe_send.py`) подтверждено: с домашнего IP — 429, через free-proxy — 200 OK.
Значит лимит на IP, НЕ на email/аккаунт.

Решение — `batch_proxy.py`: ротация free-прокси (пул `live_http_proxies.txt` +
`proxy_bot/proxies.db`, ~180 шт), парковка прокси на 180с после 429, пометка мёртвых.
Добирает до TARGET (100). Итог прогона: **100 аккаунтов, 93 с балансом 300cr ($20)**.

- `probe_send.py` — один send-code с текущего IP (проверить лимит)
- `probe_proxy.py` — send-code через N прокси (доказать что 429 = IP-based)
- `batch_proxy.py TARGET` — proxy-ротированный батч (боевой)
- `batch_resume.py` — backoff-вариант (устарел: 429 IP-based, backoff бесполезен)

Прокси-пул быстро выгорает (free-прокси: timeout/407/SSL), скрипт их паркует и идёт дальше.
Для стабильного фарма — residential/mobile прокси, не free.

