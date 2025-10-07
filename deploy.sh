#!/bin/bash

# Unified Deployment and Management Script for AI UserBot

set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
REMOTE_HOST="moon@103.76.86.123"
REMOTE_DIR="/home/moon/ai-userbot"
DOCKER_CONTEXT="persona"

# Function to display usage
usage() {
    echo -e "${BLUE}🚀 AI UserBot Unified Deployment Tool${NC}"
    echo ""
    echo "Usage: $0 [COMMAND]"
    echo ""
    echo "Commands:"
    echo "  deploy      Deploy/update bot on remote server"
    echo "  logs        Show live logs from remote server"
    echo "  status      Show container status on remote server"
    echo "  stop        Stop bot on remote server"
    echo "  start       Start bot on remote server"
    echo "  restart     Restart bot on remote server"
    echo "  update      Update bot from GitHub (production)"
    echo "  shell       Connect to bot container shell"
    echo "  session     Create new Telegram session (interactive)"
    echo "  check       Check remote server connectivity"
    echo "  help        Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 deploy   # Deploy bot"
    echo "  $0 logs     # View live logs"
    echo "  $0 status   # Check bot status"
}

# Function to check remote connectivity
check_remote() {
    echo -e "${BLUE}🔍 Checking remote server connection...${NC}"

    # Check SSH
    echo -n "SSH connection: "
    if ssh -o ConnectTimeout=5 "$REMOTE_HOST" "echo OK" 2>/dev/null; then
        echo -e "${GREEN}✅ OK${NC}"
    else
        echo -e "${RED}❌ Failed${NC}"
        exit 1
    fi

    # Check Docker context
    echo -n "Docker context: "
    if docker context ls | grep -q "$DOCKER_CONTEXT"; then
        echo -e "${GREEN}✅ OK${NC}"
    else
        echo -e "${YELLOW}Creating Docker context...${NC}"
        docker context create "$DOCKER_CONTEXT" --docker "host=ssh://$REMOTE_HOST"
    fi

    # Check remote Docker
    echo -n "Remote Docker: "
    if docker --context "$DOCKER_CONTEXT" version >/dev/null 2>&1; then
        echo -e "${GREEN}✅ OK${NC}"
    else
        echo -e "${RED}❌ Failed${NC}"
        exit 1
    fi

    # Check bot directory
    echo -n "Bot directory: "
    if ssh "$REMOTE_HOST" "test -d /home/moon/ai-userbot" 2>/dev/null; then
        echo -e "${GREEN}✅ Exists${NC}"
    else
        echo -e "${YELLOW}⚠️  Not found (will be created on deploy)${NC}"
    fi

    # Check .env file
    echo -n ".env file: "
    if ssh "$REMOTE_HOST" "test -f ~/.ai-userbot.env" 2>/dev/null; then
        echo -e "${GREEN}✅ Exists${NC}"
    else
        echo -e "${RED}⚠️  Not found (create before deploying!)${NC}"
    fi

    echo ""
    echo -e "${GREEN}✨ All checks completed!${NC}"
}

# Function to deploy bot
deploy_bot() {
    echo -e "${GREEN}🚀 Deploying AI UserBot...${NC}"
    echo "================================"

    # Switch to remote context
    echo -e "${BLUE}Switching to remote Docker context...${NC}"
    docker context use "$DOCKER_CONTEXT"

    # Prepare remote directory using Git
    echo -e "${BLUE}Cloning/updating remote repository...${NC}"
    ssh "$REMOTE_HOST" "
        if [ -d '$REMOTE_DIR/.git' ]; then
            echo 'Repository exists, pulling latest changes...';
            cd '$REMOTE_DIR';
            git pull origin main;
        else
            echo 'Cloning new repository...';
            git clone https://${GITHUB_TOKEN}@github.com/degen0root/AI-Userbot.git '$REMOTE_DIR';
        fi
        mkdir -p $REMOTE_DIR/{data,logs,configs,sessions}
    "

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
    echo -e "${BLUE}Checking Telegram session on remote...${NC}"

    # Stop service to avoid SendCode collisions
    ssh "$REMOTE_HOST" "set -a; source ~/.ai-userbot.env; set +a; cd $REMOTE_DIR && docker compose -f docker-compose.ai-userbot.yml down || true"

    # Determine session name from config
    SESSION_NAME=$(ssh "$REMOTE_HOST" "awk -F': ' '/session_name:/ {print \$2}' $REMOTE_DIR/configs/config.yaml 2>/dev/null | tr -d '\r\n\"' || true")
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
            # Build image to ensure scripts/create_session_qr_telethon.py is present
            ssh -t "$REMOTE_HOST" "set -a; source ~/.ai-userbot.env; set +a; cd $REMOTE_DIR && docker compose -f docker-compose.ai-userbot.yml build ai-userbot"
            # Run QR login bypassing entrypoint
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

    # Switch back to default context
    docker context use default

    printf '%b\n' "${GREEN}✅ Deployment complete!${NC}"
    echo ""
    printf 'Useful commands:\n'
    printf '  ssh %s\n' "$REMOTE_HOST"
    printf '  cd %s\n' "${REMOTE_DIR}"
    printf '  docker compose -f docker-compose.ai-userbot.yml logs -f\n'
    printf '  docker compose -f docker-compose.ai-userbot.yml restart\n'
    printf '  docker compose -f docker-compose.ai-userbot.yml down\n'
}

# Function to show logs
show_logs() {
    echo -e "${GREEN}📋 Showing live logs (Ctrl+C to stop):${NC}"
    ssh -t "$REMOTE_HOST" "set -a; source ~/.ai-userbot.env; set +a; cd $REMOTE_DIR && docker compose -f docker-compose.ai-userbot.yml logs -f --tail=2000"
}

# Function to show status
show_status() {
    echo -e "${GREEN}📊 Bot status:${NC}"
    ssh "$REMOTE_HOST" "set -a; source ~/.ai-userbot.env; set +a; cd $REMOTE_DIR && docker compose -f docker-compose.ai-userbot.yml ps"
}

# Function to stop bot
stop_bot() {
    echo -e "${YELLOW}🛑 Stopping bot...${NC}"
    ssh "$REMOTE_HOST" "set -a; source ~/.ai-userbot.env; set +a; cd $REMOTE_DIR && docker compose -f docker-compose.ai-userbot.yml down"
    echo -e "${GREEN}Bot stopped!${NC}"
}

# Function to start bot
start_bot() {
    echo -e "${YELLOW}🚀 Starting bot...${NC}"
    ssh "$REMOTE_HOST" "set -a; source ~/.ai-userbot.env; set +a; cd $REMOTE_DIR && docker compose -f docker-compose.ai-userbot.yml up -d"
    echo -e "${GREEN}Bot started!${NC}"
}

# Function to restart bot
restart_bot() {
    echo -e "${YELLOW}🔄 Restarting bot...${NC}"
    ssh "$REMOTE_HOST" "set -a; source ~/.ai-userbot.env; set +a; cd $REMOTE_DIR && docker compose -f docker-compose.ai-userbot.yml restart"
    echo -e "${GREEN}Bot restarted!${NC}"
}

# Function to update from GitHub
update_bot() {
    echo -e "${YELLOW}⬆️  Updating from GitHub...${NC}"
    echo "This will pull the latest code, stop the bot, rebuild the container, and restart it."
    
    # Run Docker Compose update
    ssh "$REMOTE_HOST" "cd $REMOTE_DIR && \\
        git pull && \\
        docker compose pull && \\
        docker compose up -d --build --force-recreate"
    
    if [ $? -eq 0 ]; then
        echo "✅ Bot updated successfully on remote server"
    fi
}

# Function to connect to shell
connect_shell() {
    echo -e "${GREEN}🐚 Connecting to container shell...${NC}"
    ssh -t "$REMOTE_HOST" "set -a; source ~/.ai-userbot.env; set +a; cd $REMOTE_DIR && docker compose -f docker-compose.ai-userbot.yml run --rm -it --entrypoint /bin/bash ai-userbot" || \
        echo -e "${RED}Could not connect. Is bot running?${NC}"
}

# Function to create session
create_session() {
    echo -e "${YELLOW}🔐 Creating new Telegram session...${NC}"
    ssh -t "$REMOTE_HOST" "set -a; source ~/.ai-userbot.env; set +a; cd $REMOTE_DIR && docker compose -f docker-compose.ai-userbot.yml run --rm --entrypoint '' -it ai-userbot python /app/scripts/create_session_qr_telethon.py"
}

# Main command handling
case "${1:-help}" in
    deploy)
        check_remote
        deploy_bot
        ;;
    logs)
        show_logs
        ;;
    status)
        show_status
        ;;
    stop)
        stop_bot
        ;;
    start)
        start_bot
        ;;
    restart)
        restart_bot
        ;;
    update)
        update_bot
        ;;
    shell)
        connect_shell
        ;;
    session)
        create_session
        ;;
    check)
        check_remote
        ;;
    help|*)
        usage
        ;;
esac
