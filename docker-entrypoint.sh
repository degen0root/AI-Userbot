#!/usr/bin/env sh
set -eu

echo "[entrypoint] Starting AI-Userbot container..."

# Ensure configs directory exists
if [ ! -d "/app/configs" ]; then
  mkdir -p /app/configs
fi

# Bootstrap config.yaml if missing
if [ ! -f "/app/configs/config.yaml" ]; then
  if [ -f "/app/configs/config.example.yaml" ]; then
    echo "[entrypoint] configs/config.yaml not found, seeding from example..."
    cp /app/configs/config.example.yaml /app/configs/config.yaml
  else
    echo "[entrypoint] Warning: configs/config.example.yaml not found; creating minimal config.yaml"
    cat > /app/configs/config.yaml <<'YAML'
app:
  name: "AI-UserBot"
  logging_level: "INFO"
llm:
  provider: "stub"
  model: "gpt-4o-mini"
  temperature: 0.7
  max_tokens: 150
YAML
  fi
fi

exec python /app/run.py
