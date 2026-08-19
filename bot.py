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
ADMIN_ID = 8252674515  # Admin Telegram ID si
DB_NAME = "crash_bot.db"

bot = Bot(token=TOKEN)
dp = Dispatcher()

TARGET_CRASH_X = 2.00

# O'yin holatlari (Saytga o'xshash global o'yin)
CRASH_GAME = {
    "status": "waiting",  # waiting, flying, crashed
    "multiplier": 1.00,
    "bets": {},           # user_id: {"bet": amount, "cashed": False, "name": name}
    "message_ids": {}     # user_id: message_id
}


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
        f"🚀 <b>Crash</b> o'yinida qatnashing va pul yutib oling!\n\n"
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


# =========================================================
# ⛏ MINING BO'LIMI
# =========================================================
@dp.callback_query(F.data == "mining_section")
async def mining_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    if not await check_user_deposited(user_id):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📥 Depozit Qilish", callback_data="deposit_money")],
            [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_to_menu")]
        ])
        await callback.message.edit_text(
            f"🔒 <b>MINING BO'LIMI YOPILGAN!</b>\n"
            f"──────────────────────────\n"
            f"⚠️ Mining bo'limiga ulanish uchun kamida <b>1 marta depozit</b> qilishingiz kerak!",
            reply_markup=kb, parse_mode=ParseMode.HTML
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
            f"⛏ <b>MINING BO'LIMI</b>\n──────────────────────────\n🎁 <b>Tayyor!</b> Balansingizga 100 coin qo'shishingiz mumkin.",
            reply_markup=kb, parse_mode=ParseMode.HTML
        )
    else:
        remaining = cooldown - elapsed
        minutes, seconds = remaining // 60, remaining % 60
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Yangilash", callback_data="mining_section")],
            [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_to_menu")]
        ])
        await callback.message.edit_text(
            f"⛏ <b>MINING BO'LIMI</b>\n──────────────────────────\n⏳ <b>Keyingi bonusgacha:</b> {minutes}d {seconds}s qoldi.",
            reply_markup=kb, parse_mode=ParseMode.HTML
        )

@dp.callback_query(F.data == "claim_mining")
async def claim_mining_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    if not await check_user_deposited(user_id):
        await callback.answer("⚠️ Avval depozit qilishingiz kerak!", show_alert=True)
        return

    current_time = int(time.time())
    if current_time - await get_last_claim(user_id) < 3600:
        await callback.answer("⏳ Hali 1 soat o'tmadi!", show_alert=True)
        return

    await change_balance(user_id, 100)
    await update_last_claim(user_id, current_time)
    balance = await get_balance(user_id)
    await callback.answer("🎉 +100 coin qo'shildi!", show_alert=True)
    await callback.message.edit_text(
        f"✅ <b>100 coin olindi!</b>\n💰 Yangi balans: <b>{money(balance)} coin</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏠 Asosiy Menyu", callback_data="back_to_menu")]]),
        parse_mode=ParseMode.HTML
    )


# =========================================================
# 📥 DEPOZIT VA PUL CHIQARISH TIZIMI
# =========================================================
@dp.callback_query(F.data == "deposit_money")
async def deposit_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(DepositState.waiting_amount)
    await callback.message.edit_text(
        "📥 <b>DEPOZIT QILISH</b>\nQancha pul kiritmoqchisiz? (Min: 5 000 coin):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor qilish", callback_data="back_to_menu")]]),
        parse_mode=ParseMode.HTML
    )

@dp.message(DepositState.waiting_amount)
async def deposit_amount_process(message: Message, state: FSMContext):
    if not message.text or not message.text.isdigit() or int(message.text) < 5000:
        await message.answer("❌ Minimal summa 5 000 coin. Qayta kiriting:")
        return
    await state.update_data(deposit_amount=int(message.text))
    await state.set_state(DepositState.waiting_proof)
    card_num = await get_card_number()
    await message.answer(
        f"💳 Karta raqami: <code>{card_num}</code>\nTo'lov cheki **skrinshotini** yuboring:",
        parse_mode=ParseMode.HTML
    )

@dp.message(DepositState.waiting_proof)
async def deposit_proof_process(message: Message, state: FSMContext):
    if not message.photo:
        await message.answer("❌ Iltimos, chek rasmini yuboring!")
        return
    data = await state.get_data()
    amount = data.get("deposit_amount")
    user_id = message.from_user.id
    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"dep_app:{user_id}:{amount}"),
         InlineKeyboardButton(text="❌ Rad etish", callback_data=f"dep_rej:{user_id}")]
    ])
    await bot.send_photo(
        chat_id=ADMIN_ID, photo=message.photo[-1].file_id,
        caption=f"📥 <b>YANGI DEPOZIT SO'ROVI</b>\nID: <code>{user_id}</code>\nSumma: <b>{money(amount)} coin</b>",
        reply_markup=admin_kb, parse_mode=ParseMode.HTML
    )
    await state.clear()
    await message.answer("✅ Chek adminga yuborildi!", reply_markup=main_menu(user_id))

@dp.callback_query(F.data == "withdraw_money")
async def withdraw_start(callback: CallbackQuery, state: FSMContext):
    balance = await get_balance(callback.from_user.id)
    if balance < 10000:
        await callback.answer("❌ Minimal chiqarish: 10 000 coin.", show_alert=True)
        return
    await state.set_state(WithdrawState.waiting_amount)
    await callback.message.edit_text(
        f"📤 <b>PUL CHIQARISH</b>\nBalans: {money(balance)} coin\nChiqarmoqchi bo'lgan summani yozing:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor qilish", callback_data="back_to_menu")]]),
        parse_mode=ParseMode.HTML
    )

@dp.message(WithdrawState.waiting_amount)
async def withdraw_amount_process(message: Message, state: FSMContext):
    if not message.text or not message.text.isdigit() or int(message.text) < 10000:
        await message.answer("❌ Min: 10 000 coin. Qayta kiriting:")
        return
    await state.update_data(withdraw_amount=int(message.text))
    await state.set_state(WithdrawState.waiting_card_and_name)
    await message.answer("💳 Karta raqami va egasining ismini yuboring:", parse_mode=ParseMode.HTML)

@dp.message(WithdrawState.waiting_card_and_name)
async def withdraw_card_process(message: Message, state: FSMContext):
    data = await state.get_data()
    amount = data.get("withdraw_amount")
    user_id = message.from_user.id
    if amount > await get_balance(user_id):
        await state.clear()
        await message.answer("❌ Mablag' yetarli emas!", reply_markup=main_menu(user_id))
        return
    await change_balance(user_id, -amount)
    await state.clear()
    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ To'lab berildi", callback_data=f"with_app:{user_id}"),
         InlineKeyboardButton(text="❌ Qaytarish", callback_data=f"with_rej:{user_id}:{amount}")]
    ])
    await bot.send_message(
        chat_id=ADMIN_ID,
        text=f"📤 <b>PUL CHIQARISH SO'ROVI</b>\nID: <code>{user_id}</code>\nSumma: <b>{money(amount)} coin</b>\nKarta: <code>{message.text}</code>",
        reply_markup=admin_kb, parse_mode=ParseMode.HTML
    )
    await message.answer("✅ So'rov yuborildi!", reply_markup=main_menu(user_id))

@dp.callback_query(F.data.startswith("dep_app:"))
async def approve_deposit(callback: CallbackQuery):
    _, u_id, amt = callback.data.split(":")
    await change_balance(int(u_id), int(amt))
    await set_user_deposited(int(u_id))
    await callback.answer("✅ Tasdiqlandi!")
    await callback.message.edit_caption(caption=callback.message.caption + "\n\n🟢 <b>STATUS: TASDIQLANDI</b>", parse_mode=ParseMode.HTML)
    await bot.send_message(int(u_id), f"🎉 <b>Hisobingizga +{money(int(amt))} coin qo'shildi!</b>", parse_mode=ParseMode.HTML)

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
    await change_balance(int(u_id), int(amt))
    await callback.answer("❌ Rad etildi, pul qaytarildi!")
    await callback.message.edit_text(callback.message.text + "\n\n🔴 <b>STATUS: RAD ETILDI (PUL QAYTARILDI)</b>", parse_mode=ParseMode.HTML)
    await bot.send_message(int(u_id), f"❌ Pul chiqarish rad etildi, {money(int(amt))} coin qaytarildi.", parse_mode=ParseMode.HTML)


# =========================================================
# ADMIN PANEL
# =========================================================
@dp.callback_query(F.data == "admin_panel")
async def admin_panel_handler(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return
    await state.clear()
    await callback.message.edit_text(
        f"👨‍💼 <b>ADMIN PANEL</b>\nJami foydalanuvchilar: {await get_users_count()} ta\nCrash X: {TARGET_CRASH_X:.2f}x",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚙️ Crash X ni o'zgartirish", callback_data="set_crash_x")],
            [InlineKeyboardButton(text="💳 Kartani o'zgartirish", callback_data="set_card")],
            [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_to_menu")]
        ]), parse_mode=ParseMode.HTML
    )

@dp.callback_query(F.data == "set_card")
async def set_card_prompt(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return
    await state.set_state(AdminState.waiting_card_number)
    await callback.message.edit_text("💳 Yangi karta raqamini kiriting:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Orqaga", callback_data="admin_panel")]]))

@dp.message(AdminState.waiting_card_number)
async def process_set_card(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    await set_card_number(message.text.strip())
    await state.clear()
    await message.answer("✅ Karta yangilandi!", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Admin Panel", callback_data="admin_panel")]]))

@dp.callback_query(F.data == "set_crash_x")
async def set_crash_x_prompt(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return
    await state.set_state(AdminState.waiting_crash_x)
    await callback.message.edit_text("⚙️ Yangi Crash X qiymatini kiriting (masalan: 2.5):", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Orqaga", callback_data="admin_panel")]]))

@dp.message(AdminState.waiting_crash_x)
async def process_set_crash_x(message: Message, state: FSMContext):
    global TARGET_CRASH_X
    try:
        val = float(message.text.replace(",", "."))
        if val <= 1.0: return
        TARGET_CRASH_X = round(val, 2)
        await state.clear()
        await message.answer(f"✅ Yangi Crash X: {TARGET_CRASH_X:.2f}x", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Admin Panel", callback_data="admin_panel")]]))
    except ValueError:
        await message.answer("❌ Faqat son kiriting!")


# =========================================================
# 🚀 HAKIQIY SAYTGA O'XSHASH CRASH O'YINI MANTIQLARI
# =========================================================
@dp.callback_query(F.data == "play_crash")
async def play_crash_menu(callback: CallbackQuery, state: FSMContext):
    await state.set_state(CrashState.waiting_bet)
    balance = await get_balance(callback.from_user.id)
    await callback.message.edit_text(
        f"🚀 <b>CRASH O'YINI (AVIATOR)</b>\n"
        f"──────────────────────────\n"
        f"💰 Balansingiz: <b>{money(balance)} coin</b>\n"
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
        await message.answer("❌ Mablag' yetarli emas yoki stavka juda kam!")
        return

    await change_balance(user_id, -bet)
    await state.clear()

    CRASH_GAME["bets"][user_id] = {
        "bet": bet,
        "cashed": False,
        "name": message.from_user.first_name
    }

    game_msg = await message.answer(
        f"🚀 <b>STAVKA QABUL QILINDI: {money(bet)} coin</b>\n"
        f"⏳ Keyingi reys boshlanishini kuting...",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⏳ Kutilmoqda...", callback_data="none")]]),
        parse_mode=ParseMode.HTML
    )
    CRASH_GAME["message_ids"][user_id] = game_msg.message_id

    if CRASH_GAME["status"] == "waiting":
        asyncio.create_task(run_global_crash_flight())

async def run_global_crash_flight():
    CRASH_GAME["status"] = "waiting"
    await asyncio.sleep(4)

    CRASH_GAME["status"] = "flying"
    CRASH_GAME["multiplier"] = 1.00
    crash_at = TARGET_CRASH_X

    admin_text = f"🎮 <b>YANGI REYS BOSHLANDI!</b>\nO'yinchilar soni: {len(CRASH_GAME['bets'])}\n\n"
    for u_id, data in CRASH_GAME["bets"].items():
        admin_text += f"👤 {data['name']} (ID: <code>{u_id}</code>) — {money(data['bet'])} coin\n"
    
    admin_msg = await bot.send_message(chat_id=ADMIN_ID, text=admin_text, parse_mode=ParseMode.HTML)

    cash_out_kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🎯 PULNI OLISH (CASH OUT)", callback_data="crash_cashout")]]
    )

    try:
        while CRASH_GAME["multiplier"] < crash_at:
            await asyncio.sleep(0.9)
            CRASH_GAME["multiplier"] += 0.15
            
            if CRASH_GAME["multiplier"] >= crash_at:
                CRASH_GAME["multiplier"] = crash_at

            curr_m = CRASH_GAME["multiplier"]
            progress_val = min(int((curr_m - 1.0) * 3), 10)
            bar = "🟩" * progress_val + "⬛" * (10 - progress_val)

            for u_id, m_id in list(CRASH_GAME["message_ids"].items()):
                if u_id in CRASH_GAME["bets"] and not CRASH_GAME["bets"][u_id]["cashed"]:
                    bet_val = CRASH_GAME["bets"][u_id]["bet"]
                    try:
                        await bot.edit_message_text(
                            chat_id=u_id,
                            message_id=m_id,
                            text=f"🚀 <b>RAKETA UCHMOQDA!</b>\n"
                                 f"──────────────────────────\n"
                                 f"       📈 <b>{curr_m:.2f}x</b>\n"
                                 f"──────────────────────────\n"
                                 f"📊 Grafik: [{bar}]\n"
                                 f"💰 Stavka: {money(bet_val)} coin\n"
                                 f"🎁 Hozirgi yutuq: <b>{money(int(bet_val * curr_m))} coin</b>\n"
                                 f"──────────────────────────\n"
                                 f"👥 <i>O'yinda {len(CRASH_GAME['bets'])} ta ishtirokchi bor</i>",
                            reply_markup=cash_out_kb,
                            parse_mode=ParseMode.HTML
                        )
                    except Exception:
                        pass

        CRASH_GAME["status"] = "crashed"
        
        for u_id, m_id in list(CRASH_GAME["message_ids"].items()):
            if u_id in CRASH_GAME["bets"] and not CRASH_GAME["bets"][u_id]["cashed"]:
                bet_val = CRASH_GAME["bets"][u_id]["bet"]
                try:
                    await bot.edit_message_text(
                        chat_id=u_id,
                        message_id=m_id,
                        text=f"💥 <b>BOOOOOOOM! RAKETA PORTLADI!</b>\n"
                             f"──────────────────────────\n"
                             f"📍 Portlash nuqtasi: <b>{crash_at:.2f}x</b>\n"
                             f"❌ <b>Afsus, vaqtida ulgurmadingiz va yutqazdingiz!</b>\n"
                             f"💰 Yo'qotildi: <b>-{money(bet_val)} coin</b>\n"
                             f"──────────────────────────",
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                            InlineKeyboardButton(text="🔄 Qaytadan O'ynash", callback_data="play_crash"),
                            InlineKeyboardButton(text="🏠 Asosiy Menyu", callback_data="back_to_menu")
                        ]]),
                        parse_mode=ParseMode.HTML
                    )
                except Exception:
                    pass

        CRASH_GAME["bets"].clear()
        CRASH_GAME["message_ids"].clear()
        CRASH_GAME["status"] = "waiting"
        try:
            await bot.delete_message(chat_id=ADMIN_ID, message_id=admin_msg.message_id)
        except Exception:
            pass

    except Exception as e:
        logging.error(f"Global Crash xatolik: {e}")
        CRASH_GAME["status"] = "waiting"
        CRASH_GAME["bets"].clear()
        CRASH_GAME["message_ids"].clear()

@dp.callback_query(F.data == "crash_cashout")
async def process_crash_cashout(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    if CRASH_GAME["status"] != "flying" or user_id not in CRASH_GAME["bets"] or CRASH_GAME["bets"][user_id]["cashed"]:
        await callback.answer("⚠️ Kechikdingiz yoki o'yin tugagan!", show_alert=True)
        return

    player = CRASH_GAME["bets"][user_id]
    player["cashed"] = True
    
    multiplier = CRASH_GAME["multiplier"]
    win_amount = int(player["bet"] * multiplier)
    await change_balance(user_id, win_amount)

    await callback.message.edit_text(
        f"🎉 <b>TABRIKLAYMIZ! PUL MUVAFFAQIYATLI OLINDI!</b>\n"
        f"──────────────────────────\n"
        f"📈 Koeffitsiyent: <b>{multiplier:.2f}x</b>\n"
        f"💰 Yutuq: <b>+{money(win_amount)} coin</b>\n"
        f"──────────────────────────",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🔄 Qaytadan O'ynash", callback_data="play_crash"),
            InlineKeyboardButton(text="🏠 Asosiy Menyu", callback_data="back_to_menu")
        ]]),
        parse_mode=ParseMode.HTML
    )
    await callback.answer(f"+{money(win_amount)} coin yutiboldingiz!", show_alert=True)


# =========================================================
# BOTNI ISHGA TUSHIRISH
# =========================================================
async def main():
    logging.basicConfig(level=logging.INFO)
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
