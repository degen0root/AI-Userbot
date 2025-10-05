# 🚀 Production Deployment Guide

## Quick Start

### 1. First Time Setup

```bash
# On server
ssh moon@103.76.86.123
nano ~/.ai-userbot.env

# Add your credentials:
TELEGRAM_API_ID=your_api_id
TELEGRAM_API_HASH=your_api_hash
TELEGRAM_PHONE_NUMBER=+your_phone
PROMOTED_BOT_USERNAME=womanspirit_bot
PROMOTED_BOT_NAME="ЛУННЫЙ ХРАМ"
GITHUB_USER=yourusername
GITHUB_REPO=AI-Userbot
GITHUB_BRANCH=main
```

### 2. Deploy

```bash
# From local machine
make deploy-prod
```

### 3. Manage

```bash
make prod         # Interactive menu
make prod-logs    # View logs
make prod-status  # Check status
```

## Architecture

```
GitHub Repository          Production Server
┌─────────────────┐       ┌──────────────────┐
│  Source Code    │       │ Docker Container │
│  Dockerfile     │──────>│ (built from git) │
│  Configs        │       │                  │
└─────────────────┘       │ Named Volumes:   │
                          │ - userbot_data   │
                          │ - userbot_logs   │
                          │ - userbot_config │
                          │ - userbot_sessions│
                          └──────────────────┘
```

## Key Features

- **No source code on server** - only Docker images and data
- **Persistent data** - all data stored in Docker volumes
- **Easy updates** - just push to GitHub and redeploy
- **Secure** - credentials never leave the server

## Common Tasks

### Update Bot

```bash
# Make changes locally
git add .
git commit -m "Update feature X"
git push

# Deploy
make deploy-prod
```

### Quick Deploy (git push + deploy)

```bash
make push-deploy
```

### Backup Data

```bash
make prod
# Choose option 11 (Backup data)
```

### View Config

```bash
make prod
# Choose option 8 (Edit config)
```

## Troubleshooting

### Bot not starting?
```bash
make prod-logs
# Check for errors
```

### Need to edit .env?
```bash
ssh moon@103.76.86.123
nano ~/.ai-userbot.env
```

### Container not building?
```bash
# Check GitHub settings in .env
ssh moon@103.76.86.123
cat ~/.ai-userbot.env | grep GITHUB
```

## GitHub Actions (Optional)

Add SSH key to GitHub secrets as `SSH_PRIVATE_KEY` for automatic deployment on push to main branch.
