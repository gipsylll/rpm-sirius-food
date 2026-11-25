"""
Скрипт первичного наполнения демонстрационными данными (Seed Data).

Создаёт в реальной базе данных PostgreSQL:
- Базовые роли: student, cook, courier, admin
- Тестовых пользователей каждого типа с известными паролями
- Первичное меню столовой по категориям (супы, горячее, напитки, салаты)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.security import hash_password
from app.database import SessionLocal
from app.models import MenuItem, Role, User


def seed_data():
    print("Наполнение базы данных демонстрационными данными...")
    with SessionLocal() as db:
        # 1. Роли
        roles = {}
        for role_name in ["student", "cook", "courier", "admin"]:
            r = db.query(Role).filter(Role.name == role_name).first()
            if not r:
                r = Role(name=role_name)
                db.add(r)
                db.flush()
            roles[role_name] = r

        # 2. Пользователи
        demo_users = [
            ("student@sirius.ru", "student123", "student", 5000.0, "+79991110001"),
            (
                "other_student@sirius.ru",
                "student123",
                "student",
                3000.0,
                "+79991110002",
            ),
            ("cook@sirius.ru", "cook123", "cook", 0.0, "+79992220001"),
            ("courier@sirius.ru", "courier123", "courier", 0.0, "+79993330001"),
            ("admin@sirius.ru", "admin123", "admin", 0.0, "+79994440001"),
        ]

        for email, password, role_name, balance, phone in demo_users:
            u = db.query(User).filter(User.email == email).first()
            if not u:
                u = User(
                    email=email,
                    phone=phone,
                    balance=balance,
                    is_blocked=False,
                    password_hash=hash_password(password),
                    role_id=roles[role_name].id,
                )
                db.add(u)
            else:
                u.password_hash = hash_password(password)
                u.role_id = roles[role_name].id
                u.balance = balance
                db.add(u)

        # 3. Блюда меню
        demo_menu = [
            ("Борщ сириусский", 120.0, 1),
            ("Щи по-деревенски", 110.0, 1),
            ("Пюре с котлетой", 180.0, 2),
            ("Плов узбекский", 210.0, 2),
            ("Чай с лимоном", 40.0, 3),
            ("Морс ягодный", 55.0, 3),
            ("Салат Цезарь", 160.0, 4),
        ]

        for name, price, cat_id in demo_menu:
            item = db.query(MenuItem).filter(MenuItem.name == name).first()
            if not item:
                item = MenuItem(
                    name=name,
                    price=price,
                    is_available=True,
                    category_id=cat_id,
                )
                db.add(item)

        db.commit()
    print("✔ Демонстрационные данные успешно загружены в PostgreSQL!")


if __name__ == "__main__":
    seed_data()
