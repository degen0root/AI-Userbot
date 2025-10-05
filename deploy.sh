#!/bin/bash

# Deploy script for AI UserBot on remote server

set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Configuration
REMOTE_HOST="moon@103.76.86.123"
REMOTE_DIR="/home/moon/ai-userbot"
DOCKER_CONTEXT="persona"

echo -e "${GREEN}🚀 AI UserBot Deployment Script${NC}"
echo "================================"

# Check if docker context exists
if ! docker context ls | grep -q "$DOCKER_CONTEXT"; then
    echo -e "${YELLOW}Creating Docker context...${NC}"
    docker context create "$DOCKER_CONTEXT" --docker "host=ssh://$REMOTE_HOST"
fi

# Switch to remote context
echo -e "${GREEN}Switching to remote Docker context...${NC}"
docker context use "$DOCKER_CONTEXT"

# Prepare remote directory
echo -e "${GREEN}Preparing remote directory...${NC}"
ssh "$REMOTE_HOST" "mkdir -p $REMOTE_DIR/{data,logs,configs,sessions}"

# Copy necessary files
echo -e "${GREEN}Copying files to remote server...${NC}"
rsync -avz --exclude='.git' \
    --exclude='*.session*' \
    --exclude='data/' \
    --exclude='logs/' \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    --exclude='.env' \
    --exclude='venv/' \
    --exclude='.venv/' \
    ./ "$REMOTE_HOST:$REMOTE_DIR/"

# Check if .env exists on remote
echo -e "${YELLOW}Checking .env file on remote...${NC}"
if ! ssh "$REMOTE_HOST" "test -f $REMOTE_DIR/.env"; then
    echo -e "${RED}⚠️  .env file not found on remote server!${NC}"
    echo "Please create $REMOTE_DIR/.env with your credentials"
    echo "You can use .env.example as a template"
    exit 1
fi

# Check if config exists on remote
if ! ssh "$REMOTE_HOST" "test -f $REMOTE_DIR/configs/config.yaml"; then
    echo -e "${YELLOW}Creating config.yaml from example...${NC}"
    ssh "$REMOTE_HOST" "cd $REMOTE_DIR && cp configs/config.example.yaml configs/config.yaml"
fi

# Interactive session setup
echo -e "${GREEN}Checking Telegram session on remote...${NC}"

# Stop service to avoid SendCode collisions
ssh "$REMOTE_HOST" "cd $REMOTE_DIR && docker-compose -f docker-compose.persona.yml down || true"

# Determine session name from config (fallback to sessions/userbot_session)
SESSION_NAME=$(ssh "$REMOTE_HOST" "awk -F': ' '/session_name:/ {print \\$2}' $REMOTE_DIR/configs/config.yaml 2>/dev/null | tr -d '\r\n\"' || true)
if [ -z "$SESSION_NAME" ]; then SESSION_NAME="sessions/userbot_session"; fi
SESSION_BASE=$(basename "$SESSION_NAME")
REMOTE_SESSION_FILE="$REMOTE_DIR/sessions/${SESSION_BASE}.session"

# Ensure sessions dir exists
ssh "$REMOTE_HOST" "mkdir -p $REMOTE_DIR/sessions"

if ssh "$REMOTE_HOST" "test -f $REMOTE_SESSION_FILE"; then
    echo -e "${GREEN}✓ Session exists:${NC} $REMOTE_SESSION_FILE"
else
    echo -e "${YELLOW}No session found:${NC} $REMOTE_SESSION_FILE"
    read -p "Run interactive login now (y/N)? " -n 1 -r; echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${GREEN}Starting interactive login on remote...${NC}"
        # Build image to ensure scripts/create_session.py is present in the container
        ssh -t "$REMOTE_HOST" "cd $REMOTE_DIR && docker-compose -f docker-compose.persona.yml build ai-userbot"
        # Run interactive login bypassing entrypoint so app won't start
        ssh -t "$REMOTE_HOST" "cd $REMOTE_DIR && docker-compose -f docker-compose.persona.yml run --rm --entrypoint '' -it ai-userbot sh -lc 'if [ -f /app/scripts/create_session.py ]; then python /app/scripts/create_session.py; else echo \"Script missing in image. Using inline fallback...\"; python - <<\'PY'\nimport asyncio, os, sys\nfrom getpass import getpass\nfrom pathlib import Path\nfrom pyrogram import Client\nfrom pyrogram.errors import SessionPasswordNeeded, FloodWait\n\n# Infer session name from config\nimport yaml\ncfg_path = Path(\"/app/configs/config.yaml\")\ntry:\n    data = yaml.safe_load(cfg_path.read_text(encoding=\"utf-8\")) or {}\n    session_name = ((data.get(\"telegram\") or {}).get(\"session_name\")) or \"sessions/userbot_session\"\nexcept Exception:\n    session_name = \"sessions/userbot_session\"\nPath(os.path.dirname(session_name)).mkdir(parents=True, exist_ok=True)\n\nasync def main():\n    api_id = int(os.getenv(\"TELEGRAM_API_ID\", \"0\") or 0)\n    api_hash = os.getenv(\"TELEGRAM_API_HASH\", \"\")\n    phone = os.getenv(\"TELEGRAM_PHONE_NUMBER\", \"\")\n    if not api_id or not api_hash or not phone:\n        print(\"Missing TELEGRAM_API_ID/TELEGRAM_API_HASH/TELEGRAM_PHONE_NUMBER\", file=sys.stderr)\n        return 2\n    app = Client(name=session_name, api_id=api_id, api_hash=api_hash, phone_number=phone)\n    await app.connect()\n    if await app.is_authorized():\n        print(\"Already authorized; session is valid.\")\n        await app.disconnect()\n        return 0\n    print(\"Sending login code to your Telegram...\")\n    try:\n        sent = await app.send_code(phone)\n    except FloodWait as e:\n        wait_s = getattr(e, \"x\", None) or getattr(e, \"value\", None) or 60\n        print(f\"FloodWait: wait {int(wait_s)}s...\")\n        await asyncio.sleep(int(wait_s) + 1)\n        sent = await app.send_code(phone)\n    code = input(\"Enter code: \").strip()\n    try:\n        await app.sign_in(phone_number=phone, code=code, phone_code_hash=sent.phone_code_hash)\n    except SessionPasswordNeeded:\n        pwd = os.getenv(\"TELEGRAM_2FA_PASSWORD\") or getpass(\"Enter 2FA password: \")\n        await app.check_password(password=pwd)\n    print(\"Logged in; saving session...\")\n    await app.disconnect()\n    return 0\n\nif __name__ == \"__main__\":\n    try:\n        rc = asyncio.run(main())\n    except KeyboardInterrupt:\n        rc = 130\n    sys.exit(rc)\nPY\n'"
    else
        echo -e "${YELLOW}Skipping interactive login. You can run it later manually.${NC}"
    fi
fi

# Build and deploy
echo -e "${GREEN}Building Docker image on remote...${NC}"
ssh -t "$REMOTE_HOST" "cd $REMOTE_DIR && docker-compose -f docker-compose.persona.yml build"

echo -e "${GREEN}Starting new container...${NC}"
ssh -t "$REMOTE_HOST" "cd $REMOTE_DIR && docker-compose -f docker-compose.persona.yml up -d"

# Show logs
echo -e "${GREEN}Container started! Showing logs...${NC}"
ssh -t "$REMOTE_HOST" "cd $REMOTE_DIR && docker-compose -f docker-compose.persona.yml logs -f --tail=50"

# Switch back to default context
docker context use default

echo -e "${GREEN}✅ Deployment complete!${NC}"
echo ""
echo "Useful commands:"
echo "  ssh $REMOTE_HOST"
echo "  cd $REMOTE_DIR"
echo "  docker-compose -f docker-compose.persona.yml logs -f"
echo "  docker-compose -f docker-compose.persona.yml restart"
echo "  docker-compose -f docker-compose.persona.yml down"
