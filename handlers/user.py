import datetime
from pyrogram import Client, filters
from pyrogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
)
import database as db
from config import get_flag, OWNER_IDS


def _main_reply_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("🛒 Buy Accounts"), KeyboardButton("💳 Deposit")],
            [KeyboardButton("📦 My Orders"),    KeyboardButton("👤 Profile")],
            [KeyboardButton("📊 Stock Info"),   KeyboardButton("🆘 Support")],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def _main_menu_markup():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 Buy Accounts", callback_data="buy"),
         InlineKeyboardButton("💳 Deposit",      callback_data="deposit")],
        [InlineKeyboardButton("📦 My Orders",    callback_data="my_orders"),
         InlineKeyboardButton("👤 Profile",      callback_data="profile")],
        [InlineKeyboardButton("📊 Stock Info",   callback_data="stock_info"),
         InlineKeyboardButton("🆘 Support",      callback_data="support")],
    ])


def register(app: Client):

    @app.on_message(filters.command("start") & filters.private)
    async def start(client, message: Message):
        user_id = message.from_user.id
        name    = message.from_user.first_name or "there"

        if user_id in OWNER_IDS:
            from handlers.owner import _owner_panel_markup
            total_stock = await db.get_stock_count()
            all_users   = await db.get_all_users()
            all_orders  = await db.get_all_orders()
            pending     = await db.get_pending_deposits()
            pstr        = f" ({len(pending)} ⏳)" if pending else ""
            await message.reply_text(
                f"👑 **Owner Panel**\n\n"
                f"📦 Stock: `{total_stock}` | 👥 Users: `{len(all_users)}` | 🛒 Orders: `{len(all_orders)}`\n"
                f"⏳ Pending Payments{pstr}",
                reply_markup=_owner_panel_markup()
            )
            return

        user = await db.get_user(user_id)
        await message.reply_text(
            f"👋 Welcome, **{name}**!\n\n"
            f"🏪 **TG Account Store**\n\n"
            f"Buy Telegram sessions and live accounts instantly.\n\n"
            f"💳 Balance: ₹{user.get('balance_inr', 0)} | ${user.get('balance_usd', 0)}\n\n"
            f"Choose from the menu below 👇",
            reply_markup=_main_reply_keyboard()
        )

    # ── Reply keyboard button handler ─────────────────────────────────────────
    @app.on_message(filters.private & filters.text & ~filters.command(["start", "owner", "cancel"]))
    async def reply_keyboard_handler(client, message: Message):
        uid  = message.from_user.id
        text = message.text.strip()

        btn_map = {
            "🛒 Buy Accounts": "buy",
            "💳 Deposit":      "deposit",
            "📦 My Orders":    "my_orders",
            "👤 Profile":      "profile",
            "📊 Stock Info":   "stock_info",
            "🆘 Support":      "support",
        }
        cb_data = btn_map.get(text)
        if not cb_data:
            return

        user = await db.get_user(uid)

        if cb_data == "buy":
            total = await db.get_stock_count()
            if not total:
                await message.reply("❌ No stock available right now!")
                return
            await message.reply(
                "🛒 **Buy Accounts**\n\nWhat would you like?",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📁 Telegram Session",  callback_data="buy_type_session"),
                     InlineKeyboardButton("📱 Telegram Account", callback_data="buy_type_account")],
                    [InlineKeyboardButton("🔙 Back",              callback_data="main_menu")],
                ])
            )

        elif cb_data == "deposit":
            bal_inr = user.get("balance_inr", 0)
            bal_usd = user.get("balance_usd", 0)
            await message.reply(
                f"💰 **Deposit Funds**\n\n"
                f"💳 Balance: ₹{bal_inr} | ${bal_usd}\n\n"
                f"Choose payment type:",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💳 UPI / INR", callback_data="dep_upi"),
                     InlineKeyboardButton("🪙 Crypto",    callback_data="dep_crypto")],
                    [InlineKeyboardButton("🔙 Back",      callback_data="main_menu")],
                ])
            )

        elif cb_data == "my_orders":
            orders = await db.get_orders(uid)
            if not orders:
                text_out = "🛒 **My Orders**\n\nNo orders yet. Go buy something!"
            else:
                lines = [f"🛒 **My Orders ({len(orders)})**\n"]
                for order in orders[:10]:
                    dt       = datetime.datetime.fromtimestamp(order.get("timestamp", 0)).strftime("%d %b %Y %H:%M")
                    flag     = get_flag(order.get("country", ""))
                    acc_type = order.get("acc_type", "")
                    type_str = order.get("type", "").upper()
                    lines.append(
                        f"• {flag} {order.get('country','').title()} | {type_str}"
                        + (f" | {acc_type}" if acc_type else "")
                        + f" | {dt}"
                    )
                text_out = "\n".join(lines)
            await message.reply(text_out, reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🛒 Buy More",  callback_data="buy")],
                [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")],
            ]))

        elif cb_data == "profile":
            u      = message.from_user
            orders = await db.get_orders(uid)
            joined = datetime.datetime.fromtimestamp(user.get("joined_at", 0)).strftime("%d %b %Y")
            await message.reply(
                f"👤 **Your Profile**\n\n"
                f"🆔 ID        : `{u.id}`\n"
                f"👤 Name      : {u.first_name or ''} {u.last_name or ''}\n"
                f"📛 Username  : @{u.username or 'N/A'}\n"
                f"📅 Joined    : {joined}\n\n"
                f"💰 **Balance**\n"
                f"   ₹ INR : `{user.get('balance_inr', 0)}`\n"
                f"   $ USD : `{user.get('balance_usd', 0)}`\n\n"
                f"🛒 Total Orders: `{len(orders)}`",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💳 Deposit",  callback_data="deposit"),
                     InlineKeyboardButton("🛒 Buy",      callback_data="buy")],
                    [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")],
                ])
            )

        elif cb_data == "stock_info":
            countries = await db.get_countries_with_stock()
            prices    = await db.get_prices()
            if not countries:
                text_out = "📊 **Stock Info**\n\n❌ No stock available right now.\nCheck back soon!"
            else:
                lines = ["📊 **Available Stock**\n"]
                for c, count in countries.items():
                    flag  = get_flag(c)
                    price = prices.get(c, {"inr": 0, "usd": 0})
                    lines.append(
                        f"{flag} **{c.title()}** — {count} left\n"
                        f"   💰 ₹{price['inr']} / ${price['usd']}"
                    )
                text_out = "\n".join(lines)
            await message.reply(text_out, reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🛒 Buy Now",   callback_data="buy")],
                [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")],
            ]))

        elif cb_data == "support":
            await message.reply(
                "🆘 **Support**\n\n"
                "If you have any issues, contact our support team.\n\n"
                "Please include your **User ID** and **order details**.\n\n"
                f"🆔 Your ID: `{uid}`",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")],
                ])
            )

    # ── Inline callbacks (for Back button navigation inside inline menus) ─────
    @app.on_callback_query(filters.regex("^main_menu$"))
    async def main_menu(client, callback: CallbackQuery):
        user = await db.get_user(callback.from_user.id)
        name = callback.from_user.first_name or "there"
        await callback.edit_message_text(
            f"👋 Welcome back, **{name}**!\n\n"
            f"🏪 **TG Account Store**\n\n"
            f"💳 Balance: ₹{user.get('balance_inr', 0)} | ${user.get('balance_usd', 0)}\n\n"
            f"Use the menu buttons below 👇",
            reply_markup=_main_menu_markup()
        )

    @app.on_callback_query(filters.regex("^profile$"))
    async def profile(client, callback: CallbackQuery):
        u      = callback.from_user
        user   = await db.get_user(u.id)
        orders = await db.get_orders(u.id)
        joined = datetime.datetime.fromtimestamp(user.get("joined_at", 0)).strftime("%d %b %Y")
        await callback.edit_message_text(
            f"👤 **Your Profile**\n\n"
            f"🆔 ID        : `{u.id}`\n"
            f"👤 Name      : {u.first_name or ''} {u.last_name or ''}\n"
            f"📛 Username  : @{u.username or 'N/A'}\n"
            f"📅 Joined    : {joined}\n\n"
            f"💰 **Balance**\n"
            f"   ₹ INR : `{user.get('balance_inr', 0)}`\n"
            f"   $ USD : `{user.get('balance_usd', 0)}`\n\n"
            f"🛒 Total Orders: `{len(orders)}`",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💳 Deposit", callback_data="deposit"),
                 InlineKeyboardButton("🛒 Buy",     callback_data="buy")],
                [InlineKeyboardButton("🔙 Back",    callback_data="main_menu")],
            ])
        )

    @app.on_callback_query(filters.regex("^my_orders$"))
    async def my_orders(client, callback: CallbackQuery):
        orders = await db.get_orders(callback.from_user.id)
        if not orders:
            text = "🛒 **My Orders**\n\nNo orders yet. Go buy something!"
        else:
            lines = [f"🛒 **My Orders ({len(orders)})**\n"]
            for order in orders[:10]:
                dt       = datetime.datetime.fromtimestamp(order.get("timestamp", 0)).strftime("%d %b %Y %H:%M")
                flag     = get_flag(order.get("country", ""))
                acc_type = order.get("acc_type", "")
                type_str = order.get("type", "").upper()
                lines.append(
                    f"• {flag} {order.get('country','').title()} | {type_str}"
                    + (f" | {acc_type}" if acc_type else "")
                    + f" | {dt}"
                )
            text = "\n".join(lines)
        await callback.edit_message_text(text, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🛒 Buy More", callback_data="buy")],
            [InlineKeyboardButton("🔙 Back",     callback_data="main_menu")],
        ]))

    @app.on_callback_query(filters.regex("^stock_info$"))
    async def stock_info(client, callback: CallbackQuery):
        countries = await db.get_countries_with_stock()
        prices    = await db.get_prices()
        if not countries:
            text = "📊 **Stock Info**\n\n❌ No stock available right now.\nCheck back soon!"
        else:
            lines = ["📊 **Available Stock**\n"]
            for c, count in countries.items():
                flag  = get_flag(c)
                price = prices.get(c, {"inr": 0, "usd": 0})
                lines.append(
                    f"{flag} **{c.title()}** — {count} left\n"
                    f"   💰 ₹{price['inr']} / ${price['usd']}"
                )
            text = "\n".join(lines)
        await callback.edit_message_text(text, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🛒 Buy Now", callback_data="buy")],
            [InlineKeyboardButton("🔙 Back",    callback_data="main_menu")],
        ]))

    @app.on_callback_query(filters.regex("^support$"))
    async def support(client, callback: CallbackQuery):
        await callback.edit_message_text(
            "🆘 **Support**\n\n"
            "If you have any issues, contact our support team.\n\n"
            "Please include your **User ID** and **order details**.\n\n"
            f"🆔 Your ID: `{callback.from_user.id}`",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="main_menu")],
            ])
        )
