# Vacancier Telegram Bot

A multi-user Telegram bot that broadcasts job vacancy postings to subscribers. Users can subscribe to receive job postings, with support for future billing tiers built in.

## Features

- **Multi-user subscriptions**: Users `/subscribe` via Telegram to receive job postings; `/unsubscribe` to stop
- **Command-based management**: `/start`, `/subscribe`, `/stop`, `/unsubscribe`, `/help`
- **Multi-database support**: PostgreSQL, SQLite, MySQL
- **Forward-compatible billing**: `plan` column stubbed for future paid tiers
- **Persistent state**: Remembers Telegram update offset across restarts (no message duplication or missed commands)
- **Graceful shutdown**: Handles SIGINT/SIGTERM signals cleanly
- **Partial delivery tolerance**: Marks message sent if delivered to *any* active subscriber (not all-or-nothing)

## Architecture

The bot runs two parallel loops:

1. **Update polling**: Listens for incoming Telegram commands (`/subscribe`, `/unsubscribe`, `/help`)
2. **Message broadcasting**: Fetches pending job messages and sends them to all active subscribers

Each message is marked `queue_sent=1` only after being delivered to at least one active subscriber (graceful partial failure: if 3 of 4 subscribers fail, the message is still marked sent if it reached 1+).

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
Stores user subscriptions.

| Column | Type | Default | Notes |
|--------|------|---------|-------|
| `id` | INT PRIMARY KEY | Auto-increment | |
| `chat_id` | TEXT UNIQUE | — | Telegram user ID |
| `username` | TEXT | NULL | Telegram username |
| `active` | INT | `1` | Soft delete (0 = unsubscribed) |
| `plan` | TEXT | `'free'` | Reserved for future billing (unused now) |
| `subscribed_at` | TIMESTAMP | Now | |

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

### `bot_state`
Persistent state for the bot.

| Column | Type | Notes |
|--------|------|-------|
| `key` | TEXT PRIMARY KEY | State key (e.g., `'last_update_id'`) |
| `value` | TEXT | State value |

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

- `/start` — Subscribe to job postings
- `/subscribe` — Alias for `/start`
- `/stop` — Unsubscribe
- `/unsubscribe` — Alias for `/stop`
- `/help` — Show available commands

## Development

### Running Tests

```bash
python3 -m pytest tests/ -v
```

Test coverage:
- `test_db.py`: Subscriber management (add, remove, reactivate, persistence)
- `test_sender.py`: Message formatting and Telegram API calls

### Project Structure

```
bot/
├── main.py              # Main event loop (polling + broadcasting)
├── sender.py            # Telegram API sender
├── updates.py           # Incoming command handler
├── config.py            # Environment configuration
└── db/
    ├── base.py          # Abstract driver interface
    ├── postgres.py      # PostgreSQL implementation
    ├── sqlite.py        # SQLite implementation
    └── mysql.py         # MySQL implementation
tests/
├── test_sender.py       # Sender unit tests
└── test_db.py           # Database layer tests
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

### "No active subscribers" but messages are marked sent
- By design: bot marks message sent if delivered to any subscriber
- If all subscriber sends fail, message is still counted as sent (to avoid retries)

## Billing Integration (Future)

The `subscribers.plan` column is reserved for paid tiers. Example future integration:

```python
# Filter by plan tier
BILLABLE_PLANS = {'pro', 'team', 'enterprise'}
active = [s for s in driver.list_active_subscribers() 
          if get_plan(s) in BILLABLE_PLANS]
```

Currently all subscribers are treated equally (free tier).

## License

Part of the Vacancier job board aggregator.
