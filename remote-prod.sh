#!/bin/bash

# Remote production management script

set -e

# Configuration
REMOTE_HOST="moon@103.76.86.123"
COMPOSE_FILE="docker-compose.ai-userbot.yml"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

# Function to run remote commands
remote_cmd() {
    ssh "$REMOTE_HOST" "source ~/.ai-userbot.env && $*"
}

# Main menu
show_menu() {
    echo -e "${BLUE}=== AI UserBot Production Management ===${NC}"
    echo "1) Show status"
    echo "2) View logs (live)"
    echo "3) View logs (last 100 lines)"
    echo "4) Restart bot"
    echo "5) Stop bot"
    echo "6) Start bot"
    echo "7) Update from GitHub"
    echo "8) Edit config"
    echo "9) Edit .env"
    echo "10) Show volumes"
    echo "11) Backup data"
    echo "12) Shell in container"
    echo "13) Create/refresh Telegram session (QR)"
    echo "13) Create/refresh Telegram session (interactive)"
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
            remote_cmd "docker compose -f $COMPOSE_FILE ps"
            ;;
        2)
            echo -e "${GREEN}Showing live logs (Ctrl+C to stop):${NC}"
            remote_cmd "docker compose -f $COMPOSE_FILE logs -f --tail=50"
            ;;
        3)
            echo -e "${GREEN}Last 100 lines of logs:${NC}"
            remote_cmd "docker compose -f $COMPOSE_FILE logs --tail=100"
            ;;
        4)
            echo -e "${YELLOW}Restarting bot...${NC}"
            remote_cmd "docker compose -f $COMPOSE_FILE restart"
            echo -e "${GREEN}Bot restarted!${NC}"
            ;;
        5)
            echo -e "${YELLOW}Stopping bot...${NC}"
            remote_cmd "docker compose -f $COMPOSE_FILE down"
            echo -e "${GREEN}Bot stopped!${NC}"
            ;;
        6)
            echo -e "${YELLOW}Starting bot...${NC}"
            remote_cmd "docker compose -f $COMPOSE_FILE up -d"
            echo -e "${GREEN}Bot started!${NC}"
            ;;
        7)
            echo -e "${YELLOW}Updating from GitHub...${NC}"
            echo "This will rebuild the container from latest code"
            read -p "Continue? (y/N) " -n 1 -r
            echo
            if [[ $REPLY =~ ^[Yy]$ ]]; then
                remote_cmd "docker compose -f $COMPOSE_FILE build --no-cache && docker compose -f $COMPOSE_FILE up -d"
                echo -e "${GREEN}Updated!${NC}"
            fi
            ;;
        8)
            echo -e "${GREEN}Editing config in volume...${NC}"
            # Create temporary file
            ssh "$REMOTE_HOST" "docker run --rm -v userbot_config:/config alpine cat /config/config.yaml" > /tmp/config.yaml
            ${EDITOR:-nano} /tmp/config.yaml
            # Upload back
            cat /tmp/config.yaml | ssh "$REMOTE_HOST" "docker run --rm -i -v userbot_config:/config alpine sh -c 'cat > /config/config.yaml'"
            rm /tmp/config.yaml
            echo -e "${GREEN}Config updated! Restart bot to apply.${NC}"
            ;;
        9)
            echo -e "${GREEN}Editing .env file...${NC}"
            ssh -t "$REMOTE_HOST" "nano ~/.ai-userbot.env"
            ;;
        10)
            echo -e "${GREEN}Docker volumes:${NC}"
            ssh "$REMOTE_HOST" "docker volume ls | grep userbot"
            echo ""
            echo "Volume sizes:"
            ssh "$REMOTE_HOST" "docker system df -v | grep userbot"
            ;;
        11)
            echo -e "${GREEN}Creating backup...${NC}"
            BACKUP_NAME="ai-userbot-backup-$(date +%Y%m%d-%H%M%S).tar.gz"
            ssh "$REMOTE_HOST" << EOF
docker run --rm \
    -v userbot_data:/data:ro \
    -v userbot_logs:/logs:ro \
    -v userbot_sessions:/sessions:ro \
    -v userbot_config:/config:ro \
    -v \$HOME:/backup \
    alpine tar czf /backup/$BACKUP_NAME -C / data logs sessions config
EOF
            echo -e "${GREEN}Backup created: ~/$BACKUP_NAME${NC}"
            read -p "Download backup? (y/N) " -n 1 -r
            echo
            if [[ $REPLY =~ ^[Yy]$ ]]; then
                scp "$REMOTE_HOST:~/$BACKUP_NAME" ./backups/
                echo -e "${GREEN}Downloaded to ./backups/$BACKUP_NAME${NC}"
            fi
            ;;
        12)
            echo -e "${GREEN}Connecting to container shell...${NC}"
            remote_cmd "docker compose -f $COMPOSE_FILE exec ai-userbot /bin/bash" || \
                echo -e "${RED}Could not connect. Is bot running?${NC}"
            ;;
        13)
            echo -e "${GREEN}Interactive QR login...${NC}"
            remote_cmd "docker compose -f $COMPOSE_FILE build --no-cache ai-userbot"
            ssh -t "$REMOTE_HOST" "docker compose -f $COMPOSE_FILE run --rm --entrypoint '' -it ai-userbot python /app/scripts/create_session_qr_telethon.py"
            ;;
        13)
            echo -e "${GREEN}Interactive Telegram login...${NC}"
            ssh -t "$REMOTE_HOST" "set -a; source ~/.ai-userbot.env; set +a; docker compose --env-file ~/.ai-userbot.env -f $COMPOSE_FILE run --rm --entrypoint '' -it ai-userbot python /app/scripts/create_session_qr_telethon.py"
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
