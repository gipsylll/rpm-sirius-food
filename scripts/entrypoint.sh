#!/bin/sh
set -e

echo "⏳ Ожидание готовности PostgreSQL (${DATABASE_URL})..."
python3 -c "
import time, psycopg2, os, sys
url = os.environ.get('DATABASE_URL', '')
for i in range(30):
    try:
        conn = psycopg2.connect(url)
        conn.close()
        print('✅ База данных PostgreSQL готова!')
        sys.exit(0)
    except Exception as e:
        time.sleep(1)
print('⚠️ Не удалось подключиться к БД вовремя, продолжаем...')
"

echo "📦 Применение миграций Alembic..."
alembic upgrade head || true

echo "🌱 Наполнение базы тестовыми данными (Студент, Повар, Курьер, Меню)..."
python3 scripts/seed_demo_data.py || true

echo "🚀 Запуск сервиса: $@"
exec "$@"
