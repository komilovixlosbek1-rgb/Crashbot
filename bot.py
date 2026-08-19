import asyncio
import logging
import os
import sqlite3
import random
import time
from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

TOKEN = "8925068569:AAF0Rc5EgaUzBFLvwieF_IBnqQcmAC7n7aQ"
ADMIN_ID = 8252674515  # Admin Telegram ID SI
DB_NAME = "crash_bot.db"

bot = Bot(token=TOKEN)
dp = Dispatcher()

ACTIVE_GAMES = {}


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
            username TEXT,
            balance INTEGER DEFAULT 0,
            has_deposited INTEGER DEFAULT 0
        )''',
        commit=True
    )
    # Agar jadval ilgaridan mavjud bo'lsa, ustunlarni tekshirib qo'shamiz
    try:
        await asyncio.to_thread(db_query, '''ALTER TABLE users ADD COLUMN has_deposited INTEGER DEFAULT 0''', commit=True)
    except Exception:
        pass
    try:
        await asyncio.to_thread(db_query, '''ALTER TABLE users ADD COLUMN username TEXT''', commit=True)
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
    # O'yinlar tarixi jadvali
    await asyncio.to_thread(
        db_query,
        '''CREATE TABLE IF NOT EXISTS crash_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            multiplier REAL,
            mode TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )''',
        commit=True
    )
    # Tranzaksiyalar jadvali
    await asyncio.to_thread(
        db_query,
        '''CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            type TEXT,
            amount REAL,
            status TEXT DEFAULT 'Kutilmoqda',
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )''',
        commit=True
    )

    # Boshlang'ich sozlamalar
    card = await asyncio.to_thread(db_query, "SELECT value FROM settings WHERE key = 'card_number'", fetchone=True)
    if not card:
        await asyncio.to_thread(db_query, "INSERT INTO settings (key, value) VALUES ('card_number', 'Kiritilmagan')", commit=True)
    
    mode = await asyncio.to_thread(db_query, "SELECT value FROM settings WHERE key = 'crash_mode'", fetchone=True)
    if not mode:
        await asyncio.to_thread(db_query, "INSERT INTO settings (key, value) VALUES ('crash_mode', 'admin')", commit=True)

    mult = await asyncio.to_thread(db_query, "SELECT value FROM settings WHERE key = 'admin_multiplier'", fetchone=True)
    if not mult:
        await asyncio.to_thread(db_query, "INSERT INTO settings (key, value) VALUES ('admin_multiplier', '2.00')", commit=True)

    streak = await asyncio.to_thread(db_query, "SELECT value FROM settings WHERE key = 'admin_streak'", fetchone=True)
    if not streak:
        await asyncio.to_thread(db_query, "INSERT INTO settings (key, value) VALUES ('admin_streak', '0')", commit=True)

async def get_setting(key: str) -> str:
    row = await asyncio.to_thread(db_query, "SELECT value FROM settings WHERE key = ?", (key,), fetchone=True)
    return row[0] if row else ""

async def update_setting(key: str, value: str):
    await asyncio.to_thread(db_query, "UPDATE settings SET value = ? WHERE key = ?", (str(value), key), commit=True)

async def get_card_number() -> str:
    return await get_setting("card_number")

async def set_card_number(card: str):
    await update_setting("card_number", card)

async def get_balance(user_id: int, username: str = None) -> int:
    row = await asyncio.to_thread(db_query, "SELECT balance FROM users WHERE user_id = ?", (user_id,), fetchone=True)
    if row:
        return row[0]
    else:
        uname = username or "Noma'lum"
        await asyncio.to_thread(db_query, "INSERT INTO users (user_id, username, balance, has_deposited) VALUES (?, ?, 0, 0)", (user_id, uname), commit=True)
        return 0

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

fn = lambda val: f"{val:,}".replace(",", " ")


# =========================================================
# FSM HOLATLARI
# =========================================================
class CrashState(StatesGroup):
    waiting_bet = State()

class AdminState(StatesGroup):
    waiting_crash_x = State()
    waiting_card_number = State()
    waiting_user_id = State()
    waiting_amount = State()
    waiting_broadcast = State()

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
    username = f"@{message.from_user.username}" if message.from_user.username else message.from_user.full_name
    balance = await get_balance(user_id, username)

    await message.answer(
        f"✨ <b>XUSH KELIBSIZ, {message.from_user.first_name}!</b> ✨\n"
        f"──────────────────────────\n"
        f"🚀 <b>Crash</b> o'yinida qatnashing va pul yutib oling!\n\n"
        f"💰 <b>Balansingiz:</b> {fn(balance)} coin\n"
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
        f"💰 <b>Balansingiz:</b> {fn(balance)} coin",
        reply_markup=main_menu(callback.from_user.id),
        parse_mode=ParseMode.HTML
    )

@dp.callback_query(F.data == "my_balance")
async def my_balance_handler(callback: CallbackQuery):
    balance = await get_balance(callback.from_user.id)
    await callback.answer(f"💰 Balansingiz: {fn(balance)} coin", show_alert=True)


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
            f"💡 Depozit qilsangiz har 1 soatda 100 coin bonus olish imkoniyatiga ega bo'lasiz.",
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
            f"💡 Har 1 soatda kiring va bepul bonusni oling!",
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
        f"──────────────────────────\n"
        f"✅ <b>100 coin olindi!</b> Yangi balans: <b>{fn(balance)} coin</b>",
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )


# =========================================================
# 📥 DEPOZIT VA 📤 PUL CHIQARISH TIZIMLARI
# =========================================================
@dp.callback_query(F.data == "deposit_money")
async def deposit_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(DepositState.waiting_amount)
    await callback.message.edit_text(
        "📥 <b>DEPOZIT QILISH</b>\n"
        "──────────────────────────\n"
        "Qancha pul kiritmoqchisiz? (Min: 5 000 coin)\nSummani raqamda yozing:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor qilish", callback_data="back_to_menu")]]),
        parse_mode=ParseMode.HTML
    )

@dp.message(DepositState.waiting_amount)
async def deposit_amount_process(message: Message, state: FSMContext):
    if not message.text or not message.text.isdigit():
        await message.answer("❌ Faqat raqam kiriting:")
        return
    amount = int(message.text)
    if amount < 5000:
        await message.answer("❌ Minimal summa 5 000 coin!")
        return

    await state.update_data(deposit_amount=amount)
    await state.set_state(DepositState.waiting_proof)
    card_num = await get_card_number()
    await message.answer(
        f"💳 <b>TO'LOV MA'LUMOTLARI:</b>\n"
        f"Summa: <b>{fn(amount)} so'm/coin</b>\n"
        f"Karta: <code>{card_num}</code>\n\n"
        f"📸 <b>To'lov cheki skrinshotini yuboring!</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor qilish", callback_data="back_to_menu")]]),
        parse_mode=ParseMode.HTML
    )

@dp.message(DepositState.waiting_proof)
async def deposit_proof_process(message: Message, state: FSMContext):
    if not message.photo:
        await message.answer("❌ Iltimos, chek skrinshotini rasm ko'rinishida yuboring!")
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
        caption=f"📥 <b>YANGI DEPOZIT SO'ROVI</b>\n"
                f"Foydalanuvchi: {message.from_user.full_name} ({username})\n"
                f"ID: <code>{user_id}</code>\n"
                f"Summa: <b>{fn(amount)} coin</b>\n"
                f"Izoh: {message.caption or 'Kiritilmagan'}",
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
        f"📤 <b>PUL CHIQARISH</b>\nBalans: <b>{fn(balance)} coin</b>\nQancha chiqarmoqchisiz?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor qilish", callback_data="back_to_menu")]]),
        parse_mode=ParseMode.HTML
    )

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
    await message.answer("💳 Karta raqamingiz va ism-sharifingizni yuboring (Masalan: 8600... — Ism):")

@dp.message(WithdrawState.waiting_card_and_name)
async def withdraw_card_process(message: Message, state: FSMContext):
    data = await state.get_data()
    amount = data.get("withdraw_amount")
    user_id = message.from_user.id
    card_details = message.text.strip()

    await change_balance(user_id, -amount)
    await state.clear()

    username = f"@{message.from_user.username}" if message.from_user.username else "Mavjud emas"
    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ To'lab berildi", callback_data=f"with_app:{user_id}"),
            InlineKeyboardButton(text="❌ Rad etish", callback_data=f"with_rej:{user_id}:{amount}")
        ]
    ])

    await bot.send_message(
        chat_id=ADMIN_ID,
        text=f"📤 <b>PUL CHIQARISH SO'ROVI</b>\n"
             f"Foydalanuvchi: {message.from_user.full_name} ({username})\n"
             f"ID: <code>{user_id}</code>\n"
             f"Summa: <b>{fn(amount)} coin</b>\n"
             f"Karta: <code>{card_details}</code>",
        reply_markup=admin_kb,
        parse_mode=ParseMode.HTML
    )
    await message.answer("✅ So'rov yuborildi!", reply_markup=main_menu(user_id))


# =========================================================
# ADMIN AKSIYALARI VA TASDIQLASH
# =========================================================
@dp.callback_query(F.data.startswith("dep_app:"))
async def approve_deposit(callback: CallbackQuery):
    _, u_id, amt = callback.data.split(":")
    user_id, amount = int(u_id), int(amt)
    await change_balance(user_id, amount)
    await set_user_deposited(user_id)
    await callback.answer("✅ Tasdiqlandi!")
    await callback.message.edit_caption(caption=callback.message.caption + "\n\n🟢 <b>STATUS: TASDIQLANDI</b>", parse_mode=ParseMode.HTML)
    await bot.send_message(user_id, f"🎉 Hisobingizga +{fn(amount)} coin qo'shildi va Mining ochildi!", parse_mode=ParseMode.HTML)

@dp.callback_query(F.data.startswith("dep_rej:"))
async def reject_deposit(callback: CallbackQuery):
    _, u_id = callback.data.split(":")
    await callback.answer("❌ Rad etildi!")
    await callback.message.edit_caption(caption=callback.message.caption + "\n\n🔴 <b>STATUS: RAD ETILDI</b>", parse_mode=ParseMode.HTML)
    await bot.send_message(int(u_id), "❌ Depozit so'rovingiz rad etildi.", parse_mode=ParseMode.HTML)

@dp.callback_query(F.data.startswith("with_app:"))
async def approve_withdraw(callback: CallbackQuery):
    await callback.answer("✅ To'landi!")
    await callback.message.edit_text(callback.message.text + "\n\n🟢 <b>STATUS: TO'LAB BERILDI</b>", parse_mode=ParseMode.HTML)

@dp.callback_query(F.data.startswith("with_rej:"))
async def reject_withdraw(callback: CallbackQuery):
    _, u_id, amt = callback.data.split(":")
    user_id, amount = int(u_id), int(amt)
    await change_balance(user_id, amount)
    await callback.answer("❌ Qaytarildi!")
    await callback.message.edit_text(callback.message.text + "\n\n🔴 <b>STATUS: RAD ETILDI (PUL QAYTARILDI)</b>", parse_mode=ParseMode.HTML)
    await bot.send_message(user_id, f"❌ Pul chiqarish so'rovingiz rad etilib, {fn(amount)} coin balansga qaytarildi.", parse_mode=ParseMode.HTML)


# =========================================================
# 👨‍💼 ADMIN PANEL
# =========================================================
@dp.callback_query(F.data == "admin_panel")
async def admin_panel_handler(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return
    await state.clear()
    users_count = await get_users_count()
    card_num = await get_card_number()
    cur_x = await get_setting("admin_multiplier")
    mode = await get_setting("crash_mode")
    
    await callback.message.edit_text(
        f"👨‍💼 <b>ADMIN PANEL</b>\n"
        f"──────────────────────────\n"
        f"👥 Jami foydalanuvchilar: <b>{users_count} ta</b>\n"
        f"🎯 Hozirgi Crash Rejim: <b>{mode.upper()}</b>\n"
        f"⚙️ Admin X qiymati: <b>{cur_x}x</b>\n"
        f"💳 Karta raqami: <code>{card_num}</code>\n"
        f"──────────────────────────",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👥 Foydalanuvchilar ro'yxati", callback_data="admin_users")],
            [InlineKeyboardButton(text="📊 Statistika", callback_data="admin_stats")],
            [InlineKeyboardButton(text="🎮 Crash O'yinlar tarixi", callback_data="admin_history")],
            [InlineKeyboardButton(text="⚙️ Crash X ni o'zgartirish", callback_data="set_crash_x")],
            [InlineKeyboardButton(text="💳 Kartani o'zgartirish", callback_data="set_card")],
            [InlineKeyboardButton(text="➕ Coin berish", callback_data="admin_add_coin")],
            [InlineKeyboardButton(text="➖ Coin ayirish", callback_data="admin_sub_coin")],
            [InlineKeyboardButton(text="📢 Xabar yuborish", callback_data="admin_broadcast")],
            [InlineKeyboardButton(text="🏠 Asosiy menyu", callback_data="back_to_menu")]
        ]),
        parse_mode=ParseMode.HTML
    )

@dp.callback_query(F.data == "admin_users")
async def admin_users_callback(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    count = await get_users_count()
    await callback.answer(f"Jami foydalanuvchilar: {count} ta", show_alert=True)

@dp.callback_query(F.data == "admin_stats")
async def admin_stats_callback(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    row = await asyncio.to_thread(db_query, "SELECT COUNT(*), SUM(balance) FROM users", fetchone=True)
    games = await asyncio.to_thread(db_query, "SELECT COUNT(*) FROM crash_history", fetchone=True)
    await callback.answer(f"Foydalanuvchilar: {row[0]}\nUmumiy balans: {fn(row[1] or 0)} coin\nO'yinlar soni: {games[0]}", show_alert=True)

@dp.callback_query(F.data == "admin_history")
async def admin_history_callback(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    rows = await asyncio.to_thread(db_query, "SELECT multiplier, mode, timestamp FROM crash_history ORDER BY id DESC LIMIT 10", fetchall=True)
    text = "🎮 <b>Oxirgi 10 ta Crash o'yini:</b>\n\n"
    for r in rows:
        text += f"• X: <b>{r[0]}x</b> | Rejim: {r[1]} | {r[2]}\n"
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_panel")]]), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data == "set_card")
async def set_card_prompt(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return
    await state.set_state(AdminState.waiting_card_number)
    await callback.message.edit_text("💳 Yangi karta raqamini kiriting:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor", callback_data="admin_panel")]]))

@dp.message(AdminState.waiting_card_number)
async def process_set_card(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    await set_card_number(message.text.strip())
    await state.clear()
    await message.answer("✅ Karta yangilandi!", reply_markup=main_menu(message.from_user.id))

@dp.callback_query(F.data == "set_crash_x")
async def set_crash_x_prompt(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return
    await state.set_state(AdminState.waiting_crash_x)
    await callback.message.edit_text("⚙️ Admin X qiymatini kiriting (masalan: 2.50):", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor", callback_data="admin_panel")]]))

@dp.message(AdminState.waiting_crash_x)
async def process_set_crash_x(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    try:
        val = float(message.text.replace(",", "."))
        await update_setting("admin_multiplier", str(val))
        await state.clear()
        await message.answer(f"✅ Admin X {val}x ga o'zgartirildi!", reply_markup=main_menu(message.from_user.id))
    except ValueError:
        await message.answer("❌ Faqat raqam kiriting:")

@dp.callback_query(F.data == "admin_add_coin")
async def admin_add_coin(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return
    await state.set_state(AdminState.waiting_user_id)
    await state.update_data(action="add")
    await callback.message.edit_text("Foydalanuvchi Telegram ID raqamini yuboring:")

@dp.callback_query(F.data == "admin_sub_coin")
async def admin_sub_coin(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return
    await state.set_state(AdminState.waiting_user_id)
    await state.update_data(action="sub")
    await callback.message.edit_text("Foydalanuvchi Telegram ID raqamini yuboring:")

@dp.message(AdminState.waiting_user_id)
async def admin_get_uid(message: Message, state: FSMContext):
    try:
        uid = int(message.text)
        await state.update_data(target_id=uid)
        await state.set_state(AdminState.waiting_amount)
        await message.answer("Qancha miqdorda coin bermoqchi/ayirmoqchisiz? Miqdorni kiriting:")
    except ValueError:
        await message.answer("❌ ID raqam bo'lishi kerak:")

@dp.message(AdminState.waiting_amount)
async def admin_process_amount(message: Message, state: FSMContext):
    try:
        amount = int(message.text)
        data = await state.get_data()
        uid = data.get("target_id")
        action = data.get("action")
        if action == "add":
            await change_balance(uid, amount)
            await message.answer(f"✅ {uid} ga {amount} coin qo'shildi!")
        else:
            await change_balance(uid, -amount)
            await message.answer(f"✅ {uid} dan {amount} coin olib tashlandi!")
        await state.clear()
    except ValueError:
        await message.answer("❌ Faqat raqam kiriting:")

@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_prompt(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return
    await state.set_state(AdminState.waiting_broadcast)
    await callback.message.edit_text("📢 Barcha foydalanuvchilarga yuborish uchun xabar matnini kiriting:")

@dp.message(AdminState.waiting_broadcast)
async def admin_send_broadcast(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    text = message.text
    await state.clear()
    users = await asyncio.to_thread(db_query, "SELECT user_id FROM users", fetchall=True)
    success = 0
    for u in users:
        try:
            await bot.send_message(u[0], text, parse_mode=ParseMode.HTML)
            success += 1
            await asyncio.sleep(0.05)
        except Exception:
            pass
    await message.answer(f"✅ Xabar {success} ta foydalanuvchiga muvaffaqiyatli yuborildi!")


# =========================================================
# 🚀 CRASH AVTOMATIK FONI
# =========================================================
async def start_crash_engine():
    while True:
        try:
            mode = await get_setting("crash_mode")
            admin_x = float(await get_setting("admin_multiplier") or 2.0)
            streak = int(await get_setting("admin_streak") or 0)
            
            crash_at = 2.00
            used_mode = ""

            if mode == "admin":
                crash_at = admin_x
                used_mode = "Admin X"
                streak += 1
                await update_setting("admin_streak", str(streak))
                
                if streak >= 2:
                    await update_setting("crash_mode", "random")
                    await update_setting("admin_streak", "0")
            else:
                users_count = await get_users_count()
                base_rand = random.uniform(1.20, 5.00)
                if users_count > 10:
                    crash_at = round(base_rand * random.uniform(1.0, 1.4), 2)
                else:
                    crash_at = round(base_rand, 2)
                used_mode = "Random X"
                await update_setting("crash_mode", "admin")

            await asyncio.to_thread(db_query, "INSERT INTO crash_history (multiplier, mode) VALUES (?, ?)", (crash_at, used_mode), commit=True)
        except Exception as e:
            logging.error(f"Crash engine xatoligi: {e}")

        await asyncio.sleep(5)


# =========================================================
# 🚀 CRASH O'YINI MANTIQLARI VA PARVOZ
# =========================================================
@dp.callback_query(F.data == "play_crash")
async def play_crash_menu(callback: CallbackQuery, state: FSMContext):
    await state.set_state(CrashState.waiting_bet)
    balance = await get_balance(callback.from_user.id)
    await callback.message.edit_text(
        f"🚀 <b>CRASH O'YINI</b>\n"
        f"──────────────────────────\n"
        f"📈 Raketa parvozini kuzating va portlashdan oldin pulni yechib oling!\n\n"
        f"💰 Balansingiz: <b>{fn(balance)} coin</b>\n"
        f"Stavka miqdorini kiriting (min: 100 coin):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_to_menu")]]),
        parse_mode=ParseMode.HTML
    )

@dp.message(CrashState.waiting_bet)
async def process_crash_bet(message: Message, state: FSMContext):
    if not message.text or not message.text.isdigit():
        await message.answer("❌ Faqat raqam kiriting:")
        return
    
    bet = int(message.text)
    user_id = message.from_user.id
    balance = await get_balance(user_id)

    if bet < 100 or bet > balance:
        await message.answer("❌ Noto'g'ri summa yoki balans yetarli emas!")
        return

    await change_balance(user_id, -bet)
    await state.clear()

    game_msg = await message.answer(
        f"🚀 <b>RAKETA PARVOZGA TAYYORLANMOQDA...</b>\n\n💰 Stavka: <b>{fn(bet)} coin</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⏳ Tayyorlanmoqda...", callback_data="none")]]),
        parse_mode=ParseMode.HTML
    )
    
    mode = await get_setting("crash_mode")
    admin_x = float(await get_setting("admin_multiplier") or 2.0)
    target_x = admin_x if mode == "admin" else round(random.uniform(1.2, 4.0), 2)
    
    asyncio.create_task(run_crash_flight(message.bot, user_id, bet, game_msg.message_id, target_x))

async def run_crash_flight(bot_inst, user_id, bet, message_id, crash_at):
    current_multiplier = 1.00
    ACTIVE_GAMES[user_id] = {"bet": bet, "multiplier": 1.00, "status": "flying"}
    
    await asyncio.sleep(2)
    
    while current_multiplier < crash_at:
        if user_id not in ACTIVE_GAMES or ACTIVE_GAMES[user_id]["status"] != "flying":
            return
            
        current_multiplier = round(current_multiplier + 0.05, 2)
        ACTIVE_GAMES[user_id]["multiplier"] = current_multiplier
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"🟢 Yechib olish ({current_multiplier}x)", callback_data="cash_out")]
        ])
        
        try:
            await bot_inst.edit_message_text(
                chat_id=user_id,
                message_id=message_id,
                text=f"🚀 <b>RAKETA UCHMOQDA!</b>\n\n📈 Koeffitsiyent: <b>{current_multiplier}x</b>\n💰 Stavka: <b>{fn(bet)} coin</b>",
                reply_markup=kb,
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass
            
        await asyncio.sleep(0.4)
        
    if user_id in ACTIVE_GAMES and ACTIVE_GAMES[user_id]["status"] == "flying":
        ACTIVE_GAMES[user_id]["status"] = "crashed"
        try:
            await bot_inst.edit_message_text(
                chat_id=user_id,
                message_id=message_id,
                text=f"💥 <b>RAKETA PORTLADI! ({crash_at}x)</b>\n\n❌ Afsuski, vaqtida yechib ulgurmadingiz va <b>{fn(bet)} coin</b> yutqazdingiz.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔄 Qayta o'ynash", callback_data="play_crash"), InlineKeyboardButton(text="🏠 Asosiy Menyu", callback_data="back_to_menu")]]),
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass
        if user_id in ACTIVE_GAMES:
            del ACTIVE_GAMES[user_id]

@dp.callback_query(F.data == "cash_out")
async def cash_out_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    if user_id not in ACTIVE_GAMES or ACTIVE_GAMES[user_id]["status"] != "flying":
        await callback.answer("⚠️ O'yin tugagan yoki faol emas!", show_alert=True)
        return
        
    game = ACTIVE_GAMES[user_id]
    game["status"] = "cashed_out"
    
    mult = game["multiplier"]
    bet = game["bet"]
    win_amount = int(bet * mult)
    
    await change_balance(user_id, win_amount)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Yana o'ynash", callback_data="play_crash")],
        [InlineKeyboardButton(text="🏠 Asosiy Menyu", callback_data="back_to_menu")]
    ])
    
    try:
        await callback.message.edit_text(
            f"✅ <b>MUVAFFAQIYATLI YECHIB OLINDI!</b>\n\n"
            f"🎯 Koeffitsiyent: <b>{mult}x</b>\n"
            f"💰 Yutuq: <b>+{fn(win_amount)} coin</b>",
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )
    except Exception:
        pass
        
    del ACTIVE_GAMES[user_id]
    await callback.answer(f"🎉 Tabriklaymiz! +{fn(win_amount)} coin yutib oldingiz!", show_alert=True)


# =========================================================
# BOTNI ISHGA TUSHIRISH
# =========================================================
async def main():
    logging.basicConfig(level=logging.INFO)
    await init_db()
    asyncio.create_task(start_crash_engine())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
