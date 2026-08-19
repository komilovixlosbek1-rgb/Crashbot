import asyncio
import logging
import os
import sqlite3
import time
from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

TOKEN = "8925068569:AAF0Rc5EgaUzBFLvwieF_IBnqQcmAC7n7aQ"
ADMIN_ID = 8252674515  # Admin Telegram ID SI
DB_NAME = "crash_bot.db"

bot = Bot(token=TOKEN)
dp = Dispatcher()

# Mines o'yinining statistikasini saqlash uchun
user_game_steps = {}
user_total_games = {}
TARGET_CRASH_X = 2.00
ACTIVE_GAMES = {}

def get_mines_keyboard():
    keyboard = []
    for r in range(3):
        row = []
        for c in range(3):
            row.append(InlineKeyboardButton(text="❓", callback_data=f"mine_{r}_{c}"))
        keyboard.append(row)
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

@dp.message(Command("mines"))
async def start_mines(message: Message):
    user_id = message.from_user.id
    
    if user_id not in user_total_games:
        user_total_games[user_id] = 1
    else:
        user_total_games[user_id] += 1
        
    if user_total_games[user_id] > 9:
        user_total_games[user_id] = 1
        
    user_game_steps[user_id] = 0
    game_num = user_total_games[user_id]
    
    await message.answer(
        f"💣 **Mines o'yini boshlandi!** (O'yin #{game_num})\n\nKataklardan birini tanlang:",
        reply_markup=get_mines_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )

@dp.callback_query(F.data.startswith("mine_"))
async def process_mine_click(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    if user_id not in user_game_steps:
        user_game_steps[user_id] = 0
    if user_id not in user_total_games:
        user_total_games[user_id] = 1

    game_num = user_total_games[user_id]
    step = user_game_steps[user_id] + 1
    user_game_steps[user_id] = step

    is_boom = False
    is_win = False

    if game_num == 1:
        if step > 3:
            is_boom = True
    elif game_num in [2, 3, 4]:
        is_boom = True
    elif game_num == 5:
        if step > 3:
            is_boom = True
    elif game_num in [6, 7]:
        is_boom = True
    elif game_num in [8, 9]:
        if step >= 3:
            is_win = True

    if is_win:
        await callback.message.edit_text(
            "🎉 **Tabriklaymiz! Siz 3 ta qadamni muvaffaqiyatli bosib o'tdingiz va yutdingiz!** 🏆\n\nQaytadan o'ynash uchun /mines ni bosing.",
            reply_markup=None,
            parse_mode=ParseMode.MARKDOWN
        )
    elif is_boom:
        await callback.message.edit_text(
            f"💥 **Boom! Qadam #{step}. Minaga bosib yutqazdingiz!** 😢\n\nQaytadan o'ynash uchun /mines ni bosing.",
            reply_markup=None,
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await callback.answer(f"✅ Qadam #{step}: Xavfsiz katak! Davom eting.", show_alert=False)

# =========================================================
# MA'LUMOTLAR BAZASI FUNKSIYALARI
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
    await asyncio.to_thread(db_query, "INSERT OR REPLACE INTO settings (key, value) VALUES ('card_number', ?)", (card,), commit=True)

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
    if row and row[0] == 1:
        return True
    return False

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
class CrashState(StatesGroup):
    waiting_bet = State()

class AdminState(StatesGroup):
    waiting_crash_x = State()
    waiting_card_number = State()

class DepositState(StatesGroup):
    waiting_amount = State()
    waiting_proof = State()

class WithdrawState(StatesGroup):
    waiting_amount = State()
    waiting_card_and_name = State()

# =========================================================
# KLAVIATURALAR
# =========================================================
def main_menu(user_id: int):
    kb = [
        [InlineKeyboardButton(text="🚀 Crash O'yini", callback_data="play_crash")],
        [InlineKeyboardButton(text="💣 Mines O'yini (/mines)", callback_data="play_mines_menu")],
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

# =========================================================
# START VA ASOSIY MENYU
# =========================================================
@dp.message(F.text == "/start")
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    balance = await get_balance(user_id)

    await message.answer(
        f"✨ <b>XUSH KELIBSIZ, {message.from_user.first_name}!</b> ✨\n"
        f"──────────────────────────\n"
        f"🚀 <b>Crash</b> va <b>Mines</b> o'yinlarida qatnashing!\n\n"
        f"💰 <b>Balansingiz:</b> {money(balance)} coin\n"
        f"──────────────────────────",
        reply_markup=main_menu(user_id),
        parse_mode=ParseMode.HTML
    )

@dp.callback_query(F.data == "back_to_menu")
async def back_to_menu_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    balance = await get_balance(callback.from_user.id)
    await callback.message.edit_text(
        f"🏠 <b>ASOSIY MENYU</b>\n"
        f"──────────────────────────\n"
        f"💰 <b>Balansingiz:</b> {money(balance)} coin",
        reply_markup=main_menu(callback.from_user.id),
        parse_mode=ParseMode.HTML
    )

@dp.callback_query(F.data == "my_balance")
async def my_balance_handler(callback: CallbackQuery):
    balance = await get_balance(callback.from_user.id)
    await callback.answer(f"💰 Balansingiz: {money(balance)} coin", show_alert=True)

@dp.callback_query(F.data == "play_mines_menu")
async def play_mines_menu_handler(callback: CallbackQuery):
    await callback.message.edit_text(
        "💣 <b>MINES O'YINI</b>\n"
        "──────────────────────────\n"
        "O'yinni boshlash uchun quyidagi tugmani bosing yoki /mines buyrug'ini yuboring:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎮 O'yinni boshlash (/mines)", callback_data="start_mines_action")],
            [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_to_menu")]
        ]),
        parse_mode=ParseMode.HTML
    )

@dp.callback_query(F.data == "start_mines_action")
async def start_mines_action_handler(callback: CallbackQuery):
    await start_mines(callback.message)

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
            f"⚠️ Mining bo'limiga ulanish uchun kamida <b>1 marta depozit</b> qilishingiz kerak!\n\n"
            f"💡 Depozit qilsangiz ulanasiz va har 1 soatda 100 coin bonus olish imkoniyatiga ega bo'lasiz.",
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )
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
            f"🎁 <b>Tayyor!</b> Balansingizga 100 coin qo'shishingiz mumkin.\n\n"
            f"💡 Har 1 soatda kiring va bepul bonusni oling!\n"
            f"──────────────────────────",
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
            f"⏳ <b>Keyingi bonus tayyor bo'lishiga:</b>\n"
            f"👉 <b>{minutes} daqiqa {seconds} soniya</b> qoldi.\n\n"
            f"💡 1 soat o'tgach qayta kiring va 100 coinni oling!",
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )

@dp.callback_query(F.data == "claim_mining")
async def claim_mining_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    if not await check_user_deposited(user_id):
        await callback.answer("⚠️ Avval depozit qilishingiz kerak!", show_alert=True)
        return

    current_time = int(time.time())
    last_claim = await get_last_claim(user_id)
    
    cooldown = 3600
    elapsed = current_time - last_claim

    if elapsed < cooldown:
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
        f"──────────────────────────\n"
        f"✅ <b>100 coin muvaffaqiyatli olindi!</b>\n"
        f"💰 Yangi balansingiz: <b>{money(balance)} coin</b>\n\n"
        f"⏳ Keyingi bonus 1 soatdan keyin tayyor bo'ladi.",
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )

# =========================================================
# 📥 DEPOZIT TIZIMI
# =========================================================
@dp.callback_query(F.data == "deposit_money")
async def deposit_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(DepositState.waiting_amount)
    await callback.message.edit_text(
        "📥 <b>DEPOZIT QILISH</b>\n"
        "──────────────────────────\n"
        "Qancha pul kiritmoqchisiz?\n"
        "⚠️ <b>Minimal summa:</b> 5 000 coin\n\n"
        "Summani faqat raqamlarda kiriting:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor qilish", callback_data="back_to_menu")]]),
        parse_mode=ParseMode.HTML
    )

@dp.message(DepositState.waiting_amount)
async def deposit_amount_process(message: Message, state: FSMContext):
    if not message.text or not message.text.isdigit():
        await message.answer("❌ Faqat musbat raqam kiriting:")
        return

    amount = int(message.text)
    if amount < 5000:
        await message.answer("❌ <b>Minimal kiritish summasi 5 000 coin!</b>\nQayta kiriting (5000 dan kam bo'lmasin):", parse_mode=ParseMode.HTML)
        return

    await state.update_data(deposit_amount=amount)
    await state.set_state(DepositState.waiting_proof)
    
    card_num = await get_card_number()
    await message.answer(
        f"💳 <b>TO'LOV MA'LUMOTLARI:</b>\n"
        f"──────────────────────────\n"
        f"💰 To'lanishi kerak bo'lgan summa: <b>{money(amount)} so'm/coin</b>\n"
        f"💳 Karta raqami: <code>{card_num}</code>\n"
        f"──────────────────────────\n"
        f"⚡️ <b>Yuqoridagi karta raqamiga to'lov qiling.</b>\n\n"
        f"📸 <b>To'lov cheki SKRINSHOTINI (rasmini) yuboring!</b>\n"
        f"<i>(Karta egasining ismini rasm izohiga (caption) yozib yuboring)</i>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor qilish", callback_data="back_to_menu")]]),
        parse_mode=ParseMode.HTML
    )

@dp.message(DepositState.waiting_proof)
async def deposit_proof_process(message: Message, state: FSMContext):
    if not message.photo:
        await message.answer(
            "❌ <b>Skrinshot yuborilmadi!</b>\n\n"
            "⚠️ To'lovni tasdiqlash uchun <b>to'lov cheki skrinshotini (rasmini)</b> yuborishingiz shart.\n"
            "Faqat matnli xabarlar qabul qilinmaydi!",
            parse_mode=ParseMode.HTML
        )
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

    caption_text = (
        f"📥 <b>YANGI DEPOZIT SO'ROVI</b>\n"
        f"──────────────────────────\n"
        f"👤 Foydalanuvchi: {message.from_user.full_name} ({username})\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"💰 Summa: <b>{money(amount)} coin</b>\n"
        f"📝 Izoh/Ism: <b>{message.caption or 'Kiritilmagan'}</b>\n"
        f"──────────────────────────"
    )

    await bot.send_photo(
        chat_id=ADMIN_ID,
        photo=message.photo[-1].file_id,
        caption=caption_text,
        reply_markup=admin_kb,
        parse_mode=ParseMode.HTML
    )

    await state.clear()
    await message.answer(
        "✅ <b>To'lov cheki (skrinshot) adminga yuborildi!</b>\n"
        "Tekshiruvdan so'ng balansingizga pul qo'shiladi.",
        reply_markup=main_menu(user_id),
        parse_mode=ParseMode.HTML
    )

# =========================================================
# 📤 PUL CHIQARISH TIZIMI
# =========================================================
@dp.callback_query(F.data == "withdraw_money")
async def withdraw_start(callback: CallbackQuery, state: FSMContext):
    balance = await get_balance(callback.from_user.id)
    if balance < 10000:
        await callback.answer("❌ Minimal chiqarish summasi 10 000 coin! Balansingizda mablag' yetarli emas.", show_alert=True)
        return

    await state.set_state(WithdrawState.waiting_amount)
    await callback.message.edit_text(
        f"📤 <b>PUL CHIQARISH</b>\n"
        f"──────────────────────────\n"
        f"💰 Balansingiz: <b>{money(balance)} coin</b>\n"
        f"⚠️ <b>Minimal chiqarish summasi:</b> 10 000 coin\n\n"
        f"Qancha pul chiqarmoqchisiz? Summani yozing:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor qilish", callback_data="back_to_menu")]]),
        parse_mode=ParseMode.HTML
    )

@dp.message(WithdrawState.waiting_amount)
async def withdraw_amount_process(message: Message, state: FSMContext):
    if not message.text or not message.text.isdigit():
        await message.answer("❌ Faqat musbat raqam kiriting:")
        return

    amount = int(message.text)
    user_id = message.from_user.id
    balance = await get_balance(user_id)

    if amount < 10000:
        await message.answer("❌ Minimal chiqarish summasi 10 000 coin! Qayta kiriting:")
        return

    if amount > balance:
        await state.clear()
        await message.answer(
            "❌ <b>Balansingizda yetarli mablag' mavjud emas!</b>",
            reply_markup=main_menu(user_id),
            parse_mode=ParseMode.HTML
        )
        return

    await state.update_data(withdraw_amount=amount)
    await state.set_state(WithdrawState.waiting_card_and_name)

    await message.answer(
        "💳 <b>Karta raqamingiz va Karta egasining ismini yuboring:</b>\n"
        "Misol: <i>8600 1234 5678 9012 — Eshmatov Toshmat</i>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor qilish", callback_data="back_to_menu")]]),
        parse_mode=ParseMode.HTML
    )

@dp.message(WithdrawState.waiting_card_and_name)
async def withdraw_card_process(message: Message, state: FSMContext):
    data = await state.get_data()
    amount = data.get("withdraw_amount")
    user_id = message.from_user.id
    card_details = message.text.strip() if message.text else "Kiritilmagan"

    balance = await get_balance(user_id)
    if amount > balance:
        await state.clear()
        await message.answer("❌ Balansda mablag' yetarli emas!", reply_markup=main_menu(user_id))
        return

    await change_balance(user_id, -amount)
    await state.clear()

    username = f"@{message.from_user.username}" if message.from_user.username else "Mavjud emas"
    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ To'lab berildi", callback_data=f"with_app:{user_id}"),
            InlineKeyboardButton(text="❌ Rad etish (Qaytarish)", callback_data=f"with_rej:{user_id}:{amount}")
        ]
    ])

    await bot.send_message(
        chat_id=ADMIN_ID,
        text=f"📤 <b>PUL CHIQARISH SO'ROVI</b>\n"
             f"──────────────────────────\n"
             f"👤 Foydalanuvchi: {message.from_user.full_name} ({username})\n"
             f"🆔 ID: <code>{user_id}</code>\n"
             f"💰 Summa: <b>{money(amount)} coin</b>\n"
             f"💳 Karta va Ism: <code>{card_details}</code>\n"
             f"──────────────────────────",
        reply_markup=admin_kb,
        parse_mode=ParseMode.HTML
    )

    await message.answer(
        "✅ <b>Pul chiqarish so'rovingiz qabul qilindi!</b>\n"
        "Tez orada admin pulingizni kartangizga o'tkazib beradi.",
        reply_markup=main_menu(user_id),
        parse_mode=ParseMode.HTML
    )

# =========================================================
# 👨‍💼 ADMIN HANDLERLARI
# =========================================================
@dp.callback_query(F.data.startswith("dep_app:"))
async def approve_deposit(callback: CallbackQuery):
    _, u_id, amt = callback.data.split(":")
    user_id, amount = int(u_id), int(amt)

    await change_balance(user_id, amount)
    await set_user_deposited(user_id)

    await callback.answer("✅ Depozit tasdiqlandi!")
    
    if callback.message.caption:
        await callback.message.edit_caption(caption=callback.message.caption + "\n\n🟢 <b>STATUS: TASDIQLANDI</b>", parse_mode=ParseMode.HTML)
    else:
        await callback.message.edit_text(callback.message.text + "\n\n🟢 <b>STATUS: TASDIQLANDI</b>", parse_mode=ParseMode.HTML)

    await bot.send_message(
        chat_id=user_id,
        text=f"🎉 <b>Hisobingiz to'ldirildi!</b>\n"
             f"💰 <b>+{money(amount)} coin</b> balansingizga qo'shildi.\n\n"
             f"🔓 <b>Mining bo'limi ham muvaffaqiyatli ochildi!</b>",
        parse_mode=ParseMode.HTML
    )

@dp.callback_query(F.data.startswith("dep_rej:"))
async def reject_deposit(callback: CallbackQuery):
    _, u_id = callback.data.split(":")
    user_id = int(u_id)

    await callback.answer("❌ Depozit rad etildi!")
    
    if callback.message.caption:
        await callback.message.edit_caption(caption=callback.message.caption + "\n\n🔴 <b>STATUS: RAD ETILDI</b>", parse_mode=ParseMode.HTML)
    else:
        await callback.message.edit_text(callback.message.text + "\n\n🔴 <b>STATUS: RAD ETILDI</b>", parse_mode=ParseMode.HTML)

    await bot.send_message(
        chat_id=user_id,
        text="❌ <b>Sizning depozit so'rovingiz admin tomonidan rad etildi.</b>",
        parse_mode=ParseMode.HTML
    )

@dp.callback_query(F.data.startswith("with_app:"))
async def approve_withdraw(callback: CallbackQuery):
    await callback.answer("✅ To'lov tasdiqlandi!")
    await callback.message.edit_text(callback.message.text + "\n\n🟢 <b>STATUS: TO'LAB BERILDI</b>", parse_mode=ParseMode.HTML)

@dp.callback_query(F.data.startswith("with_rej:"))
async def reject_withdraw(callback: CallbackQuery):
    _, u_id, amt = callback.data.split(":")
    user_id, amount = int(u_id), int(amt)

    await change_balance(user_id, amount)
    await callback.answer("❌ Rad etildi va pul balansga qaytarildi!")
    await callback.message.edit_text(callback.message.text + "\n\n🔴 <b>STATUS: RAD ETILDI (PUL QAYTARILDI)</b>", parse_mode=ParseMode.HTML)

    await bot.send_message(
        chat_id=user_id,
        text=f"❌ <b>Pul chiqarish so'rovingiz rad etildi!</b>\n💰 <b>{money(amount)} coin</b> balansingizga qaytarildi.",
        parse_mode=ParseMode.HTML
    )

@dp.callback_query(F.data == "admin_panel")
async def admin_panel_handler(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    await state.clear()
    
    users_count = await get_users_count()
    card_num = await get_card_number()
    
    await callback.message.edit_text(
        f"👨‍💼 <b>ADMIN PANEL</b>\n"
        f"──────────────────────────\n"
        f"👥 <b>Jami foydalanuvchilar:</b> {users_count} ta\n"
        f"🎯 <b>Hozirgi Crash X:</b> {TARGET_CRASH_X:.2f}x\n"
        f"💳 <b>Hozirgi Karta raqami:</b> <code>{card_num}</code>\n"
        f"──────────────────────────",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚙️ Crash X ni o'zgartirish", callback_data="set_crash_x")],
            [InlineKeyboardButton(text="💳 Kartani o'zgartirish", callback_data="set_card")],
            [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_to_menu")]
        ]),
        parse_mode=ParseMode.HTML
    )

@dp.callback_query(F.data == "set_card")
async def set_card_prompt(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    await state.set_state(AdminState.waiting_card_number)
    await callback.message.edit_text(
        "💳 <b>YANGI KARTA RAQAMINI KIRITING:</b>\n"
        "Masalan: <code>8600 1234 5678 9012</code>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor qilish", callback_data="admin_panel")]]),
        parse_mode=ParseMode.HTML
    )

@dp.message(AdminState.waiting_card_number)
async def process_set_card(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    
    new_card = message.text.strip() if message.text else ""
    await set_card_number(new_card)
    await state.clear()
    
    await message.answer(
        f"✅ <b>Karta raqami yangilandi!</b>\n\nYangi karta: <code>{new_card}</code>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="👨‍💼 Admin Panel", callback_data="admin_panel")]]),
        parse_mode=ParseMode.HTML
    )

@dp.callback_query(F.data == "set_crash_x")
async def set_crash_x_prompt(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    await state.set_state(AdminState.waiting_crash_x)
    await callback.message.edit_text(
        f"⚙️ <b>YANGI CRASH X QIYMATINI KIRITING:</b>\n"
        f"Misol uchun: <code>1.5</code>, <code>2.8</code>, <code>5.0</code>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor qilish", callback_data="admin_panel")]]),
        parse_mode=ParseMode.HTML
    )

@dp.message(AdminState.waiting_crash_x)
async def process_set_crash_x(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    
    global TARGET_CRASH_X
    try:
        val = float(message.text.replace(",", "."))
        if val <= 1.0:
            await message.answer("❌ Qiymat 1.01 dan yuqori bo'lishi kerak!")
            return
        TARGET_CRASH_X = round(val, 2)
        await state.clear()
        await message.answer(
            f"✅ <b>Crash X muvaffaqiyatli o'zgartirildi! ({TARGET_CRASH_X:.2f}x)</b>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="👨‍💼 Admin Panel", callback_data="admin_panel")]]),
            parse_mode=ParseMode.HTML
        )
    except ValueError:
        await message.answer("❌ Noto'g'ri format! Faqat son kiriting (masalan: 2.5):")

# =========================================================
# 🚀 CRASH O'YINI MANTIQLARI
# =========================================================
@dp.callback_query(F.data == "play_crash")
async def play_crash_menu(callback: CallbackQuery, state: FSMContext):
    await state.set_state(CrashState.waiting_bet)
    balance = await get_balance(callback.from_user.id)
    await callback.message.edit_text(
        f"🚀 <b>CRASH O'YINI</b>\n"
        f"──────────────────────────\n"
        f"📈 Raketa parvozini kuzating va portlashdan oldin pulni yechib oling!\n\n"
        f"💰 Balansingiz: <b>{money(balance)} coin</b>\n"
        f"Stavka miqdorini kiriting (min: 100 coin):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_to_menu")]]),
        parse_mode=ParseMode.HTML
    )

@dp.message(CrashState.waiting_bet)
async def process_crash_bet(message: Message, state: FSMContext):
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

    game_msg = await message.answer(
        f"🚀 <b>RAKETA PARVOZGA TAYYORLANMOQDA...</b>\n\n💰 Stavka: <b>{money(bet)} coin</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⏳ Tayyorlanmoqda...", callback_data="none")]]),
        parse_mode=ParseMode.HTML
    )
    
    asyncio.create_task(run_crash_flight(message.bot, user_id, bet, game_msg.message_id))

async def run_crash_flight(bot_inst, user_id, bet, message_id):
    current_multiplier = 1.00
    crash_at = TARGET_CRASH_X

    ACTIVE_GAMES[user_id] = {"bet": bet, "multiplier": 1.00, "status": "flying"}
    
    cash_out_keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🎯 PULNI OLISH (CASH OUT)", callback_data="crash_cashout")]]
    )

    try:
        while current_multiplier < crash_at:
            await asyncio.sleep(1.2)
            current_multiplier += 0.20
            
            if current_multiplier >= crash_at:
                current_multiplier = crash_at

            if user_id not in ACTIVE_GAMES or ACTIVE_GAMES[user_id].get("status") != "flying":
                return

            ACTIVE_GAMES[user_id]["multiplier"] = current_multiplier

            progress_val = min(int((current_multiplier - 1.0) * 2), 10)
            bar = "🟩" * progress_val + "⬜" * (10 - progress_val)

            try:
                await bot_inst.edit_message_text(
                    chat_id=user_id,
                    message_id=message_id,
                    text=f"🚀 <b>CRASH — RAKETA UCHMOQDA!</b>\n"
                         f"──────────────────────────\n"
                         f"     🚀 <b>{current_multiplier:.2f}x</b>\n"
                         f"──────────────────────────\n"
                         f"📊 <b>Balandlik:</b> [{bar}]\n"
                         f"💰 <b>Stavka:</b> {money(bet)} coin\n"
                         f"🎁 <b>Yutuq koeffitsiyenti:</b> {current_multiplier:.2f}x\n"
                         f"──────────────────────────\n"
                         f"⚡️ <i>Portlab ketishidan oldin pulni olib qoling!</i>",
                    reply_markup=cash_out_keyboard,
                    parse_mode=ParseMode.HTML
                )
            except Exception:
                pass

        if user_id in ACTIVE_GAMES and ACTIVE_GAMES[user_id]["status"] == "flying":
            ACTIVE_GAMES[user_id]["status"] = "crashed"
            await bot_inst.edit_message_text(
                chat_id=user_id,
                message_id=message_id,
                text=f"💥 <b>BOOOOOOOM! Raketa portlab ketdi! ({crash_at:.2f}x)</b>\n\n"
                     f"❌ Afsuski, vaqtida ulgurmadingiz va stavkangiz kuydi.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏠 Asosiy Menyu", callback_data="back_to_menu")]]),
                parse_mode=ParseMode.HTML
            )
            ACTIVE_GAMES.pop(user_id, None)
    except Exception as e:
        logging.error(f"Crash error: {e}")

@dp.callback_query(F.data == "crash_cashout")
async def crash_cashout_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    if user_id not in ACTIVE_GAMES or ACTIVE_GAMES[user_id]["status"] != "flying":
        await callback.answer("⚠️ Faol o'yin topilmadi yoki raketa allaqachon portlagan!", show_alert=True)
        return

    game = ACTIVE_GAMES[user_id]
    game["status"] = "cashed_out"
    
    bet = game["bet"]
    multiplier = game["multiplier"]
    win_amount = int(bet * multiplier)

    await change_balance(user_id, win_amount)
    ACTIVE_GAMES.pop(user_id, None)

    await callback.message.edit_text(
        f"🎉 <b>TABRIKLAYMIZ! MUVAFFAQIYATLI PULNI YECHDINGIZ!</b>\n"
        f"──────────────────────────\n"
        f"💰 Stavka: <b>{money(bet)} coin</b>\n"
        f"📈 Koeffitsiyent: <b>{multiplier:.2f}x</b>\n"
        f"🏆 Yutuq: <b>+{money(win_amount)} coin</b>\n"
        f"──────────────────────────",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏠 Asosiy Menyu", callback_data="back_to_menu")]]),
        parse_mode=ParseMode.HTML
    )

# =========================================================
# BOTNI ISHGA TUSHIRISH
# =========================================================
async def main():
    logging.basicConfig(level=logging.INFO)
    await init_db()
    print("Bot ishga tushdi...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
