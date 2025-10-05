FROM python:3.11-slim

# Установка системных зависимостей
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    make \
    && rm -rf /var/lib/apt/lists/*

# Установка рабочей директории
WORKDIR /app

# Копирование файла зависимостей
COPY requirements.txt .

# Установка Python зависимостей
RUN pip install --no-cache-dir -r requirements.txt

# Копирование исходного кода
COPY src/ ./src/
COPY configs/ ./configs/
COPY scripts/ ./scripts/
COPY run.py .
COPY manage.py .
COPY test_bot_context.py .
COPY test_human_behavior.py .

# Создание директорий для данных
RUN mkdir -p logs data

# Установка переменных окружения
ENV PYTHONPATH=/app
ENV TZ=Europe/Moscow

# Установка psutil для healthcheck
RUN pip install psutil

# Healthcheck
HEALTHCHECK --interval=5m --timeout=10s --start-period=30s --retries=3 \
    CMD python scripts/healthcheck.py || exit 1

# Entrypoint to ensure config exists
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

ENTRYPOINT ["/app/docker-entrypoint.sh"]
