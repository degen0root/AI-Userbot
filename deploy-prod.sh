#!/bin/bash

# Production deployment script - builds from GitHub

set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Configuration
REMOTE_HOST="moon@103.76.86.123"
DOCKER_CONTEXT="persona"
GITHUB_USER="${GITHUB_USER:-degen0root}"
GITHUB_REPO="${GITHUB_REPO:-AI-Userbot}"
GITHUB_BRANCH="${GITHUB_BRANCH:-main}"

echo -e "${GREEN}🚀 AI UserBot Production Deployment${NC}"
echo "================================"
echo "GitHub: $GITHUB_USER/$GITHUB_REPO ($GITHUB_BRANCH)"
echo "Server: $REMOTE_HOST"
echo ""

# Check Git status
echo -e "${GREEN}Checking Git status...${NC}"
if [ -n "$(git status --porcelain)" ]; then
    echo -e "${YELLOW}⚠️  You have uncommitted changes!${NC}"
    git status --short
    echo ""
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Push to GitHub
echo -e "${GREEN}Pushing to GitHub...${NC}"
git push origin $(git branch --show-current)

# Check if docker context exists
if ! docker context ls | grep -q "$DOCKER_CONTEXT"; then
    echo -e "${YELLOW}Creating Docker context...${NC}"
    docker context create "$DOCKER_CONTEXT" --docker "host=ssh://$REMOTE_HOST"
fi

# Create .env file on remote if not exists
echo -e "${GREEN}Checking remote .env file...${NC}"
ssh "$REMOTE_HOST" << 'EOF'
if [ ! -f ~/.ai-userbot.env ]; then
    echo "Creating .env template..."
    cat > ~/.ai-userbot.env << 'ENV'
# Telegram API
TELEGRAM_API_ID=your_api_id
TELEGRAM_API_HASH=your_api_hash
TELEGRAM_PHONE_NUMBER=+your_phone

# LLM (optional)
# OPENAI_API_KEY=sk-...
# ANTHROPIC_API_KEY=sk-ant-...
# GOOGLE_API_KEY=...

# Promoted bot
PROMOTED_BOT_USERNAME=womanspirit_bot
PROMOTED_BOT_NAME="ЛУННЫЙ ХРАМ"

# GitHub settings for build
GITHUB_USER=yourusername
GITHUB_REPO=AI-Userbot
GITHUB_BRANCH=main
ENV
    echo "⚠️  Created ~/.ai-userbot.env - PLEASE EDIT IT WITH YOUR CREDENTIALS!"
    exit 1
fi
EOF

if [ $? -ne 0 ]; then
    echo -e "${RED}Please edit ~/.ai-userbot.env on the server first!${NC}"
    echo "ssh $REMOTE_HOST nano ~/.ai-userbot.env"
    exit 1
fi

# Copy docker-compose.prod.yml to remote
echo -e "${GREEN}Copying docker compose file...${NC}"
scp docker-compose.prod.yml "$REMOTE_HOST:~/docker-compose.ai-userbot.yml"

########################################
# Prepare config in volume and session  #
########################################
echo -e "${GREEN}Preparing config volume...${NC}"
ssh "$REMOTE_HOST" << 'EOF'
# Check if config exists in volume
if ! docker run --rm -v userbot_config:/config alpine test -f /config/config.yaml; then
  echo "Creating config.yaml in volume from example (if available) or minimal..."
  if [ -f ~/AI-Userbot/configs/config.example.yaml ]; then
    docker run --rm \
      -v ~/AI-Userbot/configs/config.example.yaml:/source/config.yaml:ro \
      -v userbot_config:/config alpine cp /source/config.yaml /config/config.yaml
  else
    cat > /tmp/config.yaml << 'CONFIG'
app:
  name: "AI-UserBot"
  logging_level: "INFO"
telegram:
  session_name: "sessions/userbot_session"
persona:
  name: "Анна"
  age: 28
  bio: "Мама двоих детей, подруга создательницы ЛУННЫЙ ХРАМ"
policy:
  promotion_probability: 0.03
  min_gap_seconds_per_chat: 300
  typing_speed_wpm: 40
  timezone: "Europe/Moscow"
llm:
  provider: "stub"
  model: "gpt-4o-mini"
  temperature: 0.7
  max_tokens: 150
CONFIG
    docker run --rm -v /tmp/config.yaml:/source/config.yaml:ro -v userbot_config:/config alpine cp /source/config.yaml /config/config.yaml
    rm /tmp/config.yaml
  fi
  echo "Config created in volume"
fi

# Ensure session_name uses sessions/ path for persistence
if docker run --rm -v userbot_config:/config alpine sh -lc "grep -q '^\\s*session_name: \\\"userbot_session\\\"' /config/config.yaml"; then
  echo "Adjusting session_name to sessions/userbot_session for persistence..."
  docker run --rm -v userbot_config:/config alpine sh -lc "sed -i 's|session_name: \"userbot_session\"|session_name: \"sessions/userbot_session\"|' /config/config.yaml"
fi

# Show effective session_name
echo -n "Session path: "
docker run --rm -v userbot_config:/config alpine sh -lc "awk -F': ' '/session_name:/ {print \$2}' /config/config.yaml | tr -d '\"' || true"
EOF

# Interactive session setup if missing
echo -e "${GREEN}Checking for existing Telegram session...${NC}"
echo -e "${YELLOW}Ensuring service is stopped to avoid SendCode collisions...${NC}"
ssh "$REMOTE_HOST" "set -a; source ~/.ai-userbot.env; set +a; docker compose -f docker-compose.ai-userbot.yml down || true"
ssh "$REMOTE_HOST" << 'EOF'
SESSION_NAME=$(docker run --rm -v userbot_config:/config alpine sh -lc "awk -F': ' '/session_name:/ {print \$2}' /config/config.yaml | tr -d '\"' || true")
if [ -z "$SESSION_NAME" ]; then SESSION_NAME="sessions/userbot_session"; fi
SESSION_FILE="/sessions/$(basename "$SESSION_NAME").session"
if docker run --rm -v userbot_sessions:/sessions alpine test -f "$SESSION_FILE"; then
  echo "Session exists: $SESSION_FILE"
else
  echo "No session found at $SESSION_FILE"
  echo "An interactive login is needed to create the session."
fi
EOF

read -p "Run interactive login now (y/N)? " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
  echo -e "${GREEN}Starting interactive login on remote...${NC}"
  # Build image to ensure /app/scripts/create_session.py exists
  ssh -t "$REMOTE_HOST" "set -a; source ~/.ai-userbot.env; set +a; docker compose --env-file ~/.ai-userbot.env -f docker-compose.ai-userbot.yml build ai-userbot"
  # Use --entrypoint '' to bypass image entrypoint; then run the script inside
  ssh -t "$REMOTE_HOST" "set -a; source ~/.ai-userbot.env; set +a; docker compose --env-file ~/.ai-userbot.env -f docker-compose.ai-userbot.yml run --rm --entrypoint '' -it ai-userbot python /app/scripts/create_session.py"
fi

# Offer installing session from a local file (bypass FloodWait)
read -p "Or provide path to a local .session file to upload (empty to skip): " LOCAL_SESS
if [ -n "$LOCAL_SESS" ]; then
  echo -e "${GREEN}Uploading local session file and installing into volume...${NC}"
  scp "$LOCAL_SESS" "$REMOTE_HOST:/tmp/userbot_session.session"
  ssh "$REMOTE_HOST" "docker run --rm -v userbot_sessions:/sessions -v /tmp/userbot_session.session:/src/session:ro alpine cp /src/session /sessions/userbot_session.session && rm /tmp/userbot_session.session"
  echo -e "${GREEN}✓ Session installed to volume userbot_sessions${NC}"
fi

echo -e "${GREEN}Deploying container...${NC}"
ssh "$REMOTE_HOST" << 'EOF'
set -a; source ~/.ai-userbot.env; set +a
docker compose -f docker-compose.ai-userbot.yml down || true
echo "Building from GitHub..."
docker compose -f docker-compose.ai-userbot.yml build --no-cache
docker compose -f docker-compose.ai-userbot.yml up -d
EOF

# Show logs
echo -e "${GREEN}Container started! Showing logs...${NC}"
ssh "$REMOTE_HOST" "docker compose -f docker-compose.ai-userbot.yml logs -f --tail=50"
