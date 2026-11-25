#!/bin/bash
set -e

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

TARGET=${1:-all}

# Определение команды uv
if command -v uv >/dev/null 2>&1; then
    UV_CMD="uv"
elif [ -f "/opt/homebrew/bin/uv" ]; then
    UV_CMD="/opt/homebrew/bin/uv"
else
    UV_CMD="python3 -m"
fi

echo -e "${BLUE}========================================================================${NC}"
echo -e "${BLUE}     СИРИУС.ЕДА: ПОЛНАЯ ПРОВЕРКА И ДЕМОНСТРАЦИЯ ЛАБОРАТОРНЫХ РАБОТ     ${NC}"
echo -e "${BLUE}     Режим запуска: ${CYAN}${TARGET}${NC} (доступны: 3, 4, 5, 6, all)             ${NC}"
echo -e "${BLUE}========================================================================${NC}"

# 1. Запуск автоматических тестов
echo -e "\n${YELLOW}Шаг 1: Запуск автоматических тестов (47 тестов Clean Architecture)...${NC}"
$UV_CMD run pytest -v

# Функция проверки и запуска Uvicorn при необходимости
ensure_server_running() {
    if ! curl -s http://127.0.0.1:8000/docs > /dev/null; then
        echo -e "Сервер API на http://127.0.0.1:8000 не запущен. Запускаем в фоне..."
        $UV_CMD run uvicorn app.main:app --port 8000 &
        SERVER_PID=$!
        sleep 3
        TRAP_KILL=true
    else
        echo -e "${GREEN}Сервер API уже работает на http://127.0.0.1:8000!${NC}"
        TRAP_KILL=false
    fi
}

# Функция наполнения БД тестовыми данными
ensure_seed_data() {
    echo -e "\n${YELLOW}Проверка и наполнение базы данных демо-данными...${NC}"
    $UV_CMD run python3 scripts/seed_demo_data.py || true
}

TRAP_KILL=false

case "$TARGET" in
    3)
        ensure_server_running
        ensure_seed_data
        echo -e "\n${YELLOW}>>> Запуск демонстрации Лабораторной работы № 3 (Безопасность)...${NC}"
        $UV_CMD run python3 scripts/demo_lab3_security.py
        ;;
    4)
        ensure_server_running
        ensure_seed_data
        echo -e "\n${YELLOW}>>> Запуск демонстрации Лабораторной работы № 4 (Кеширование Redis)...${NC}"
        $UV_CMD run python3 scripts/demo_lab4_caching.py
        ;;
    5)
        echo -e "\n${YELLOW}>>> Запуск демонстрации Лабораторной работы № 5 (Celery)...${NC}"
        $UV_CMD run python3 scripts/demo_lab5_celery.py
        ;;
    check)
        echo -e "\n${YELLOW}>>> Комплексная проверка всех ручек API и сервисов...${NC}"
        $UV_CMD run python3 scripts/verify_all_endpoints.py
        ;;
    6)
        echo -e "\n${YELLOW}>>> Запуск демонстрации Практической работы № 6 (gRPC)...${NC}"
        $UV_CMD run python3 scripts/demo_lab6_grpc.py
        ;;
    all|*)
        ensure_server_running
        ensure_seed_data
        echo -e "\n${YELLOW}>>> Запуск демонстрации Лабораторной работы № 3 (Безопасность)...${NC}"
        $UV_CMD run python3 scripts/demo_lab3_security.py

        echo -e "\n${YELLOW}>>> Запуск демонстрации Лабораторной работы № 4 (Кеширование Redis)...${NC}"
        $UV_CMD run python3 scripts/demo_lab4_caching.py

        echo -e "\n${YELLOW}>>> Запуск демонстрации Лабораторной работы № 5 (Celery)...${NC}"
        $UV_CMD run python3 scripts/demo_lab5_celery.py

        echo -e "\n${YELLOW}>>> Запуск демонстрации Практической работы № 6 (gRPC)...${NC}"
        $UV_CMD run python3 scripts/demo_lab6_grpc.py
        ;;
esac

if [ "$TRAP_KILL" = true ]; then
    kill $SERVER_PID 2>/dev/null || true
fi

echo -e "\n${GREEN}========================================================================${NC}"
echo -e "${GREEN}               ВСЕ ПРОВЕРКИ И ДЕМОНСТРАЦИИ УСПЕШНЫ!                    ${NC}"
echo -e "${GREEN}========================================================================${NC}"
