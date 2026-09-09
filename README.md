# Vacancier Telegram Bot

A multi-user Telegram bot that broadcasts job vacancy postings to subscribers. Users can subscribe for free with a trial period, then upgrade to paid monthly or yearly plans via Telegram Stars.

## Features

- **Multi-user subscriptions**: Users `/subscribe` via Telegram to receive job postings; `/unsubscribe` to stop
- **Free trial period**: New subscribers get 10 free messages (configurable, can switch to time-based)
- **Trial quota enforcement**: Only sends up to remaining quota per delivery pass; respects both message-count and time-based trials
- **Paid subscriptions**: Monthly or yearly plans via Telegram Stars (XTR) — native, no external payment provider
- **Trial gating**: Pure function-based, switchable between message-count or time-interval limits via env var
- **Command-based management**: `/start`, `/subscribe`, `/stop`, `/unsubscribe`, `/upgrade`, `/cancel`, `/help`, `/filters`, `/updates`
- **Filter management**: Subscribers can create custom job filters (keyword-based or AI-based)
- **Payment tracking**: Audit log of all payments with idempotency guard (no double-charging on webhook replays)
- **Subscription expiry**: Automatic downgrade to free on expiry; auto-renewal for monthly plans (Telegram-native)
- **Multi-database support**: PostgreSQL, SQLite, MySQL
- **Persistent state**: Remembers Telegram update offset across restarts (no message duplication or missed commands)
- **Graceful shutdown**: Handles SIGINT/SIGTERM signals cleanly
- **Clean unsubscribe**: Clears pending messages from Redis cache, so resubscribing starts fresh with a new trial quota

## Architecture

The bot runs two parallel loops in `bot/main.py`:

1. **Update polling**: Listens for incoming Telegram commands (`/subscribe`, `/unsubscribe`, `/upgrade`, `/filters`, `/updates`)
2. **Message delivery**: Fetches pending messages from Redis and sends to active subscribers, respecting trial quotas

### Message Flow

```
Parser (vacancier-parser-v2)
    ↓ (fetch, deduplicate, save messages)
    
Database: messages table
    ↓
    
Matcher (vacancier-parser-v2/matcher.py)
    ↓ (match messages against subscriber filters)
    
Redis: pending:{chat_id} sets
    ↓ (messages staged, not yet delivered)
    
Bot Delivery Loop (bot/main.py)
    ↓ (check: is subscriber active? in trial? enough quota?)
    ↓ (cap delivery: max = remaining_quota for free subscribers)
    
Telegram: messages sent
    ↓ (only here do we update messages_received counter)
    
Database: subscribers table (messages_received, message_sent_last_date)
```

### Trial Quota Enforcement

For **free subscribers on message-based trial**:
- Quota limit = `TRIAL_MESSAGE_LIMIT` (default 10)
- Remaining = limit − `messages_received`
- Delivery loop sends **only** up to remaining quota, leaving excess messages in Redis for later
- Counters update **only after confirmed Telegram delivery** (not at staging time)

For **free subscribers on time-based trial** or **paid subscribers**:
- No message-count limit, send all pending messages

This ensures:
1. Users can resubscribe and get a fresh trial quota
2. Undelivered messages don't count toward quota
3. Failed deliveries don't double-count

## Installation

```bash
pip install -r requirements.txt
```

## Configuration

Set environment variables (or add to a `.env` file):

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `BOT_TOKEN` | Yes | — | Telegram bot token from [@BotFather](https://t.me/botfather) |
| `DB_DRIVER` | No | `sqlite` | Database driver: `postgres`, `sqlite`, `mysql` |
| `DB_DSN` | Yes | — | Database connection string |
| `BATCH_SIZE` | No | `10` | Messages to fetch per poll |
| `POLL_INTERVAL_SEC` | No | `60` | Seconds between message polls |
| `SEND_DELAY_SEC` | No | `0.5` | Delay between sending to each subscriber (rate limiting) |
| `STARS_PRICE_MONTHLY` | No | `100` | Telegram Stars price for monthly subscription |
| `STARS_PRICE_YEARLY` | No | `1000` | Telegram Stars price for yearly subscription |
| `TRIAL_TYPE` | No | `messages` | Trial gating: `messages` (count-based) or `days` (time-based) |
| `TRIAL_MESSAGE_LIMIT` | No | `10` | Free messages allowed per subscriber (if `TRIAL_TYPE=messages`) |
| `TRIAL_DAYS` | No | `2` | Free trial duration in days (if `TRIAL_TYPE=days`) |
| `CHAT_ID` | No | — | *Deprecated*: only used for single-recipient backwards-compat mode |

### Database Connection Examples

**PostgreSQL:**
```
postgresql://user:password@localhost:5432/vacancier
```

**SQLite:**
```
/path/to/vacancier.db
```

**MySQL:**
```
mysql://user:password@localhost:3306/vacancier
```

## Database Schema

### `subscribers`
Stores user subscriptions and payment state.

| Column | Type | Default | Notes |
|--------|------|---------|-------|
| `id` | INT PRIMARY KEY | Auto-increment | |
| `chat_id` | TEXT UNIQUE | — | Telegram user ID |
| `username` | TEXT | NULL | Telegram username |
| `active` | INT | `1` | Soft delete (0 = unsubscribed) |
| `plan` | TEXT | `'free'` | Subscription plan: `'free'`, `'monthly'`, `'yearly'` |
| `subscribed_at` | TIMESTAMP | Now | Time of subscription (trial start for time-based trials) |
| `expires_at` | TIMESTAMP | NULL | When paid subscription expires (NULL for free) |
| `star_charge_id` | TEXT | NULL | Telegram payment charge ID for recurring subscription cancellation |
| `messages_received` | INT | `0` | Count of messages delivered while on free trial (reset to 0 on resubscribe) |
| `message_sent_last_date` | TIMESTAMP | NULL | created_date of last message sent to this subscriber |
| `trial_notice_sent` | INT | `0` | Guard flag: `1` = trial-ended notice already sent |

### `messages`
Job vacancy messages from the parser.

| Column | Type | Notes |
|--------|------|-------|
| `id` | INT PRIMARY KEY | |
| `description` | TEXT | HTML-stripped job description |
| `tg_channel_link` | TEXT | Source channel link |
| `tg_message_link` | TEXT UNIQUE | Original message URL |
| `created_date` | TIMESTAMP | When job was posted |
| `source` | TEXT | Job board source |
| `queue_sent` | INT | Broadcast status (0 = pending, 1 = sent) |
| `read` | INT | Read status |
| `matched_keywords` | JSONB | Array of matching keyword groups |

### `filters`
Subscriber-defined filters for receiving only relevant job postings.

| Column | Type | Notes |
|--------|------|-------|
| `id` | INT PRIMARY KEY | |
| `subscriber_id` | INT | References subscribers(id) |
| `name` | VARCHAR(255) | Filter name (e.g., "Python Backend") |
| `type` | VARCHAR(10) | `'json'` or `'file'` |
| `extra` | TEXT | Filter config (JSON rules or file path) |
| `created_at` | TIMESTAMP | When filter was created |

### `subscriber_filters`
Junction table: which filters does each subscriber have?

| Column | Type | Notes |
|--------|------|-------|
| `id` | INT PRIMARY KEY | |
| `subscriber_id` | INT | References subscribers(id) |
| `filter_id` | INT | References filters(id) |
| `created_at` | TIMESTAMP | When filter was added to subscriber |

### `bot_state`
Persistent state for the bot.

| Column | Type | Notes |
|--------|------|-------|
| `key` | TEXT PRIMARY KEY | State key (e.g., `'last_update_id'`) |
| `value` | TEXT | State value |

### `bot_settings`
Trial configuration and pricing settings.

| Column | Type | Notes |
|--------|------|-------|
| `id` | INT PRIMARY KEY | Always 1 (singleton) |
| `stars_price_monthly` | INT | Price in Telegram Stars for monthly subscription |
| `stars_price_yearly` | INT | Price in Telegram Stars for yearly subscription |
| `trial_type` | TEXT | `'messages'` (count-based) or `'days'` (time-based) |
| `trial_message_limit` | INT | Max free messages (if `trial_type='messages'`) |
| `trial_days` | INT | Free trial duration in days (if `trial_type='days'`) |

### `payments`
Audit log of all payments (for idempotency and accounting).

| Column | Type | Notes |
|--------|------|-------|
| `id` | INT PRIMARY KEY | Auto-increment |
| `chat_id` | TEXT | Telegram user ID |
| `plan` | TEXT | Plan purchased: `'monthly'` or `'yearly'` |
| `amount` | INT | Telegram Stars charged |
| `provider` | TEXT | Payment provider (currently `'stars'`, stub for future Stripe, etc.) |
| `telegram_payment_charge_id` | TEXT UNIQUE | Telegram charge ID; uniqueness guard against duplicate processing |
| `is_recurring` | INT | `1` if auto-renewing (monthly), `0` if one-time (yearly) |
| `created_at` | TIMESTAMP | When payment was recorded |

## Usage

### Start the bot

```bash
python bot/main.py
```

Or with custom config:
```bash
BOT_TOKEN=your_token DB_DSN=postgresql://... python bot/main.py
```

### User Commands (in Telegram)

Send any of these to the bot:

- `/start` — Subscribe to job postings (free, trial period applies)
- `/subscribe` — Alias for `/start`
- `/stop` — Unsubscribe and clear pending messages (fresh quota on next `/subscribe`)
- `/unsubscribe` — Alias for `/stop`
- `/upgrade` — View subscription plans (Monthly ⭐100 / Yearly ⭐1000) and purchase via Telegram Stars
- `/cancel` — Cancel auto-renewal of monthly subscription (access continues until expiry)
- `/filters` — List your configured message filters (if any)
- `/updates` — Manually fetch and view pending job messages from cache
- `/help` — Show available commands

#### Payment Flow

1. User sends `/upgrade`
2. Bot shows inline menu: "Monthly ⭐100" and "Yearly ⭐1000"
3. **Monthly plan**: User taps button → Bot creates invoice link, sends message with "Pay ⭐100/month" button → User taps button → Telegram payment sheet
4. **Yearly plan**: User taps button → Bot sends in-chat invoice directly → Telegram payment sheet
5. User confirms payment with their Telegram Stars balance
6. Bot receives payment webhook and activates the plan:
   - **Monthly**: Auto-renewing via Telegram (30-day cycle), user can `/cancel` to stop renewal
   - **Yearly**: One-time payment, covers 365 days, manual renewal required via `/upgrade`

#### Trial Period

Free subscribers start with a trial. Once expired, they stop receiving messages and see a one-time notice to `/upgrade`.

- **Message-based trial** (default): First 10 messages delivered, then locked out
- **Time-based trial**: First 2 days of subscription, then locked out
- **Switch modes**: Change `TRIAL_TYPE` env var to `"messages"` or `"days"` (no code changes needed)

## Development

### Running Tests

```bash
python3 -m pytest tests/ -v
```

Test coverage (40 tests):
- `test_db.py`: Subscriber management, payments, trial tracking, message counting, schema migration, connection resilience
- `test_sender.py`: Message formatting, invoicing, invoice links, pre-checkout handling, menu rendering
- `test_updates.py`: Command parsing, payment flow, idempotency, upgrade/cancel logic
- `test_trial.py`: Trial gating logic (message-based and time-based)

### Project Structure

```
bot/
├── main.py              # Main event loop (polling + broadcasting + trial gating)
├── sender.py            # Telegram Bot API (messages, invoices, payments, menus)
├── updates.py           # Command handler (text, callbacks, payments, pre-checkout)
├── trial.py             # Trial gating logic (pure function, no I/O)
├── config.py            # Environment configuration
└── db/
    ├── base.py          # Abstract driver interface
    ├── postgres.py      # PostgreSQL implementation
    ├── sqlite.py        # SQLite implementation
    └── mysql.py         # MySQL implementation
tests/
├── test_sender.py       # Telegram API methods
├── test_updates.py      # Command & payment handling
├── test_db.py           # Database operations
└── test_trial.py        # Trial gating logic
```

## Troubleshooting

### Bot not receiving commands
- Verify `BOT_TOKEN` is valid (check with `curl https://api.telegram.org/bot$BOT_TOKEN/getMe`)
- Ensure database is accessible (`DB_DSN`)
- Check logs for "Started. driver=..." message
- Watch for "Error handling update" logs

### Subscribers not receiving messages
- Confirm they ran `/start` or `/subscribe`
- Check `subscribers.active=1` in database
- Verify `messages.queue_sent=0` on pending jobs
- Check Telegram API rate limits (default 0.5s delay between sends)

### Bot reprocesses old updates after restart
- Delete the `bot_state` row where `key='last_update_id'` to reset
- Bot persists offset to prevent re-handling commands after restart

### Subscriber unsubscribed then resubscribed, but still got old messages
- `/stop` now clears the Redis cache (`pending:{chat_id}`) — old messages should not appear on resubscribe
- Check Redis: `redis-cli SMEMBERS pending:{chat_id}` should be empty after `/stop`
- If not empty: redis may not be connected during unsubscribe; restart the bot to reconnect
- On resubscribe (`/subscribe`), `messages_received` is reset to 0, giving a fresh trial quota

### "No active subscribers" but messages are marked sent
- By design: bot marks message sent if delivered to any subscriber
- If all subscriber sends fail, message is still counted as sent (to avoid retries)

### Free subscriber not receiving messages after N deliveries
- Check `TRIAL_TYPE` and limits: `TRIAL_TYPE=messages` with `TRIAL_MESSAGE_LIMIT=10` means 10 free messages
- Verify `subscribers.messages_received >= 10` and `trial_notice_sent=1` in database
- Trial gating is independent of plan: even `plan='free'` subscribers can receive messages while `is_trial_active()` returns `True`
- The delivery loop caps messages per pass: if subscriber has 3/10 quota used, only 7 more messages are sent this pass

### Subscriber received more messages than quota allows
- This should not happen (bot caps delivery to remaining quota)
- If it does: check that the matcher repo's `cache/publisher.py` is not updating `messages_received` (removed in recent refactor)
- Only `bot/main.py` should update `messages_received` after actual delivery

### Subscriber stopped receiving after their subscription expired
- Check `subscribers.plan` (should be downgraded to `'free'` by the expiry sweep)
- Verify `subscribers.expires_at < now()` triggered the downgrade
- Look for "trial-ended notice" or expiry message sent to that chat_id in logs

### Payment webhook not processed (user paid but plan not activated)
- Check `payments` table for duplicate `telegram_payment_charge_id` — the bot dropped the second update due to idempotency
- Telegram may redeliver the same update multiple times; the UNIQUE constraint on charge_id prevents double-charging
- Subscriber's `plan` should still be activated from the first delivery

### Switching from message-based to time-based trial (or vice versa)
- No database migration needed: change `TRIAL_TYPE` env var and restart
- Active subscribers' `subscribed_at` and `messages_received` are both preserved
- Next broadcast loop will apply the new trial logic (old message counts are ignored if `TRIAL_TYPE=days`)

## Paid Subscriptions via Telegram Stars

The bot integrates with Telegram's native payment system (Telegram Stars, currency `XTR`). No external payment provider account or SDK needed.

### How It Works

1. **Payment Processing**: When a user sends `/upgrade` and confirms payment, Telegram sends a `successful_payment` webhook update
2. **Idempotency**: Payment charge IDs are stored in the `payments` table with a UNIQUE constraint — duplicate webhook deliveries are safely ignored
3. **Plan Activation**: Upon successful payment, `subscribers.plan` is set to `'monthly'` or `'yearly'` and `expires_at` is computed
4. **Monthly (Auto-Renew)**: Telegram's `subscription_period=2592000` (30 days) — Telegram itself re-charges every 30 days and fires a fresh `successful_payment`. User can `/cancel` to turn off auto-renewal
5. **Yearly (Manual)**: One-time payment with 365-day coverage. User must `/upgrade` again to renew
6. **Expiry Handling**: Main loop calls `downgrade_expired_subscribers()` each iteration — any paid plan past its `expires_at` is downgraded to `'free'` and the user gets a one-time expiry notice

### Future Payment Methods

The `payments.provider` column is a forward-compatibility stub (currently always `'stars'`). To add Stripe or another provider:
- Implement a new webhook handler for that provider
- Insert rows into `payments` with `provider='stripe'` (or similar)
- No schema migration needed — the table is agnostic to payment method

## License

Part of the Vacancier job board aggregator.
