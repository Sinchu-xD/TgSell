import os
import re
import time
import asyncio
from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
import database as db
from config import get_flag, SESSIONS_DIR, API_ID, API_HASH

_pending = {}


# ── Combined country+category keyboard ───────────────────────────────────────

async def _country_category_kb(cb_prefix: str, back_cb: str):
    """
    One button per country+category combination.
    Label: {flag} {Country} {Category}  ₹{inr}/${usd}  [{stock}]

    Countries with no typed categories get one button showing total stock.
    """
    countries = await db.get_countries_with_stock()
    if not countries:
        return None, None
    prices = await db.get_prices()
    rows   = []

    for country in sorted(countries.keys()):
        flag        = get_flag(country)
        price       = prices.get(country, {"inr": 0, "usd": 0})
        type_counts = await db.get_stock_count_by_type(country)
        total       = countries[country]

        if type_counts:
            for cat, cnt in sorted(type_counts.items()):
                if cnt > 0:
                    label = (
                        f"{flag} {country.title()} {cat}  "
                        f"₹{price['inr']}/${price['usd']}  [{cnt}]"
                    )
                    rows.append([InlineKeyboardButton(
                        label,
                        callback_data=f"{cb_prefix}{country}||{cat}"
                    )])
            no_type = total - sum(type_counts.values())
            if no_type > 0:
                label = (
                    f"{flag} {country.title()}  "
                    f"₹{price['inr']}/${price['usd']}  [{no_type}]"
                )
                rows.append([InlineKeyboardButton(
                    label,
                    callback_data=f"{cb_prefix}{country}||"
                )])
        else:
            label = (
                f"{flag} {country.title()}  "
                f"₹{price['inr']}/${price['usd']}  [{total}]"
            )
            rows.append([InlineKeyboardButton(
                label,
                callback_data=f"{cb_prefix}{country}||"
            )])

    rows.append([InlineKeyboardButton("🔙 Back", callback_data=back_cb)])
    return countries, InlineKeyboardMarkup(rows)


def register(app: Client):

    # ── Buy menu ──────────────────────────────────────────────────────────────
    @app.on_callback_query(filters.regex("^buy$"))
    async def buy_menu(client, callback: CallbackQuery):
        total = await db.get_stock_count()
        if not total:
            await callback.answer("❌ No stock available right now!", show_alert=True)
            return
        await callback.edit_message_text(
            "🛒 **Buy Accounts**\n\nWhat would you like?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📁 TG Session File",  callback_data="buy_type_session")],
                [InlineKeyboardButton("📱 TG Live Account",  callback_data="buy_type_account")],
                [InlineKeyboardButton("🔙 Back",             callback_data="main_menu")],
            ])
        )

    # ── TG Session — country+category list ────────────────────────────────────
    @app.on_callback_query(filters.regex("^buy_type_session$"))
    async def buy_type_session(client, callback: CallbackQuery):
        countries, kb = await _country_category_kb("buy_s_t_", "buy")
        if not countries:
            await callback.answer("❌ No stock available!", show_alert=True)
            return
        await callback.edit_message_text(
            "📁 **TG Session File**\n\nSelect country & category:",
            reply_markup=kb
        )

    # ── TG Account — country+category list ───────────────────────────────────
    @app.on_callback_query(filters.regex("^buy_type_account$"))
    async def buy_type_account(client, callback: CallbackQuery):
        countries, kb = await _country_category_kb("buy_a_t_", "buy")
        if not countries:
            await callback.answer("❌ No stock available!", show_alert=True)
            return
        await callback.edit_message_text(
            "📱 **TG Live Account**\n\nSelect country & category:",
            reply_markup=kb
        )

    # ── Session: button → confirm ─────────────────────────────────────────────
    @app.on_callback_query(filters.regex(r"^buy_s_t_(.+)\|\|(.*)$"))
    async def buy_s_detail(client, callback: CallbackQuery):
        country  = callback.matches[0].group(1)
        acc_type = callback.matches[0].group(2)
        await _show_confirm(callback, country, acc_type, "session")

    # ── Account: button → confirm ─────────────────────────────────────────────
    @app.on_callback_query(filters.regex(r"^buy_a_t_(.+)\|\|(.*)$"))
    async def buy_a_detail(client, callback: CallbackQuery):
        country  = callback.matches[0].group(1)
        acc_type = callback.matches[0].group(2)
        await _show_confirm(callback, country, acc_type, "account")

    async def _show_confirm(callback: CallbackQuery, country: str, acc_type: str, kind: str):
        flag    = get_flag(country)
        price   = await db.get_price(country)
        user    = await db.get_user(callback.from_user.id)
        bal_inr = user.get("balance_inr", 0)

        filter_type = None if acc_type in ("any", "") else acc_type
        stock   = await db.get_stock_count(country, filter_type)
        disp    = acc_type if acc_type not in ("any", "") else "Any Available"

        kind_label = "📁 Session File" if kind == "session" else "📱 Live Account"
        cb_buy     = f"buynow_{kind[0]}_{country}||{acc_type}"
        back_cb    = f"buy_type_{'session' if kind == 'session' else 'account'}"

        has_bal = bal_inr >= price["inr"]
        status  = "✅ Sufficient" if has_bal else "❌ Insufficient"

        text = (
            f"{kind_label}\n\n"
            f"{flag} **{country.title()}**\n"
            f"🏷️ Type    : `{disp}`\n"
            f"📦 Stock   : `{stock}` left\n\n"
            f"💰 Price   : ₹`{price['inr']}` / $`{price['usd']}`\n"
            f"💳 Balance : ₹`{bal_inr}`  {status}"
        )

        if has_bal and stock > 0:
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"✅ Buy Now — ₹{price['inr']}", callback_data=cb_buy)],
                [InlineKeyboardButton("💳 Deposit", callback_data="deposit"),
                 InlineKeyboardButton("🔙 Back",    callback_data=back_cb)],
            ])
        elif stock == 0:
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Out of Stock", callback_data="noop")],
                [InlineKeyboardButton("🔙 Back", callback_data=back_cb)],
            ])
        else:
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    f"💳 Deposit ₹{price['inr'] - bal_inr} More",
                    callback_data="deposit"
                )],
                [InlineKeyboardButton("🔙 Back", callback_data=back_cb)],
            ])
        await callback.edit_message_text(text, reply_markup=kb)

    # ── Buy Now: Session ──────────────────────────────────────────────────────
    @app.on_callback_query(filters.regex(r"^buynow_s_(.+)\|\|(.*)$"))
    async def buynow_session(client, callback: CallbackQuery):
        country  = callback.matches[0].group(1)
        acc_type = callback.matches[0].group(2)
        filter_t = None if acc_type in ("any", "") else acc_type

        price = await db.get_price(country)
        user  = await db.get_user(callback.from_user.id)
        flag  = get_flag(country)

        if user.get("balance_inr", 0) < price["inr"]:
            await callback.answer(
                f"❌ Insufficient balance!\nNeed ₹{price['inr']}, have ₹{user.get('balance_inr', 0)}",
                show_alert=True
            )
            return

        account = await db.pop_account_from_stock(country, filter_t)
        if not account:
            await callback.answer("❌ Out of stock! Try again later.", show_alert=True)
            return

        await db.deduct_balance(callback.from_user.id, amount_inr=price["inr"])
        phone       = account.get("phone", "unknown")
        actual_type = account.get("acc_type", "")
        session_f   = os.path.join(SESSIONS_DIR, f"stock_{phone.replace('+', '')}.session")

        await db.add_order({
            "user_id": callback.from_user.id, "country": country,
            "type": "session", "phone": phone, "acc_type": actual_type,
        })

        type_line = f"\n🏷️ Type: `{actual_type}`" if actual_type else ""
        done_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🛒 Buy More",  callback_data="buy")],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")],
        ])
        await callback.edit_message_text(
            f"✅ **Purchase Successful!**\n\n"
            f"{flag} {country.title()}{type_line}\n"
            f"📱 `{phone}`\n💰 Deducted: ₹{price['inr']}\n\n📁 Sending file...",
            reply_markup=done_kb
        )

        # Ensure session is on disk — restore from MongoDB/cache if wiped
        session_name_s = f"stock_{phone.replace('+', '')}"
        session_available = await db.ensure_session_on_disk(session_name_s)

        if session_available and os.path.exists(session_f):
            await client.send_document(
                callback.from_user.id, session_f,
                caption=(
                    f"🎉 **Your Telegram Session**\n\n"
                    f"{flag} {country.title()}{type_line}\n📱 `{phone}`\n\n"
                    f"⚠️ Do NOT share this file!\n\nThank you — **TG Account Store** 🏪"
                ),
                reply_markup=done_kb
            )
        else:
            await client.send_message(
                callback.from_user.id,
                f"⚠️ Session file missing on server.\n📱 `{phone}`\nContact support.",
                reply_markup=done_kb
            )

    # ── Buy Now: Live Account ─────────────────────────────────────────────────
    @app.on_callback_query(filters.regex(r"^buynow_a_(.+)\|\|(.*)$"))
    async def buynow_account(client, callback: CallbackQuery):
        uid      = callback.from_user.id
        country  = callback.matches[0].group(1)
        acc_type = callback.matches[0].group(2)
        filter_t = None if acc_type in ("any", "") else acc_type

        price = await db.get_price(country)
        user  = await db.get_user(uid)
        flag  = get_flag(country)

        if user.get("balance_inr", 0) < price["inr"]:
            await callback.answer(
                f"❌ Insufficient balance!\nNeed ₹{price['inr']}, have ₹{user.get('balance_inr', 0)}",
                show_alert=True
            )
            return

        if uid in _pending:
            await callback.answer("⏳ A purchase is already in progress.", show_alert=True)
            return

        account = await db.pop_account_from_stock(country, filter_t)
        if not account:
            await callback.answer("❌ Out of stock! Try again later.", show_alert=True)
            return

        phone        = account.get("phone", "")
        two_step     = account.get("two_step", "")
        actual_type  = account.get("acc_type", "")
        session_name = f"stock_{phone.replace('+', '')}"
        session_file = os.path.join(SESSIONS_DIR, f"{session_name}.session")

        # Restore session from MongoDB/cache if disk file is missing
        if not os.path.exists(session_file):
            restored = await db.ensure_session_on_disk(session_name)
            if not restored:
                await db.add_account_back_to_stock(country, account)
                await callback.answer("❌ Session file missing. Contact support.", show_alert=True)
                return

        await db.deduct_balance(uid, amount_inr=price["inr"])
        await db.add_order({
            "user_id": uid, "country": country,
            "type": "account", "phone": phone, "acc_type": actual_type,
        })
        new_bal = (await db.get_user(uid)).get("balance_inr", 0)

        type_line = f"\n🏷️ Type    : `{actual_type}`" if actual_type else ""

        # ── Step 1: Send ONLY phone number immediately ─────────────────────────
        await callback.edit_message_text(
            f"🎉 **Account Purchased!**\n\n"
            f"{flag} **{country.title()} Telegram Account**"
            f"{type_line}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📱 Phone    : `{phone}`\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 Deducted : ₹{price['inr']}\n"
            f"💳 Remaining: ₹{new_bal}\n\n"
            f"📨 Login with this number — OTP & 2-Step will be sent here automatically.\n\n"
            f"Thank you — **TG Account Store** 🏪",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🛒 Buy More",  callback_data="buy")],
                [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")],
            ])
        )

        # ── Step 2: Watch 777000 in background — send OTP + 2-step on arrival ─
        purchase_ts = time.time()
        _pending[uid] = True

        async def _watch_otp():
            sc = Client(session_name, api_id=API_ID, api_hash=API_HASH,
                        workdir=SESSIONS_DIR, no_updates=True)
            otp_code = None
            try:
                await sc.connect()
                for _ in range(75):          # up to 5 minutes (75 × 4 s)
                    await asyncio.sleep(4)
                    try:
                        async for m in sc.get_chat_history(777000, limit=3):
                            msg_ts = m.date.timestamp() if m.date else 0
                            if msg_ts < purchase_ts:
                                break        # older than this purchase — stop
                            txt   = getattr(m, "text", "") or ""
                            match = re.search(r"\b(\d{5,6})\b", txt)
                            if match:
                                otp_code = match.group(1)
                                break
                    except Exception:
                        pass
                    if otp_code:
                        break
            except Exception:
                pass
            finally:
                try: await sc.disconnect()
                except Exception: pass
                _pending.pop(uid, None)

            if otp_code:
                two_step_line = (
                    f"🔐 2-Step : `{two_step}`\n⚠️ Change 2-Step password after login!"
                    if two_step else "🔐 2-Step : `none`"
                )
                await client.send_message(
                    uid,
                    f"🔑 **OTP Received for `{phone}`**\n\n"
                    f"Code     : **`{otp_code}`**\n"
                    f"{two_step_line}\n\n"
                    f"⚡ Enter OTP now — expires in ~2 minutes!"
                )
            else:
                await client.send_message(
                    uid,
                    f"⚠️ No OTP arrived for `{phone}` within 5 minutes.\n"
                    f"Try logging in again — the OTP will be forwarded when it arrives."
                )

        asyncio.create_task(_watch_otp())

    @app.on_callback_query(filters.regex("^noop$"))
    async def noop(client, callback: CallbackQuery):
        await callback.answer()
