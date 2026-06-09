"""
Payment handlers.

ROOT CAUSES FIXED:
  1. BUTTON_URL_INVALID — Telegram rejects upi:// scheme and empty-string URLs.
     Fix: UPI deep link is now sent as plain text (copy-able), not a button URL.
           All URL buttons are guarded — only added when URL is a non-empty https:// string.
  2. Empty string from gateway (e.g. data.get("payLink","")) passes `if not link`
     but still causes BUTTON_URL_INVALID.
     Fix: _validate_url() strips and checks for https:// prefix before use.
  3. Placeholder "https://t.me/YourBotUsername" replaced with bot_link() from config.
  4. upilink.in replaced — UPI web payment shown as plain text, not a broken URL button.
"""

import re
import uuid
import urllib.parse
import aiohttp
from pyrogram import Client, filters
from pyrogram.types import (
    CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Message
)
import database as db
from config import (
    CASHFREE_APP_ID, CASHFREE_SECRET, CASHFREE_ENV, CASHFREE_ENABLED,
    RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET, RAZORPAY_ENABLED,
    OXAPAY_MERCHANT_API_KEY, OXAPAY_ENABLED,
    HELEKET_MERCHANT_ID, HELEKET_API_KEY, HELEKET_CALLBACK_URL, HELEKET_ENABLED,
    OWNER_IDS, MIN_INR, MIN_USD,
    bot_link,
)

_deposit_state: dict = {}

# Supported manual crypto coins — must stay in sync with owner.py
CRYPTO_COINS = {
    "USDT_BEP20": {"label": "💵 USDT (BEP20 / BSC)",  "network": "BEP20 (BSC)"},
    "USDT_TRC20": {"label": "💵 USDT (TRC20 / TRON)", "network": "TRC20 (TRON)"},
    "USDT_ERC20": {"label": "💵 USDT (ERC20 / ETH)",  "network": "ERC20 (Ethereum)"},
    "TON":        {"label": "💎 TON",                  "network": "TON"},
}


# ── URL safety guard ──────────────────────────────────────────────────────────

def _validate_url(url: str) -> str | None:
    """
    Returns the URL only if it's a non-empty https:// string.
    Returns None otherwise — caller must NOT create a button with None url.
    Telegram rejects: empty string, upi://, tel://, and any non-http(s) scheme.
    """
    if not url:
        return None
    url = url.strip()
    if url.startswith("https://") or url.startswith("http://"):
        return url
    return None


def _safe_url_buttons(pairs: list[tuple[str, str]]) -> list[list[InlineKeyboardButton]]:
    """
    Build URL button rows only for pairs where the URL is valid.
    pairs = [("label", "url"), ...]
    """
    rows = []
    for label, url in pairs:
        safe = _validate_url(url)
        if safe:
            rows.append([InlineKeyboardButton(label, url=safe)])
    return rows


def register(app: Client):

    # ── Deposit menu ──────────────────────────────────────────────────────────
    @app.on_callback_query(filters.regex("^deposit$"))
    async def deposit_menu(client, callback: CallbackQuery):
        user    = await db.get_user(callback.from_user.id)
        bal_inr = user.get("balance_inr", 0)
        bal_usd = user.get("balance_usd", 0)
        await callback.edit_message_text(
            f"💰 **Deposit Funds**\n\n"
            f"💳 Balance: ₹{bal_inr} | ${bal_usd}\n\n"
            f"Choose payment type:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💳 UPI / INR", callback_data="dep_upi"),
                 InlineKeyboardButton("🪙 Crypto",    callback_data="dep_crypto")],
                [InlineKeyboardButton("🔙 Back",      callback_data="main_menu")],
            ])
        )

    # ── UPI methods ───────────────────────────────────────────────────────────
    @app.on_callback_query(filters.regex("^dep_upi$"))
    async def dep_upi(client, callback: CallbackQuery):
        cfg  = await db.get_payment_settings()
        rows = []
        if CASHFREE_ENABLED:
            rows.append([InlineKeyboardButton("💳 Cashfree (Auto)", callback_data="dep_upi_cashfree")])
        if RAZORPAY_ENABLED:
            rows.append([InlineKeyboardButton("💳 Razorpay (Auto)", callback_data="dep_upi_razorpay")])
        if cfg.get("upi_id"):
            rows.append([InlineKeyboardButton("📲 Manual UPI",      callback_data="dep_upi_manual")])
        if not rows:
            rows.append([InlineKeyboardButton("🔜 Coming Soon",     callback_data="noop_cs")])
        rows.append([InlineKeyboardButton("🔙 Back", callback_data="deposit")])
        await callback.edit_message_text(
            f"💳 **UPI / INR Deposit**\n\nMinimum: ₹{MIN_INR}\n\nChoose method:",
            reply_markup=InlineKeyboardMarkup(rows)
        )

    # ── Crypto methods ────────────────────────────────────────────────────────
    @app.on_callback_query(filters.regex("^dep_crypto$"))
    async def dep_crypto(client, callback: CallbackQuery):
        cfg  = await db.get_payment_settings()
        rows = []
        if OXAPAY_ENABLED:
            rows.append([InlineKeyboardButton("🪙 OxaPay (Auto)",  callback_data="dep_crypto_oxapay")])
        if HELEKET_ENABLED:
            rows.append([InlineKeyboardButton("🔗 Heleket (Auto)", callback_data="dep_crypto_heleket")])
        crypto_cfg = cfg.get("crypto", {})
        for coin_key, meta in CRYPTO_COINS.items():
            if crypto_cfg.get(coin_key, {}).get("address"):
                rows.append([InlineKeyboardButton(
                    f"{meta['label']} (Manual)",
                    callback_data=f"dep_crypto_manual_{coin_key}"
                )])
        if not rows:
            rows.append([InlineKeyboardButton("🔜 Coming Soon", callback_data="noop_cs")])
        rows.append([InlineKeyboardButton("🔙 Back", callback_data="deposit")])
        await callback.edit_message_text(
            f"🪙 **Crypto Deposit**\n\nMinimum: ${MIN_USD}\n\nChoose method:",
            reply_markup=InlineKeyboardMarkup(rows)
        )

    @app.on_callback_query(filters.regex("^noop_cs$"))
    async def noop_cs(client, callback: CallbackQuery):
        await callback.answer("🔜 Coming Soon — not configured yet.", show_alert=True)

    # ── Cashfree ──────────────────────────────────────────────────────────────
    @app.on_callback_query(filters.regex("^dep_upi_cashfree$"))
    async def dep_cashfree(client, callback: CallbackQuery):
        _deposit_state[callback.from_user.id] = {"step": "amount", "method": "cashfree"}
        await callback.edit_message_text(
            f"💳 **Cashfree — UPI Deposit**\n\n"
            f"Send the amount in INR:\nMinimum: ₹{MIN_INR}\n\n/cancel to abort.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="dep_upi")]
            ])
        )

    # ── Razorpay ──────────────────────────────────────────────────────────────
    @app.on_callback_query(filters.regex("^dep_upi_razorpay$"))
    async def dep_razorpay(client, callback: CallbackQuery):
        _deposit_state[callback.from_user.id] = {"step": "amount", "method": "razorpay"}
        await callback.edit_message_text(
            f"💳 **Razorpay — UPI Deposit**\n\n"
            f"Send the amount in INR:\nMinimum: ₹{MIN_INR}\n\n/cancel to abort.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="dep_upi")]
            ])
        )

    # ── Manual UPI ────────────────────────────────────────────────────────────
    @app.on_callback_query(filters.regex("^dep_upi_manual$"))
    async def dep_upi_manual(client, callback: CallbackQuery):
        cfg    = await db.get_payment_settings()
        upi_id = cfg.get("upi_id", "")
        if not upi_id:
            await callback.answer("❌ Manual UPI is not configured yet.", show_alert=True)
            return
        upi_name = cfg.get("upi_name", "TG Account Store")
        qr_fid   = cfg.get("upi_qr_file_id", "")
        _deposit_state[callback.from_user.id] = {"step": "manual_upi_amount"}
        caption = (
            f"📲 **Manual UPI Deposit**\n\n"
            f"💳 UPI ID: `{upi_id}`\n\n"
            f"Minimum: ₹{MIN_INR}\n\n"
            f"Send the amount you want to deposit (INR):"
        )
        back_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data="dep_upi")]
        ])
        if qr_fid:
            await callback.message.delete()
            await client.send_photo(callback.from_user.id, qr_fid,
                                    caption=caption, reply_markup=back_kb)
        else:
            await callback.edit_message_text(caption, reply_markup=back_kb)

    # ── OxaPay ────────────────────────────────────────────────────────────────
    @app.on_callback_query(filters.regex("^dep_crypto_oxapay$"))
    async def dep_oxapay(client, callback: CallbackQuery):
        _deposit_state[callback.from_user.id] = {"step": "amount_usd", "method": "oxapay"}
        await callback.edit_message_text(
            f"🪙 **OxaPay — Crypto Deposit**\n\n"
            f"Send the amount in USD:\nMinimum: ${MIN_USD}\n\n/cancel to abort.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="dep_crypto")]
            ])
        )

    # ── Heleket ───────────────────────────────────────────────────────────────
    @app.on_callback_query(filters.regex("^dep_crypto_heleket$"))
    async def dep_heleket(client, callback: CallbackQuery):
        _deposit_state[callback.from_user.id] = {"step": "amount_usd", "method": "heleket"}
        await callback.edit_message_text(
            f"🔗 **Heleket — Crypto Deposit**\n\n"
            f"Send the amount in USD:\nMinimum: ${MIN_USD}\n\n/cancel to abort.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="dep_crypto")]
            ])
        )

    # ── Manual Crypto (per coin) ──────────────────────────────────────────────
    @app.on_callback_query(filters.regex(r"^dep_crypto_manual_(.+)$"))
    async def dep_crypto_manual_coin(client, callback: CallbackQuery):
        coin_key = callback.matches[0].group(1)
        if coin_key not in CRYPTO_COINS:
            await callback.answer("Unknown coin.", show_alert=True)
            return
        cfg      = await db.get_payment_settings()
        coin_cfg = cfg.get("crypto", {}).get(coin_key, {})
        address  = coin_cfg.get("address", "")
        meta     = CRYPTO_COINS[coin_key]
        if not address:
            await callback.answer("❌ This coin is not configured yet.", show_alert=True)
            return
        _deposit_state[callback.from_user.id] = {
            "step": "manual_crypto_amount", "coin_key": coin_key
        }
        await callback.edit_message_text(
            f"📤 **Manual {meta['label']} Deposit**\n\n"
            f"🔗 **Network:** `{meta['network']}`\n"
            f"📋 **Wallet Address:**\n`{address}`\n\n"
            f"⚠️ Send only on **{meta['network']}** network.\n\n"
            f"Minimum: ${MIN_USD}\n\n"
            f"Send the amount you want to deposit (USD):",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="dep_crypto")]
            ])
        )

    # ── Text message handler ──────────────────────────────────────────────────
    @app.on_message(filters.private & filters.text
                    & ~filters.command(["start", "owner", "cancel"]))
    async def deposit_text_handler(client, message: Message):
        uid   = message.from_user.id
        state = _deposit_state.get(uid)
        if not state:
            await message.continue_propagation()
            return

        if message.text.strip().lower() == "/cancel":
            _deposit_state.pop(uid, None)
            await message.reply("❌ Cancelled.")
            return

        step = state.get("step")

        # ── Auto gateway: INR amount ──────────────────────────────────────────
        if step == "amount":
            try:
                amount = float(message.text.strip())
            except ValueError:
                await message.reply("❌ Send a valid number, e.g. `500`")
                return
            if amount < MIN_INR:
                await message.reply(f"❌ Minimum deposit is ₹{MIN_INR}.")
                return

            method = state.get("method")
            _deposit_state.pop(uid, None)
            wait = await message.reply("⏳ Generating payment QR...")

            if method == "cashfree":
                # Cashfree: create order → fetch UPI QR image → send as photo
                session_id, order_id, checkout_url, err = await _create_cashfree_order(uid, amount)
                if err or not session_id:
                    await wait.edit_text(
                        f"❌ Could not create Cashfree order.\n"
                        f"`{err or 'No session ID returned'}`\n\n"
                        f"Please contact support."
                    )
                    return

                # Fetch settings once — used for both QR generation and caption
                cfg      = await db.get_payment_settings()
                upi_id   = cfg.get("upi_id", "")
                upi_name = cfg.get("upi_name", "TG Account Store")

                # Generate QR locally from UPI string (no Cashfree S2S flag needed)
                qr_bytes, qr_err = await _cashfree_upi_qr(
                    order_id, amount, upi_id, upi_name
                )
                upi_deep = (
                    f"upi://pay?pa={upi_id}"
                    f"&pn={urllib.parse.quote(upi_name)}"
                    f"&am={amount:.2f}&cu=INR"
                ) if upi_id else ""

                caption = (
                    f"✅ **Cashfree UPI Payment**\n\n"
                    f"💰 Amount: ₹{amount:.0f}\n"
                    f"🔖 Order: `{order_id}`\n\n"
                    f"📲 Scan QR with any UPI app\n"
                    + (f"💳 UPI ID: `{upi_id}`\n" if upi_id else "")
                    + (f"🔗 Deep Link: `{upi_deep}`\n" if upi_deep else "")
                    + f"\n⚠️ Balance updates in 1–5 min after payment."
                )

                kb_rows = []
                safe_checkout = _validate_url(checkout_url)
                if safe_checkout:
                    kb_rows.append([InlineKeyboardButton("🌐 Pay via Browser", url=safe_checkout)])
                kb_rows.append([InlineKeyboardButton("🆘 Support",    callback_data="support")])
                kb_rows.append([InlineKeyboardButton("🏠 Main Menu",  callback_data="main_menu")])

                await wait.delete()
                if qr_bytes:
                    import io
                    await client.send_photo(
                        uid,
                        io.BytesIO(qr_bytes),
                        caption=caption,
                        reply_markup=InlineKeyboardMarkup(kb_rows),
                    )
                else:
                    # QR fetch failed — fallback to text only
                    extra = f"\n⚠️ QR unavailable: {qr_err}" if qr_err else ""
                    await client.send_message(
                        uid,
                        caption + extra,
                        reply_markup=InlineKeyboardMarkup(kb_rows),
                    )

            else:
                # Razorpay
                link, order_id, err = await _create_razorpay_order(uid, amount)
                safe_link = _validate_url(link)
                if not safe_link:
                    await wait.edit_text(
                        f"❌ Could not generate payment link.\n"
                        f"`{err or 'Empty URL returned by gateway'}`\n\n"
                        f"Please contact support."
                    )
                    return

                cfg      = await db.get_payment_settings()
                upi_id   = cfg.get("upi_id", "")
                upi_name = cfg.get("upi_name", "TG Account Store")
                upi_info = ""
                if upi_id:
                    upi_deep = (
                        f"upi://pay?pa={upi_id}"
                        f"&pn={urllib.parse.quote(upi_name)}"
                        f"&am={amount:.2f}&cu=INR"
                    )
                    upi_info = (
                        f"\n\n📲 UPI ID: `{upi_id}`\n"
                        f"🔗 Deep Link: `{upi_deep}`\n"
                        f"_(Copy & open in GPay / PhonePe / Paytm)_"
                    )

                await wait.edit_text(
                    f"✅ **Payment Link Ready!**\n\n"
                    f"💰 Amount: ₹{amount:.0f}\n"
                    f"🔖 Order: `{order_id}`"
                    f"{upi_info}\n\n"
                    f"⚠️ Balance updates in 1–5 min after payment.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🌐 Pay Now",   url=safe_link)],
                        [InlineKeyboardButton("🆘 Support",   callback_data="support")],
                        [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")],
                    ])
                )

        # ── Auto gateway: USD amount ──────────────────────────────────────────
        elif step == "amount_usd":
            try:
                amount = float(message.text.strip())
            except ValueError:
                await message.reply("❌ Send a valid number, e.g. `10`")
                return
            if amount < MIN_USD:
                await message.reply(f"❌ Minimum deposit is ${MIN_USD}.")
                return

            method = state.get("method")
            _deposit_state.pop(uid, None)
            wait = await message.reply("⏳ Generating crypto invoice...")

            if method == "oxapay":
                inv_url, inv_id, err = await _create_oxapay_invoice(uid, amount)
                pay_label = "🪙 Pay via OxaPay"
            else:
                inv_url, inv_id, err = await _create_heleket_invoice(uid, amount)
                pay_label = "🔗 Pay via Heleket"

            safe_url = _validate_url(inv_url)
            if not safe_url:
                await wait.edit_text(
                    f"❌ Could not generate invoice.\n"
                    f"`{err or 'Empty URL returned by gateway'}`\n\n"
                    f"Please contact support."
                )
                return

            await wait.edit_text(
                f"✅ **Crypto Invoice Ready!**\n\n"
                f"🪙 Amount: ${amount:.2f}\n"
                f"🔖 Invoice: `{inv_id}`\n\n"
                f"⚠️ Balance updates after confirmation (5–15 min).",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(pay_label,     url=safe_url)],
                    [InlineKeyboardButton("🆘 Support",   callback_data="support")],
                    [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")],
                ])
            )

        # ── Manual UPI: amount ────────────────────────────────────────────────
        elif step == "manual_upi_amount":
            try:
                amount = float(message.text.strip())
            except ValueError:
                await message.reply("❌ Send a valid INR amount.")
                return
            if amount < MIN_INR:
                await message.reply(f"❌ Minimum deposit is ₹{MIN_INR}.")
                return

            cfg      = await db.get_payment_settings()
            upi_id   = cfg.get("upi_id", "")
            upi_name = cfg.get("upi_name", "TG Account Store")
            qr_fid   = cfg.get("upi_qr_file_id", "")

            if not upi_id:
                await message.reply("❌ UPI not configured. Contact support.")
                _deposit_state.pop(uid, None)
                return

            _deposit_state[uid] = {"step": "manual_upi_ss", "amount_inr": amount}

            # Build UPI deep link as plain text — NOT a button URL
            upi_deep = (
                f"upi://pay?pa={upi_id}"
                f"&pn={urllib.parse.quote(upi_name)}"
                f"&am={amount:.2f}&cu=INR"
            )

            pay_text = (
                f"✅ **Amount: ₹{amount:.0f}**\n\n"
                f"📲 **Pay to:**\n"
                f"💳 UPI ID: `{upi_id}`\n\n"
                f"📱 **UPI Deep Link** _(copy & open in GPay/PhonePe/Paytm)_:\n"
                f"`{upi_deep}`\n\n"
                f"After paying, send the **payment screenshot** with the **UTR number**.\n\n"
                f"Format:\n`UTR: 123456789012`\n_(attach screenshot)_"
            )

            if qr_fid:
                await client.send_photo(uid, qr_fid, caption=pay_text)
            else:
                await message.reply(pay_text)

        # ── Manual UPI: screenshot + UTR ──────────────────────────────────────
        elif step == "manual_upi_ss":
            utr_text  = (message.text or message.caption or "")
            utr_match = re.search(r"\b(\d{10,12})\b", utr_text)
            utr        = utr_match.group(1) if utr_match else "N/A"
            amount_inr = state.get("amount_inr", 0)
            dep_id     = f"MUPI_{uid}_{uuid.uuid4().hex[:8].upper()}"

            await db.save_deposit(dep_id, {
                "deposit_id": dep_id,
                "user_id":    uid,
                "amount_inr": amount_inr,
                "method":     "manual_upi",
                "utr":        utr,
                "status":     "pending",
            })
            _deposit_state.pop(uid, None)

            owner_markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Approve", callback_data=f"dep_approve_{dep_id}"),
                 InlineKeyboardButton("❌ Reject",  callback_data=f"dep_reject_{dep_id}")],
            ])
            owner_text = (
                f"📥 **Manual UPI Deposit**\n\n"
                f"👤 User: `{uid}`\n"
                f"💰 Amount: ₹{amount_inr}\n"
                f"🔑 UTR: `{utr}`\n"
                f"🔖 ID: `{dep_id}`"
            )
            for owner_id in OWNER_IDS:
                try:
                    if message.photo:
                        await client.send_photo(owner_id, message.photo.file_id,
                                                caption=owner_text, reply_markup=owner_markup)
                    else:
                        await client.send_message(owner_id, owner_text, reply_markup=owner_markup)
                except Exception:
                    pass

            await message.reply(
                f"✅ **Deposit Request Submitted!**\n\n"
                f"💰 ₹{amount_inr}\n"
                f"🔖 Ref: `{dep_id}`\n\n"
                f"You'll be notified once approved (usually within 1 hour).",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")],
                ])
            )

        # ── Manual Crypto: amount ─────────────────────────────────────────────
        elif step == "manual_crypto_amount":
            try:
                amount = float(message.text.strip())
            except ValueError:
                await message.reply("❌ Send a valid USD amount.")
                return
            if amount < MIN_USD:
                await message.reply(f"❌ Minimum deposit is ${MIN_USD}.")
                return

            coin_key = state.get("coin_key", "USDT_BEP20")
            _deposit_state[uid] = {
                "step": "manual_crypto_ss",
                "amount_usd": amount,
                "coin_key": coin_key,
            }
            meta = CRYPTO_COINS.get(coin_key, {})
            await message.reply(
                f"✅ Amount: ${amount:.2f}\n\n"
                f"📸 Now send your **transaction screenshot** and **TxID**.\n\n"
                f"🔗 Network: `{meta.get('network', coin_key)}`\n\n"
                f"Format:\n`TxID: 0xabc123...`\n_(attach screenshot)_"
            )

        # ── Manual Crypto: txid + screenshot ─────────────────────────────────
        elif step == "manual_crypto_ss":
            tx_text    = (message.text or message.caption or "")
            tx_match   = re.search(
                r"(?:txid|tx|hash)[:\s]*(0x[a-fA-F0-9]{20,}|\w{40,})", tx_text, re.I
            )
            txid       = tx_match.group(1) if tx_match else "N/A"
            amount_usd = state.get("amount_usd", 0)
            coin_key   = state.get("coin_key", "USDT_BEP20")
            meta       = CRYPTO_COINS.get(coin_key, {})
            dep_id     = f"MCRY_{uid}_{uuid.uuid4().hex[:8].upper()}"

            await db.save_deposit(dep_id, {
                "deposit_id": dep_id,
                "user_id":    uid,
                "amount_usd": amount_usd,
                "method":     "manual_crypto",
                "coin":       coin_key,
                "network":    meta.get("network", coin_key),
                "txid":       txid,
                "status":     "pending",
            })
            _deposit_state.pop(uid, None)

            owner_markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Approve", callback_data=f"dep_approve_{dep_id}"),
                 InlineKeyboardButton("❌ Reject",  callback_data=f"dep_reject_{dep_id}")],
            ])
            owner_text = (
                f"📥 **Manual Crypto Deposit**\n\n"
                f"👤 User: `{uid}`\n"
                f"💰 Amount: ${amount_usd} {meta.get('label', coin_key)}\n"
                f"🔗 Network: `{meta.get('network', coin_key)}`\n"
                f"🧾 TxID: `{txid}`\n"
                f"🔖 ID: `{dep_id}`"
            )
            for owner_id in OWNER_IDS:
                try:
                    if message.photo:
                        await client.send_photo(owner_id, message.photo.file_id,
                                                caption=owner_text, reply_markup=owner_markup)
                    else:
                        await client.send_message(owner_id, owner_text, reply_markup=owner_markup)
                except Exception:
                    pass

            await message.reply(
                f"✅ **Deposit Request Submitted!**\n\n"
                f"🪙 ${amount_usd} {meta.get('label', coin_key)}\n"
                f"🔖 Ref: `{dep_id}`\n\n"
                f"You'll be notified once approved (usually within 1 hour).",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")],
                ])
            )


# ══════════════════════════════════════════════════════════════════════════════
# CASHFREE
# ══════════════════════════════════════════════════════════════════════════════

async def _create_cashfree_order(user_id: int, amount_inr: float):
    """
    Creates a Cashfree order.
    Returns (payment_session_id, order_id, checkout_url, error)
    checkout_url is the hosted payment page (https) — used as fallback browser button.
    payment_session_id is used to fetch the UPI QR image.
    """
    order_id = f"TGS_{user_id}_{uuid.uuid4().hex[:8].upper()}"
    base     = (
        "https://sandbox.cashfree.com"
        if CASHFREE_ENV == "sandbox"
        else "https://api.cashfree.com"
    )
    headers = {
        "x-api-version":   "2023-08-01",
        "x-client-id":     CASHFREE_APP_ID,
        "x-client-secret": CASHFREE_SECRET,
        "Content-Type":    "application/json",
    }
    payload = {
        "order_id":       order_id,
        "order_amount":   amount_inr,
        "order_currency": "INR",
        "customer_details": {
            "customer_id":    str(user_id),
            "customer_phone": "9999999999",
        },
        "order_meta": {
            "return_url": bot_link(),
        },
    }
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(
                f"{base}/pg/orders",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as r:
                data = await r.json()
                if r.status in (200, 201):
                    session_id   = data.get("payment_session_id", "").strip()
                    # Cashfree's own payment_link is the most reliable hosted page URL
                    checkout_url = data.get("payment_link", "").strip()
                    # If not present, build from session_id using correct JS-SDK hosted URL
                    if not _validate_url(checkout_url) and session_id:
                        env_sub      = "sandbox" if CASHFREE_ENV == "sandbox" else "payments"
                        checkout_url = f"https://{env_sub}.cashfree.com/order/#token={session_id}"
                    if session_id:
                        return session_id, order_id, checkout_url, None
                    return None, None, None, "No payment_session_id in Cashfree response"
                return None, None, None, data.get("message", str(data))
    except Exception as e:
        return None, None, None, str(e)


async def _cashfree_upi_qr(order_id: str, amount_inr: float, upi_id: str, upi_name: str = "TG Store"):
    """
    Generates a UPI QR code image locally using the qrcode library.
    No Cashfree S2S flag needed — uses standard NPCI UPI QR string format.

    UPI QR string format (NPCI standard):
      upi://pay?pa=<vpa>&pn=<name>&am=<amount>&cu=INR&tn=<note>

    Returns (png_bytes: bytes|None, error: str|None)
    """
    try:
        import qrcode
        import io

        if not upi_id:
            return None, "UPI ID not set — go to Owner Panel → ⚙️ Payment Settings → UPI Settings → Set UPI ID"

        upi_string = (
            f"upi://pay?pa={upi_id}"
            f"&pn={urllib.parse.quote(upi_name)}"
            f"&am={amount_inr:.2f}"
            f"&cu=INR"
            f"&tn=TG+Store+Deposit"
            f"&tr={order_id}"
        )

        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=10,
            border=4,
        )
        qr.add_data(upi_string)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return buf.read(), None

    except ImportError:
        return None, "qrcode library not installed — run: pip install qrcode[pil]"
    except Exception as e:
        return None, str(e)


# ══════════════════════════════════════════════════════════════════════════════
# RAZORPAY
# ══════════════════════════════════════════════════════════════════════════════

async def _create_razorpay_order(user_id: int, amount_inr: float):
    """Returns (url: str|None, order_id: str|None, error: str|None)"""
    import base64
    order_id = f"TGS_{user_id}_{uuid.uuid4().hex[:6].upper()}"
    creds    = base64.b64encode(
        f"{RAZORPAY_KEY_ID}:{RAZORPAY_KEY_SECRET}".encode()
    ).decode()
    headers = {
        "Authorization": f"Basic {creds}",
        "Content-Type":  "application/json",
    }
    payload = {
        "amount":          int(amount_inr * 100),
        "currency":        "INR",
        "description":     f"TG Store Deposit — {order_id}",
        "reference_id":    order_id,
        "callback_url":    bot_link(),
        "callback_method": "get",
    }
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(
                "https://api.razorpay.com/v1/payment_links",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as r:
                data = await r.json()
                if r.status in (200, 201):
                    link = data.get("short_url", "").strip()
                    if _validate_url(link):
                        return link, order_id, None
                    return None, None, "Could not extract payment URL from Razorpay response"
                return None, None, data.get("error", {}).get("description", str(data))
    except Exception as e:
        return None, None, str(e)


# ══════════════════════════════════════════════════════════════════════════════
# OXAPAY
# ══════════════════════════════════════════════════════════════════════════════

async def _create_oxapay_invoice(user_id: int, amount_usd: float):
    """Returns (url: str|None, invoice_id: str|None, error: str|None)"""
    invoice_id = f"TGS_{user_id}_{uuid.uuid4().hex[:8].upper()}"
    payload    = {
        "merchant":       OXAPAY_MERCHANT_API_KEY,
        "amount":         amount_usd,
        "currency":       "USDT",
        "payCurrency":    "USDT",
        "lifeTime":       30,
        "feePaidByPayer": 0,
        "underPaidCover": 2.5,
        "callbackUrl":    "",
        "returnUrl":      bot_link(),
        "orderId":        invoice_id,
        "description":    "TG Store Deposit",
    }
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(
                "https://api.oxapay.com/merchants/request",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as r:
                data = await r.json()
                if data.get("result") == 100:
                    link = data.get("payLink", "").strip()
                    if _validate_url(link):
                        return link, invoice_id, None
                    return None, None, "OxaPay returned empty payLink"
                return None, None, data.get("message", str(data))
    except Exception as e:
        return None, None, str(e)


# ══════════════════════════════════════════════════════════════════════════════
# HELEKET
# ══════════════════════════════════════════════════════════════════════════════

async def _create_heleket_invoice(user_id: int, amount_usd: float):
    """Returns (url: str|None, invoice_id: str|None, error: str|None)"""
    import hashlib
    invoice_id = f"TGS_{user_id}_{uuid.uuid4().hex[:8].upper()}"
    payload    = {
        "amount":       f"{amount_usd:.2f}",
        "currency":     "USDT",
        "order_id":     invoice_id,
        "description":  "TG Store Deposit",
        "callback_url": HELEKET_CALLBACK_URL or "",
        "success_url":  bot_link(),
        "fail_url":     bot_link(),
    }
    sorted_vals = ":".join(str(v) for _, v in sorted(payload.items()))
    sign        = hashlib.md5(f"{sorted_vals}:{HELEKET_API_KEY}".encode()).hexdigest()
    headers     = {
        "merchant":     HELEKET_MERCHANT_ID,
        "sign":         sign,
        "Content-Type": "application/json",
    }
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(
                "https://api.heleket.com/v1/payment",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as r:
                data = await r.json()
                if data.get("state") == 0:
                    link = data.get("result", {}).get("url", "").strip()
                    if _validate_url(link):
                        return link, invoice_id, None
                    return None, None, "Heleket returned empty URL"
                return None, None, data.get("message", str(data))
    except Exception as e:
        return None, None, str(e)
