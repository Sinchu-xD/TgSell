"""
MongoDB-based database layer using Motor (async).
All operations are async — call with await.

Session files are stored in MongoDB (collection: sessions) as binary blobs.
An in-memory cache (dict) is used for fast access.
On startup, all sessions are restored from MongoDB to disk.
If cache is cleared/restarted, sessions are re-fetched from MongoDB on demand.
"""

import os
import time
from motor.motor_asyncio import AsyncIOMotorClient
from config import MONGO_URI, MONGO_DB, SESSIONS_DIR

_client: AsyncIOMotorClient = None
_db = None

# ── In-memory session cache: { session_name: bytes } ─────────────────────────
_session_cache: dict[str, bytes] = {}


async def init_db():
    """Call once at bot startup."""
    global _client, _db
    import asyncio
    loop = asyncio.get_event_loop()
    _client = AsyncIOMotorClient(MONGO_URI, io_loop=loop)
    _db = _client[MONGO_DB]

    # Indexes for fast lookups
    await _db.users.create_index("user_id", unique=True)
    await _db.stock.create_index("country")
    await _db.prices.create_index("country", unique=True)
    await _db.orders.create_index("user_id")
    await _db.orders.create_index("timestamp")
    await _db.deposits.create_index("deposit_id", unique=True)
    await _db.deposits.create_index("user_id")
    await _db.deposits.create_index("status")
    await _db.sessions.create_index("name", unique=True)
    # settings collection uses string _id keys, no extra index needed

    print(f"✅ MongoDB connected → {MONGO_DB}")

    # Restore all session files from MongoDB to disk + warm up cache
    await restore_all_sessions()
    await sync_stock_with_sessions()


def get_db():
    return _db


# ── SESSION STORAGE ───────────────────────────────────────────────────────────

async def save_session(session_name: str, session_bytes: bytes):
    """
    Save a Pyrogram .session file into MongoDB and memory cache.
    session_name: e.g. 'stock_919876543210'  (without .session extension)
    session_bytes: raw bytes of the .session file
    """
    _session_cache[session_name] = session_bytes
    await _db.sessions.update_one(
        {"name": session_name},
        {"$set": {
            "name": session_name,
            "data": session_bytes,
            "updated_at": int(time.time()),
        }},
        upsert=True,
    )


async def load_session(session_name: str) -> bytes | None:
    """
    Load session bytes. Checks memory cache first, then MongoDB.
    Returns None if not found.
    """
    # 1. Memory cache hit
    if session_name in _session_cache:
        return _session_cache[session_name]

    # 2. MongoDB fallback
    doc = await _db.sessions.find_one({"name": session_name})
    if doc:
        data = doc["data"]
        _session_cache[session_name] = data
        return data

    return None


async def delete_session(session_name: str):
    """Delete session from MongoDB and memory cache."""
    _session_cache.pop(session_name, None)
    await _db.sessions.delete_one({"name": session_name})
    # Also remove the disk file if it exists
    path = os.path.join(SESSIONS_DIR, f"{session_name}.session")
    if os.path.exists(path):
        os.remove(path)


async def restore_all_sessions():
    """
    On startup: fetch all sessions from MongoDB, write them to disk,
    and warm up the in-memory cache.
    """
    os.makedirs(SESSIONS_DIR, exist_ok=True)
    count = 0
    async for doc in _db.sessions.find({}):
        name: str = doc["name"]
        data: bytes = doc["data"]
        _session_cache[name] = data
        path = os.path.join(SESSIONS_DIR, f"{name}.session")
        with open(path, "wb") as f:
            f.write(data)
        count += 1
    if count:
        print(f"✅ Restored {count} session(s) from MongoDB to disk")
    else:
        print("ℹ️  No sessions in MongoDB to restore")


async def ensure_session_on_disk(session_name: str) -> bool:
    """
    Make sure a session file exists on disk.
    If missing from disk but present in DB/cache, restore it.
    Returns True if session is available, False if not found anywhere.
    """
    path = os.path.join(SESSIONS_DIR, f"{session_name}.session")
    if os.path.exists(path):
        return True

    data = await load_session(session_name)
    if data is None:
        return False

    os.makedirs(SESSIONS_DIR, exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return True


async def sync_stock_with_sessions():
    """
    Remove stock accounts whose session cannot be found in MongoDB or on disk.
    Called once at startup after restore_all_sessions().
    """
    async for doc in _db.stock.find({}):
        valid = []
        for acc in doc.get("accounts", []):
            phone = acc["phone"].replace("+", "")
            session_name = f"stock_{phone}"
            # Check disk (already restored) or MongoDB
            path = os.path.join(SESSIONS_DIR, f"{session_name}.session")
            if os.path.exists(path) or session_name in _session_cache:
                valid.append(acc)
            else:
                # One last check in MongoDB directly
                doc_check = await _db.sessions.find_one({"name": session_name})
                if doc_check:
                    valid.append(acc)

        await _db.stock.update_one(
            {"_id": doc["_id"]},
            {"$set": {"accounts": valid}}
        )
    print("✅ Stock synced with session files")


# ── USERS ─────────────────────────────────────────────────────────────────────

async def get_user(user_id: int) -> dict:
    doc = await _db.users.find_one({"user_id": user_id})
    if not doc:
        doc = {
            "user_id":     user_id,
            "balance_inr": 0.0,
            "balance_usd": 0.0,
            "joined_at":   int(time.time()),
        }
        await _db.users.insert_one(doc)
    doc.pop("_id", None)
    return doc


async def update_user(user_id: int, data: dict):
    await _db.users.update_one(
        {"user_id": user_id},
        {"$set": data},
        upsert=True
    )


async def add_balance(user_id: int, amount_inr: float = 0, amount_usd: float = 0):
    await _db.users.update_one(
        {"user_id": user_id},
        {
            "$inc": {"balance_inr": round(amount_inr, 2), "balance_usd": round(amount_usd, 2)},
            "$setOnInsert": {"joined_at": int(time.time())},
        },
        upsert=True
    )


async def deduct_balance(user_id: int, amount_inr: float = 0, amount_usd: float = 0):
    await add_balance(user_id, amount_inr=-amount_inr, amount_usd=-amount_usd)


async def get_all_users() -> list[dict]:
    cursor = _db.users.find({}, {"_id": 0})
    return await cursor.to_list(length=None)


# ── STOCK ─────────────────────────────────────────────────────────────────────

async def add_account_to_stock(country: str, account: dict):
    """Push one account into a country's stock array."""
    country = country.lower().strip()
    account["added_at"] = int(time.time())
    await _db.stock.update_one(
        {"country": country},
        {"$push": {"accounts": account}},
        upsert=True
    )


async def get_stock_count(country: str = None, acc_type: str = None) -> int:
    """Count stock. Optionally filter by country and/or acc_type."""
    if country:
        doc = await _db.stock.find_one({"country": country.lower().strip()})
        accounts = doc.get("accounts", []) if doc else []
        if acc_type:
            accounts = [a for a in accounts if a.get("acc_type", "") == acc_type]
        return len(accounts)
    pipeline = [{"$project": {"count": {"$size": "$accounts"}}}]
    cursor = _db.stock.aggregate(pipeline)
    total = 0
    async for doc in cursor:
        total += doc.get("count", 0)
    return total


async def get_stock_count_by_type(country: str) -> dict:
    """Returns {acc_type: count} for a given country."""
    doc = await _db.stock.find_one({"country": country.lower().strip()})
    if not doc:
        return {}
    counts = {}
    for account in doc.get("accounts", []):
        t = account.get("acc_type", "")
        if t:
            counts[t] = counts.get(t, 0) + 1
    return counts


async def get_categories_for_country(country: str) -> list:
    """Returns sorted list of unique non-empty acc_type values for a country."""
    doc = await _db.stock.find_one({"country": country.lower().strip()})
    if not doc:
        return []
    cats = set()
    for acc in doc.get("accounts", []):
        t = acc.get("acc_type", "")
        if t:
            cats.add(t)
    return sorted(cats)


async def pop_account_from_stock(country: str, acc_type: str = None) -> dict | None:
    """
    Atomically remove and return the first matching account.
    If acc_type is given (and not "any"), only accounts of that type are popped.
    """
    return await _pop_first_account(country, acc_type)


async def _pop_first_account(country: str, acc_type: str = None) -> dict | None:
    """Atomic pop using find + $pull pattern."""
    doc = await _db.stock.find_one({"country": country.lower().strip()})
    if not doc or not doc.get("accounts"):
        return None

    account = None
    for a in doc["accounts"]:
        if acc_type and acc_type != "any":
            if a.get("acc_type", "") == acc_type:
                account = a
                break
        else:
            account = a
            break

    if not account:
        return None

    result = await _db.stock.update_one(
        {"country": country.lower().strip()},
        {"$pull": {"accounts": {
            "added_at": account.get("added_at"),
            "phone":    account.get("phone")
        }}}
    )
    if result.modified_count == 0:
        return None
    return account


async def get_countries_with_stock() -> dict:
    """Returns {country: count} for countries with stock > 0."""
    pipeline = [
        {"$project": {"country": 1, "count": {"$size": "$accounts"}}},
        {"$match": {"count": {"$gt": 0}}},
        {"$sort": {"country": 1}},
    ]
    result = {}
    async for doc in _db.stock.aggregate(pipeline):
        result[doc["country"]] = doc["count"]
    return result


async def get_all_countries() -> list[str]:
    """All countries that have ever had stock or a price set."""
    stock_countries  = await _db.stock.distinct("country")
    price_countries  = await _db.prices.distinct("country")
    all_c = sorted(set(stock_countries) | set(price_countries))
    return all_c


async def add_account_back_to_stock(country: str, account: dict):
    """Push account back (used on failed purchase)."""
    await add_account_to_stock(country, account)


# ── PRICES ────────────────────────────────────────────────────────────────────

async def set_price(country: str, inr: float, usd: float):
    country = country.lower().strip()
    await _db.prices.update_one(
        {"country": country},
        {"$set": {"inr": inr, "usd": usd, "updated_at": int(time.time())}},
        upsert=True
    )


async def get_price(country: str) -> dict:
    doc = await _db.prices.find_one({"country": country.lower().strip()})
    if not doc:
        return {"inr": 0.0, "usd": 0.0}
    return {"inr": doc.get("inr", 0.0), "usd": doc.get("usd", 0.0)}


async def get_prices() -> dict:
    result = {}
    async for doc in _db.prices.find({}, {"_id": 0}):
        result[doc["country"]] = {"inr": doc.get("inr", 0), "usd": doc.get("usd", 0)}
    return result


# ── ORDERS ────────────────────────────────────────────────────────────────────

async def add_order(order: dict):
    order["timestamp"] = int(time.time())
    await _db.orders.insert_one(order)


async def get_orders(user_id: int = None) -> list[dict]:
    query = {"user_id": user_id} if user_id else {}
    cursor = _db.orders.find(query, {"_id": 0}).sort("timestamp", -1)
    return await cursor.to_list(length=None)


async def get_all_orders() -> list[dict]:
    cursor = _db.orders.find({}, {"_id": 0}).sort("timestamp", -1)
    return await cursor.to_list(length=None)


# ── DEPOSITS ──────────────────────────────────────────────────────────────────

async def save_deposit(deposit_id: str, data: dict):
    data["deposit_id"] = deposit_id
    data.setdefault("created_at", int(time.time()))
    await _db.deposits.update_one(
        {"deposit_id": deposit_id},
        {"$set": data},
        upsert=True
    )


async def get_deposit(deposit_id: str) -> dict | None:
    doc = await _db.deposits.find_one({"deposit_id": deposit_id}, {"_id": 0})
    return doc


async def update_deposit(deposit_id: str, data: dict):
    data["updated_at"] = int(time.time())
    await _db.deposits.update_one(
        {"deposit_id": deposit_id},
        {"$set": data}
    )


async def get_all_deposits() -> list[dict]:
    cursor = _db.deposits.find({}, {"_id": 0}).sort("created_at", -1)
    return await cursor.to_list(length=None)


async def get_pending_deposits() -> list[dict]:
    cursor = _db.deposits.find({"status": "pending"}, {"_id": 0}).sort("created_at", -1)
    return await cursor.to_list(length=None)


# ── PAYMENT SETTINGS (UPI + Crypto addresses — set by owner via bot) ──────────

async def get_payment_settings() -> dict:
    """
    Returns the full payment settings document.
    Structure:
      {
        "upi_id":   "name@upi",
        "upi_name": "Store Name",
        "upi_qr_file_id": "<telegram file_id>",   # photo sent by owner
        "crypto": {
          "USDT_BEP20": {"address": "0x...", "network": "BEP20 (BSC)"},
          "USDT_TRC20": {"address": "T...",  "network": "TRC20 (TRON)"},
          "TON":        {"address": "EQ...", "network": "TON"},
          "USDT_ERC20": {"address": "0x...", "network": "ERC20 (ETH)"},
        }
      }
    """
    doc = await _db.settings.find_one({"_id": "payment_settings"})
    if not doc:
        return {}
    doc.pop("_id", None)
    return doc


async def set_payment_settings(data: dict):
    """Merge-update the payment settings document."""
    await _db.settings.update_one(
        {"_id": "payment_settings"},
        {"$set": data},
        upsert=True
    )
