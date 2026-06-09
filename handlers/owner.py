import asyncio
import datetime
import os
from pyrogram import Client, filters
from pyrogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from pyrogram.errors import SessionPasswordNeeded, PhoneCodeExpired, PhoneCodeInvalid
import database as db
from config import OWNER_IDS, get_flag, SESSIONS_DIR, API_ID, API_HASH

# Crypto coins supported for manual deposit
# Must stay in sync with handlers/payments.py → CRYPTO_COINS
CRYPTO_COINS = {
    "USDT_BEP20": {"label": "USDT BEP20 (BSC)", "network": "BEP20 (BSC)"},
    "USDT_TRC20": {"label": "USDT TRC20 (TRON)", "network": "TRC20 (TRON)"},
    "USDT_ERC20": {"label": "USDT ERC20 (ETH)", "network": "ERC20 (Ethereum)"},
    "TON": {"label": "TON", "network": "TON"},
}


def _is_owner(_, __, update):
    user = getattr(update, "from_user", None)
    return bool(user and user.id in OWNER_IDS)


owner_msg_filter = filters.create(_is_owner) & filters.private
owner_cb_filter = filters.create(_is_owner)

_add_stock_state = {}
_set_price_state = {}
_broadcast_state = {}
_pay_settings_state = {}  # for payment settings input flow


def _owner_panel_markup():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("➕ Add Stock", callback_data="owner_add_stock"),
                InlineKeyboardButton("💰 Set Price", callback_data="owner_set_price"),
            ],
            [
                InlineKeyboardButton("📊 View Stock", callback_data="owner_view_stock"),
                InlineKeyboardButton(
                    "💳 Add Balance", callback_data="owner_add_balance"
                ),
            ],
            [
                InlineKeyboardButton("📢 Broadcast", callback_data="owner_broadcast"),
                InlineKeyboardButton("👥 All Users", callback_data="owner_all_users"),
            ],
            [
                InlineKeyboardButton("🛒 All Orders", callback_data="owner_all_orders"),
                InlineKeyboardButton("💸 Deposits", callback_data="owner_deposits"),
            ],
            [
                InlineKeyboardButton(
                    "⏳ Pending Payments", callback_data="owner_pending_deps"
                )
            ],
            [
                InlineKeyboardButton(
                    "⚙️ Payment Settings", callback_data="owner_pay_settings"
                )
            ],
        ]
    )


async def _countries_buttons(cb_prefix, back_cb, include_new=False):
    countries = await db.get_all_countries()
    rows, row = [], []
    for c in countries:
        row.append(
            InlineKeyboardButton(
                f"{get_flag(c)} {c.title()}", callback_data=f"{cb_prefix}{c}"
            )
        )
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    if include_new:
        rows.append(
            [InlineKeyboardButton("✏️ New Country", callback_data=f"{cb_prefix}__new__")]
        )
    rows.append([InlineKeyboardButton("🔙 Back", callback_data=back_cb)])
    return rows


# ── Helpers ───────────────────────────────────────────────────────────────────


def _dep_amount_str(dep):
    if dep.get("amount_inr"):
        return f"₹{dep['amount_inr']:.0f} INR"
    return f"${dep.get('amount_usd', 0):.2f} USDT"


def _dep_method_label(dep):
    return {"manual_upi": "📲 Manual UPI", "manual_crypto": "📤 Manual Crypto"}.get(
        dep.get("method", ""), dep.get("method", "")
    )


def _dep_detail_text(dep):
    dt = datetime.datetime.fromtimestamp(dep.get("created_at", 0)).strftime(
        "%d %b %Y %H:%M"
    )
    lines = [
        f"🔖 **Deposit ID:** `{dep['deposit_id']}`",
        f"👤 **User ID:** `{dep['user_id']}`",
        f"💰 **Amount:** {_dep_amount_str(dep)}",
        f"🏦 **Method:** {_dep_method_label(dep)}",
        f"📅 **Date:** {dt}",
    ]
    if dep.get("coin"):
        lines.append(f"🪙 **Coin:** {dep['coin']}")
    if dep.get("network"):
        lines.append(f"🔗 **Network:** `{dep['network']}`")
    if dep.get("utr"):
        lines.append(f"🔑 **UTR:** `{dep['utr']}`")
    if dep.get("txid"):
        lines.append(f"🧾 **TxID:** `{dep['txid']}`")
    return "\n".join(lines)


def _dep_action_markup(dep_id, back_cb="owner_pending_deps"):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Approve", callback_data=f"dep_approve_{dep_id}"
                ),
                InlineKeyboardButton("❌ Reject", callback_data=f"dep_reject_{dep_id}"),
            ],
            [InlineKeyboardButton("🔙 Back to Pending", callback_data=back_cb)],
        ]
    )


def register(app: Client):
    # ── /owner ────────────────────────────────────────────────────────────────
    @app.on_message(filters.command("owner") & owner_msg_filter)
    async def owner_panel(client, message: Message):
        total_stock = await db.get_stock_count()
        all_users = await db.get_all_users()
        all_orders = await db.get_all_orders()
        pending = await db.get_pending_deposits()
        pstr = f" ({len(pending)} ⏳)" if pending else ""
        await message.reply_text(
            f"👑 **Owner Panel**\n\n"
            f"📦 Stock: `{total_stock}` | 👥 Users: `{len(all_users)}` | 🛒 Orders: `{len(all_orders)}`\n"
            f"⏳ Pending Payments{pstr}",
            reply_markup=_owner_panel_markup(),
        )

    @app.on_callback_query(filters.regex("^owner_back$") & owner_cb_filter)
    async def owner_back(client, callback: CallbackQuery):
        total_stock = await db.get_stock_count()
        all_users = await db.get_all_users()
        all_orders = await db.get_all_orders()
        pending = await db.get_pending_deposits()
        pstr = f" ({len(pending)} ⏳)" if pending else ""
        await callback.edit_message_text(
            f"👑 **Owner Panel**\n\n"
            f"📦 Stock: `{total_stock}` | 👥 Users: `{len(all_users)}` | 🛒 Orders: `{len(all_orders)}`\n"
            f"⏳ Pending Payments{pstr}",
            reply_markup=_owner_panel_markup(),
        )

    # ══════════════════════════════════════════════════════════════════════════
    # ⚙️ PAYMENT SETTINGS
    # ══════════════════════════════════════════════════════════════════════════

    async def _pay_settings_menu(callback: CallbackQuery):
        cfg = await db.get_payment_settings()
        upi_id = cfg.get("upi_id", "❌ Not set")
        upi_name = cfg.get("upi_name", "❌ Not set")
        qr_set = "✅ Set" if cfg.get("upi_qr_file_id") else "❌ Not set"
        crypto_cfg = cfg.get("crypto", {})

        lines = [
            "⚙️ **Payment Settings**\n",
            "━━━━ 💳 UPI ━━━━",
            f"📲 UPI ID  : `{upi_id}`",
            f"🏷️ Name    : `{upi_name}`",
            f"🖼️ QR Code : {qr_set}",
            "",
            "━━━━ 🪙 Crypto ━━━━",
        ]
        for key, meta in CRYPTO_COINS.items():
            addr = crypto_cfg.get(key, {}).get("address", "")
            status = f"`{addr[:12]}...`" if addr else "❌ Not set"
            lines.append(f"• {meta['label']}: {status}")

        await callback.edit_message_text(
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "💳 UPI Settings", callback_data="pset_upi_menu"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "🪙 Crypto Settings", callback_data="pset_crypto_menu"
                        )
                    ],
                    [InlineKeyboardButton("🔙 Back", callback_data="owner_back")],
                ]
            ),
        )

    @app.on_callback_query(filters.regex("^owner_pay_settings$") & owner_cb_filter)
    async def owner_pay_settings(client, callback: CallbackQuery):
        await _pay_settings_menu(callback)

    # ── UPI settings sub-menu ─────────────────────────────────────────────────
    @app.on_callback_query(filters.regex("^pset_upi_menu$") & owner_cb_filter)
    async def pset_upi_menu(client, callback: CallbackQuery):
        cfg = await db.get_payment_settings()
        upi_id = cfg.get("upi_id", "❌ Not set")
        name = cfg.get("upi_name", "❌ Not set")
        qr_set = "✅ Set" if cfg.get("upi_qr_file_id") else "❌ Not set"
        await callback.edit_message_text(
            f"💳 **UPI Settings**\n\n"
            f"📲 UPI ID  : `{upi_id}`\n"
            f"🏷️ Name    : `{name}`\n"
            f"🖼️ QR Code : {qr_set}\n\n"
            f"Tap a button to update:",
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("✏️ Set UPI ID", callback_data="pset_upi_id")],
                    [InlineKeyboardButton("✏️ Set Name", callback_data="pset_upi_name")],
                    [InlineKeyboardButton("🖼️ Upload QR", callback_data="pset_upi_qr")],
                    [
                        InlineKeyboardButton(
                            "🗑️ Remove QR", callback_data="pset_upi_qr_del"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "🔙 Back", callback_data="owner_pay_settings"
                        )
                    ],
                ]
            ),
        )

    @app.on_callback_query(filters.regex("^pset_upi_id$") & owner_cb_filter)
    async def pset_upi_id(client, callback: CallbackQuery):
        _pay_settings_state[callback.from_user.id] = {"step": "upi_id"}
        await callback.edit_message_text(
            "✏️ **Set UPI ID**\n\nSend the UPI VPA:\nExample: `yourname@upi`\n\n/cancel to abort.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Back", callback_data="pset_upi_menu")]]
            ),
        )

    @app.on_callback_query(filters.regex("^pset_upi_name$") & owner_cb_filter)
    async def pset_upi_name(client, callback: CallbackQuery):
        _pay_settings_state[callback.from_user.id] = {"step": "upi_name"}
        await callback.edit_message_text(
            "✏️ **Set UPI Display Name**\n\nSend the name shown in UPI apps:\nExample: `TG Account Store`\n\n/cancel to abort.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Back", callback_data="pset_upi_menu")]]
            ),
        )

    @app.on_callback_query(filters.regex("^pset_upi_qr$") & owner_cb_filter)
    async def pset_upi_qr(client, callback: CallbackQuery):
        _pay_settings_state[callback.from_user.id] = {"step": "upi_qr"}
        await callback.edit_message_text(
            "🖼️ **Upload UPI QR Code**\n\nSend the QR image as a **photo**.\n\n/cancel to abort.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Back", callback_data="pset_upi_menu")]]
            ),
        )

    @app.on_callback_query(filters.regex("^pset_upi_qr_del$") & owner_cb_filter)
    async def pset_upi_qr_del(client, callback: CallbackQuery):
        await db.set_payment_settings({"upi_qr_file_id": ""})
        await callback.answer("✅ QR removed.", show_alert=True)
        await _pay_settings_menu(callback)

    # ── Crypto settings sub-menu ──────────────────────────────────────────────
    @app.on_callback_query(filters.regex("^pset_crypto_menu$") & owner_cb_filter)
    async def pset_crypto_menu(client, callback: CallbackQuery):
        cfg = await db.get_payment_settings()
        crypto_cfg = cfg.get("crypto", {})
        lines = ["🪙 **Crypto Settings**\n", "Tap a coin to set its wallet address:\n"]
        rows = []
        for key, meta in CRYPTO_COINS.items():
            addr = crypto_cfg.get(key, {}).get("address", "")
            status = "✅" if addr else "❌"
            label = f"{status} {meta['label']}"
            rows.append([InlineKeyboardButton(label, callback_data=f"pset_coin_{key}")])
        rows.append(
            [InlineKeyboardButton("🔙 Back", callback_data="owner_pay_settings")]
        )
        await callback.edit_message_text(
            "\n".join(lines), reply_markup=InlineKeyboardMarkup(rows)
        )

    @app.on_callback_query(filters.regex(r"^pset_coin_(.+)$") & owner_cb_filter)
    async def pset_coin(client, callback: CallbackQuery):
        coin_key = callback.matches[0].group(1)
        if coin_key not in CRYPTO_COINS:
            await callback.answer("Unknown coin.", show_alert=True)
            return
        meta = CRYPTO_COINS[coin_key]
        cfg = await db.get_payment_settings()
        cur_addr = cfg.get("crypto", {}).get(coin_key, {}).get("address", "")
        cur_status = f"`{cur_addr}`" if cur_addr else "❌ Not set"
        _pay_settings_state[callback.from_user.id] = {
            "step": "crypto_address",
            "coin_key": coin_key,
        }
        await callback.edit_message_text(
            f"🪙 **{meta['label']}**\n"
            f"🔗 Network: `{meta['network']}`\n\n"
            f"Current address: {cur_status}\n\n"
            f"Send the new wallet address:\n\n/cancel to abort.",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🗑️ Remove Address",
                            callback_data=f"pset_coin_del_{coin_key}",
                        )
                    ],
                    [InlineKeyboardButton("🔙 Back", callback_data="pset_crypto_menu")],
                ]
            ),
        )

    @app.on_callback_query(filters.regex(r"^pset_coin_del_(.+)$") & owner_cb_filter)
    async def pset_coin_del(client, callback: CallbackQuery):
        coin_key = callback.matches[0].group(1)
        if coin_key not in CRYPTO_COINS:
            await callback.answer("Unknown coin.", show_alert=True)
            return
        await db.set_payment_settings({f"crypto.{coin_key}.address": ""})
        await callback.answer(
            f"✅ {CRYPTO_COINS[coin_key]['label']} address removed.", show_alert=True
        )
        # Refresh crypto menu
        cfg = await db.get_payment_settings()
        crypto_cfg = cfg.get("crypto", {})
        rows = []
        for key, meta in CRYPTO_COINS.items():
            addr = crypto_cfg.get(key, {}).get("address", "")
            status = "✅" if addr else "❌"
            rows.append(
                [
                    InlineKeyboardButton(
                        f"{status} {meta['label']}", callback_data=f"pset_coin_{key}"
                    )
                ]
            )
        rows.append(
            [InlineKeyboardButton("🔙 Back", callback_data="owner_pay_settings")]
        )
        await callback.edit_message_text(
            "🪙 **Crypto Settings**\n\nTap a coin to set its wallet address:\n",
            reply_markup=InlineKeyboardMarkup(rows),
        )

    # ══════════════════════════════════════════════════════════════════════════
    # PENDING PAYMENTS
    # ══════════════════════════════════════════════════════════════════════════

    @app.on_callback_query(filters.regex("^owner_pending_deps$") & owner_cb_filter)
    async def owner_pending_deps(client, callback: CallbackQuery):
        pending = await db.get_pending_deposits()
        manual = [
            d for d in pending if d.get("method") in ("manual_upi", "manual_crypto")
        ]
        if not manual:
            await callback.edit_message_text(
                "✅ **No Pending Payments**\n\nAll deposits are processed.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 Back", callback_data="owner_back")]]
                ),
            )
            return

        upi_deps = [d for d in manual if d.get("method") == "manual_upi"]
        crypto_deps = [d for d in manual if d.get("method") == "manual_crypto"]
        lines = [f"⏳ **Pending Payments ({len(manual)})**\n"]
        if upi_deps:
            lines.append(f"💳 UPI: {len(upi_deps)}")
        if crypto_deps:
            lines.append(f"🪙 Crypto: {len(crypto_deps)}")

        rows = []
        for dep in upi_deps:
            dt = datetime.datetime.fromtimestamp(dep.get("created_at", 0)).strftime(
                "%d %b %H:%M"
            )
            rows.append(
                [
                    InlineKeyboardButton(
                        f"💳 {_dep_amount_str(dep)} | {dep['user_id']} | {dt}",
                        callback_data=f"dep_view_{dep['deposit_id']}",
                    )
                ]
            )
        for dep in crypto_deps:
            dt = datetime.datetime.fromtimestamp(dep.get("created_at", 0)).strftime(
                "%d %b %H:%M"
            )
            network = dep.get("network", dep.get("coin", ""))
            rows.append(
                [
                    InlineKeyboardButton(
                        f"🪙 {_dep_amount_str(dep)} | {network} | {dep['user_id']} | {dt}",
                        callback_data=f"dep_view_{dep['deposit_id']}",
                    )
                ]
            )
        rows.append(
            [
                InlineKeyboardButton("🔄 Refresh", callback_data="owner_pending_deps"),
                InlineKeyboardButton("🔙 Back", callback_data="owner_back"),
            ]
        )
        await callback.edit_message_text(
            "\n".join(lines), reply_markup=InlineKeyboardMarkup(rows)
        )

    @app.on_callback_query(filters.regex(r"^dep_view_(.+)$") & owner_cb_filter)
    async def dep_view(client, callback: CallbackQuery):
        dep_id = callback.matches[0].group(1)
        deposit = await db.get_deposit(dep_id)
        if not deposit:
            await callback.answer("Deposit not found.", show_alert=True)
            return
        status = deposit.get("status", "pending")
        if status != "pending":
            icon = "✅ APPROVED" if status == "approved" else "❌ REJECTED"
            await callback.edit_message_text(
                f"{_dep_detail_text(deposit)}\n\n**Status:** {icon}",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "🔙 Back", callback_data="owner_pending_deps"
                            )
                        ]
                    ]
                ),
            )
            return
        await callback.edit_message_text(
            f"📋 **Deposit Details**\n\n{_dep_detail_text(deposit)}\n\n⏳ **Status:** Pending",
            reply_markup=_dep_action_markup(dep_id),
        )

    # ── Approve ───────────────────────────────────────────────────────────────
    @app.on_callback_query(filters.regex(r"^dep_approve_(.+)$") & owner_cb_filter)
    async def dep_approve(client, callback: CallbackQuery):
        dep_id = callback.matches[0].group(1)
        deposit = await db.get_deposit(dep_id)
        if not deposit:
            await callback.answer("Deposit not found.", show_alert=True)
            return
        if deposit.get("status") != "pending":
            await callback.answer("Already processed.", show_alert=True)
            return

        uid = deposit["user_id"]
        if "crypto" in deposit.get("method", ""):
            amount_usd = deposit.get("amount_usd", 0)
            await db.add_balance(uid, amount_usd=amount_usd)
            credit_text = f"${amount_usd:.2f} USDT"
        else:
            amount_inr = deposit.get("amount_inr", 0)
            await db.add_balance(uid, amount_inr=amount_inr)
            credit_text = f"₹{amount_inr:.0f} INR"

        await db.update_deposit(dep_id, {"status": "approved"})
        try:
            await client.send_message(
                uid,
                f"✅ **Deposit Approved!**\n\n"
                f"💰 {credit_text} added to your balance.\n"
                f"🔖 Ref: `{dep_id}`\n\nThank you — TG Account Store 🏪",
            )
        except Exception:
            pass
        await callback.edit_message_reply_markup(
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            f"✅ APPROVED — {credit_text}", callback_data="noop"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "🔙 Pending List", callback_data="owner_pending_deps"
                        )
                    ],
                ]
            )
        )
        await callback.answer(f"✅ Approved! {credit_text} credited.", show_alert=True)

    # ── Reject ────────────────────────────────────────────────────────────────
    @app.on_callback_query(filters.regex(r"^dep_reject_(.+)$") & owner_cb_filter)
    async def dep_reject(client, callback: CallbackQuery):
        dep_id = callback.matches[0].group(1)
        deposit = await db.get_deposit(dep_id)
        if not deposit:
            await callback.answer("Deposit not found.", show_alert=True)
            return
        if deposit.get("status") != "pending":
            await callback.answer("Already processed.", show_alert=True)
            return

        uid = deposit["user_id"]
        await db.update_deposit(dep_id, {"status": "rejected"})
        try:
            await client.send_message(
                uid,
                f"❌ **Deposit Rejected**\n\n"
                f"Your request `{dep_id}` was not approved.\n"
                f"Contact support if you believe this is an error.",
            )
        except Exception:
            pass
        await callback.edit_message_reply_markup(
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("❌ REJECTED", callback_data="noop")],
                    [
                        InlineKeyboardButton(
                            "🔙 Pending List", callback_data="owner_pending_deps"
                        )
                    ],
                ]
            )
        )
        await callback.answer("❌ Rejected.", show_alert=True)

    @app.on_callback_query(filters.regex("^noop$"))
    async def noop(client, callback: CallbackQuery):
        await callback.answer()

    # ══════════════════════════════════════════════════════════════════════════
    # ADD STOCK
    # ══════════════════════════════════════════════════════════════════════════

    # ──────────────────────────────────────────────────────────────────────────
    # ADD STOCK — Step 1: Country picker with existing stock summary
    # ──────────────────────────────────────────────────────────────────────────
    @app.on_callback_query(filters.regex("^owner_add_stock$") & owner_cb_filter)
    async def owner_add_stock(client, callback: CallbackQuery):
        await _show_country_picker(callback)

    async def _show_country_picker(callback: CallbackQuery):
        """Show country list with existing stock counts + type breakdown."""
        countries = await db.get_all_countries()
        stock_by_c = await db.get_countries_with_stock()
        prices = await db.get_prices()

        rows = []
        for c in sorted(countries):
            flag = get_flag(c)
            count = stock_by_c.get(c, 0)
            price = prices.get(c, {"inr": 0, "usd": 0})
            label = f"{flag} {c.title()}  |  {count} in stock  |  ₹{price['inr']}"
            rows.append([InlineKeyboardButton(label, callback_data=f"oas_pick_{c}")])

        rows.append(
            [InlineKeyboardButton("➕ New Country", callback_data="oas_pick___new__")]
        )
        rows.append([InlineKeyboardButton("🔙 Back", callback_data="owner_back")])

        await callback.edit_message_text(
            "➕ **Add Stock**\n\nExisting countries shown with current stock.\nPick one or add new:",
            reply_markup=InlineKeyboardMarkup(rows),
        )

    # ──────────────────────────────────────────────────────────────────────────
    # ADD STOCK — Step 2: Country selected → show existing types + ask phone
    # ──────────────────────────────────────────────────────────────────────────
    @app.on_callback_query(filters.regex(r"^oas_pick_(.+)$") & owner_cb_filter)
    async def oas_pick(client, callback: CallbackQuery):
        country_raw = callback.matches[0].group(1)
        uid = callback.from_user.id

        if country_raw == "__new__":
            _add_stock_state[uid] = {"step": "country"}
            await callback.edit_message_text(
                "✏️ **New Country**\n\nSend the country name:\nExample: `India`\n\n/cancel to abort."
            )
            return

        flag = get_flag(country_raw)
        type_counts = await db.get_stock_count_by_type(country_raw)
        total = await db.get_stock_count(country_raw)
        price = await db.get_price(country_raw)

        # Build type breakdown string
        if type_counts:
            type_lines = "\n".join(
                f"   • {t}: `{c}`" for t, c in sorted(type_counts.items())
            )
            no_type = total - sum(type_counts.values())
            if no_type > 0:
                type_lines += f"\n   • No Type: `{no_type}`"
        else:
            type_lines = "   _(no stock yet)_"

        _add_stock_state[uid] = {"step": "phone", "country": country_raw, "flag": flag}
        await callback.edit_message_text(
            f"{flag} **{country_raw.title()}**\n\n"
            f"📦 **Current Stock:** `{total}`\n"
            f"💰 Price: ₹{price['inr']} / ${price['usd']}\n\n"
            f"🏷️ **Types in stock:**\n{type_lines}\n\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"📱 Send the phone number to add (with country code):\n"
            f"`+919876543210`\n\n/cancel to abort.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Back", callback_data="owner_add_stock")]]
            ),
        )

    # ──────────────────────────────────────────────────────────────────────────
    # ADD STOCK — Step 3: Account type picker (after 2-step)
    # Shows already existing types with counts so owner knows what's needed
    # ──────────────────────────────────────────────────────────────────────────
    async def _ask_acc_type_cb(callback: CallbackQuery, country: str):
        """Dynamic category picker sent as a new reply message."""
        await _send_category_picker(callback.message, country, callback.from_user.id)

    # ── Dynamic category picker (shared by message and callback flows) ─────────
    async def _send_category_picker(target_message, country: str, uid: int):
        """
        Always shows buttons so the owner can tap rather than type:
          • Existing categories → one button each
          • ➕ New Category  (type a new name)
          • ❌ No Category   (skip)
        """
        categories = await db.get_categories_for_country(country)
        type_counts = await db.get_stock_count_by_type(country)
        flag = get_flag(country)

        rows = []
        for cat in categories:
            cb_data = f"oas_ce_{cat}"[:64]
            rows.append([InlineKeyboardButton(f"✅ {cat}", callback_data=cb_data)])
        rows.append(
            [InlineKeyboardButton("➕ New Category", callback_data="oas_cat_new")]
        )
        rows.append(
            [InlineKeyboardButton("❌ No Category", callback_data="oas_cat_none")]
        )

        if type_counts:
            existing_str = "  |  ".join(
                f"{t}: {c}" for t, c in sorted(type_counts.items())
            )
        elif categories:
            existing_str = "none in stock yet"
        else:
            existing_str = "no categories set yet"

        await target_message.reply(
            f"{flag} **{country.title()}** — Select Category\n\n"
            f"📦 Current: `{existing_str}`\n\n"
            f"Pick a category for this account:",
            reply_markup=InlineKeyboardMarkup(rows),
        )

    # ── Category callbacks ────────────────────────────────────────────────────
    @app.on_callback_query(filters.regex(r"^oas_ce_(.+)$") & owner_cb_filter)
    async def oas_cat_existing(client, callback: CallbackQuery):
        uid = callback.from_user.id
        cat = callback.matches[0].group(1)
        await callback.answer(f"✅ {cat}")
        await callback.message.edit_text(
            f"✅ Category selected: **{cat}**\n\n⏳ Saving..."
        )
        await _finalize_add_stock(client, callback.message, uid, cat)

    @app.on_callback_query(filters.regex("^oas_cat_none$") & owner_cb_filter)
    async def oas_cat_none(client, callback: CallbackQuery):
        uid = callback.from_user.id
        await callback.answer("✅ No Category")
        await callback.message.edit_text("✅ No category selected\n\n⏳ Saving...")
        await _finalize_add_stock(client, callback.message, uid, "")

    @app.on_callback_query(filters.regex("^oas_cat_new$") & owner_cb_filter)
    async def oas_cat_new(client, callback: CallbackQuery):
        uid = callback.from_user.id
        if uid not in _add_stock_state:
            await callback.answer("Session expired. Start over.", show_alert=True)
            return
        _add_stock_state[uid]["step"] = "category_text"
        await callback.edit_message_text(
            "✏️ **New Category**\n\n"
            "Type the category name:\n"
            "Examples: `Spam Free`, `2026 Acc`, `Old Acc`\n\n"
            "Send `none` to skip.\n\n/cancel to abort.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Back", callback_data="owner_add_stock")]]
            ),
        )

    # ──────────────────────────────────────────────────────────────────────────
    # ADD STOCK — Add More (same country, skip to phone step)
    # ──────────────────────────────────────────────────────────────────────────
    @app.on_callback_query(filters.regex(r"^oas_addmore_(.+)$") & owner_cb_filter)
    async def oas_addmore(client, callback: CallbackQuery):
        country = callback.matches[0].group(1)
        uid = callback.from_user.id
        flag = get_flag(country)

        type_counts = await db.get_stock_count_by_type(country)
        total = await db.get_stock_count(country)
        price = await db.get_price(country)

        if type_counts:
            type_lines = "\n".join(
                f"   • {t}: `{c}`" for t, c in sorted(type_counts.items())
            )
            no_type = total - sum(type_counts.values())
            if no_type > 0:
                type_lines += f"\n   • No Type: `{no_type}`"
        else:
            type_lines = "   _(empty)_"

        _add_stock_state[uid] = {"step": "phone", "country": country, "flag": flag}
        await callback.edit_message_text(
            f"{flag} **{country.title()}** — Add Another\n\n"
            f"📦 Current Stock: `{total}` | ₹{price['inr']}\n\n"
            f"🏷️ Types:\n{type_lines}\n\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"📱 Send the phone number (with country code):\n"
            f"`+919876543210`\n\n/cancel to abort.",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🔙 Country List", callback_data="owner_add_stock"
                        )
                    ]
                ]
            ),
        )

    # ══════════════════════════════════════════════════════════════════════════
    # SET PRICE
    # ══════════════════════════════════════════════════════════════════════════

    @app.on_callback_query(filters.regex("^owner_set_price$") & owner_cb_filter)
    async def owner_set_price(client, callback: CallbackQuery):
        rows = await _countries_buttons("osp_pick_", "owner_back", include_new=True)
        await callback.edit_message_text(
            "💰 **Set Price**\n\nPick a country:",
            reply_markup=InlineKeyboardMarkup(rows),
        )

    @app.on_callback_query(filters.regex(r"^osp_pick_(.+)$") & owner_cb_filter)
    async def osp_pick(client, callback: CallbackQuery):
        country_raw = callback.matches[0].group(1)
        uid = callback.from_user.id
        if country_raw == "__new__":
            _set_price_state[uid] = {"step": "country"}
            await callback.edit_message_text(
                "✏️ **New Country**\n\nSend the country name:\n\n/cancel to abort.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 Back", callback_data="owner_set_price")]]
                ),
            )
        else:
            flag = get_flag(country_raw)
            cur = await db.get_price(country_raw)
            _set_price_state[uid] = {"step": "inr", "country": country_raw}
            await callback.edit_message_text(
                f"{flag} **{country_raw.title()}**\n"
                f"Current: ₹{cur['inr']} / ${cur['usd']}\n\n"
                f"Send new **INR** price:\nExample: `150`\n\n/cancel to abort.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 Back", callback_data="owner_set_price")]]
                ),
            )

    # ══════════════════════════════════════════════════════════════════════════
    # VIEW STOCK
    # ══════════════════════════════════════════════════════════════════════════

    @app.on_callback_query(filters.regex("^owner_view_stock$") & owner_cb_filter)
    async def owner_view_stock(client, callback: CallbackQuery):
        countries = await db.get_countries_with_stock()
        prices = await db.get_prices()
        total = await db.get_stock_count()
        if not countries:
            text = "📦 **Stock is Empty**"
        else:
            lines = ["📦 **Full Stock**\n"]
            for c, count in countries.items():
                flag = get_flag(c)
                price = prices.get(c, {"inr": 0, "usd": 0})
                lines.append(
                    f"{flag} **{c.title()}:** {count} | ₹{price['inr']} / ${price['usd']}"
                )
            lines.append(f"\n📦 **Total:** {total}")
            text = "\n".join(lines)
        await callback.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "➕ Add Stock", callback_data="owner_add_stock"
                        )
                    ],
                    [InlineKeyboardButton("🔙 Back", callback_data="owner_back")],
                ]
            ),
        )

    # ══════════════════════════════════════════════════════════════════════════
    # ADD BALANCE
    # ══════════════════════════════════════════════════════════════════════════

    @app.on_callback_query(filters.regex("^owner_add_balance$") & owner_cb_filter)
    async def owner_add_balance(client, callback: CallbackQuery):
        _broadcast_state[callback.from_user.id] = {"step": "balance_uid"}
        await callback.edit_message_text(
            "💳 **Add Balance**\n\nSend user's Telegram ID:\n\n/cancel to abort.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Back", callback_data="owner_back")]]
            ),
        )

    # ══════════════════════════════════════════════════════════════════════════
    # BROADCAST
    # ══════════════════════════════════════════════════════════════════════════

    @app.on_callback_query(filters.regex("^owner_broadcast$") & owner_cb_filter)
    async def owner_broadcast(client, callback: CallbackQuery):
        _broadcast_state[callback.from_user.id] = {"step": "broadcast_msg"}
        await callback.edit_message_text(
            "📢 **Broadcast**\n\nSend the message:\n\n/cancel to abort.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Back", callback_data="owner_back")]]
            ),
        )

    # ══════════════════════════════════════════════════════════════════════════
    # ALL USERS
    # ══════════════════════════════════════════════════════════════════════════

    @app.on_callback_query(filters.regex("^owner_all_users$") & owner_cb_filter)
    async def owner_all_users(client, callback: CallbackQuery):
        users = await db.get_all_users()
        if not users:
            text = "👥 **No Users Yet**"
        else:
            lines = [f"👥 **All Users ({len(users)})**\n"]
            for u in users[:20]:
                lines.append(
                    f"• `{u['user_id']}` — ₹{u.get('balance_inr', 0)} | ${u.get('balance_usd', 0)}"
                )
            if len(users) > 20:
                lines.append(f"\n... and {len(users) - 20} more")
            text = "\n".join(lines)
        await callback.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Back", callback_data="owner_back")]]
            ),
        )

    # ══════════════════════════════════════════════════════════════════════════
    # ALL ORDERS
    # ══════════════════════════════════════════════════════════════════════════

    @app.on_callback_query(filters.regex("^owner_all_orders$") & owner_cb_filter)
    async def owner_all_orders(client, callback: CallbackQuery):
        orders = await db.get_all_orders()
        if not orders:
            text = "🛒 **No Orders Yet**"
        else:
            lines = [f"🛒 **All Orders ({len(orders)})**\n"]
            for order in orders[:15]:
                dt = datetime.datetime.fromtimestamp(
                    order.get("timestamp", 0)
                ).strftime("%d %b %H:%M")
                flag = get_flag(order.get("country", ""))
                lines.append(
                    f"• {flag} {order.get('country', '').title()} | "
                    f"{order.get('type', '').upper()} | `{order.get('user_id', '')}` | {dt}"
                )
            text = "\n".join(lines)
        await callback.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Back", callback_data="owner_back")]]
            ),
        )

    # ══════════════════════════════════════════════════════════════════════════
    # ALL DEPOSITS
    # ══════════════════════════════════════════════════════════════════════════

    @app.on_callback_query(filters.regex("^owner_deposits$") & owner_cb_filter)
    async def owner_deposits(client, callback: CallbackQuery):
        deposits = await db.get_all_deposits()
        if not deposits:
            text = "💸 **No Deposits Yet**"
        else:
            pending = [d for d in deposits if d.get("status") == "pending"]
            lines = [
                f"💸 **Deposits ({len(deposits)} total | {len(pending)} pending)**\n"
            ]
            for dep in deposits[:15]:
                dt = datetime.datetime.fromtimestamp(dep.get("created_at", 0)).strftime(
                    "%d %b %H:%M"
                )
                status = {"pending": "⏳", "approved": "✅", "rejected": "❌"}.get(
                    dep.get("status", ""), "❓"
                )
                lines.append(
                    f"{status} `{dep.get('user_id', '')}` | {_dep_amount_str(dep)} | {dep.get('method', '')} | {dt}"
                )
            text = "\n".join(lines)
        await callback.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "⏳ Pending", callback_data="owner_pending_deps"
                        )
                    ],
                    [InlineKeyboardButton("🔙 Back", callback_data="owner_back")],
                ]
            ),
        )

    # ══════════════════════════════════════════════════════════════════════════
    # TEXT + PHOTO HANDLER (owner inputs)
    # ══════════════════════════════════════════════════════════════════════════

    @app.on_message(
        filters.private
        & owner_msg_filter
        & (filters.text | filters.photo)
        & ~filters.command(["start", "owner"])
    )
    async def owner_input_handler(client, message: Message):
        uid = message.from_user.id
        text = (message.text or message.caption or "").strip()

        if text.lower() == "/cancel":
            _add_stock_state.pop(uid, None)
            _set_price_state.pop(uid, None)
            _broadcast_state.pop(uid, None)
            _pay_settings_state.pop(uid, None)
            await message.reply("❌ Cancelled.")
            return

        # ── PAYMENT SETTINGS input ────────────────────────────────────────────
        ps = _pay_settings_state.get(uid)
        if ps:
            step = ps.get("step")

            if step == "upi_id":
                if not text or "@" not in text:
                    await message.reply(
                        "❌ That doesn't look like a valid UPI ID (e.g. `name@upi`)."
                    )
                    return
                await db.set_payment_settings({"upi_id": text})
                del _pay_settings_state[uid]
                await message.reply(
                    f"✅ **UPI ID updated!**\n\n`{text}`",
                    reply_markup=InlineKeyboardMarkup(
                        [
                            [
                                InlineKeyboardButton(
                                    "🔙 UPI Settings", callback_data="pset_upi_menu"
                                )
                            ]
                        ]
                    ),
                )

            elif step == "upi_name":
                if not text:
                    await message.reply("❌ Name can't be empty.")
                    return
                await db.set_payment_settings({"upi_name": text})
                del _pay_settings_state[uid]
                await message.reply(
                    f"✅ **UPI Name updated!**\n\n`{text}`",
                    reply_markup=InlineKeyboardMarkup(
                        [
                            [
                                InlineKeyboardButton(
                                    "🔙 UPI Settings", callback_data="pset_upi_menu"
                                )
                            ]
                        ]
                    ),
                )

            elif step == "upi_qr":
                if not message.photo:
                    await message.reply("❌ Send the QR as a **photo**, not a file.")
                    return
                file_id = message.photo.file_id
                await db.set_payment_settings({"upi_qr_file_id": file_id})
                del _pay_settings_state[uid]
                await message.reply(
                    "✅ **QR Code saved!**\n\nUsers will now see this QR when paying manually.",
                    reply_markup=InlineKeyboardMarkup(
                        [
                            [
                                InlineKeyboardButton(
                                    "🔙 UPI Settings", callback_data="pset_upi_menu"
                                )
                            ]
                        ]
                    ),
                )

            elif step == "crypto_address":
                coin_key = ps.get("coin_key")
                address = text
                if not address:
                    await message.reply("❌ Address can't be empty.")
                    return
                meta = CRYPTO_COINS.get(coin_key, {})
                await db.set_payment_settings(
                    {
                        f"crypto.{coin_key}.address": address,
                        f"crypto.{coin_key}.network": meta.get("network", coin_key),
                    }
                )
                del _pay_settings_state[uid]
                await message.reply(
                    f"✅ **{meta.get('label', coin_key)} address updated!**\n\n"
                    f"🔗 Network: `{meta.get('network', coin_key)}`\n"
                    f"📋 Address: `{address}`",
                    reply_markup=InlineKeyboardMarkup(
                        [
                            [
                                InlineKeyboardButton(
                                    "🔙 Crypto Settings",
                                    callback_data="pset_crypto_menu",
                                )
                            ]
                        ]
                    ),
                )
            return

        # ── ADD STOCK ─────────────────────────────────────────────────────────
        state = _add_stock_state.get(uid)
        if state:
            step = state.get("step")
            if step == "country":
                country = text.lower()
                _add_stock_state[uid].update(
                    {"country": country, "flag": get_flag(country), "step": "phone"}
                )
                await message.reply(
                    f"{get_flag(country)} **{country.title()}**\n\n📱 Send phone number:\n`+919876543210`"
                )
            elif step == "phone":
                phone = text
                _add_stock_state[uid].update({"phone": phone, "step": "connecting"})
                await message.reply(f"📱 `{phone}` — Connecting and sending OTP...")
                user_client = Client(
                    f"stock_{phone.replace('+', '')}",
                    api_id=API_ID,
                    api_hash=API_HASH,
                    workdir=SESSIONS_DIR,
                    no_updates=True,
                )
                await user_client.connect()
                try:
                    sent = await user_client.send_code(phone)
                    _add_stock_state[uid].update(
                        {
                            "phone_code_hash": sent.phone_code_hash,
                            "user_client": user_client,
                            "step": "otp",
                        }
                    )
                    await message.reply(
                        f"✅ OTP sent to `{phone}`!\n\n📨 Send OTP (numbers only):\n⚠️ Expires in 5 min."
                    )
                except Exception as e:
                    await user_client.disconnect()
                    del _add_stock_state[uid]
                    await message.reply(f"❌ Error: `{e}`")
            elif step == "otp":
                otp = text.replace(" ", "")
                if not otp.isdigit():
                    await message.reply("❌ Numbers only!")
                    return
                user_client = state["user_client"]
                phone = state["phone"]
                phone_code_hash = state["phone_code_hash"]
                try:
                    await user_client.sign_in(phone, phone_code_hash, otp)
                    _add_stock_state[uid].update({"step": "two_step", "two_step": ""})
                    await message.reply(
                        "✅ OTP verified!\n\n🔐 2-Step Verification?\n• Yes → send password\n• No → send `none`"
                    )
                except SessionPasswordNeeded:
                    _add_stock_state[uid]["step"] = "two_step_required"
                    await message.reply("🔐 2-Step required! Send the password:")
                except PhoneCodeInvalid:
                    await message.reply("❌ Wrong OTP! Try again.")
                except PhoneCodeExpired:
                    await user_client.disconnect()
                    del _add_stock_state[uid]
                    await message.reply("❌ OTP expired. Start over.")
                except Exception as e:
                    await message.reply(f"❌ Error: `{e}`")
            elif step == "two_step":
                two_step = "" if text.lower() == "none" else text
                _add_stock_state[uid]["two_step"] = two_step
                _add_stock_state[uid]["step"] = "acc_type"
                await _send_type_picker(message, state.get("country", ""), uid)
            elif step == "two_step_required":
                try:
                    await state["user_client"].check_password(text)
                    _add_stock_state[uid]["two_step"] = text
                    _add_stock_state[uid]["step"] = "acc_type"
                    await _send_type_picker(message, state.get("country", ""), uid)
                except Exception as e:
                    await message.reply(f"❌ Wrong password: `{e}`")
            elif step == "category_text":
                cat = "" if text.lower() == "none" else text.strip()
                await _finalize_add_stock(client, message, uid, cat)
            return

        # ── SET PRICE ─────────────────────────────────────────────────────────
        price_state = _set_price_state.get(uid)
        if price_state:
            step = price_state.get("step")
            if step == "country":
                country = text.lower()
                _set_price_state[uid].update({"country": country, "step": "inr"})
                await message.reply(
                    f"{get_flag(country)} **{country.title()}**\n\nSend **INR** price:"
                )
            elif step == "inr":
                try:
                    inr = float(text)
                    _set_price_state[uid].update({"inr": inr, "step": "usd"})
                    await message.reply(f"₹ INR: `{inr}` ✅\n\nSend **USD** price:")
                except ValueError:
                    await message.reply("❌ Send a valid number.")
            elif step == "usd":
                try:
                    usd = float(text)
                    country = _set_price_state[uid]["country"]
                    inr = _set_price_state[uid]["inr"]
                    await db.set_price(country, inr, usd)
                    del _set_price_state[uid]
                    await message.reply(
                        f"✅ **Price Updated!**\n\n{get_flag(country)} {country.title()}\n₹{inr} / ${usd}"
                    )
                except ValueError:
                    await message.reply("❌ Send a valid number.")
            return

        # ── ADD BALANCE / BROADCAST ───────────────────────────────────────────
        bst = _broadcast_state.get(uid, {})
        if bst.get("step") == "balance_uid":
            try:
                target = int(text)
                _broadcast_state[uid].update(
                    {"target_uid": target, "step": "balance_amount"}
                )
                await message.reply("💰 Send INR amount:")
            except ValueError:
                await message.reply("❌ Send a valid User ID.")
            return
        if bst.get("step") == "balance_amount":
            try:
                amount = float(text)
                target = _broadcast_state[uid]["target_uid"]
                await db.add_balance(target, amount_inr=amount)
                del _broadcast_state[uid]
                await message.reply(f"✅ ₹{amount} added to `{target}`")
            except ValueError:
                await message.reply("❌ Send a valid amount.")
            return
        if bst.get("step") == "broadcast_msg":
            all_users = await db.get_all_users()
            sent_c = failed_c = 0
            del _broadcast_state[uid]
            prog = await message.reply(f"📢 Broadcasting to {len(all_users)} users...")
            for u in all_users:
                try:
                    await client.send_message(int(u["user_id"]), text)
                    sent_c += 1
                    await asyncio.sleep(0.05)
                except Exception:
                    failed_c += 1
            await prog.edit_text(
                f"✅ **Broadcast Complete!**\n\n✅ Sent: {sent_c}\n❌ Failed: {failed_c}"
            )

    # ── Finalize add stock ────────────────────────────────────────────────────
    async def _send_type_picker(message, country: str, uid: int):
        """Dynamic category picker — delegates to shared helper."""
        await _send_category_picker(message, country, uid)

    async def _finalize_add_stock(client, message, uid, acc_type: str = ""):
        state = _add_stock_state.get(uid)
        if not state:
            return
        user_client = state["user_client"]
        phone = state["phone"]
        country = state["country"]
        flag = state["flag"]
        two_step = state.get("two_step", "")

        # ── Disconnect before reading session file ─────────────────────────
        try:
            await user_client.disconnect()
        except Exception:
            pass

        # ── Save session file → MongoDB + memory cache ─────────────────────
        session_name = f"stock_{phone.replace('+', '')}"
        session_path = os.path.join(SESSIONS_DIR, f"{session_name}.session")
        session_saved = False
        try:
            if os.path.exists(session_path):
                with open(session_path, "rb") as f:
                    session_bytes = f.read()
                await db.save_session(session_name, session_bytes)
                session_saved = True
        except Exception as e:
            print(f"⚠️ Failed to backup session {session_name} to MongoDB: {e}")

        # ── Add to stock DB ────────────────────────────────────────────────
        await db.add_account_to_stock(
            country, {"phone": phone, "two_step": two_step, "acc_type": acc_type}
        )
        del _add_stock_state[uid]

        price = await db.get_price(country)
        count = await db.get_stock_count(country)
        total = await db.get_stock_count()
        type_label = f"\n🏷️ Type: `{acc_type}`" if acc_type else ""
        session_status = "✅ Backed up to DB" if session_saved else "⚠️ Backup failed"

        await message.reply(
            f"✅ **Stock Added!**\n\n"
            f"{flag} {country.title()}\n"
            f"📱 `{phone}`\n"
            f"🔐 2-Step: `{two_step or 'None'}`"
            f"{type_label}\n"
            f"💾 Session: {session_status}\n\n"
            f"📦 {country.title()} stock: {count} | Total: {total}\n"
            f"💰 Prices: ₹{price['inr']} / ${price['usd']}",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "➕ Add More", callback_data=f"oas_addmore_{country}"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "💰 Set Price", callback_data="owner_set_price"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "🔙 Owner Panel", callback_data="owner_back"
                        )
                    ],
                ]
            ),
        )
