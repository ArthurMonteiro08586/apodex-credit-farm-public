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



## OPENAI-COMPATIBLE BRIDGE (главное)

`apodex_bridge.py` — шлюз, который превращает пул consumer-акков (300cr/$20 каждый)
в обычную OpenAI-совместимую API. Работает через ТОТ ЖЕ SSE-эндпоинт, что и веб-апп:
`POST www.apodex.ai/api/chat/stream` (mode=standard|pro, version=1.1).

### Запуск
```bash
export GMAIL_USER=you@gmail.com GMAIL_APP_PASS=xxxx   # только для bridge_reauth.py
python bridge_reauth.py        # оживить токены пула (TTL ~1ч, re-login по OTP)
python apodex_bridge.py        # :8420, пул accounts_web.json
```

### Использование (любой OpenAI-клиент)
```bash
curl http://127.0.0.1:8420/v1/chat/completions \n  -H "Content-Type: application/json" \n  -d '{"model":"apodex-web","messages":[{"role":"user","content":"hi"}]}'
```
- `apodex-web`      = standard (Deep Research, ~5-6 cr ≈ $0.4/запрос, ~10с)
- `apodex-web-pro`  = pro (Deep Solve: web_search + tool calls + отчёт .md, ~54 cr ≈ $3.6, ~5мин)
- `stream:true` поддерживается (SSE, OpenAI-формат)
- `/healthz` — статистика пула; `/v1/models` — список
- `BRIDGE_AUTH=secret` — защита фронта Bearer-ом

### Механика пула
- каждый запрос берёт свободный акк, после — отпускает (thread-safe)
- 401/403 → акк помечается dead, авто-ротация на следующий (до 8 попыток)
- 429 → ротация + sleep (BRIDGE_429_SLEEP)
- баланс <5cr → акк retiring; баланс проверяется раз в 40мин
- hot-reload: bridge_reauth.py переписывает accounts_web.json — мост подхватывает без рестарта

### Модели веб-аппа (/api/config, live)
| mode | tier | server_model_id | доступ |
|---|---|---|---|
| standard | Deep Research | `standard` v1.1 | granted |
| pro | Deep Solve | `pro` v1.1 | granted |
| heavy | Deep Discover | `agent-swarm-gv` | **denied** (пейвол) |

### Цены (замерено по /api/vip/credit-transactions)
- standard: -5…-6 cr/запрос → ~50 запросов с акка
- pro: -54 cr/исследование → ~5 исследований с акка
- 100 акков = ~$2000 эквивалента = ~5000 standard или ~500 pro-research

### SSE-события апстрима (что видит мост)
job_started → engine_route → start_of_workflow → title_updated → start_of_agent
→ message (delta.content / delta.reasoning_content) → tool_call / tool_call_result
→ task_board_update → deliverables_update → final_answer → end_of_workflow → share_id → done

### Известные ограничения
- 429 на chat/stream — по IP ИЛИ по частоте акка; лечится ротацией пула
- refresh_token одноразовый и тоже истекает → revive только через новый OTP (bridge_reauth)
- heavy-модель (Deep Discover) недоступна free-аккам
