import asyncio
import logging
import os
import re
import sqlite3
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from aiohttp import web
from aiogram import Bot, Dispatcher, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    FSInputFile,
)
import yt_dlp

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("savetrack")

# TO'G'RILANDI: Atrof-muhit o'zgaruvchilari nomlari to'g'ri ko'rsatildi
BOT_TOKEN = os.getenv("8958554064:AAGQ7LhZCYczJANX2BSiZTxceVEJ0_oyYUs", "").strip()
ADMIN_ID_RAW = os.getenv("8738813282", "").strip()
ADMIN_ID = int(ADMIN_ID_RAW) if ADMIN_ID_RAW.isdigit() else 0
PORT = int(os.getenv("PORT", "10000"))
DB_PATH = os.getenv("DB_PATH", "savetrack.sqlite3")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is missing.")
if not ADMIN_ID:
    raise RuntimeError("ADMIN_ID environment variable is missing or invalid.")

bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
pending_links: dict[int, str] = {}


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY)")
        conn.execute("""CREATE TABLE IF NOT EXISTS channels (
            id TEXT PRIMARY KEY, url TEXT NOT NULL
        )""")


def add_user(user_id: int):
    with db() as conn:
        conn.execute("INSERT OR IGNORE INTO users(user_id) VALUES(?)", (user_id,))


def get_users():
    with db() as conn:
        return [row["user_id"] for row in conn.execute("SELECT user_id FROM users")]


def get_channels():
    with db() as conn:
        return [dict(row) for row in conn.execute("SELECT id, url FROM channels ORDER BY rowid")]


def add_channel(channel_id: str, url: str):
    with db() as conn:
        conn.execute("INSERT OR REPLACE INTO channels(id, url) VALUES(?, ?)", (channel_id, url))


def remove_channel(channel_id: str):
    with db() as conn:
        conn.execute("DELETE FROM channels WHERE id=?", (channel_id,))


class AdminState(StatesGroup):
    channel_id = State()
    channel_url = State()
    broadcast = State()


def admin_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Statistika"), KeyboardButton(text="📢 Kanallar")],
            [KeyboardButton(text="✉️ Xabar yuborish"), KeyboardButton(text="❌ Yopish")],
        ],
        resize_keyboard=True,
    )


def channels_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Kanal qo‘shish", callback_data="admin:add")],
        [InlineKeyboardButton(text="📋 Ro‘yxat / O‘chirish", callback_data="admin:list")],
    ])


async def check_subscriptions(user_id: int):
    missing = []
    for channel in get_channels():
        try:
            member = await bot.get_chat_member(channel["id"], user_id)
            if member.status in ("left", "kicked"):
                missing.append(channel)
        except Exception:
            log.exception("Obunani tekshirishda xatolik: channel=%s", channel["id"])
    return missing


def subscription_keyboard(channels):
    rows = [
        [InlineKeyboardButton(text=f"➕ {i}-kanalga obuna bo‘lish", url=ch["url"])]
        for i, ch in enumerate(channels, start=1)
    ]
    rows.append([InlineKeyboardButton(text="✅ Tekshirish", callback_data="sub:check")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def valid_http_url(value: str) -> bool:
    try:
        parsed = urlparse(value.strip())
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


@dp.message(CommandStart())
async def start(message: types.Message):
    add_user(message.from_user.id)
    missing = await check_subscriptions(message.from_user.id)
    if missing:
        await message.answer(
            "⚠️ Botdan foydalanish uchun quyidagi kanallarga obuna bo‘ling:",
            reply_markup=subscription_keyboard(missing),
        )
        return
    await message.answer(
        f"Assalomu alaykum, {types.html.quote(message.from_user.full_name)}!\n\n"
        "📥 Video yoki audio olish uchun YouTube Shorts, YouTube, Instagram yoki "
        "boshqa qo‘llab-quvvatlanadigan platforma havolasini yuboring."
    )


@dp.callback_query(F.data == "sub:check")
async def subscription_check(call: types.CallbackQuery):
    missing = await check_subscriptions(call.from_user.id)
    if missing:
        await call.answer("❌ Hali barcha kanallarga obuna bo‘lmagansiz.", show_alert=True)
        return
    await call.answer("Obuna tasdiqlandi!")
    try:
        await call.message.delete()
    except Exception:
        pass
    await bot.send_message(call.from_user.id, "✅ Rahmat! Endi video havolasini yuborishingiz mumkin.")


@dp.message(Command("admin"))
async def admin_start(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("👑 Admin panel", reply_markup=admin_keyboard())


@dp.message(F.text == "❌ Yopish")
async def admin_close(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await state.clear()
    await message.answer("Admin panel yopildi.", reply_markup=ReplyKeyboardRemove())


@dp.message(F.text == "📊 Statistika")
async def stats(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer(
        f"📊 <b>Statistika</b>\n\nFoydalanuvchilar: {len(get_users())}\n"
        f"Majburiy kanallar: {len(get_channels())}"
    )


@dp.message(F.text == "📢 Kanallar")
async def manage_channels(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("Majburiy obuna kanallari:", reply_markup=channels_keyboard())


@dp.callback_query(F.data.startswith("admin:"))
async def admin_channel_callbacks(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Ruxsat yo‘q.", show_alert=True)
        return
    if call.data == "admin:add":
        await state.set_state(AdminState.channel_id)
        await call.message.answer(
            "Kanal ID sini yuboring (masalan, -1001234567890).\n"
            "Bot kanalga administrator qilib qo‘shilgan bo‘lishi kerak."
        )
    elif call.data == "admin:list":
        channels = get_channels()
        if not channels:
            await call.message.answer("Hozircha kanal qo‘shilmagan.")
        else:
            rows = [
                [InlineKeyboardButton(
                    text=f"🗑 {ch['id']}",
                    callback_data="admin:del:" + ch["id"][:45]
                )]
                for ch in channels
            ]
            await call.message.answer(
                "O‘chirish uchun kanal tugmasini bosing:",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
            )
    await call.answer()


@dp.callback_query(F.data.startswith("admin:del:"))
async def admin_delete_channel(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Ruxsat yo‘q.", show_alert=True)
        return
    channel_id = call.data.removeprefix("admin:del:")
    remove_channel(channel_id)
    await call.answer("Kanal o‘chirildi.")
    try:
        await call.message.edit_text(f"🗑 Kanal o‘chirildi: {channel_id}")
    except Exception:
        pass


@dp.message(AdminState.channel_id)
async def receive_channel_id(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    channel_id = (message.text or "").strip()
    if not re.fullmatch(r"-?\d{5,20}|@[A-Za-z0-9_]{5,}", channel_id):
        await message.answer("Kanal ID noto‘g‘ri. Masalan: -1001234567890. Qayta yuboring.")
        return
    await state.update_data(channel_id=channel_id)
    await state.set_state(AdminState.channel_url)
    await message.answer("Endi kanalning https://t.me/... havolasini yuboring.")


@dp.message(AdminState.channel_url)
async def receive_channel_url(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    url = (message.text or "").strip()
    if not valid_http_url(url) or "t.me/" not in url:
        await message.answer("Telegram kanal havolasini to‘g‘ri yuboring.")
        return
    data = await state.get_data()
    add_channel(data["channel_id"], url)
    await state.clear()
    await message.answer("✅ Kanal saqlandi.", reply_markup=admin_keyboard())


@dp.message(F.text == "✉️ Xabar yuborish")
async def broadcast_start(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await state.set_state(AdminState.broadcast)
    await message.answer("Barcha foydalanuvchilarga yuboriladigan xabarni yuboring (matn, rasm yoki video bo‘lishi mumkin).")


@dp.message(AdminState.broadcast)
async def broadcast_send(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    sent = 0
    failed = 0
    for user_id in get_users():
        try:
            await message.copy_to(chat_id=user_id)
            sent += 1
            await asyncio.sleep(0.04)
        except Exception:
            failed += 1
    await state.clear()
    await message.answer(f"✅ Yuborildi: {sent}\n❌ Yuborilmadi: {failed}", reply_markup=admin_keyboard())


@dp.message(F.text.regexp(r"^https?://"))
async def media_link(message: types.Message):
    add_user(message.from_user.id)
    url = (message.text or "").strip()
    if not valid_http_url(url):
        await message.answer("❌ Havola noto‘g‘ri.")
        return
    missing = await check_subscriptions(message.from_user.id)
    if missing:
        await message.answer(
            "⚠️ Davom etish uchun kanallarga obuna bo‘ling:",
            reply_markup=subscription_keyboard(missing),
        )
        return
    pending_links[message.from_user.id] = url
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎬 Video yuklash", callback_data="download:video"),
            InlineKeyboardButton(text="🎵 MP3 audio", callback_data="download:audio"),
        ]
    ])
    await message.reply("Formatni tanlang:", reply_markup=keyboard)


@dp.callback_query(F.data.in_({"download:video", "download:audio"}))
async def download_media(call: types.CallbackQuery):
    await call.answer()
    url = pending_links.get(call.from_user.id)
    if not url:
        await call.message.answer("Havola muddati tugagan. Havolani qayta yuboring.")
        return

    missing = await check_subscriptions(call.from_user.id)
    if missing:
        await call.message.answer(
            "Avval kanallarga obuna bo‘ling:",
            reply_markup=subscription_keyboard(missing),
        )
        return

    is_audio = call.data == "download:audio"
    await call.message.edit_text("⏳ Yuklanmoqda. Biroz kuting...")
    temp_dir = tempfile.mkdtemp(prefix="savetrack_")
    output_template = str(Path(temp_dir) / "%(id)s.%(ext)s")

    options = {
        "outtmpl": output_template,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "retries": 3,
        "fragment_retries": 3,
        "socket_timeout": 30,
        "format": "bestaudio/best" if is_audio else "best[ext=mp4]/best",
    }
    if is_audio:
        options["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }]

    try:
        def run_download():
            with yt_dlp.YoutubeDL(options) as ydl:
                ydl.download([url])

        await asyncio.get_running_loop().run_in_executor(None, run_download)
        files = [p for p in Path(temp_dir).glob("*") if p.is_file()]
        if is_audio:
            candidates = [p for p in files if p.suffix.lower() == ".mp3"]
        else:
            candidates = [p for p in files if p.suffix.lower() == ".mp4"]
            if not candidates:
                candidates = files
        if not candidates:
            raise RuntimeError("Download completed but no output file was found.")

        output = max(candidates, key=lambda p: p.stat().st_size)
        if output.stat().st_size > 49 * 1024 * 1024:
            await call.message.answer(
                "❌ Fayl Telegram bot orqali yuborish uchun juda katta (50 MB dan oshdi)."
            )
            return

        await call.message.answer("📤 Fayl Telegramga yuborilmoqda...")
        media = FSInputFile(output)
        if is_audio:
            await bot.send_audio(call.from_user.id, media, caption="🎵 Tayyor!")
        elif output.suffix.lower() == ".mp4":
            await bot.send_video(call.from_user.id, media, caption="🎬 Tayyor!")
        else:
            await bot.send_document(call.from_user.id, media, caption="📁 Fayl tayyor!")
        try:
            await call.message.delete()
        except Exception:
            pass
    except Exception:
        log.exception("Media download failed for user_id=%s", call.from_user.id)
        await call.message.answer(
            "❌ Yuklash amalga oshmadi. Havola ochiq ekanini tekshiring yoki boshqa video bilan urinib ko‘ring. "
            "Admin Render Logs orqali aniq xatoni ko‘rishi mumkin."
        )
    finally:
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)


# ALDAMCHI (CHROYLI) VEB-SAYT QISMI
async def health(request):
    html_content = """
    <!DOCTYPE html>
    <html lang="uz">
    <head>
        <meta charset="UTF-8">
        <title>SaveTrack Bot Status</title>
        <style>
            body { font-family: Arial, sans-serif; text-align: center; background: #0f172a; color: #f8fafc; padding-top: 100px; }
            .card { background: #1e293b; display: inline-block; padding: 40px; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.5); }
            h1 { color: #38bdf8; }
            p { color: #94a3b8; }
        </style>
    </head>
    <body>
        <div class="card">
            <h1>🚀 SaveTrack Bot Online</h1>
            <p>Telegram botimiz faol holatda va ishlamoqda.</p>
            <p>Botdan foydalanish uchun Telegram'ga o'ting.</p>
        </div>
    </body>
    </html>
    """
    return web.Response(text=html_content, content_type="text/html")


async def run_web_server():
    app = web.Application()
    app.router.add_get("/", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    log.info("Health server started on port %s", PORT)


async def main():
    init_db()
    await run_web_server()
    log.info("SaveTrack Bot started.")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
    