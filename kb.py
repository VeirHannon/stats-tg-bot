import os
import json
import hashlib
import secrets
import sqlite3
import logging
from datetime import datetime

import telebot
from telebot import types

# Bot token is read from the environment. Never hard-code secrets in source.
#   Linux/macOS: export BOT_TOKEN="123456:ABC..."
#   Windows:     set BOT_TOKEN=123456:ABC...
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is not set.")

DB_PATH = os.environ.get("DB_PATH", "db.db")

bot = telebot.TeleBot(BOT_TOKEN)

# Internal diagnostics go to the logger, not to end users / stdout.
logger = logging.getLogger(__name__)

json_array = []


def remove_markup(message):
    markup = types.ReplyKeyboardRemove()
    bot.send_message(message.chat.id, "Keyboard removed.", reply_markup=markup)


def delete_last_messages(message, n):
    for i in range(n):
        bot.delete_message(message.chat.id, message.message_id - i)


def verify_password(password, hashed_password, salt):
    """Compare a plaintext password against a stored sha256(password + salt) hash."""
    password_salt = password + salt
    hashed_password_check = hashlib.sha256(password_salt.encode()).hexdigest()
    return hashed_password_check == hashed_password


def hash_password(password, salt):
    """Return sha256(password + salt) as a hex digest."""
    return hashlib.sha256((password + salt).encode()).hexdigest()


def init_db(db_path=None):
    """Create the database schema if needed and seed default users on first run.

    Safe to call on every startup: tables are created with IF NOT EXISTS and the
    default users are only inserted when the `users` table is empty. Two accounts
    are seeded for testing:

        login "admin" / password "admin"  (role Admin)
        login "jun"   / password "jun"    (role Junior)

    Change or remove these before using the bot for anything real.
    """
    path = db_path or DB_PATH
    conn = sqlite3.connect(path)
    c = conn.cursor()

    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            login        TEXT,
            password     TEXT,
            salt         TEXT,
            role         TEXT,
            faculty      INTEGER,
            published    INTEGER,
            publishedinf INTEGER
        );
        CREATE TABLE IF NOT EXISTS credentials (
            login        TEXT,
            faculty      INTEGER,
            published    INTEGER,
            publishedinf INTEGER,
            role         TEXT DEFAULT 'Junior'
        );
        CREATE TABLE IF NOT EXISTS logined (
            user_id    INTEGER PRIMARY KEY,
            username   TEXT,
            role       TEXT,
            start_sent INTEGER
        );
        CREATE TABLE IF NOT EXISTS reports (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            date      TEXT,
            login     TEXT,
            created   INTEGER,
            published INTEGER,
            category  TEXT
        );
        CREATE TABLE IF NOT EXISTS work_data (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            login        TEXT    NOT NULL,
            date         TEXT    NOT NULL,
            publishedinf INTEGER NOT NULL,
            published    INTEGER NOT NULL
        );
        """
    )

    c.execute("SELECT COUNT(*) FROM users")
    if c.fetchone()[0] == 0:
        defaults = [
            ("admin", "admin", "Admin", 1),
            ("jun", "jun", "Junior", 1),
        ]
        for login, password, role, faculty in defaults:
            salt = secrets.token_hex(16)
            c.execute(
                "INSERT INTO users (login, password, salt, role, faculty, published, publishedinf) "
                "VALUES (?, ?, ?, ?, ?, 0, 0)",
                (login, hash_password(password, salt), salt, role, faculty),
            )
        logger.info("Seeded default users: admin/admin (Admin), jun/jun (Junior).")

    conn.commit()
    conn.close()


def check_login_password(db_path: str, username: str, password: str):
    """Authenticate a user against hashed credentials stored in the database.

    Expects the `users` table to hold `password` (sha256 hash) and `salt`
    columns rather than a plaintext password.
    """
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT password, salt FROM users WHERE login=?", (username,)
        )
        result = cursor.fetchone()
        conn.close()

        if result is None:
            return False

        hashed_password, salt = result
        return verify_password(password, hashed_password, salt or "")

    except sqlite3.Error as e:
        logger.error("Error checking login and password: %s", e)
        return False


def check_faculty(login):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("SELECT faculty FROM users WHERE login=?", (login,))
    result = c.fetchone()

    conn.close()

    if result:
        return result[0]
    else:
        return None


def get_role_by_login(login):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT role FROM users WHERE login=?", (login,))
    row = c.fetchone()
    if row:
        return row[0]
    return None


def add_published(login, published):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("UPDATE credentials SET published = ? WHERE login = ?", (published, login))

    conn.commit()
    conn.close()


def check_user_exists(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM logined WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result is not None


def add_publishedinf(login, publishedinf):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE credentials SET publishedinf = ? WHERE login = ?", (publishedinf, login))
    conn.commit()
    conn.close()


def generate_report():
    now = datetime.now()
    date_time = now.strftime("%Y-%m-%d")

    report_text = f"Date - {date_time}\n"
    report_text += "Login - created - published\n"
    report_text += "\n"

    conn = sqlite3.connect(DB_PATH)

    for faculty in ("4", "3", "2", "1"):
        report_text += f"F{faculty}:\n"
        for row in conn.execute(
            "SELECT login, published, publishedinf FROM credentials "
            "WHERE role = 'Junior' AND faculty = ?",
            (faculty,),
        ):
            published = row[1] if row[1] is not None else 0
            publishedinf = row[2] if row[2] is not None else 0
            report_text += f"{row[0]} - {publishedinf} - {published}\n"
        report_text += "\n"

    published = 0
    for row in conn.execute("SELECT published FROM credentials WHERE role = 'Junior'"):
        published += row[0] if row[0] is not None else 0

    publishedinf = 0
    for row in conn.execute("SELECT publishedinf FROM credentials WHERE role = 'Junior'"):
        publishedinf += row[0] if row[0] is not None else 0

    report_text += f"\nTotal work created: {publishedinf}"
    report_text += f"\nTotal work published: {published}"
    conn.close()

    return report_text


def delete_monthly_archives(db_path: str):
    """Delete monthly archives from the database if it's the 1st day of the month."""
    now = datetime.now()
    if now.day == 1:
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM work_data WHERE created_at < ?", (now.replace(day=1),))
            conn.commit()
            conn.close()
        except sqlite3.Error as e:
            logger.error("Error deleting archives: %s", e)
    else:
        logger.debug("Not the 1st day of the month, skipping archive deletion.")


def get_reports_from_file():
    try:
        with open('Otchet.json', 'r') as file:
            otchet = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        otchet = []
    return otchet


def clear_file(filename):
    with open(filename, "w") as file:
        pass


def clear_credentials():
    current_time = datetime.now().time()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    if current_time.hour == 0 and current_time.minute == 0:
        cursor.execute("DELETE FROM credentials")
        conn.commit()
        logger.info("Credentials table cleared successfully.")
    else:
        logger.debug("Current time is not 00:00. Credentials not cleared.")

    conn.close()


def parse_and_insert_report(report_text):
    lines = report_text.strip().split('\n')
    date_line = lines[0]
    date = date_line.split(' - ')[1].strip()

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Remove all data for this date before inserting the new data
    cursor.execute('DELETE FROM reports WHERE date=?', (date,))

    category = None
    for line in lines[2:]:
        if line.endswith(':'):
            category = line[:-1]
        elif '-' in line:
            parts = line.split(' - ')
            login = parts[0].strip()
            created = int(parts[1].strip())
            published = int(parts[2].strip())
            cursor.execute('''
                INSERT INTO reports (date, login, created, published, category)
                VALUES (?, ?, ?, ?, ?)
            ''', (date, login, created, published, category))

    conn.commit()
    conn.close()


def read_from_db(day=None, month=None):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Build the SQL query depending on which of day/month are provided
    if day is not None and month is not None:
        cursor.execute('''
            SELECT date, login, created, published, category FROM reports
            WHERE strftime('%d', date) = ? AND strftime('%m', date) = ?
        ''', (f'{day:02}', f'{month:02}'))
    elif month is not None:
        cursor.execute('''
            SELECT date, login, created, published, category FROM reports
            WHERE strftime('%m', date) = ?
        ''', (f'{month:02}',))
    else:
        cursor.execute('''
            SELECT date, login, created, published, category FROM reports
        ''')

    rows = cursor.fetchall()

    if not rows:
        conn.close()
        if day is not None and month is not None:
            return f"No report for {day:02}.{month:02}"
        elif month is not None:
            return f"No report for month {month:02}"
        else:
            return "No data"

    report_dict = {}
    total_created = 0
    total_published = 0
    date = rows[0][0]  # Assume all records share the same date

    for row in rows:
        _, login, created, published, category = row
        if category not in report_dict:
            report_dict[category] = []
        report_dict[category].append((login, created, published))
        total_created += created
        total_published += published

    report_text = f"Date - {date}\n\n"

    for category in sorted(report_dict.keys()):
        report_text += f"{category}:\n\n"
        for login, created, published in report_dict[category]:
            report_text += f"{login} - {created} - {published}\n"
        report_text += "\n"

    report_text += f"Total work created: {total_created}\n"
    report_text += f"Total work published: {total_published}\n"

    conn.close()
    return report_text


def add_credentials(login, faculty):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("SELECT * FROM credentials WHERE login = ? AND faculty = ?", (login, faculty))
    if c.fetchone() is None:
        c.execute(
            "INSERT INTO credentials (login, faculty, published, publishedinf) VALUES (?, ?, 0, 0)",
            (login, faculty),
        )

    conn.commit()
    conn.close()


def is_login_exists(login: str) -> bool:
    try:
        with open('credentials.json', 'r') as f:
            data = json.load(f)
            for user in data:
                if user["login"] == login:
                    return True
    except (FileNotFoundError, json.JSONDecodeError):
        return False
    return False


def create_logins_array():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT login FROM credentials")
    logins = c.fetchall()
    conn.close()
    if not logins:
        return []
    return [login[0] for login in logins]


def check_json_file():
    try:
        with open('credentials.json', 'r') as f:
            data = json.load(f)
            return bool(data)
    except (FileNotFoundError, json.JSONDecodeError):
        return False


def save_work_data(logins):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    now = datetime.now()
    date_time = now.strftime("%Y-%m-%d")

    # Delete existing data for the current date
    c.execute("DELETE FROM work_data WHERE date = ?", (date_time,))

    for login in logins:
        c.execute("SELECT published, publishedinf FROM credentials WHERE login = ?", (login,))
        cred = c.fetchone()
        if cred is None:
            logger.warning("Skipping %s: not present in credentials table", login)
            continue
        published = cred[0]
        publishedinf = cred[1]

        c.execute(
            "INSERT INTO work_data (login, date, publishedinf, published) VALUES (?, ?, ?, ?)",
            (login, date_time, publishedinf, published),
        )

    conn.commit()
    conn.close()


def display_work_data(message):
    user_id = message.from_user.id
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT username FROM logined WHERE user_id=?", (user_id,))
    login_row = c.fetchone()

    if login_row is None:
        conn.close()
        return "You are not logged in."

    login = str(login_row[0])
    c.execute(
        "SELECT date, publishedinf, published FROM work_data WHERE login = ? ORDER BY date DESC",
        (login,),
    )
    data = c.fetchall()
    conn.close()

    if not data:
        return "No statistics yet."

    output = f"Login: {login}\n"

    for item in data:
        date, publishedinf, published = item
        output += f"Date: {date}\n"
        output += f"Created: {publishedinf}\n"
        output += f"Published: {published}\n\n"

    return output


def display_work_data_by_login(login):
    """Return a work-data summary for an arbitrary login (used by supervisors)."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT date, publishedinf, published FROM work_data WHERE login = ? ORDER BY date DESC",
        (login,),
    )
    data = c.fetchall()
    conn.close()

    if not data:
        return None

    output = f"Login: {login}\n"
    for date, publishedinf, published in data:
        output += f"Date: {date}\n"
        output += f"Created: {publishedinf}\n"
        output += f"Published: {published}\n\n"

    return output


def is_time_2359():
    now = datetime.now()
    return now.hour == 23 and now.minute == 59


def get_faculty_logins(faculty):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    query = "SELECT login FROM users WHERE faculty = ? AND role = ?"
    cursor.execute(query, (faculty, 'Junior'))
    logins = [row[0] for row in cursor.fetchall()]

    cursor.close()
    conn.close()

    return logins


def is_user_on_shift(user_id):
    """Return True if the user is currently on shift (has a credentials entry)."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Look up the user's login by their ID
    query = "SELECT username FROM logined WHERE user_id = ?"
    cursor.execute(query, (user_id,))
    login_row = cursor.fetchone()

    if login_row is None:
        cursor.close()
        conn.close()
        return False

    login = login_row[0]

    # Check whether the user is on shift
    query = "SELECT EXISTS(SELECT 1 FROM credentials WHERE login = ?)"
    cursor.execute(query, (login,))
    result = cursor.fetchone()[0]

    cursor.close()
    conn.close()

    return result


# Backwards-compatible alias for the old "on duty" name.
is_user_on_duty = is_user_on_shift
