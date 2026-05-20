# Vacancier Telegram Bot

A Telegram bot that manages and distributes job vacancy messages to a Telegram channel. The bot polls a database for pending messages and sends them in batches at configurable intervals.

## Features

- **Database Agnostic**: Supports SQLite, PostgreSQL, and MySQL backends
- **Batch Processing**: Sends messages in configurable batches
- **Message Tracking**: Tracks which messages have been sent
- **Graceful Shutdown**: Handles SIGINT and SIGTERM signals
- **Docker Ready**: Includes Dockerfile for containerized deployment
- **Configurable**: All behavior controlled via environment variables

## Requirements

- Python 3.12+
- SQLite, PostgreSQL, or MySQL (depending on configuration)

## Installation

### Local Setup

1. Clone the repository and navigate to the bot directory:
```bash
cd vacancier-tg-bot
```

2. Install dependencies:
```bash
make install
# or
pip install -r requirements.txt
```r

3. Copy the environment template and configure it:
```bash
cp .env.example .env
```

4. Initialize the database (for SQLite):
```bash
make init-db
```

## Configuration

Create a `.env` file with the following variables:

### Required Variables

- `BOT_TOKEN`: Your Telegram bot token from [@BotFather](https://t.me/botfather)
- `CHAT_ID`: The Telegram channel/chat ID where messages will be sent (negative for channels)
- `DB_DSN`: Database connection string or path

### Optional Variables

- `DB_DRIVER`: Database backend (default: `sqlite`)
  - `sqlite`: Local SQLite database
  - `postgres`: PostgreSQL database
  - `mysql`: MySQL database
- `BATCH_SIZE`: Number of messages to send per batch (default: `10`)
- `POLL_INTERVAL_SEC`: Seconds between polls (default: `60`)
- `SEND_DELAY_SEC`: Delay between individual message sends in seconds (default: `0.5`)

### Example Configuration

**SQLite (local):**
```env
BOT_TOKEN=123456789:AABBccDDeeFFggHH
CHAT_ID=-1001234567890
DB_DRIVER=sqlite
DB_DSN=./messages.db
BATCH_SIZE=10
POLL_INTERVAL_SEC=60
SEND_DELAY_SEC=0.5
```

**PostgreSQL:**
```env
BOT_TOKEN=123456789:AABBccDDeeFFggHH
CHAT_ID=-1001234567890
DB_DRIVER=postgres
DB_DSN=postgres://user:password@localhost:5432/vacancies
```

**MySQL:**
```env
BOT_TOKEN=123456789:AABBccDDeeFFggHH
CHAT_ID=-1001234567890
DB_DRIVER=mysql
DB_DSN=mysql://user:password@localhost:3306/vacancies
```

## Database Schema

The bot expects a `messages` table with the following structure:

```sql
CREATE TABLE messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    description     TEXT NOT NULL,
    tg_channel_link TEXT NOT NULL,
    tg_message_link TEXT NOT NULL UNIQUE,
    created_date    TEXT NOT NULL,
    queue_sent      INTEGER NOT NULL DEFAULT 0,
    read            INTEGER NOT NULL DEFAULT 0
);
```

## Usage

### Running Locally

```bash
make run
# or
python -m bot.main
```

### Running with Docker

Build the image:
```bash
docker build -t vacancier-bot .
```

Run the container:
```bash
docker compose up
```

## Architecture

### Core Components

- **`bot/main.py`**: Main event loop that polls the database and orchestrates message sending
- **`bot/config.py`**: Loads and validates environment configuration
- **`bot/sender.py`**: Handles Telegram API communication
- **`bot/db/`**: Database abstraction layer with driver implementations
  - `base.py`: Abstract database interface
  - `sqlite.py`: SQLite driver
  - `postgres.py`: PostgreSQL driver
  - `mysql.py`: MySQL driver

### Workflow

1. Bot loads configuration from environment variables
2. Connects to configured database backend
3. Continuously polls database at configured interval for pending messages
4. Retrieves batch of pending messages (query filters by `queue_sent == 0`)
5. Sends each message to Telegram channel with delay between sends
6. Marks successfully sent messages in database (`queue_sent = 1`)
7. Logs all operations and errors

## Development

### Project Structure

```
vacancier-tg-bot/
├── bot/
│   ├── __init__.py
│   ├── main.py           # Main event loop
│   ├── config.py         # Configuration management
│   ├── sender.py         # Telegram sender
│   └── db/
│       ├── __init__.py
│       ├── base.py       # Abstract base class
│       ├── sqlite.py     # SQLite implementation
│       ├── postgres.py   # PostgreSQL implementation
│       └── mysql.py      # MySQL implementation
├── .env                  # Environment configuration (local only)
├── .env.example          # Configuration template
├── requirements.txt      # Python dependencies
├── Dockerfile            # Container definition
├── Makefile             # Development tasks
└── README.md            # This file
```

### Adding a New Database Driver

1. Create a new driver file in `bot/db/` (e.g., `sqlite.py`)
2. Inherit from `bot.db.base.DatabaseDriver`
3. Implement required methods:
   - `get_pending(batch_size)`: Retrieve pending messages
   - `mark_sent(message_ids)`: Mark messages as sent
   - `close()`: Close database connection
4. Register the driver in `bot/db/__init__.py`

## Troubleshooting

### Bot not sending messages
- Check that `BOT_TOKEN` is valid
- Verify `CHAT_ID` is correct and the bot has permissions to post
- Ensure database contains messages with `queue_sent = 0`
- Check logs for errors: `python -m bot.main`

### Database connection errors
- Verify `DB_DSN` is correct for your database type
- Ensure database server is running and accessible
- Check database user permissions

### Performance tuning
- Increase `BATCH_SIZE` to send more messages per poll cycle
- Decrease `POLL_INTERVAL_SEC` to check database more frequently
- Adjust `SEND_DELAY_SEC` to control API rate limiting

## License

MIT
