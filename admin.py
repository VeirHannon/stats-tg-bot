import time
import logging
import threading

import telebot
from telebot import types

import kb
from kb import *
from kb import bot

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def background_worker():
    """Periodic maintenance loop: snapshot work data, roll reports, clean up."""
    while True:
        try:
            logins = create_logins_array()
            save_work_data(logins)
            report = generate_report()
            parse_and_insert_report(report)
            delete_monthly_archives(DB_PATH)
            clear_credentials()
        except Exception as e:
            logger.error("Background worker error: %s", e)
        time.sleep(60)


def main():
    init_db()
    thread = threading.Thread(target=background_worker, daemon=True)
    thread.start()
    while True:
        try:
            bot.polling(none_stop=True)
        except Exception as e:
            logger.error("Polling error: %s", e)
            time.sleep(15)


# Month labels shown to the user. Index + 1 == month number.
months = [
    'January',
    'February',
    'March',
    'April',
    'May',
    'June',
    'July',
    'August',
    'September',
    'October',
    'November',
    'December',
]


@bot.message_handler(commands=['start'])
def start(message):
    starting(message)


@bot.message_handler(commands=['logout'])
def logout(message):
    markup = types.ReplyKeyboardRemove()
    user_id = message.from_user.id
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM logined WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()
    bot.send_message(message.chat.id, "You have been logged out.", reply_markup=markup)
    starting(message)


def check_login(message):
    """Return (logined, role) for the given message's user."""
    user_id = message.from_user.id
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT role FROM logined WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    if result:
        return True, result[0]
    return False, None


def starting(message):
    logined, role = check_login(message)
    if not logined:
        bot.register_next_step_handler(message, get_login)
        bot.send_message(message.from_user.id, "Enter your login:")
    else:
        role_check(role, message)


def role_check(role, message):
    if role == "Junior":
        user_id = message.from_user.id
        if is_user_on_shift(user_id):
            JuniorMain2(message)
        else:
            JuniorMain(message)
    elif role in ("Mid", "Admin"):
        MidMain(message)


def get_login(message):
    global Login
    Login = message.text
    if Login == "/start":
        start(message)
    else:
        bot.register_next_step_handler(message, get_pass, Login)
        bot.send_message(message.from_user.id, "Now enter your password:")


def get_pass(message, Login):
    if message.text == "/start":
        start(message)
        return

    global FacultyNum, user_data
    user_data = {}
    FacultyNum = str(check_faculty(Login))
    Pass = message.text
    authenticated = check_login_password(DB_PATH, Login, Pass)
    role = get_role_by_login(Login)
    faculty = "F" + str(check_faculty(Login))

    if authenticated:
        bot.send_message(message.from_user.id, f'{Login} - {role} - {faculty}')
        user_id = message.from_user.id
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO logined (user_id, username, role)
            VALUES (?, ?, ?)
        ''', (user_id, Login, role))
        conn.commit()
        conn.close()
        MainProg(message, role, Login)
    else:
        bot.send_message(message.from_user.id, "Invalid login or password.")
        starting(message)


def MainProg(message, role, Login):
    if role == "Junior":
        user_id = message.from_user.id
        if is_user_on_shift(user_id):
            JuniorMain2(message)
        else:
            JuniorMain(message)
    elif role in ("Mid", "Admin"):
        MidMain(message)


# ---------------------------------------------------------------------------
# Junior flow
# ---------------------------------------------------------------------------

def JuniorMain(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(
        types.KeyboardButton("Start shift"),
        types.KeyboardButton("Log out"),
    )
    bot.send_message(message.chat.id, "Choose an action", reply_markup=markup)
    bot.register_next_step_handler(message, JuniorShiftMenu)


def JuniorShiftMenu(message):
    if message.text == "Start shift":
        user_id = message.from_user.id
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT username FROM logined WHERE user_id=?", (user_id,))
        login_row = c.fetchone()
        conn.close()
        if login_row is None:
            bot.send_message(message.from_user.id, "You are not logged in.")
            starting(message)
            return
        login = str(login_row[0])
        faculty = check_faculty(login)
        add_credentials(login, faculty)
        JuniorMain2(message)
    elif message.text in ("Log out", "/logout"):
        logout(message)
    elif message.text == "/start":
        start(message)


def JuniorMain2(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(
        types.KeyboardButton("Submit report"),
        types.KeyboardButton("My statistics"),
        types.KeyboardButton("Log out"),
    )
    bot.send_message(message.chat.id, "Choose an action", reply_markup=markup)
    bot.register_next_step_handler(message, JuniorReportMenu)


def JuniorReportMenu(message):
    if message.text == "Submit report":
        bot.send_message(message.from_user.id, "Enter the amount of work you processed:")
        bot.register_next_step_handler(message, JuniorReportSubmit)
    elif message.text == "My statistics":
        statistics = display_work_data(message)
        bot.send_message(message.from_user.id, statistics)
        JuniorMain2(message)
    elif message.text == "/start":
        start(message)
    elif message.text in ("Log out", "/logout"):
        logout(message)


def JuniorReportSubmit(message):
    global user_data
    try:
        published_inf = int(message.text)
    except ValueError:
        bot.send_message(message.from_user.id, "The amount of work must be a number.")
        JuniorMain2(message)
        return

    user_id = message.from_user.id
    if check_user_exists(user_id):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT username FROM logined WHERE user_id=?", (user_id,))
        login_row = cursor.fetchone()
        conn.close()
        login = str(login_row[0])
        add_publishedinf(login, published_inf)
        bot.send_message(message.from_user.id, f'{login} - {published_inf}')
        JuniorMain2(message)
    else:
        bot.send_message(message.from_user.id, "Something went wrong, please try again.")
        JuniorMain2(message)


# ---------------------------------------------------------------------------
# Mid / Admin flow
# ---------------------------------------------------------------------------

def MidMain(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.row(
        types.KeyboardButton("Juniors"),
        types.KeyboardButton("Generate report"),
    )
    markup.row(
        types.KeyboardButton("Daily report archive"),
        types.KeyboardButton("Junior report archive"),
    )
    markup.row(types.KeyboardButton("Log out"))
    bot.send_message(message.chat.id, "Choose an action", reply_markup=markup)
    bot.register_next_step_handler(message, handle_text)


def handle_text(message):
    if message.text == "Juniors":
        logins = create_logins_array()
        buttons = [types.KeyboardButton(login) for login in logins]
        JuniorsMid(message, buttons)
    elif message.text == "Generate report":
        bot.send_message(message.from_user.id, generate_report())
        MidMain(message)
    elif message.text == "Daily report archive":
        Archive(message)
    elif message.text == "Junior report archive":
        JuniorArchiveAdmin(message)
    elif message.text == "Back":
        MidMain(message)
    elif message.text in ("Log out", "/logout"):
        logout(message)
    elif message.text == "/start":
        start(message)


def JuniorsMid(message, buttons):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(*buttons, types.KeyboardButton("Back"))
    bot.send_message(message.from_user.id, "Choose a junior", reply_markup=markup)
    bot.register_next_step_handler(message, publish_temp)


def publish_temp(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    login = message.text
    if login == "Back":
        MidMain(message)
    elif message.text == "/start":
        start(message)
    elif message.text == "/logout":
        logout(message)
    else:
        bot.send_message(
            message.chat.id,
            "Enter the amount of work processed by this junior",
            reply_markup=markup,
        )
        bot.register_next_step_handler(message, publish, login)


def JuniorArchiveAdmin(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.row(
        types.KeyboardButton("Department 1"),
        types.KeyboardButton("Department 2"),
    )
    markup.row(
        types.KeyboardButton("Department 3"),
        types.KeyboardButton("Department 4"),
    )
    bot.send_message(message.chat.id, "Choose a department:", reply_markup=markup)
    bot.register_next_step_handler(message, JuniorArchiveAdmin2)


def JuniorArchiveAdmin2(message):
    if message.text == "/start":
        start(message)
        return

    faculty_map = {
        "Department 1": "1",
        "Department 2": "2",
        "Department 3": "3",
        "Department 4": "4",
    }
    faculty = faculty_map.get(message.text)
    if faculty is None:
        MidMain(message)
        return

    names = get_faculty_logins(faculty)
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(*create_buttons(names), types.KeyboardButton("Back"))
    bot.send_message(message.from_user.id, "Choose a junior", reply_markup=markup)
    bot.register_next_step_handler(message, JuniorArchiveCheck)


def JuniorArchiveCheck(message):
    if message.text == "Back":
        MidMain(message)
    elif message.text == "/start":
        start(message)
    else:
        junior_login = message.text
        info = display_work_data_by_login(junior_login)
        if info:
            bot.send_message(message.from_user.id, info)
        else:
            bot.send_message(message.from_user.id, "No report available for the selected junior.")
        MidMain(message)


def create_buttons(items):
    return [types.KeyboardButton(item) for item in items]


def create_buttonsday(days):
    return [types.KeyboardButton(str(day)) for day in days]


def Archive(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(*create_buttons(months), types.KeyboardButton("Back"))
    bot.send_message(message.from_user.id, "Choose a month", reply_markup=markup)
    bot.register_next_step_handler(message, handle_archive)


def handle_archive(message):
    if message.text == "/start":
        start(message)
    else:
        Archivefunc(message)


def Archivefunc(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    month = message.text
    if month == "Back":
        MidMain(message)
        return
    if message.text == "/start":
        start(message)
        return
    if month not in months:
        MidMain(message)
        return

    month_index = months.index(month) + 1
    if month_index in (1, 3, 5, 7, 8, 10, 12):
        days = 31
    elif month_index == 2:
        days = 29
    else:
        days = 30

    btn_days = create_buttonsday(range(1, days + 1))
    markup.add(*btn_days)
    markup.row(types.KeyboardButton("Back"))
    bot.send_message(message.from_user.id, "Choose a day", reply_markup=markup)
    bot.register_next_step_handler(message, read_archive_day, month_index)


def read_archive_day(message, month_index):
    if message.text == "Back":
        MidMain(message)
    elif message.text == "/start":
        start(message)
    else:
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        day = int(message.text)
        report = read_from_db(day, month_index)
        bot.send_message(message.from_user.id, report, reply_markup=markup)
        MidMain(message)


def publish_again(message, login):
    bot.send_message(message.chat.id, "Enter the amount of work processed by this junior")
    bot.register_next_step_handler(message, publish, login)


def publish(message, login):
    try:
        amount = int(message.text)
        bot.send_message(message.from_user.id, f'{login} - {amount}')
        add_published(login, amount)
        MidMain(message)
    except ValueError:
        bot.send_message(message.from_user.id, "The amount of work must be a number.")
        publish_again(message, login)


if __name__ == "__main__":
    main()
