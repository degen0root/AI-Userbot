#!/bin/bash

# Quick check script for remote server

REMOTE_HOST="moon@103.76.86.123"
DOCKER_CONTEXT="persona"

echo "🔍 Checking remote server connection..."

# Check SSH
echo -n "SSH connection: "
if ssh -o ConnectTimeout=5 "$REMOTE_HOST" "echo OK" 2>/dev/null; then
    echo "✅ OK"
else
    echo "❌ Failed"
    exit 1
fi

# Check Docker context
echo -n "Docker context: "
if docker context ls | grep -q "$DOCKER_CONTEXT"; then
    echo "✅ OK"
else
    echo "❌ Not found"
    exit 1
fi

# Check Docker on remote
echo -n "Remote Docker: "
if docker --context "$DOCKER_CONTEXT" version >/dev/null 2>&1; then
    echo "✅ OK"
else
    echo "❌ Failed"
    exit 1
fi

# Check if bot directory exists
echo -n "Bot directory: "
if ssh "$REMOTE_HOST" "test -d /home/moon/ai-userbot" 2>/dev/null; then
    echo "✅ Exists"
else
    echo "⚠️  Not found (will be created on deploy)"
fi

# Check if .env exists
echo -n ".env file: "
if ssh "$REMOTE_HOST" "test -f /home/moon/ai-userbot/.env" 2>/dev/null; then
    echo "✅ Exists"
else
    echo "⚠️  Not found (create before deploying!)"
fi

echo ""
echo "✨ All checks completed!"
