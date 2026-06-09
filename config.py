import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN    = os.environ.get("BOT_TOKEN", "")
BOT_USERNAME = os.environ.get("BOT_USERNAME", "")   # e.g. MyStoreBot  (no @)
API_ID       = int(os.environ.get("API_ID", "0"))
API_HASH     = os.environ.get("API_HASH", "")
OWNER_IDS    = [int(x.strip()) for x in os.environ.get("OWNER_IDS", "").split(",") if x.strip()]

SESSIONS_DIR = "sessions"
DATA_DIR     = "data"

# ── MongoDB ───────────────────────────────────────────────────────────────────
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB  = os.environ.get("MONGO_DB", "tgstore")

# ── Cashfree ──────────────────────────────────────────────────────────────────
CASHFREE_APP_ID  = os.environ.get("CASHFREE_APP_ID", "")
CASHFREE_SECRET  = os.environ.get("CASHFREE_SECRET", "")
CASHFREE_ENV     = os.environ.get("CASHFREE_ENV", "production")   # sandbox | production
CASHFREE_ENABLED = bool(CASHFREE_APP_ID and CASHFREE_SECRET)

# ── Razorpay ──────────────────────────────────────────────────────────────────
RAZORPAY_KEY_ID     = os.environ.get("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "")
RAZORPAY_ENABLED    = bool(RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET)

# ── OxaPay ───────────────────────────────────────────────────────────────────
OXAPAY_MERCHANT_API_KEY = os.environ.get("OXAPAY_MERCHANT_API_KEY", "")
OXAPAY_ENABLED          = bool(OXAPAY_MERCHANT_API_KEY)

# ── Heleket ───────────────────────────────────────────────────────────────────
HELEKET_MERCHANT_ID  = os.environ.get("HELEKET_MERCHANT_ID", "")
HELEKET_API_KEY      = os.environ.get("HELEKET_API_KEY", "")
HELEKET_CALLBACK_URL = os.environ.get("HELEKET_CALLBACK_URL", "")
HELEKET_ENABLED      = bool(HELEKET_MERCHANT_ID and HELEKET_API_KEY)

# ── Deposit limits ────────────────────────────────────────────────────────────
MIN_INR = 10
MIN_USD = 1

# ── Country flags ─────────────────────────────────────────────────────────────
COUNTRY_FLAGS = {
    "india": "🇮🇳", "pakistan": "🇵🇰", "usa": "🇺🇸", "uk": "🇬🇧",
    "russia": "🇷🇺", "bangladesh": "🇧🇩", "nepal": "🇳🇵", "indonesia": "🇮🇩",
    "malaysia": "🇲🇾", "philippines": "🇵🇭", "vietnam": "🇻🇳", "thailand": "🇹🇭",
    "turkey": "🇹🇷", "brazil": "🇧🇷", "germany": "🇩🇪", "france": "🇫🇷",
    "canada": "🇨🇦", "australia": "🇦🇺", "china": "🇨🇳", "japan": "🇯🇵",
    "kenya": "🇰🇪", "nigeria": "🇳🇬", "ghana": "🇬🇭", "egypt": "🇪🇬",
    "uae": "🇦🇪", "saudi arabia": "🇸🇦", "iran": "🇮🇷", "iraq": "🇮🇶",
    "ukraine": "🇺🇦", "poland": "🇵🇱", "spain": "🇪🇸", "italy": "🇮🇹",
    "mexico": "🇲🇽", "argentina": "🇦🇷",
}

def get_flag(country: str) -> str:
    return COUNTRY_FLAGS.get(country.lower().strip(), "🌍")

def bot_link() -> str:
    """Returns https://t.me/<BOT_USERNAME> or a safe fallback."""
    if BOT_USERNAME:
        return f"https://t.me/{BOT_USERNAME}"
    return "https://t.me"
