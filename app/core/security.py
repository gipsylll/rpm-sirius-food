"""
Модуль криптографической безопасности.

Отвечает за одностороннее хеширование паролей с использованием соли (bcrypt)
и проверку совпадения пароля с его хешем.
"""

import bcrypt


def hash_password(password: str) -> str:
    """Возвращает bcrypt-хеш переданного пароля."""
    pwd_bytes = password.encode("utf-8")[:72]
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pwd_bytes, salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Проверяет соответствие открытого пароля хешу."""
    if not plain_password or not hashed_password:
        return False
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8")[:72],
            hashed_password.encode("utf-8"),
        )
    except (ValueError, TypeError):
        return False
