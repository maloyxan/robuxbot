import asyncio
import logging
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ================= КОНФИГУРАЦИЯ =================
# Вставь сюда свой токен от BotFather
BOT_TOKEN = "8435153206:AAGNknByNxqmuqHLbDYn_S1HqbvEjL0_v7g" 

# Вставь сюда свой цифровой ID (число), узнать можно в @userinfobot
ADMIN_ID = 7834799163

# Номер карты
CARD_NUMBER = "5536917743123983"

# ================= ДАННЫЕ =================
# Цены на робуксы
PRICES = {
    "100": 49,
    "400": 189,
    "800": 399,
    "1200": 559,
    "2400": 1199,
    "5000": 2199
}

# Отзывы (30 штук)
FAKE_REVIEWS = [
    "Всё пришло моментально, спасибо!", "Лучший шоп, беру не первый раз.", "Сначала боялся, но всё честно. Респект.", 
    "Админ ответил за 5 минут, робуксы на базе.", "Цены вообще копейки, буду брать ещё.", "Пришли за 10 минут, советую.",
    "Топчик! Купил 400 робуксов, всё ок.", "Спасибо MacroRobux, не обманули.", "Долго искал где купить, тут выгоднее всего.",
    "Кайф, теперь я мажор в брукхевене))", "Всё супер, спасибо поддержке за помощь.", "Быстро, чётко, надёжно.",
    "Рекомендую друзьям, всё работает.", "Пришли ровно 800, комиссию покрыли (вроде).", "Спс, всё гуд.",
    # Страница 2
    "Оплатил, через 2 минуты уже на аккаунте. Магия!", "С кайфом, беру тут 5-й раз.", "Не скам! Реально пришли.",
    "Думал кидалово, а оказалось всё честно. Спасибо!", "Поддержка душевная, помогли разобраться с пассом.",
    "MacroRobux — вы лучшие! ❤️", "За 1000 рублей насыпали кучу робуксов, имба.", "Всё чисто, карта работает.",
    "Ждал минут 20, но главное что пришли.", "Топ за свои деньги.", "Братик посоветовал, не пожалел.",
    "10/10, быстро и дёшево.", "Всё пришло, спасибочки!", "Буду закупаться только тут.", "Робаксы на месте, я доволен."
]

# ================= МАШИНА СОСТОЯНИЙ (FSM) =================
class SupportState(StatesGroup):
    waiting_for_message = State()

# ================= ИНИЦИАЛИЗАЦИЯ =================
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ================= КЛАВИАТУРЫ =================

def get_main_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="💎 За покупками!", callback_data="purchase"))
    builder.row(InlineKeyboardButton(text="💬 Поддержка", callback_data="support"),
                InlineKeyboardButton(text="⭐ Наши отзывы", callback_data="reviews_0"))
    return builder.as_markup()

def get_robux_keyboard():
    builder = InlineKeyboardBuilder()
    for amount, price in PRICES.items():
        builder.button(text=f"💎 {amount} ({price} ₽)", callback_data=f"robux_{amount}")
    builder.adjust(2) # По 2 кнопки в ряд
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main"))
    return builder.as_markup()

def get_payment_keyboard(amount):
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="✅ Я оплатил", callback_data=f"paid_{amount}"))
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="back_to_purchase"))
    return builder.as_markup()

def get_reviews_keyboard(page=0):
    builder = InlineKeyboardBuilder()
    
    # Логика пагинации
    total_reviews = len(FAKE_REVIEWS)
    items_per_page = 15
    start_index = page * items_per_page
    end_index = start_index + items_per_page
    
    # Кнопки переключения
    buttons_row = []
    if page > 0:
        buttons_row.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"reviews_{page-1}"))
    
    # Показываем номер страницы
    buttons_row.append(InlineKeyboardButton(text=f"📄 {page+1}/2", callback_data="ignore"))
    
    if end_index < total_reviews:
        buttons_row.append(InlineKeyboardButton(text="Вперед ➡️", callback_data=f"reviews_{page+1}"))
        
    builder.row(*buttons_row)
    builder.row(InlineKeyboardButton(text="🔙 В меню", callback_data="back_to_main"))
    return builder.as_markup()

# ================= ХЕНДЛЕРЫ (ОБРАБОТЧИКИ) =================

@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    text = (
        "👋 <b>Привет, Роблоксер!</b> Это <b>MacroRobux</b>.\n\n"
        "🚀 Здесь ты можешь купить робуксы по самым <b>выгодным ценам</b> на рынке!\n"
        "⚡️ Моментальная доставка\n"
        "🔒 Гарантия безопасности\n\n"
        "👇 Выбери действие ниже:"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=get_main_keyboard())

# --- Callback: Навигация ---
@dp.callback_query(F.data == "back_to_main")
async def go_main(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    text = (
        "👋 <b>Привет, Роблоксер!</b> Это <b>MacroRobux</b>.\n\n"
        "👇 Выбери действие ниже:"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=get_main_keyboard())

# --- Callback: Покупка ---
@dp.callback_query(F.data == "purchase")
async def show_purchase(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "💎 <b>Выберите количество робуксов:</b>\n\n"
        "🔥 <i>Лучшие цены только у нас!</i>",
        parse_mode="HTML",
        reply_markup=get_robux_keyboard()
    )

@dp.callback_query(F.data == "back_to_purchase")
async def back_purchase(callback: types.CallbackQuery):
    await show_purchase(callback)

# --- Логика выбора товара и оплаты ---
@dp.callback_query(F.data.startswith("robux_"))
async def process_buy(callback: types.CallbackQuery):
    amount = callback.data.split("_")[1]
    price = PRICES[amount]
    
    text = (
        f"🛒 Вы собираетесь купить: <b>{amount} робуксов</b>\n"
        f"💰 К оплате: <b>{price} рублей</b>\n\n"
        "💳 <b>Для покупки произведите платеж по карте:</b>\n"
        f"<code>{CARD_NUMBER}</code>\n"
        "(Нажмите на номер карты, чтобы скопировать)\n\n"
        "⚠️ <i>После перевода обязательно нажмите кнопку «Я оплатил»</i>"
    )
    
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=get_payment_keyboard(amount))

@dp.callback_query(F.data.startswith("paid_"))
async def process_paid(callback: types.CallbackQuery):
    amount = callback.data.split("_")[1]
    user = callback.from_user
    
    # Сообщение пользователю
    await callback.message.edit_text(
        "✅ <b>Заявка принята!</b>\n\n"
        "Администратор скоро проверит платеж и начислит робуксы.\n"
        "Обычно это занимает 5-15 минут.\n\n"
        "Спасибо за покупку в MacroRobux! ❤️",
        parse_mode="HTML",
        reply_markup=None # Убираем кнопки, чтобы не спамили
    )
    
    # Уведомление админу
    admin_text = (
        "💰 <b>НОВАЯ ОПЛАТА!</b>\n\n"
        f"👤 Юзер: {user.full_name} (@{user.username})\n"
        f"🆔 ID: <code>{user.id}</code>\n"
        f"💎 Сумма: <b>{amount} R$</b>\n"
        f"💵 Ожидай поступления на карту."
    )
    try:
        await bot.send_message(ADMIN_ID, admin_text, parse_mode="HTML")
    except Exception as e:
        print(f"Не удалось отправить уведомление админу: {e}")

# --- Callback: Отзывы ---
@dp.callback_query(F.data.startswith("reviews_"))
async def show_reviews(callback: types.CallbackQuery):
    page = int(callback.data.split("_")[1])
    
    start = page * 15
    end = start + 15
    current_reviews = FAKE_REVIEWS[start:end]
    
    text = "⭐ <b>Отзывы наших клиентов:</b>\n\n"
    text += "<i>Нам доверяют уже более 2-ух лет!</i>\n\n"
    
    for i, review in enumerate(current_reviews, 1):
        text += f"👤 <b>Клиент:</b> {review}\n"
        
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=get_reviews_keyboard(page))
    
@dp.callback_query(F.data == "ignore")
async def ignore_click(callback: types.CallbackQuery):
    await callback.answer("Вы уже на этой странице")

# --- Callback: Поддержка (Клиентская часть) ---
@dp.callback_query(F.data == "support")
async def start_support(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "👨‍💻 <b>Техническая поддержка MacroRobux</b>\n\n"
        "Опишите вашу проблему или задайте вопрос одним сообщением ниже.\n"
        "Администратор ответит вам в ближайшее время.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardBuilder().row(InlineKeyboardButton(text="🔙 Отмена", callback_data="back_to_main")).as_markup()
    )
    await state.set_state(SupportState.waiting_for_message)

@dp.message(SupportState.waiting_for_message)
async def forward_to_admin(message: types.Message, state: FSMContext):
    # Отправляем сообщение админу
    user_info = (
        "📩 <b>НОВОЕ ОБРАЩЕНИЕ В ТП</b>\n\n"
        f"👤 От: {message.from_user.full_name} (@{message.from_user.username})\n"
        f"🆔 ID: <code>{message.from_user.id}</code>\n\n"
        "<b>Текст сообщения:</b>\n"
    )
    
    try:
        await bot.send_message(ADMIN_ID, user_info + message.text, parse_mode="HTML")
        await message.answer("✅ <b>Сообщение отправлено!</b> Ждите ответа админа.", parse_mode="HTML")
    except Exception as e:
        await message.answer("❌ Ошибка отправки. Попробуйте позже.")
    
    await state.clear()

# --- Поддержка (Админская часть) ---
# Админ пишет: /answer ID ТЕКСТ
@dp.message(Command("answer"))
async def admin_answer(message: types.Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID:
        return

    if command.args is None:
        await message.answer("⚠️ Ошибка. Используй: `/answer ID ТЕКСТ`")
        return

    try:
        args = command.args.split(" ", 1)
        user_id = int(args[0])
        text = args[1]
    except (ValueError, IndexError):
        await message.answer("⚠️ Ошибка формата. Используй: `/answer ID ТЕКСТ`")
        return

    try:
        await bot.send_message(user_id, f"👨‍💻 <b>Ответ от поддержки:</b>\n\n{text}", parse_mode="HTML")
        await message.answer(f"✅ Ответ отправлен пользователю {user_id}")
    except Exception as e:
        await message.answer(f"❌ Не удалось отправить (возможно бот заблокирован): {e}")

# ================= ЗАПУСК =================
async def main():
    print("Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот выключен")
