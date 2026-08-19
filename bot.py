import asyncio                                        
import logging
import sqlite3
import time
from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

TOKEN = "8925068569:AAF0Rc5EgaUzBFLvwieF_IBnqQcmAC7n7aQ"
ADMIN_ID = 8252674515  
DB_NAME = "crash_bot.db"

bot = Bot(token=TOKEN)
dp = Dispatcher()

# Vaqtinchalik xotira
user_game_steps = {}
user_total_games = {}
user_mines_bets = {}

# Mines yutuq koeffitsiyentlari (X)
MINES_MULTIPLIERS = {
    1: 1.20,
    2: 1.50,
    3: 2.00,
    4: 2.80,
    5: 4.00,
    6: 6.00
}

def get_mines_keyboard(step: int, current_x: float, bet: int):
    keyboard = []
    # 3x3 Mines kataklari
    for r in range(3):
        row = []
        for c in range(3):
            row.append(InlineKeyboardButton(text="💣", callback_data=f"mine_{r}_{c}"))
        keyboard.append(row)
    
    current_win = int(bet * current_x) if step > 0 else 0
    
    # Pulni yechib olish tugmasi
    if step > 0:
        keyboard.append([InlineKeyboardButton(text=f"💰 Olish (Cash Out): {money(current_win)} ({current_x:.2f}x)", callback_data="mines_cashout")])
    else:
        keyboard.append([InlineKeyboardButton(text="🎯 Katakni tanlang...", callback_data="none")])
        
    keyboard.append([InlineKeyboardButton(text="❌ O'yinni to'xtatish", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


# =========================================================
# MA'LUMOTLAR BAZASI
# =========================================================
def db_query(query: str, params: tuple = (), fetchone: bool = False, fetchall: bool = False, commit: bool = False):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(query, params)
    result = None
    if fetchone:
        result = cursor.fetchone()
    elif fetchall:
        result = cursor.fetchall()
    if commit:
        conn.commit()
    conn.close()
    return result

async def init_db():
    await asyncio.to_thread(
        db_query,
        '''CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            balance INTEGER DEFAULT 10000,
            has_deposited INTEGER DEFAULT 0
        )''',
        commit=True
    )
    try:
        await asyncio.to_thread(
            db_query,
            '''ALTER TABLE users ADD COLUMN has_deposited INTEGER DEFAULT 0''',
            commit=True
        )
    except Exception:
        pass

    await asyncio.to_thread(
        db_query,
        '''CREATE TABLE IF NOT EXISTS mining (
            user_id INTEGER PRIMARY KEY,
            last_claim INTEGER DEFAULT 0
        )''',
        commit=True
    )
    await asyncio.to_thread(
        db_query,
        '''CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )''',
        commit=True
    )
    card = await asyncio.to_thread(db_query, "SELECT value FROM settings WHERE key = 'card_number'", fetchone=True)
    if not card:
        await asyncio.to_thread(db_query, "INSERT INTO settings (key, value) VALUES ('card_number', 'Kiritilmagan')", commit=True)

async def get_card_number() -> str:
    row = await asyncio.to_thread(db_query, "SELECT value FROM settings WHERE key = 'card_number'", fetchone=True)
    return row[0] if row else "Kiritilmagan"

async def set_card_number(card: str):
    await asyncio.to_thread(db_query, "UPDATE settings SET value = ? WHERE key = 'card_number'", (card,), commit=True)

async def get_balance(user_id: int) -> int:
    row = await asyncio.to_thread(db_query, "SELECT balance FROM users WHERE user_id = ?", (user_id,), fetchone=True)
    if row:
        return row[0]
    else:
        await asyncio.to_thread(db_query, "INSERT INTO users (user_id, balance, has_deposited) VALUES (?, 10000, 0)", (user_id,), commit=True)
        return 10000

async def change_balance(user_id: int, amount: int):
    await get_balance(user_id)
    await asyncio.to_thread(db_query, "UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id), commit=True)

async def check_user_deposited(user_id: int) -> bool:
    row = await asyncio.to_thread(db_query, "SELECT has_deposited FROM users WHERE user_id = ?", (user_id,), fetchone=True)
    return row and row[0] == 1

async def set_user_deposited(user_id: int):
    await asyncio.to_thread(db_query, "UPDATE users SET has_deposited = 1 WHERE user_id = ?", (user_id,), commit=True)

async def get_last_claim(user_id: int) -> int:
    row = await asyncio.to_thread(db_query, "SELECT last_claim FROM mining WHERE user_id = ?", (user_id,), fetchone=True)
    return row[0] if row else 0

async def update_last_claim(user_id: int, timestamp: int):
    await asyncio.to_thread(db_query, "INSERT OR REPLACE INTO mining (user_id, last_claim) VALUES (?, ?)", (user_id, timestamp), commit=True)

async def get_users_count() -> int:
    row = await asyncio.to_thread(db_query, "SELECT COUNT(*) FROM users", fetchone=True)
    return row[0] if row else 0

def money(val: int) -> str:
    return f"{val:,}".replace(",", " ")


# =========================================================
# FSM HOLATLARI
# =========================================================
class MinesState(StatesGroup):
    waiting_bet = State()

class DepositState(StatesGroup):
    waiting_amount = State()
    waiting_proof = State()

class WithdrawState(StatesGroup):
    waiting_amount = State()
    waiting_card_and_name = State()

class AdminState(StatesGroup):
    waiting_card_number = State()


# =========================================================
# ASOSIY MENYU
# =========================================================
def main_menu(user_id: int):
    kb = [
        [InlineKeyboardButton(text="💣 Mines O'yini", callback_data="play_mines")],
        [InlineKeyboardButton(text="⛏ Mining (+100 coin)", callback_data="mining_section")],
        [InlineKeyboardButton(text="💰 Balans", callback_data="my_balance")],
        [
            InlineKeyboardButton(text="📥 Depozit", callback_data="deposit_money"),
            InlineKeyboardButton(text="📤 Pul chiqarish", callback_data="withdraw_money")
        ]
    ]
    if user_id == ADMIN_ID:
        kb.append([InlineKeyboardButton(text="👨‍💼 Admin Panel", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


@dp.message(F.text == "/start")
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    balance = await get_balance(user_id)

    await message.answer(
        f"✨ <b>XUSH KELIBSIZ, {message.from_user.first_name}!</b> ✨\n"
        f"──────────────────────────\n"
        f"💣 <b>Mines</b> o'yinida qatnashing, kataklarni ochib X larni yig'ing va pul yutib oling!\n\n"
        f"💰 <b>Balansingiz:</b> {money(balance)} coin\n"
        f"──────────────────────────",
        reply_markup=main_menu(user_id),
        parse_mode=ParseMode.HTML
    )

@dp.callback_query(F.data == "back_to_menu")
async def back_to_menu_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    balance = await get_balance(callback.from_user.id)
    
    text = (
        f"🏠 <b>ASOSIY MENYU</b>\n"
        f"──────────────────────────\n"
        f"💰 <b>Balansingiz:</b> {money(balance)} coin"
    )
    
    try:
        await callback.message.edit_text(text, reply_markup=main_menu(callback.from_user.id), parse_mode=ParseMode.HTML)
    except Exception:
        await callback.message.answer(text, reply_markup=main_menu(callback.from_user.id), parse_mode=ParseMode.HTML)
    await callback.answer()

@dp.callback_query(F.data == "my_balance")
async def my_balance_handler(callback: CallbackQuery):
    balance = await get_balance(callback.from_user.id)
    await callback.answer(f"💰 Balansingiz: {money(balance)} coin", show_alert=True)


# =========================================================
# 💣 MINES O'YINI
# =========================================================
@dp.callback_query(F.data == "play_mines")
async def play_mines_menu(callback: CallbackQuery, state: FSMContext):
    await state.set_state(MinesState.waiting_bet)
    balance = await get_balance(callback.from_user.id)
    
    text = (
        f"💣 <b>MINES O'YINI</b>\n"
        f"──────────────────────────\n"
        f"🎯 Xavfsiz kataklarni tanlang va koeffitsiyentlarni (X) oshiring!\n\n"
        f"💰 Balansingiz: <b>{money(balance)} coin</b>\n"
        f"Stavka miqdorini kiriting (min: 100 coin):"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_to_menu")]])
    
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    await callback.answer()

@dp.message(MinesState.waiting_bet)
async def process_mines_bet(message: Message, state: FSMContext):
    if not message.text or not message.text.isdigit():
        await message.answer("❌ Faqat musbat raqam kiriting:")
        return
    
    bet = int(message.text)
    user_id = message.from_user.id
    balance = await get_balance(user_id)

    if bet < 100 or bet > balance:
        await message.answer("❌ Noto'g'ri summa yoki hisobda mablag' yetarli emas!")
        return

    await change_balance(user_id, -bet)
    await state.clear()

    if user_id not in user_total_games:
        user_total_games[user_id] = 1
    else:
        user_total_games[user_id] += 1
        
    if user_total_games[user_id] > 6:
        user_total_games[user_id] = 1
        
    user_game_steps[user_id] = 0
    user_mines_bets[user_id] = bet
    game_num = user_total_games[user_id]

    current_x = 1.00
    await message.answer(
        f"💣 <b>Mines o'yini boshlandi!</b> (O'yin #{game_num})\n"
        f"💰 Stavka: <b>{money(bet)} coin</b>\n"
        f"📈 Hozirgi X: <b>{current_x:.2f}x</b>\n\n"
        f"Xavfsiz katakni tanlang:",
        reply_markup=get_mines_keyboard(0, current_x, bet),
        parse_mode=ParseMode.HTML
    )

@dp.callback_query(F.data.startswith("mine_"))
async def process_mine_click(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    if user_id not in user_game_steps or user_id not in user_mines_bets:
        await callback.answer("⚠️ Faol o'yin topilmadi! Yangi o'yin boshlang.", show_alert=True)
        return

    game_num = user_total_games.get(user_id, 1)
    step = user_game_steps[user_id] + 1
    user_game_steps[user_id] = step

    is_boom = False
    if game_num == 1 and step > 3:
        is_boom = True
    elif game_num in [2, 3] and step > 2:
        is_boom = True
    elif game_num in [4, 5] and step > 4:
        is_boom = True

    current_x = MINES_MULTIPLIERS.get(step, 1.20)
    bet = user_mines_bets[user_id]
    current_win = int(bet * current_x)

    if is_boom:
        user_game_steps.pop(user_id, None)
        user_mines_bets.pop(user_id, None)

        try:
            await callback.message.edit_text(
                f"💥 <b>Boom! Minaga bosib yutqazdingiz!</b> 😢\n"
                f"Bosqich: {step} | Oxirgi X: {current_x:.2f}x\n\n"
                f"Qaytadan o'ynash uchun tugmani bosing:",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💣 Qaytadan o'ynash", callback_data="play_mines")]]),
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass
        await callback.answer("💥 Yutqazdingiz!", show_alert=True)
    else:
        await callback.answer(f"✅ Qadam #{step}: X: {current_x:.2f}x", show_alert=False)
        try:
            await callback.message.edit_text(
                f"💣 <b>Mines o'yini davom etmoqda...</b>\n"
                f"💰 Stavka: <b>{money(bet)} coin</b>\n"
                f"🎯 Ochilgan kataklar: <b>{step} ta</b>\n"
                f"📈 Koeffitsiyent: <b>{current_x:.2f}x</b>\n"
                f"💵 Hozirgi yutuq: <b>{money(current_win)} coin</b>\n\n"
                f"Keyingi katakni tanlang yoki pulni oling:",
                reply_markup=get_mines_keyboard(step, current_x, bet),
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass

@dp.callback_query(F.data == "mines_cashout")
async def mines_cashout_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    if user_id not in user_game_steps or user_id not in user_mines_bets:
        await callback.answer("⚠️ Faol o'yin topilmadi!", show_alert=True)
        return

    step = user_game_steps[user_id]
    if step == 0:
        await callback.answer("⚠️ Hali katak ochmadingiz!", show_alert=True)
        return

    current_x = MINES_MULTIPLIERS.get(step, 1.20)
    bet = user_mines_bets[user_id]
    win_amount = int(bet * current_x)

    await change_balance(user_id, win_amount)
    balance = await get_balance(user_id)

    user_game_steps.pop(user_id, None)
    user_mines_bets.pop(user_id, None)

    try:
        await callback.message.edit_text(
            f"✅ <b>PUL MUVAFFAQIYATLI OLINDI! (CASH OUT)</b>\n"
            f"──────────────────────────\n"
            f"🎯 <b>Bosqich:</b> {step} ta katak\n"
            f"📈 <b>Koeffitsiyent:</b> {current_x:.2f}x\n"
            f"💰 <b>Yutuq:</b> +{money(win_amount)} coin\n"
            f"💳 <b>Balans:</b> {money(balance)} coin\n"
            f"──────────────────────────",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💣 Qaytadan o'ynash", callback_data="play_mines")]]),
            parse_mode=ParseMode.HTML
        )
    except Exception:
        pass
    await callback.answer("💰 Pul muvaffaqiyatli yechib olindi!", show_alert=True)


# =========================================================
# ⛏ MINING BO'LIMI
# =========================================================
@dp.callback_query(F.data == "mining_section")
async def mining_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    is_deposited = await check_user_deposited(user_id)
    if not is_deposited:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📥 Depozit Qilish", callback_data="deposit_money")],
            [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_to_menu")]
        ])
        await callback.message.edit_text(
            f"🔒 <b>MINING BO'LIMI YOPILGAN!</b>\n"
            f"──────────────────────────\n"
            f"⚠️ Mining bo'limiga ulanish uchun kamida <b>1 marta depozit</b> qilishingiz kerak!",
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )
        await callback.answer()
        return

    current_time = int(time.time())
    last_claim = await get_last_claim(user_id)
    cooldown = 3600
    elapsed = current_time - last_claim

    if elapsed >= cooldown:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎁 100 Coin Olish", callback_data="claim_mining")],
            [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_to_menu")]
        ])
        await callback.message.edit_text(
            f"⛏ <b>MINING BO'LIMI</b>\n"
            f"──────────────────────────\n"
            f"🎁 <b>Tayyor!</b> Balansingizga 100 coin qo'shishingiz mumkin.",
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )
    else:
        remaining = cooldown - elapsed
        minutes = remaining // 60
        seconds = remaining % 60
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Yangilash", callback_data="mining_section")],
            [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_to_menu")]
        ])
        await callback.message.edit_text(
            f"⛏ <b>MINING BO'LIMI</b>\n"
            f"──────────────────────────\n"
            f"⏳ <b>Keyingi bonus tayyor bo'lishiga:</b> {minutes} daqiqa {seconds} soniya qoldi.",
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )
    await callback.answer()

@dp.callback_query(F.data == "claim_mining")
async def claim_mining_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    if not await check_user_deposited(user_id):
        await callback.answer("⚠️ Avval depozit qilishingiz kerak!", show_alert=True)
        return

    current_time = int(time.time())
    last_claim = await get_last_claim(user_id)
    if current_time - last_claim < 3600:
        await callback.answer("⏳ Hali 1 soat o'tmadi!", show_alert=True)
        return

    await change_balance(user_id, 100)
    await update_last_claim(user_id, current_time)
    balance = await get_balance(user_id)
    await callback.answer("🎉 +100 coin balansingizga qo'shildi!", show_alert=True)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Holatni tekshirish", callback_data="mining_section")],
        [InlineKeyboardButton(text="🏠 Asosiy Menyu", callback_data="back_to_menu")]
    ])
    await callback.message.edit_text(
        f"⛏ <b>MINING BO'LIMI</b>\n"
        f"✅ <b>100 coin muvaffaqiyatli olindi!</b>\n"
        f"💰 Yangi balansingiz: <b>{money(balance)} coin</b>",
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )


# =========================================================
# 📥 DEPOZIT VA 📤 PUL CHIQARISH
# =========================================================
@dp.callback_query(F.data == "deposit_money")
async def deposit_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(DepositState.waiting_amount)
    await callback.message.edit_text(
        "📥 <b>DEPOZIT QILISH</b>\nQancha pul kiritmoqchisiz? (Min: 5 000 coin):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor qilish", callback_data="back_to_menu")]]),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()

@dp.message(DepositState.waiting_amount)
async def deposit_amount_process(message: Message, state: FSMContext):
    if not message.text or not message.text.isdigit():
        await message.answer("❌ Faqat raqam kiriting:")
        return

    amount = int(message.text)
    if amount < 5000:
        await message.answer("❌ Minimal kiritish summasi 5 000 coin!")
        return

    await state.update_data(deposit_amount=amount)
    await state.set_state(DepositState.waiting_proof)
    card_num = await get_card_number()
    
    await message.answer(
        f"💳 <b>Karta raqami:</b> <code>{card_num}</code>\n"
        f"💰 Summa: <b>{money(amount)} so'm</b>\n\n"
        f"📸 To'lov cheki skrinshotini yuboring:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor qilish", callback_data="back_to_menu")]]),
        parse_mode=ParseMode.HTML
    )

@dp.message(DepositState.waiting_proof)
async def deposit_proof_process(message: Message, state: FSMContext):
    if not message.photo:
        await message.answer("❌ Skrinshot yuborilmadi! To'lov chekini yuboring.")
        return

    data = await state.get_data()
    amount = data.get("deposit_amount")
    user_id = message.from_user.id
    username = f"@{message.from_user.username}" if message.from_user.username else "Mavjud emas"

    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"dep_app:{user_id}:{amount}"),
            InlineKeyboardButton(text="❌ Rad etish", callback_data=f"dep_rej:{user_id}")
        ]
    ])

    await bot.send_photo(
        chat_id=ADMIN_ID,
        photo=message.photo[-1].file_id,
        caption=f"📥 <b>YANGI DEPOZIT</b>\n👤 Foydalanuvchi: {message.from_user.full_name} ({username})\n💰 Summa: {money(amount)}",
        reply_markup=admin_kb,
        parse_mode=ParseMode.HTML
    )

    await state.clear()
    await message.answer("✅ Chek adminga yuborildi!", reply_markup=main_menu(user_id))


@dp.callback_query(F.data == "withdraw_money")
async def withdraw_start(callback: CallbackQuery, state: FSMContext):
    balance = await get_balance(callback.from_user.id)
    if balance < 10000:
        await callback.answer("❌ Minimal chiqarish summasi 10 000 coin!", show_alert=True)
        return

    await state.set_state(WithdrawState.waiting_amount)
    await callback.message.edit_text(
        f"📤 <b>PUL CHIQARISH</b>\nBalans: {money(balance)} coin\nQancha chiqarmoqchisiz?:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor qilish", callback_data="back_to_menu")]]),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()

@dp.message(WithdrawState.waiting_amount)
async def withdraw_amount_process(message: Message, state: FSMContext):
    if not message.text or not message.text.isdigit():
        await message.answer("❌ Faqat raqam kiriting:")
        return

    amount = int(message.text)
    user_id = message.from_user.id
    balance = await get_balance(user_id)

    if amount < 10000 or amount > balance:
        await message.answer("❌ Miqdor noto'g'ri yoki balansda mablag' yetarli emas!")
        return

    await state.update_data(withdraw_amount=amount)
    await state.set_state(WithdrawState.waiting_card_and_name)
    await message.answer("💳 Karta raqamingiz va ism-sharifingizni yuboring:", reply_markup=main_menu(user_id))

@dp.message(WithdrawState.waiting_card_and_name)
async def withdraw_card_process(message: Message, state: FSMContext):
    data = await state.get_data()
    amount = data.get("withdraw_amount")
    user_id = message.from_user.id
    card_details = message.text.strip() if message.text else "Kiritilmagan"

    await change_balance(user_id, -amount)
    await state.clear()

    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ To'lab berildi", callback_data=f"with_app:{user_id}"),
            InlineKeyboardButton(text="❌ Rad etish", callback_data=f"with_rej:{user_id}:{amount}")
        ]
    ])

    await bot.send_message(
        chat_id=ADMIN_ID,
        text=f"📤 <b>PUL CHIQARISH SO'ROVI</b>\nID: {user_id}\nSumma: {money(amount)}\nKarta: {card_details}",
        reply_markup=admin_kb,
        parse_mode=ParseMode.HTML
    )
    await message.answer("✅ So'rov adminga yuborildi!", reply_markup=main_menu(user_id))


# =========================================================
# ADMIN CALLBACKS
# =========================================================
@dp.callback_query(F.data.startswith("dep_app:"))
async def approve_deposit(callback: CallbackQuery):
    _, u_id, amt = callback.data.split(":")
    user_id, amount = int(u_id), int(amt)
    await change_balance(user_id, amount)
    await set_user_deposited(user_id)
    await callback.answer("✅ Tasdiqlandi!")
    await callback.message.edit_caption(caption=callback.message.caption + "\n\n🟢 TASDIQLANDI", parse_mode=ParseMode.HTML)
    await bot.send_message(user_id, f"🎉 Hisobingizga +{money(amount)} qo'shildi!")

@dp.callback_query(F.data.startswith("dep_rej:"))
async def reject_deposit(callback: CallbackQuery):
    _, u_id = callback.data.split(":")
    await callback.answer("❌ Rad etildi!")
    await callback.message.edit_caption(caption=callback.message.caption + "\n\n🔴 RAD ETILDI", parse_mode=ParseMode.HTML)
    await bot.send_message(int(u_id), "❌ Depozit so'rovingiz rad etildi.")

@dp.callback_query(F.data.startswith("with_app:"))
async def approve_withdraw(callback: CallbackQuery):
    await callback.answer("✅ To'landi!")
    await callback.message.edit_text(callback.message.text + "\n\n🟢 TO'LAB BERILDI", parse_mode=ParseMode.HTML)

@dp.callback_query(F.data.startswith("with_rej:"))
async def reject_withdraw(callback: CallbackQuery):
    _, u_id, amt = callback.data.split(":")
    user_id, amount = int(u_id), int(amt)
    await change_balance(user_id, amount)
    await callback.answer("❌ Qaytarildi!")
    await callback.message.edit_text(callback.message.text + "\n\n🔴 RAD ETILDI (PUL QAYTARILDI)", parse_mode=ParseMode.HTML)
    await bot.send_message(user_id, f"❌ Pul chiqarish rad etildi, {money(amount)} balansga qaytarildi.")


# =========================================================
# ADMIN PANEL
# =========================================================
@dp.callback_query(F.data == "admin_panel")
async def admin_panel_handler(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Siz admin emassiz!", show_alert=True)
        return
    await state.clear()
    users_count = await get_users_count()
    card_num = await get_card_number()
    
    await callback.message.edit_text(
        f"👨‍💼 <b>ADMIN PANEL</b>\n👥 Foydalanuvchilar: {users_count} ta\n💳 Karta: <code>{card_num}</code>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Kartani o'zgartirish", callback_data="set_card")],
            [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_to_menu")]
        ]),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()

@dp.callback_query(F.data == "set_card")
async def set_card_prompt(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    await state.set_state(AdminState.waiting_card_number)
    await callback.message.edit_text("💳 Yangi karta raqamini kiriting:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor qilish", callback_data="admin_panel")]]))
    await callback.answer()

@dp.message(AdminState.waiting_card_number)
async def process_set_card(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    new_card = message.text.strip() if message.text else ""
    await set_card_number(new_card)
    await state.clear()
    await message.answer(f"✅ Karta yangilandi: {new_card}", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="👨‍💼 Admin Panel", callback_data="admin_panel")]]))


# =========================================================
# MAIN
# =========================================================
async def main():
    logging.basicConfig(level=logging.INFO)
    await init_db()
    await bot.delete_webhook(drop_pending_updates=True)
    print("🤖 Bot muvaffaqiyatli ishga tushdi!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Bot to'xtatildi!")
