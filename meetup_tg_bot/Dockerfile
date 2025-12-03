# СОБОР ЗАВИСИМОСТЕЙ
# выбираем базовый образ
FROM python:3.10-slim AS py-deps

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# создаём рабочую директорию
WORKDIR /app

# устанавливаем системные зависимости
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# копируем файл зависимостей
#COPY ../requirements.txt ./requirements.txt
COPY requirements.txt ./requirements.txt

# устанавливаем зависимости
RUN pip install --no-cache-dir -r requirements.txt


# СБОР ФИНАЛЬНОГО ОБРАЗА STATIC
# выбираем используемый базовый образ
FROM python:3.10-slim AS static

# создаём рабочую директорию
WORKDIR /app/meetup_tg_bot

# копируем зависимости
COPY --from=py-deps /usr/local /usr/local

# копируем backend
COPY . .


# СБОР ФИНАЛЬНОГО ОБРАЗА MIGRATE
# выбираем используемый базовый образ
FROM python:3.10-slim AS migrate

# создаём рабочую директорию
WORKDIR /app/meetup_tg_bot

# копируем зависимости
COPY --from=py-deps /usr/local /usr/local

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# копируем backend
COPY ./meetup_tg_bot .

CMD ["python", "manage.py", "migrate", "--noinput"]


# СБОР ФИНАЛЬНОГО ОБРАЗА WEB_PROD
# выбираем используемый базовый образ
FROM python:3.10-slim AS web-prod

# создаём рабочую директорию
WORKDIR /app

# копируем зависимости
COPY --from=py-deps /usr/local /usr/local

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# копируем backend
COPY . .


# СБОР ФИНАЛЬНОГО ОБРАЗА WEB_DEV
# выбираем используемый базовый образ
FROM python:3.10-slim AS web-dev

# создаём рабочую директорию
WORKDIR /app

# копируем зависимости
COPY --from=py-deps /usr/local /usr/local

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
