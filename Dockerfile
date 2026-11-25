FROM python:3.11-slim

# Системные зависимости для компиляции и работы с PostgreSQL
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Копируем быстрый установщик пакетов uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Копируем манифест зависимостей
COPY pyproject.toml uv.lock ./

# Устанавливаем все зависимости проекта
RUN uv sync --frozen --no-cache --no-dev

# Копируем исходный код
COPY . .

# Добавляем .venv в переменные окружения
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app"

EXPOSE 8000 50051 5555

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
