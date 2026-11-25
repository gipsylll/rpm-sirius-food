#!/usr/bin/env python3
"""Send the Lab 9 test error to the configured Sentry project."""

import os
import subprocess
from pathlib import Path

import requests
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def compose(env, *args):
    return subprocess.run(
        ["docker", "compose", *args],
        cwd=ROOT,
        env=env,
        check=True,
    )


def main():
    file_values = dotenv_values(ROOT / ".env")
    dsn = os.environ.get("SENTRY_DSN") or file_values.get("SENTRY_DSN")
    if not dsn or not dsn.strip():
        print("SENTRY_DSN не найден.")
        print("Добавьте DSN проекта Sentry в корневой .env и запустите скрипт снова.")
        return 2

    env = os.environ.copy()
    env["SENTRY_DSN"] = dsn
    env["SENTRY_TEST_ENABLED"] = "1"
    print("Пересоздаю API с включённым Sentry...")
    compose(env, "up", "-d", "--force-recreate", "api")

    response = requests.get(
        "http://127.0.0.1:8000/__debug__/sentry",
        headers={"X-Correlation-ID": "sentry-demo"},
        timeout=30,
    )
    if response.status_code != 500:
        raise RuntimeError(
            f"Тестовый endpoint вернул HTTP {response.status_code}, ожидался 500"
        )
    print("PASS: тестовая ошибка отправлена из API с correlation_id=sentry-demo")
    print("Откройте Sentry и проверьте событие с тегом correlation_id=sentry-demo.")

    env["SENTRY_TEST_ENABLED"] = "0"
    compose(env, "up", "-d", "--force-recreate", "api")
    print("Тестовый endpoint отключён.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
