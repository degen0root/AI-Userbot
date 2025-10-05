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
GITHUB_USER="${GITHUB_USER:-yourusername}"
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
echo -e "${GREEN}Copying docker-compose file...${NC}"
scp docker-compose.prod.yml "$REMOTE_HOST:~/docker-compose.ai-userbot.yml"

# Create config in volume if not exists
echo -e "${GREEN}Preparing config volume...${NC}"
ssh "$REMOTE_HOST" << 'EOF'
# Check if config exists in volume
if ! docker run --rm -v userbot_config:/config alpine test -f /config/config.yaml; then
    echo "Creating config.yaml in volume..."
    # Create temporary config
    cat > /tmp/config.yaml << 'CONFIG'
app:
  name: "AI-UserBot"
  logging_level: "INFO"

persona:
  name: "Анна"
  age: 28
  bio: "Мама двоих детей, подруга создательницы ЛУННЫЙ ХРАМ"
  interests:
    - "йога"
    - "медитация"
    - "путешествия"
    - "материнство"
  writing_style: "теплый и дружелюбный"

policy:
  promotion_probability: 0.03
  min_gap_seconds_per_chat: 300
  typing_speed_wpm: 40
  timezone: "Europe/Moscow"

llm:
  provider: "openai"
  model: "gpt-4o-mini"
  temperature: 0.7
  max_tokens: 150
CONFIG
    
    # Copy to volume
    docker run --rm -v /tmp/config.yaml:/source/config.yaml:ro \
        -v userbot_config:/config alpine cp /source/config.yaml /config/
    rm /tmp/config.yaml
    echo "Config created in volume"
fi
EOF

# Deploy using remote docker-compose
echo -e "${GREEN}Deploying container...${NC}"
ssh "$REMOTE_HOST" << EOF
# Load environment
set -a
source ~/.ai-userbot.env
set +a

# Stop old container
docker-compose -f docker-compose.ai-userbot.yml down || true

# Pull and build
echo "Building from GitHub..."
docker-compose -f docker-compose.ai-userbot.yml build --no-cache

# Start new container
docker-compose -f docker-compose.ai-userbot.yml up -d
EOF

# Show logs
echo -e "${GREEN}Container started! Showing logs...${NC}"
ssh "$REMOTE_HOST" "docker-compose -f docker-compose.ai-userbot.yml logs -f --tail=50"
