.PHONY: help build up down logs shell clean test stats

# Default target
help:
	@echo "AI UserBot - Docker Commands"
	@echo ""
	@echo "Local commands:"
	@echo "  make build    - Build Docker image"
	@echo "  make up       - Start container in background"
	@echo "  make down     - Stop container"
	@echo "  make logs     - Show container logs"
	@echo "  make shell    - Open shell in container"
	@echo "  make clean    - Clean up data and sessions"
	@echo "  make test     - Run tests in container"
	@echo "  make stats    - Show bot statistics"
	@echo ""
	@echo "Production commands (moon@103.76.86.123):"
	@echo "  make deploy-prod   - Deploy from GitHub"
	@echo "  make push-deploy   - Git push + deploy"
	@echo "  make prod          - Management console"
	@echo "  make prod-logs     - Show logs"
	@echo "  make prod-status   - Show status"
	@echo "  make prod-restart  - Restart bot"

# Build Docker image
build:
	docker-compose build

# Start services
up:
	docker-compose up -d
	@echo "✅ AI UserBot started!"
	@echo "Run 'make logs' to see output"

# Stop services
down:
	docker-compose down
	@echo "🛑 AI UserBot stopped"

# Show logs
logs:
	docker-compose logs -f ai-userbot

# Open shell in container
shell:
	docker-compose exec ai-userbot /bin/bash

# Clean up data
clean:
	@echo "⚠️  This will delete all data and sessions!"
	@read -p "Are you sure? [y/N] " confirm && [ "$$confirm" = "y" ] || exit 1
	rm -rf data/* logs/* *.session *.session-journal
	@echo "✅ Cleaned up"

# Run tests
test:
	docker-compose run --rm ai-userbot python test_bot_context.py
	docker-compose run --rm ai-userbot python test_human_behavior.py

# Show statistics
stats:
	docker-compose exec ai-userbot python manage.py --stats

# Development mode with live reload
dev:
	docker-compose run --rm -v ./src:/app/src ai-userbot python run.py

# First time setup
setup:
	@echo "🚀 Setting up AI UserBot..."
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo "✅ Created .env file - please edit it with your credentials"; \
	else \
		echo "✅ .env file already exists"; \
	fi
	@if [ ! -f configs/config.yaml ]; then \
		cp configs/config.example.yaml configs/config.yaml; \
		echo "✅ Created config.yaml - you can customize it"; \
	else \
		echo "✅ config.yaml already exists"; \
	fi
	@echo ""
	@echo "📝 Next steps:"
	@echo "1. Edit .env file with your Telegram credentials"
	@echo "2. Customize configs/config.yaml if needed"
	@echo "3. Run 'make build' to build Docker image"
	@echo "4. Run 'make up' to start the bot"

# Production deployment (from GitHub)
deploy-prod:
	@echo "🚀 Deploying to production from GitHub..."
	./deploy-prod.sh

# Production management
prod:
	@echo "🎮 Opening production management console..."
	./remote-prod.sh

# Quick production commands
prod-logs:
	ssh moon@103.76.86.123 "docker-compose -f docker-compose.ai-userbot.yml logs -f --tail=50"

prod-status:
	ssh moon@103.76.86.123 "docker-compose -f docker-compose.ai-userbot.yml ps"

prod-restart:
	ssh moon@103.76.86.123 "docker-compose -f docker-compose.ai-userbot.yml restart"

# Git push and deploy
push-deploy:
	@echo "📤 Pushing to GitHub and deploying..."
	git add -A
	git commit -m "Deploy: $$(date +%Y-%m-%d\ %H:%M:%S)" || true
	git push origin main
	./deploy-prod.sh
