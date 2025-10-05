# 🚀 Руководство по развертыванию AI UserBot

## Production развертывание (из GitHub)

### Концепция

- Исходный код хранится в GitHub репозитории
- На сервере хранятся только Docker контейнер и volumes с данными
- При деплое контейнер собирается прямо из GitHub
- Все данные сохраняются в named volumes для персистентности

### Преимущества

- Нет исходного кода на production сервере
- Легкий откат к предыдущим версиям
- Автоматизация через GitHub Actions
- Чистое разделение кода и данных

## Быстрый старт

### Предварительные требования

1. SSH доступ к серверу (в нашем случае `moon@103.76.86.123`)
2. Docker и docker-compose установлены на сервере
3. Настроен SSH ключ для беспарольного доступа

### Быстрый старт

```bash
# 1. Первый раз - настройка .env на сервере
ssh moon@103.76.86.123
nano ~/.ai-userbot.env  # Добавить ваши credentials

# 2. Деплой из GitHub
make deploy-prod

# 3. Управление ботом
make prod
```

### Основные команды

```bash
# Деплой
make deploy-prod      # Полный деплой из GitHub
make push-deploy      # Git push + деплой

# Управление
make prod            # Интерактивное меню
make prod-logs       # Просмотр логов
make prod-status     # Статус контейнера
make prod-restart    # Перезапуск бота
```

### Пошаговая инструкция

#### 1. Настройка GitHub репозитория

```bash
# Создайте репозиторий на GitHub
# Загрузите код:
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/yourusername/AI-Userbot.git
git push -u origin main
```

#### 2. Создание .env файла на сервере

**ВАЖНО**: Файл `.env` НЕ копируется автоматически из соображений безопасности!

```bash
# На сервере
cd ~/ai-userbot
nano .env
```

Добавьте ваши credentials:

```env
# Telegram API
TELEGRAM_API_ID=your_api_id
TELEGRAM_API_HASH=your_api_hash
TELEGRAM_PHONE_NUMBER=+your_phone

# LLM (опционально)
OPENAI_API_KEY=sk-...

# Promoted bot
PROMOTED_BOT_USERNAME=womanspirit_bot
PROMOTED_BOT_NAME="ЛУННЫЙ ХРАМ"
```

#### 3. Деплой

С локальной машины:

```bash
# Автоматический деплой
make deploy

# Или вручную
./deploy.sh
```

Скрипт выполнит:
- Создание Docker контекста
- Копирование файлов на сервер
- Сборку Docker образа
- Запуск контейнера

### Управление ботом

#### Интерактивное меню

```bash
make remote
# или
./remote-manage.sh
```

Доступные опции:
1. Статус бота
2. Просмотр логов (live)
3. Просмотр логов (последние 100 строк)
4. Перезапуск бота
5. Остановка бота
6. Запуск бота
7. Обновление конфигурации
8. Статистика
9. Очистка сессий
10. Shell доступ

#### Быстрые команды

```bash
# Просмотр логов
make remote-logs

# Статус
make remote-status

# Прямой SSH
ssh moon@103.76.86.123
cd ~/ai-userbot
docker-compose -f docker-compose.persona.yml logs -f
```

### Обновление бота

1. Внесите изменения локально
2. Запустите деплой:

```bash
make deploy
```

### Мониторинг

#### Просмотр логов

```bash
# С локальной машины
docker --context persona logs -f ai-userbot-persona

# На сервере
cd ~/ai-userbot
docker-compose -f docker-compose.persona.yml logs -f --tail=100
```

#### Проверка ресурсов

```bash
# На сервере
docker stats ai-userbot-persona
```

### Бэкапы

#### Сохранение данных

```bash
# На сервере
cd ~/ai-userbot
tar -czf backup-$(date +%Y%m%d).tar.gz data/ sessions/ configs/config.yaml

# Скачать на локальную машину
scp moon@103.76.86.123:~/ai-userbot/backup-*.tar.gz ./backups/
```

### Troubleshooting

#### Бот не запускается

1. Проверьте .env файл на сервере
2. Проверьте логи: `make remote-logs`
3. Проверьте доступную память: `ssh moon@103.76.86.123 free -h`

#### Ошибки подключения

```bash
# Проверить Docker контекст
docker context ls

# Пересоздать контекст
docker context rm persona
docker context create persona --docker "host=ssh://moon@103.76.86.123"
```

#### Session ошибки

```bash
# Очистить сессии через меню
make remote
# Выбрать опцию 9

# Или вручную
ssh moon@103.76.86.123
cd ~/ai-userbot
rm -f sessions/*.session*
```

### Безопасность

1. **Никогда** не коммитьте .env файл
2. Используйте сложные пароли для API ключей
3. Регулярно обновляйте Docker образы
4. Мониторьте использование ресурсов

### Автоматизация

#### Systemd service (опционально)

Создайте на сервере `/etc/systemd/system/ai-userbot.service`:

```ini
[Unit]
Description=AI UserBot
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/home/moon/ai-userbot
ExecStart=/usr/local/bin/docker-compose -f docker-compose.persona.yml up -d
ExecStop=/usr/local/bin/docker-compose -f docker-compose.persona.yml down
User=moon

[Install]
WantedBy=multi-user.target
```

Активация:

```bash
sudo systemctl enable ai-userbot
sudo systemctl start ai-userbot
```
