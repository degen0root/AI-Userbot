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
if ! ssh "$REMOTE_HOST" "test -f ~/.ai-userbot.env"; then
    echo -e "${RED}⚠️  .env file not found on remote server!${NC}"
    echo "Please create ~/.ai-userbot.env with your credentials"
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
ssh "$REMOTE_HOST" "set -a; source ~/.ai-userbot.env; set +a; cd $REMOTE_DIR && docker compose -f docker-compose.ai-userbot.yml down || true"

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
    echo -n 'Run interactive login now (y/N)? '; read -n 1 -r REPLY; echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${GREEN}Starting interactive QR login on remote...${NC}"
        # Build image to ensure scripts/create_session_qr_telethon.py is present in the container
        ssh -t "$REMOTE_HOST" "set -a; source ~/.ai-userbot.env; set +a; cd $REMOTE_DIR && docker compose -f docker-compose.ai-userbot.yml build ai-userbot"
        # Run QR login bypassing entrypoint so app won't start
        ssh -t "$REMOTE_HOST" "set -a; source ~/.ai-userbot.env; set +a; cd $REMOTE_DIR && docker compose -f docker-compose.ai-userbot.yml run --rm --entrypoint '' -it ai-userbot python /app/scripts/create_session_qr_telethon.py"
    else
        echo -e "${YELLOW}Skipping interactive login. You can run it later manually.${NC}"
    fi
fi

# Build and deploy
echo -e "${GREEN}Building Docker image on remote...${NC}"
ssh -t "$REMOTE_HOST" "set -a; source ~/.ai-userbot.env; set +a; cd $REMOTE_DIR && docker compose -f docker-compose.ai-userbot.yml build"

echo -e "${GREEN}Starting new container...${NC}"
ssh -t "$REMOTE_HOST" "set -a; source ~/.ai-userbot.env; set +a; cd $REMOTE_DIR && docker compose -f docker-compose.ai-userbot.yml up -d"

# Show logs
echo -e "${GREEN}Container started! Showing logs...${NC}"
ssh -t "$REMOTE_HOST" "set -a; source ~/.ai-userbot.env; set +a; cd $REMOTE_DIR && docker compose -f docker-compose.ai-userbot.yml logs -f --tail=50"

# Switch back to default context
docker context use default

echo -e "${GREEN}✅ Deployment complete!${NC}"
echo ""
echo 'Useful commands:'
echo "  ssh $REMOTE_HOST"
echo "  cd $REMOTE_DIR"
echo '  docker compose -f docker-compose.ai-userbot.yml logs -f'
echo '  docker compose -f docker-compose.ai-userbot.yml restart'
echo '  docker compose -f docker-compose.ai-userbot.yml down'
