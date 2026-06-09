"""
Webhook server — only active routes are registered based on available keys.
Gateways with no keys configured are silently skipped (never crash).
"""

import hashlib
import hmac
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

# Auto-load .env if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.responses import JSONResponse
import uvicorn

import database as db
from config import (
    CASHFREE_SECRET, CASHFREE_ENABLED,
    RAZORPAY_KEY_SECRET, RAZORPAY_ENABLED,
    OXAPAY_MERCHANT_API_KEY, OXAPAY_ENABLED,
    HELEKET_API_KEY, HELEKET_ENABLED,
    BOT_TOKEN,
)


# ── Startup ────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_db()
    print("✅ MongoDB connected for webhook server")
    yield


app = FastAPI(title="TG Store Webhooks", docs_url=None, redoc_url=None, lifespan=lifespan)


# ── Helpers ────────────────────────────────────────────────────────────────────

async def _notify_user(user_id: int, text: str):
    import aiohttp
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        async with aiohttp.ClientSession() as s:
            await s.post(url, json={
                "chat_id": user_id, "text": text, "parse_mode": "Markdown"
            }, timeout=aiohttp.ClientTimeout(total=8))
    except Exception as e:
        print(f"[notify] failed for {user_id}: {e}")


def _user_id_from_order(order_id: str):
    """Order IDs: TGS_{user_id}_{random}"""
    try:
        parts = order_id.split("_")
        if len(parts) >= 3 and parts[0] == "TGS":
            return int(parts[1])
    except Exception:
        pass
    return None


async def _credit(order_id, user_id, method, amount_inr=0, amount_usd=0) -> bool:
    """Idempotent credit: returns False if already processed, True if newly credited."""
    existing = await db.get_deposit(order_id)
    if existing and existing.get("status") == "approved":
        return False
    await db.save_deposit(order_id, {
        "deposit_id": order_id,
        "user_id":    user_id,
        "amount_inr": amount_inr,
        "amount_usd": amount_usd,
        "method":     method,
        "status":     "approved",
    })
    await db.add_balance(user_id, amount_inr=amount_inr, amount_usd=amount_usd)
    return True


# ── Health ─────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    active = []
    if CASHFREE_ENABLED: active.append("cashfree")
    if RAZORPAY_ENABLED: active.append("razorpay")
    if OXAPAY_ENABLED:   active.append("oxapay")
    if HELEKET_ENABLED:  active.append("heleket")
    return {"status": "ok", "active_gateways": active}


# ══════════════════════════════════════════════════════════════════════════════
# CASHFREE
# ══════════════════════════════════════════════════════════════════════════════

if CASHFREE_ENABLED:
    @app.post("/cashfree/webhook")
    async def cashfree_webhook(
        request: Request,
        x_webhook_signature: str = Header(None),
        x_webhook_timestamp: str = Header(None),
    ):
        raw_body = await request.body()

        if not x_webhook_signature or not x_webhook_timestamp:
            raise HTTPException(400, "Missing signature headers")

        sign_body = x_webhook_timestamp + raw_body.decode()
        expected  = hmac.new(
            CASHFREE_SECRET.encode(), sign_body.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, x_webhook_signature):
            raise HTTPException(403, "Invalid signature")

        try:
            data = json.loads(raw_body)
        except Exception:
            raise HTTPException(400, "Invalid JSON")

        order_data   = data.get("data", {}).get("order", {})
        payment_data = data.get("data", {}).get("payment", {})
        order_id     = order_data.get("order_id", "")
        order_status = order_data.get("order_status", "")
        amount       = float(payment_data.get("payment_amount", 0))

        print(f"[Cashfree] order={order_id} status={order_status} amount=₹{amount}")

        if order_status != "PAID":
            return JSONResponse({"status": "ignored"})

        user_id = _user_id_from_order(order_id)
        if not user_id:
            return JSONResponse({"status": "ignored", "reason": "unknown order format"})

        credited = await _credit(order_id, user_id, "cashfree", amount_inr=amount)
        if not credited:
            return JSONResponse({"status": "already_processed"})

        await _notify_user(user_id,
            f"✅ *Deposit Confirmed!*\n\n"
            f"💰 ₹{amount:.0f} INR added to your balance.\n"
            f"🔖 Ref: `{order_id}`\n\nThank you — *TG Account Store* 🏪"
        )
        print(f"[Cashfree] ✅ Credited ₹{amount} to user {user_id}")
        return JSONResponse({"status": "ok"})

else:
    @app.post("/cashfree/webhook")
    async def cashfree_disabled(request: Request):
        return JSONResponse({"status": "gateway_not_configured"}, status_code=503)


# ══════════════════════════════════════════════════════════════════════════════
# RAZORPAY
# ══════════════════════════════════════════════════════════════════════════════

if RAZORPAY_ENABLED:
    @app.post("/razorpay/webhook")
    async def razorpay_webhook(
        request: Request,
        x_razorpay_signature: str = Header(None),
    ):
        raw_body = await request.body()

        if not x_razorpay_signature:
            raise HTTPException(400, "Missing X-Razorpay-Signature")

        expected = hmac.new(
            RAZORPAY_KEY_SECRET.encode(), raw_body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, x_razorpay_signature):
            raise HTTPException(403, "Invalid signature")

        try:
            data = json.loads(raw_body)
        except Exception:
            raise HTTPException(400, "Invalid JSON")

        event = data.get("event", "")
        print(f"[Razorpay] event={event}")

        if event not in ("payment_link.paid", "payment.captured"):
            return JSONResponse({"status": "ignored"})

        if event == "payment_link.paid":
            entity       = data.get("payload", {}).get("payment_link", {}).get("entity", {})
            order_id     = entity.get("reference_id", "")
            amount_paise = entity.get("amount_paid", 0)
        else:
            entity       = data.get("payload", {}).get("payment", {}).get("entity", {})
            order_id     = entity.get("description", "").split("—")[-1].strip()
            amount_paise = entity.get("amount", 0)

        amount_inr = amount_paise / 100
        user_id    = _user_id_from_order(order_id)
        if not user_id:
            return JSONResponse({"status": "ignored", "reason": "unknown order format"})

        credited = await _credit(order_id, user_id, "razorpay", amount_inr=amount_inr)
        if not credited:
            return JSONResponse({"status": "already_processed"})

        await _notify_user(user_id,
            f"✅ *Deposit Confirmed!*\n\n"
            f"💰 ₹{amount_inr:.0f} INR added to your balance.\n"
            f"🔖 Ref: `{order_id}`\n\nThank you — *TG Account Store* 🏪"
        )
        print(f"[Razorpay] ✅ Credited ₹{amount_inr} to user {user_id}")
        return JSONResponse({"status": "ok"})

else:
    @app.post("/razorpay/webhook")
    async def razorpay_disabled(request: Request):
        return JSONResponse({"status": "gateway_not_configured"}, status_code=503)


# ══════════════════════════════════════════════════════════════════════════════
# OXAPAY  (correct name — not Oxypay)
# ══════════════════════════════════════════════════════════════════════════════

if OXAPAY_ENABLED:
    @app.post("/oxapay/webhook")
    async def oxapay_webhook(request: Request):
        raw_body = await request.body()
        try:
            data = json.loads(raw_body)
        except Exception:
            raise HTTPException(400, "Invalid JSON")

        received_key = data.get("merchant", "")
        if received_key and received_key != OXAPAY_MERCHANT_API_KEY:
            raise HTTPException(403, "Invalid merchant key")

        status   = data.get("status", "")
        order_id = data.get("orderId", "")
        amount   = float(data.get("payAmount", data.get("amount", 0)))

        print(f"[OxaPay] status={status} order={order_id} amount=${amount}")

        if status != "Paid":
            return JSONResponse({"status": "ignored"})

        user_id = _user_id_from_order(order_id)
        if not user_id:
            return JSONResponse({"status": "ignored", "reason": "unknown order format"})

        credited = await _credit(order_id, user_id, "oxapay", amount_usd=amount)
        if not credited:
            return JSONResponse({"status": "already_processed"})

        await _notify_user(user_id,
            f"✅ *Crypto Deposit Confirmed!*\n\n"
            f"🪙 ${amount:.2f} USDT added to your balance.\n"
            f"🔖 Ref: `{order_id}`\n\nThank you — *TG Account Store* 🏪"
        )
        print(f"[OxaPay] ✅ Credited ${amount} to user {user_id}")
        return JSONResponse({"status": "ok"})

else:
    @app.post("/oxapay/webhook")
    async def oxapay_disabled(request: Request):
        return JSONResponse({"status": "gateway_not_configured"}, status_code=503)


# ══════════════════════════════════════════════════════════════════════════════
# HELEKET
# ══════════════════════════════════════════════════════════════════════════════

if HELEKET_ENABLED:
    @app.post("/heleket/webhook")
    async def heleket_webhook(request: Request):
        """
        Heleket sends a POST with JSON body.
        Signature: md5(sorted_values:api_key) in the 'sign' header.
        """
        import hashlib as _hashlib
        raw_body = await request.body()
        try:
            data = json.loads(raw_body)
        except Exception:
            raise HTTPException(400, "Invalid JSON")

        # Verify signature
        received_sign = data.pop("sign", None)
        if received_sign:
            sorted_vals = ":".join(str(v) for _, v in sorted(data.items()))
            expected_sign = _hashlib.md5(
                f"{sorted_vals}:{HELEKET_API_KEY}".encode()
            ).hexdigest()
            if received_sign != expected_sign:
                raise HTTPException(403, "Invalid signature")

        status   = data.get("status", "")
        order_id = data.get("order_id", "")
        amount   = float(data.get("payer_amount", data.get("amount", 0)))

        print(f"[Heleket] status={status} order={order_id} amount=${amount}")

        # Heleket paid status is "paid" (lowercase)
        if status.lower() != "paid":
            return JSONResponse({"status": "ignored"})

        user_id = _user_id_from_order(order_id)
        if not user_id:
            return JSONResponse({"status": "ignored", "reason": "unknown order format"})

        credited = await _credit(order_id, user_id, "heleket", amount_usd=amount)
        if not credited:
            return JSONResponse({"status": "already_processed"})

        await _notify_user(user_id,
            f"✅ *Crypto Deposit Confirmed!*\n\n"
            f"🔗 ${amount:.2f} USDT added to your balance.\n"
            f"🔖 Ref: `{order_id}`\n\nThank you — *TG Account Store* 🏪"
        )
        print(f"[Heleket] ✅ Credited ${amount} to user {user_id}")
        return JSONResponse({"status": "ok"})

else:
    @app.post("/heleket/webhook")
    async def heleket_disabled(request: Request):
        return JSONResponse({"status": "gateway_not_configured"}, status_code=503)


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("WEBHOOK_PORT", 8001))
    active = []
    if CASHFREE_ENABLED: active.append("Cashfree ✅")
    if RAZORPAY_ENABLED: active.append("Razorpay ✅")
    if OXAPAY_ENABLED:   active.append("OxaPay ✅")
    if HELEKET_ENABLED:  active.append("Heleket ✅")
    if not active:       active.append("None — add keys to .env")

    print(f"🌐 Webhook server starting on port {port}")
    print(f"   Active gateways: {', '.join(active)}")
    print(f"   Health → GET /health")
    uvicorn.run(app, host="0.0.0.0", port=port)
