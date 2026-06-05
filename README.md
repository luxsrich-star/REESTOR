# REESTOR

Telegram Mini App для управления аккаунтами и автоматизации рассылок.

## Быстрый старт

### 1. Установка зависимостей

```bash
# Frontend
cd frontend && npm install

# Backend
cd backend && npm install
```

### 2. Локальная разработка

```bash
# Backend (нужен PostgreSQL + Redis локально)
cd backend && npm run start:dev

# Frontend
cd frontend && npm run dev
```

### 3. Деплой на Railway

1. Зайди на https://railway.app и создай аккаунт
2. New Project → Deploy from GitHub repo
3. Добавь сервисы:
   - **reestor-backend** (папка /backend)
   - **reestor-frontend** (папка /frontend)
   - **PostgreSQL** (плагин)
   - **Redis** (плагин)
4. Заполни переменные окружения из .env.example

### 4. Переменные Railway (Backend)

| Переменная | Значение |
|---|---|
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` |
| `REDIS_URL` | `${{Redis.REDIS_URL}}` |
| `JWT_SECRET` | сгенерировать 64 символа |
| `TELEGRAM_BOT_TOKEN` | от @BotFather |
| `FRONTEND_URL` | https://твой-домен.railway.app |
| `ENCRYPTION_KEY` | сгенерировать 32 символа |

### 5. Переменные Railway (Frontend)

| Переменная | Значение |
|---|---|
| `VITE_API_URL` | https://твой-backend.railway.app/api/v1 |

## Структура проекта

```
reestor/
├── frontend/    # React + Vite + TypeScript
├── backend/     # NestJS + TypeORM
└── railway.toml
```
