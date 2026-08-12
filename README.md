# Statistics Control Telegram Bot

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
![Python](https://img.shields.io/badge/language-python-blue)

A Telegram bot for tracking work reports across a small team. Users log in with a
role (Junior / Mid / Admin), start a shift, submit how much work they processed,
and view their statistics. Supervisors can generate reports, browse per-junior
archives, and look up daily report history.

This started as an old university project and is shared as-is, in case the
structure is useful to someone building a similar reporting bot.

## Features

- Role-based menus (Junior submit their own work; Mid/Admin review and report)
- Daily work snapshots and automatic monthly archive cleanup
- Per-department (faculty) junior archives
- Salted sha256 password storage

## Requirements

- Python 3.8+
- A Telegram bot token from [@BotFather](https://t.me/BotFather)

## Setup

1. Clone the repo and install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

2. Provide your bot token via environment variable:

   ```bash
   export BOT_TOKEN="123456:your-token-here"     # Linux/macOS
   set BOT_TOKEN=123456:your-token-here           # Windows
   ```

   Optionally set DB_PATH if you want the database somewhere other than `db.db`.

3. Run the bot:

   ```bash
   python admin.py
   ```

On first run the database is created automatically and seeded with two test
accounts:

| Login   | Password | Role   |
|---------|----------|--------|
| admin | admin  | Admin  |
| jun   | jun    | Junior |

Change or remove these before using the bot for anything real. A `schema.sql`
file is also included if you prefer to create the database manually.

## Passwords

Passwords are stored as sha256(password + salt) with a per-user random salt in
the users table. New users should be added with a hashed password - see
hash_password in kb.py.

## Project structure

| File                       | Purpose                                            |
|----------------------------|----------------------------------------------------|
| admin.py                 | Bot entry point, handlers, menu flow               |
| kb.py                    | Database helpers, schema init, shared bot instance |
| schema.sql               | Database schema (optional manual setup)            |
| credentials.example.json | Example structure for credentials.json           |

## Notes / possible improvements

- User session state is kept in module-level globals, which is not safe for many
  concurrent users. A per-user state store keyed by Telegram user_id would be a
  natural next step.
- credentials.json is only used by a couple of helper functions; most data lives
  in the SQLite database.

## License

MIT
