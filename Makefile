.PHONY: install run init-db

install:
	pip install -r requirements.txt

run:
	python -m bot.main

init-db:
	sqlite3 messages.db "CREATE TABLE IF NOT EXISTS messages ( \
		id              INTEGER PRIMARY KEY AUTOINCREMENT, \
		description     TEXT NOT NULL, \
		tg_channel_link TEXT NOT NULL, \
		tg_message_link TEXT NOT NULL UNIQUE, \
		created_date    TEXT NOT NULL, \
		queue_sent      INTEGER NOT NULL DEFAULT 0, \
		read            INTEGER NOT NULL DEFAULT 0 \
	);"
