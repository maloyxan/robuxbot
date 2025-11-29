import re
import asyncio
import logging
import aiosqlite
from aiogram import Bot, Dispatcher, Router, F, types
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties 
from pyrogram import Client as PyroClient, enums
from pyrogram.errors import FloodWait, SessionPasswordNeeded, PhoneCodeInvalid, PasswordHashInvalid
from typing import Dict, Any, Tuple

# --- КОНФИГУРАЦИЯ ---
BOT_TOKEN = "8380230924:AAGY43fow1R-hZDOd11PgEISspIHhw-BHCg"  
ADMIN_IDS = [7834799163, 7623901324] 

API_ID = 25524964      
API_HASH = "cb400b2fd7148a0c4135f69b229d7f82" 

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Инициализация
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)

# Временное хранилище
active_setups: Dict[int, Dict[str, Any]] = {}
active_loops: Dict[int, asyncio.Task] = {}

# --- БАЗА ДАННЫХ ---
DB_NAME = "bot_database.db"

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                has_sub BOOLEAN DEFAULT 0
            )
        """)
        # !!! ОБНОВЛЕННАЯ СТРУКТУРА: + burst_mode, + cycle_delay !!!
        await db.execute("""
            CREATE TABLE IF NOT EXISTS mailing_settings (
                user_id INTEGER PRIMARY KEY,
                message_text TEXT,
                chats_list TEXT,
                delay_seconds INTEGER DEFAULT 5,
                is_cyclic BOOLEAN DEFAULT 0,
                burst_mode BOOLEAN DEFAULT 0,
                cycle_delay INTEGER DEFAULT 300
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                session_string TEXT,
                phone_number TEXT
            )
        """)
        await db.commit()
        
        # Миграции (добавление колонок, если старая БД)
        try:
            await db.execute("SELECT is_cyclic FROM mailing_settings LIMIT 1")
        except aiosqlite.OperationalError:
            await db.execute("ALTER TABLE mailing_settings ADD COLUMN is_cyclic BOOLEAN DEFAULT 0")
            await db.commit()
            
        try:
            await db.execute("SELECT burst_mode FROM mailing_settings LIMIT 1")
        except aiosqlite.OperationalError:
            await db.execute("ALTER TABLE mailing_settings ADD COLUMN burst_mode BOOLEAN DEFAULT 0")
            await db.execute("ALTER TABLE mailing_settings ADD COLUMN cycle_delay INTEGER DEFAULT 300")
            await db.commit()


# --- ФУНКЦИИ БД ---
async def check_subscription(user_id: int) -> bool:
    if user_id in ADMIN_IDS: return True
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT has_sub FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            return row is not None and row[0] == 1

async def add_user(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id, has_sub) VALUES (?, 0)", (user_id,))
        await db.execute("INSERT OR IGNORE INTO mailing_settings (user_id, message_text, chats_list, delay_seconds, is_cyclic, burst_mode, cycle_delay) VALUES (?, '', '', 5, 0, 0, 300)", (user_id,))
        await db.commit()

async def activate_sub(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET has_sub = 1 WHERE user_id = ?", (user_id,))
        await db.commit()

async def save_mailing_data(user_id: int, text: str = None, chats: str = None, delay: int = None, is_cyclic: bool = None, burst_mode: bool = None, cycle_delay: int = None):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR IGNORE INTO mailing_settings (user_id, message_text, chats_list, delay_seconds, is_cyclic, burst_mode, cycle_delay) VALUES (?, '', '', 5, 0, 0, 300)", (user_id,))
        
        if text is not None:
            await db.execute("UPDATE mailing_settings SET message_text = ? WHERE user_id = ?", (text, user_id))
        if chats is not None:
            await db.execute("UPDATE mailing_settings SET chats_list = ? WHERE user_id = ?", (chats, user_id))
        if delay is not None:
            await db.execute("UPDATE mailing_settings SET delay_seconds = ? WHERE user_id = ?", (delay, user_id))
        if is_cyclic is not None:
            await db.execute("UPDATE mailing_settings SET is_cyclic = ? WHERE user_id = ?", (int(is_cyclic), user_id))
        if burst_mode is not None:
            await db.execute("UPDATE mailing_settings SET burst_mode = ? WHERE user_id = ?", (int(burst_mode), user_id))
        if cycle_delay is not None:
            await db.execute("UPDATE mailing_settings SET cycle_delay = ? WHERE user_id = ?", (cycle_delay, user_id))
        await db.commit()

async def get_mailing_data(user_id: int) -> Tuple[str, str, int, bool, bool, int]:
    """Возвращает: text, chats, msg_delay, is_cyclic, burst_mode, cycle_delay"""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT message_text, chats_list, delay_seconds, is_cyclic, burst_mode, cycle_delay FROM mailing_settings WHERE user_id = ?", (user_id,)) as cursor:
            res = await cursor.fetchone()
            if not res:
                await db.execute("INSERT INTO mailing_settings (user_id, message_text, chats_list, delay_seconds, is_cyclic, burst_mode, cycle_delay) VALUES (?, '', '', 5, 0, 0, 300)", (user_id,))
                await db.commit()
                return ('', '', 5, False, False, 300)
            
            # Обработка NULL значений (на случай миграции)
            burst = bool(res[4]) if res[4] is not None else False
            c_delay = res[5] if res[5] is not None else 300
            
            return (res[0], res[1], res[2], bool(res[3]), burst, c_delay)

async def add_account(user_id: int, session_string: str, phone: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT INTO accounts (user_id, session_string, phone_number) VALUES (?, ?, ?)", 
                         (user_id, session_string, phone))
        await db.commit()

async def get_user_accounts(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT session_string FROM accounts WHERE user_id = ?", (user_id,)) as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

async def delete_all_accounts(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM accounts WHERE user_id = ?", (user_id,))
        await db.commit()

# --- FSM ---
class BotStates(StatesGroup):
    waiting_for_text = State()
    waiting_for_chats = State()
    waiting_for_delay = State()
    waiting_for_cycle_delay = State() # НОВОЕ СОСТОЯНИЕ
    
    login_phone = State()
    login_code = State()
    login_2fa = State()
    waiting_for_session_string = State()

# --- КЛАВИАТУРЫ ---
def get_main_menu():
    kb = [
        [KeyboardButton(text="⚙️ Настроить текст"), KeyboardButton(text="📋 Добавить чаты")],
        [KeyboardButton(text="⏱ Задержка (Смс)"), KeyboardButton(text="⏳ Задержка (Цикл)")], # ОБНОВЛЕНО
        [KeyboardButton(text="🔁 Цикл рассылки"), KeyboardButton(text="🚀 Запустить рассылку")],
        [KeyboardButton(text="👤 Добавить аккаунты"), KeyboardButton(text="ℹ️ Профиль")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def get_cycle_keyboard(is_cyclic: bool, burst_mode: bool):
    builder = InlineKeyboardBuilder()
    
    # Кнопка Цикличности
    cycle_text = "Цикл: ВЫКЛ ❌" if not is_cyclic else "Цикл: ВКЛ ✅"
    cycle_data = "cycle_on" if not is_cyclic else "cycle_off"
    builder.row(InlineKeyboardButton(text=cycle_text, callback_data=cycle_data))
    
    # Кнопка Burst Mode
    burst_text = "⚡️ Моментально: ВЫКЛ" if not burst_mode else "⚡️ Моментально: ВКЛ 🔥"
    burst_data = "burst_on" if not burst_mode else "burst_off"
    builder.row(InlineKeyboardButton(text=burst_text, callback_data=burst_data))
    
    return builder.as_markup()

def get_start_stop_keyboard(is_running: bool):
    builder = InlineKeyboardBuilder()
    if is_running:
        builder.add(InlineKeyboardButton(text="🔴 ОСТАНОВИТЬ ЦИКЛ", callback_data="stop_loop"))
    else:
        builder.add(InlineKeyboardButton(text="🟢 ЗАПУСТИТЬ РАССЫЛКУ", callback_data="start_loop"))
    return builder.as_markup()

def get_accounts_keyboard():
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="🔑 Получить строку (Войти)", callback_data="login_auto"))
    builder.add(InlineKeyboardButton(text="📝 Ввести строку вручную", callback_data="login_manual"))
    builder.row(InlineKeyboardButton(text="🗑 Удалить все аккаунты", callback_data="delete_sessions"))
    return builder.as_markup()

def get_pay_keyboard():
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="💎 Купить подписку (1000₽)", callback_data="buy_subscription"))
    return builder.as_markup()

def get_confirm_pay_keyboard():
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="✅ Я оплатил", callback_data="i_paid"))
    builder.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_start"))
    return builder.as_markup()


# --- ОСНОВНАЯ ЛОГИКА РАССЫЛКИ ---

def process_premium_text(text: str) -> str:
    if not text:
        return ""
    # Заменяем <tg-emoji emoji-id="..."> на <emoji id="...">
    text = text.replace('<tg-emoji emoji-id="', '<emoji id="')
    text = text.replace('</tg-emoji>', '</emoji>')
    return text

async def run_broadcast(user_id: int, text: str, chats: list, sessions: list, msg_delay: int, burst_mode: bool) -> str:
    """Выполняет рассылку. Учитывает burst_mode и Premium Emoji."""
    report = []
    
    # !!! КОНВЕРТАЦИЯ ТЕКСТА ПОД PYROGRAM !!!
    # Превращаем теги Aiogram в теги, понятные Pyrogram
    final_text = process_premium_text(text)

    for session in sessions:
        if user_id in active_loops and active_loops[user_id].cancelled(): return "⛔️ Отменено пользователем"
        
        client = PyroClient(
            name=f"session_{user_id}_{sessions.index(session)}", 
            api_id=API_ID, 
            api_hash=API_HASH, 
            session_string=session,
            in_memory=True
        )
        
        me = None
        try:
            await client.start()
            me = await client.get_me()
            
            # Проверка на наличие премиума у аккаунта (необязательно, но полезно для логов)
            is_premium = getattr(me, "is_premium", False)
            premium_badge = "🌟" if is_premium else "👤"
            
            report_line = f"{premium_badge} <b>Акк:</b> {me.first_name}"
            success_count = 0
            fail_count = 0
            
            for chat_link in chats:
                if user_id in active_loops and active_loops[user_id].cancelled(): 
                    await client.stop()
                    return "⛔️ Отменено пользователем"

                chat_link = chat_link.strip()
                if not chat_link: continue
                
                try:
                    if chat_link.startswith('https://t.me/'):
                        chat_link = chat_link.split('/')[-1]
                    
                    chat_id = chat_link
                    try:
                        joined_chat = await client.join_chat(chat_link)
                        chat_id = joined_chat.id
                    except Exception:
                        pass
                    
                    # !!! ОТПРАВКА С PARSE_MODE !!!
                    await client.send_message(
                        chat_id, 
                        final_text, 
                        parse_mode=enums.ParseMode.HTML
                    )
                    success_count += 1
                    
                    if not burst_mode:
                        await asyncio.sleep(msg_delay) 
                    else:
                        await asyncio.sleep(0.1) 
                    
                except FloodWait as e:
                    logging.warning(f"FloodWait: {e.value}s")
                    await asyncio.sleep(e.value + 1)
                except Exception as e:
                    fail_count += 1
            
            report_line += f" | ✅ {success_count} | ❌ {fail_count}"
            report.append(report_line)
            
        except Exception as e:
            report.append(f"❌ Ошибка сессии: {e}")
        finally:
            if client.is_connected:
                await client.stop()
    
    return "\n".join(report)

async def start_mailing_loop(user_id: int):
    try:
        while True:
            # Получаем свежие данные перед каждым кругом
            data = await get_mailing_data(user_id)
            text, chats_raw, msg_delay, is_cyclic, burst_mode, cycle_delay = data
            sessions = await get_user_accounts(user_id)
            chats = chats_raw.split("|")

            if not sessions:
                await bot.send_message(user_id, "⚠️ Нет аккаунтов для рассылки!")
                break

            mode_msg = "⚡️ МОМЕНТАЛЬНЫЙ" if burst_mode else f"⏱ Обычный (задержка {msg_delay}с)"
            await bot.send_message(user_id, f"🚀 **Старт цикла!**\nРежим: {mode_msg}")

            report = await run_broadcast(user_id, text, chats, sessions, msg_delay, burst_mode)
            
            if len(report) > 4000: report = report[:4000] + "..."
            await bot.send_message(user_id, f"📊 **Отчет:**\n{report}")
            
            if not is_cyclic:
                await bot.send_message(user_id, "🏁 Рассылка завершена (Цикл выключен).")
                break

            await bot.send_message(user_id, f"⏳ Жду **{cycle_delay} сек.** до следующего круга...")
            await asyncio.sleep(cycle_delay)

    except asyncio.CancelledError:
        await bot.send_message(user_id, "🛑 Рассылка принудительно остановлена.")
    except Exception as e:
        logging.exception(f"Loop error user {user_id}")
        await bot.send_message(user_id, f"❌ Ошибка цикла: {e}")
    finally:
        if user_id in active_loops:
            del active_loops[user_id]


# --- ХЕНДЛЕРЫ ---

@router.message(CommandStart())
async def cmd_start(message: types.Message):
    await add_user(message.from_user.id)
    if not await check_subscription(message.from_user.id):
        await message.answer("🚫 <b>Доступ запрещен!</b>\nОплатите подписку.", reply_markup=get_pay_keyboard())
    else:
        await message.answer("👋 Меню управления:", reply_markup=get_main_menu())

async def is_allowed(message: types.Message):
    if not await check_subscription(message.from_user.id):
        await message.answer("⛔️ Нужна подписка!")
        return False
    return True

# --- ТЕКСТ И ЧАТЫ ---
@router.message(F.text == "⚙️ Настроить текст")
async def set_text(message: types.Message, state: FSMContext):
    if not await is_allowed(message): return
    await message.answer("📝 Введите текст рассылки:")
    await state.set_state(BotStates.waiting_for_text)

@router.message(BotStates.waiting_for_text)
async def set_text_fin(message: types.Message, state: FSMContext):
    # message.html_text сохраняет форматирование и теги <tg-emoji>
    await save_mailing_data(message.from_user.id, text=message.html_text)
    await message.answer("✅ Текст с форматированием (и эмодзи) сохранен.")
    await state.clear()

@router.message(F.text == "📋 Добавить чаты")
async def add_chats(message: types.Message, state: FSMContext):
    if not await is_allowed(message): return
    await message.answer("🔗 Пришлите список ссылок (каждая с новой строки):")
    await state.set_state(BotStates.waiting_for_chats)

@router.message(BotStates.waiting_for_chats)
async def add_chats_fin(message: types.Message, state: FSMContext):
    links = [l.strip() for l in message.text.split('\n') if l.strip()]
    cleaned_links = []
    for link in links:
        if link.startswith('https://t.me/'):
            cleaned_links.append(link.split('/')[-1])
        else:
            cleaned_links.append(link)

    await save_mailing_data(message.from_user.id, chats="|".join(cleaned_links))
    await message.answer(f"✅ Чатов сохранено: {len(cleaned_links)}")
    await state.clear()

# --- ЗАДЕРЖКИ ---
@router.message(F.text == "⏱ Задержка (Смс)")
async def set_delay_msg(message: types.Message, state: FSMContext):
    if not await is_allowed(message): return
    data = await get_mailing_data(message.from_user.id)
    await message.answer(
        f"⏱ <b>Задержка между сообщениями</b>\nСейчас: {data[2]} сек.\n"
        "Введите новое значение (сек):"
    )
    await state.set_state(BotStates.waiting_for_delay)

@router.message(BotStates.waiting_for_delay)
async def set_delay_msg_fin(message: types.Message, state: FSMContext):
    try:
        val = int(message.text)
        if val < 0: val = 0
        await save_mailing_data(message.from_user.id, delay=val)
        await message.answer(f"✅ Задержка сообщений: {val} сек.")
        await state.clear()
    except ValueError:
        await message.answer("⚠️ Введите число.")

@router.message(F.text == "⏳ Задержка (Цикл)")
async def set_delay_cycle(message: types.Message, state: FSMContext):
    if not await is_allowed(message): return
    data = await get_mailing_data(message.from_user.id)
    cycle_delay = data[5]
    await message.answer(
        f"⏳ <b>Задержка цикла</b>\n"
        f"Время ожидания после прохода по всем чатам перед новым стартом.\n\n"
        f"Сейчас: <b>{cycle_delay} сек.</b> (примерно {round(cycle_delay/60, 1)} мин)\n"
        "Введите новое значение (в секундах):"
    )
    await state.set_state(BotStates.waiting_for_cycle_delay)

@router.message(BotStates.waiting_for_cycle_delay)
async def set_delay_cycle_fin(message: types.Message, state: FSMContext):
    try:
        val = int(message.text)
        if val < 10: val = 10 # Минимальное ограничение для здравого смысла
        await save_mailing_data(message.from_user.id, cycle_delay=val)
        await message.answer(f"✅ Задержка цикла: {val} сек.")
        await state.clear()
    except ValueError:
        await message.answer("⚠️ Введите число.")

# --- УПРАВЛЕНИЕ ЦИКЛОМ И BURST MODE ---

@router.message(F.text == "🔁 Цикл рассылки")
async def set_cycle_menu(message: types.Message):
    if not await is_allowed(message): return
    data = await get_mailing_data(message.from_user.id)
    is_cyclic = data[3]
    burst_mode = data[4]
    
    await message.answer(
        f"⚙️ <b>Настройки режима рассылки</b>\n\n"
        f"🔁 <b>Цикличность:</b> {'ВКЛ' if is_cyclic else 'ВЫКЛ'}\n"
        f"⚡️ <b>Моментальная отправка:</b> {'ВКЛ' if burst_mode else 'ВЫКЛ'}\n\n"
        f"<i>Если 'Моментально' включено, сообщения отправляются без пауз.</i>",
        reply_markup=get_cycle_keyboard(is_cyclic, burst_mode)
    )

@router.callback_query(F.data.in_({"cycle_on", "cycle_off", "burst_on", "burst_off"}))
async def toggle_cycle_settings(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    data = await get_mailing_data(user_id)
    is_cyclic = data[3]
    burst_mode = data[4]
    
    if callback.data == "cycle_on": is_cyclic = True
    elif callback.data == "cycle_off": is_cyclic = False
    elif callback.data == "burst_on": burst_mode = True
    elif callback.data == "burst_off": burst_mode = False
    
    await save_mailing_data(user_id, is_cyclic=is_cyclic, burst_mode=burst_mode)
    
    await callback.message.edit_text(
        f"⚙️ <b>Настройки режима рассылки</b>\n\n"
        f"🔁 <b>Цикличность:</b> {'ВКЛ' if is_cyclic else 'ВЫКЛ'}\n"
        f"⚡️ <b>Моментальная отправка:</b> {'ВКЛ' if burst_mode else 'ВЫКЛ'}",
        reply_markup=get_cycle_keyboard(is_cyclic, burst_mode)
    )
    await callback.answer("Настройки обновлены")


# --- ЗАПУСК ---

@router.message(F.text == "🚀 Запустить рассылку")
async def mailing_control(message: types.Message):
    if not await is_allowed(message): return
    
    data = await get_mailing_data(message.from_user.id)
    # text, chats, msg_delay, is_cyclic, burst_mode, cycle_delay
    text, chats_raw, msg_delay, is_cyclic, burst_mode, cycle_delay = data
    sessions = await get_user_accounts(message.from_user.id)
    
    is_running = message.from_user.id in active_loops
    
    if not text or not chats_raw: 
        return await message.answer("⚠️ Настройте текст и чаты!")
    if not sessions: 
        return await message.answer("⚠️ Добавьте аккаунты!")
    
    chats = chats_raw.split("|")
    
    status_text = "🔴 АКТИВНА" if is_running else "🟢 ГОТОВА"
    burst_text = "⚡️ БЕЗ ЗАДЕРЖКИ" if burst_mode else f"⏱ {msg_delay} сек"
    
    await message.answer(
        f"🚀 <b>Панель запуска</b>\n"
        f"Статус: {status_text}\n"
        f"Аккаунтов: {len(sessions)} | Чатов: {len(chats)}\n\n"
        f"Режим отправки: <b>{burst_text}</b>\n"
        f"Цикличность: <b>{'ВКЛ' if is_cyclic else 'ВЫКЛ'}</b>\n"
        f"Пауза цикла: <b>{cycle_delay} сек.</b>",
        reply_markup=get_start_stop_keyboard(is_running)
    )

@router.callback_query(F.data == "start_loop")
async def start_loop_handler(callback: types.CallbackQuery):
    if callback.from_user.id in active_loops:
        return await callback.answer("Уже работает!", show_alert=True)
    
    await callback.message.edit_text("🚀 Запускаю процессы...")
    task = asyncio.create_task(start_mailing_loop(callback.from_user.id))
    active_loops[callback.from_user.id] = task
    
    await callback.message.edit_reply_markup(reply_markup=get_start_stop_keyboard(True))
    await callback.answer("Поехали!")

@router.callback_query(F.data == "stop_loop")
async def stop_loop_handler(callback: types.CallbackQuery):
    if callback.from_user.id in active_loops:
        active_loops[callback.from_user.id].cancel()
        del active_loops[callback.from_user.id]
        await callback.message.edit_text("🛑 Остановлено.", reply_markup=get_start_stop_keyboard(False))
    else:
        await callback.answer("Не запущено.")

# ... (ОСТАЛЬНЫЕ ХЕНДЛЕРЫ LOGIN, PROFILE, PAYMENT БЕЗ ИЗМЕНЕНИЙ) ...
# Копируем старые хендлеры авторизации и профиля сюда, они не менялись,
# но Profile можно чуть обновить для красоты:

@router.message(F.text == "ℹ️ Профиль")
async def profile(message: types.Message):
    accs = await get_user_accounts(message.from_user.id)
    data = await get_mailing_data(message.from_user.id)
    # text, chats, msg_delay, is_cyclic, burst_mode, cycle_delay
    
    await message.answer(
        f"🆔 {message.from_user.id}\n"
        f"📱 Аккаунтов: {len(accs)}\n"
        f"⚙️ Режим Burst: {'ВКЛ' if data[4] else 'ВЫКЛ'}\n"
        f"⏱ Задержка смс: {data[2]} сек\n"
        f"⏳ Задержка цикла: {data[5]} сек"
    )

@router.message(F.text == "👤 Добавить аккаунты")
async def acc_menu(message: types.Message):
    if not await is_allowed(message): return
    accs = await get_user_accounts(message.from_user.id)
    await message.answer(f"Аккаунтов: {len(accs)}", reply_markup=get_accounts_keyboard())

@router.callback_query(F.data == "delete_sessions")
async def del_sessions(callback: types.CallbackQuery):
    if callback.from_user.id in active_loops:
        active_loops[callback.from_user.id].cancel()
        del active_loops[callback.from_user.id]
    await delete_all_accounts(callback.from_user.id)
    await callback.answer("Удалено!", show_alert=True)
    await callback.message.delete()

# --- LOGIN HANDLERS (стандартные) ---
@router.callback_query(F.data == "login_auto")
async def login_auto_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("📞 Введите номер (например +79001234567):")
    await state.set_state(BotStates.login_phone)

@router.message(BotStates.login_phone)
async def login_get_phone(message: types.Message, state: FSMContext):
    phone = message.text.strip().replace(" ", "")
    user_id = message.from_user.id
    status_msg = await message.answer("🔄 Соединение...")
    client = PyroClient(name=f"setup_{user_id}", api_id=API_ID, api_hash=API_HASH, in_memory=True)
    try:
        await client.connect()
        sent_code = await client.send_code(phone)
        active_setups[user_id] = {"client": client, "phone": phone, "phone_hash": sent_code.phone_code_hash}
        await status_msg.edit_text("📨 Введите код из Telegram:")
        await state.set_state(BotStates.login_code)
    except Exception as e:
        await status_msg.edit_text(f"❌ Ошибка: {e}")
        await client.disconnect()

@router.message(BotStates.login_code)
async def login_get_code(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    code = message.text.replace(" ", "")
    if user_id not in active_setups: return await state.clear()
    data = active_setups[user_id]
    client = data["client"]
    try:
        await client.sign_in(data["phone"], data["phone_hash"], code)
        s = await client.export_session_string()
        await add_account(user_id, s, data["phone"])
        await message.answer("✅ Аккаунт добавлен!")
        await client.disconnect()
        del active_setups[user_id]
        await state.clear()
    except SessionPasswordNeeded:
        await message.answer("🔒 Введите пароль 2FA:")
        await state.set_state(BotStates.login_2fa)
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")
        await client.disconnect()

@router.message(BotStates.login_2fa)
async def login_get_password(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id not in active_setups: return await state.clear()
    client = active_setups[user_id]["client"]
    try:
        await client.check_password(password=message.text)
        s = await client.export_session_string()
        await add_account(user_id, s, active_setups[user_id]["phone"])
        await message.answer("✅ Аккаунт добавлен!")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")
    finally:
        await client.disconnect()
        del active_setups[user_id]
        await state.clear()

@router.callback_query(F.data == "login_manual")
async def manual_session(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("📝 Вставьте Session String:")
    await state.set_state(BotStates.waiting_for_session_string)

@router.message(BotStates.waiting_for_session_string)
async def manual_session_fin(message: types.Message, state: FSMContext):
    try:
        client = PyroClient(":memory:", api_id=API_ID, api_hash=API_HASH, session_string=message.text, in_memory=True)
        await client.start()
        me = await client.get_me()
        await client.stop()
        await add_account(message.from_user.id, message.text, str(me.phone_number))
        await message.answer(f"✅ Добавлен: {me.first_name}")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")
    await state.clear()

@router.callback_query(F.data == "buy_subscription")
async def buy_sub_process(callback: types.CallbackQuery):
    await callback.message.edit_text("💳 Оплата 1000р...", reply_markup=get_confirm_pay_keyboard())

@router.callback_query(F.data == "i_paid")
async def i_paid_process(callback: types.CallbackQuery):
    await callback.message.edit_text("⏳ Проверяем...")
    try: await bot.send_message(ADMIN_IDS[0], f"💰 Оплата {callback.from_user.id}\n/grant {callback.from_user.id}")
    except: pass

@router.callback_query(F.data == "back_to_start")
async def back_process(callback: types.CallbackQuery):
    await callback.message.delete()
    await cmd_start(callback.message)

@router.message(Command("grant"))
async def grant_access(message: types.Message):
    if message.from_user.id in ADMIN_IDS:
        try:
            tid = int(message.text.split()[1])
            await activate_sub(tid)
            await message.answer("✅ OK")
            await bot.send_message(tid, "🎉 Подписка активна! /start")
        except: pass

async def main():
    await init_db()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
