#!/bin/bash

# Local monitoring script for AI UserBot

set -e

# Configuration
REMOTE_HOST="103.76.86.123"
REMOTE_USER="moon"
REMOTE_DIR="/home/moon/ai-userbot"
COMPOSE_FILE="docker-compose.ai-userbot.yml"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

# Function to run remote commands
remote_cmd() {
    ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "$REMOTE_USER@$REMOTE_HOST" "$*"
}

# Main menu
show_menu() {
    echo -e "${BLUE}=== AI UserBot Local Monitor ===${NC}"
    echo "1) Show bot status"
    echo "2) View logs (last 50 lines)"
    echo "3) View logs (live)"
    echo "4) Restart bot"
    echo "5) Stop bot"
    echo "6) Start bot"
    echo "7) Show statistics"
    echo "8) Create QR session"
    echo "9) Check resources"
    echo "0) Exit"
    echo -n "Choose option: "
}

# Main loop
while true; do
    show_menu
    read -r choice

    case $choice in
        1)
            echo -e "${GREEN}Bot status:${NC}"
            remote_cmd "cd $REMOTE_DIR && docker compose -f $COMPOSE_FILE ps"
            ;;
        2)
            echo -e "${GREEN}Last 50 lines of logs:${NC}"
            remote_cmd "cd $REMOTE_DIR && docker compose -f $COMPOSE_FILE logs --tail=50"
            ;;
        3)
            echo -e "${GREEN}Live logs (Ctrl+C to stop):${NC}"
            remote_cmd "cd $REMOTE_DIR && docker compose -f $COMPOSE_FILE logs -f --tail=20"
            ;;
        4)
            echo -e "${YELLOW}Restarting bot...${NC}"
            remote_cmd "cd $REMOTE_DIR && docker compose -f $COMPOSE_FILE restart"
            echo -e "${GREEN}Bot restarted!${NC}"
            ;;
        5)
            echo -e "${YELLOW}Stopping bot...${NC}"
            remote_cmd "cd $REMOTE_DIR && docker compose -f $COMPOSE_FILE down"
            echo -e "${GREEN}Bot stopped!${NC}"
            ;;
        6)
            echo -e "${YELLOW}Starting bot...${NC}"
            remote_cmd "cd $REMOTE_DIR && docker compose -f $COMPOSE_FILE up -d"
            echo -e "${GREEN}Bot started!${NC}"
            ;;
        7)
            echo -e "${GREEN}Bot statistics:${NC}"
            remote_cmd "cd $REMOTE_DIR && docker compose -f $COMPOSE_FILE exec ai-userbot-persona python manage.py stats" 2>/dev/null || \
                echo -e "${RED}Could not get statistics. Is bot running?${NC}"
            ;;
        8)
            echo -e "${YELLOW}Creating QR session...${NC}"
            remote_cmd "cd $REMOTE_DIR && docker compose -f $COMPOSE_FILE run --rm ai-userbot-persona python /app/scripts/create_session_qr_telethon.py"
            ;;
        9)
            echo -e "${GREEN}System resources:${NC}"
            remote_cmd "df -h /home && echo '--- Memory ---' && free -h && echo '--- Docker stats ---' && docker stats --no-stream ai-userbot-persona 2>/dev/null || echo 'Bot not running'"
            ;;
        0)
            echo -e "${GREEN}Goodbye!${NC}"
            exit 0
            ;;
        *)
            echo -e "${RED}Invalid option!${NC}"
            ;;
    esac

    echo
    echo "Press Enter to continue..."
    read -r
    clear
done
