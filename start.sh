#!/bin/bash
set -e

# Auto restore .env from backup if missing
if [ ! -f .env ] && [ -f /home/ubuntu/.env.tgsell.backup ]; then
  cp /home/ubuntu/.env.tgsell.backup .env
  echo "♻️ Restored .env from backup"
fi

# Load .env
if [ -f .env ]; then
  export $(grep -v '^#' .env | xargs)
  echo "✅ .env loaded"
else
  echo "⚠️  No .env file found — using existing environment variables"
fi

# Validate required vars
if [ -z "$BOT_TOKEN" ] || [ -z "$API_ID" ] || [ -z "$API_HASH" ]; then
  echo "❌ Missing BOT_TOKEN, API_ID or API_HASH in .env — aborting."
  exit 1
fi

echo "🚀 Starting TG Account Store..."

# Only start webhook server if at least one auto-gateway key is present
WEBHOOK_NEEDED=false
[ -n "$CASHFREE_APP_ID" ]           && WEBHOOK_NEEDED=true
[ -n "$RAZORPAY_KEY_ID" ]           && WEBHOOK_NEEDED=true
[ -n "$OXAPAY_MERCHANT_API_KEY" ]   && WEBHOOK_NEEDED=true   # fixed: was OXYPAY_
[ -n "$HELEKET_MERCHANT_ID" ]       && WEBHOOK_NEEDED=true   # added

WEBHOOK_PORT=${WEBHOOK_PORT:-8001}
WEBHOOK_PID=""

if [ "$WEBHOOK_NEEDED" = true ]; then
  # Kill anything already on that port
  if lsof -i :$WEBHOOK_PORT -t &>/dev/null; then
    echo "⚠️  Port $WEBHOOK_PORT in use — killing existing process..."
    sudo fuser -k ${WEBHOOK_PORT}/tcp 2>/dev/null || true
    sleep 1
  fi
  python webhook_server.py &
  WEBHOOK_PID=$!
  echo "🌐 Webhook server started (PID $WEBHOOK_PID) on port $WEBHOOK_PORT"
else
  echo "ℹ️  No auto-gateway keys configured — webhook server skipped"
fi

# Start bot (blocking)
python main.py

# Cleanup on exit
if [ -n "$WEBHOOK_PID" ]; then
  kill $WEBHOOK_PID 2>/dev/null && echo "🛑 Webhook server stopped"
fi
