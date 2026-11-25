"""add password_hash, roles, refresh_tokens

Revision ID: 001_auth_roles
Revises:
Create Date: 2026-10-17 19:50:00

"""

import sqlalchemy as sa

from alembic import op

revision = "001_auth_roles"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    # 1. Создаём таблицу ролей, если её нет
    if "roles" not in tables:
        op.create_table(
            "roles",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(50), unique=True, nullable=False),
        )
        op.execute(
            "INSERT INTO roles (name) VALUES ('student'), ('cook'), ('courier'), ('admin')"
        )

    # 2. Создаем или обновляем таблицу users
    if "users" not in tables:
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), primary_key=True, index=True),
            sa.Column("email", sa.String(), unique=True, nullable=False),
            sa.Column("phone", sa.String(), nullable=True),
            sa.Column("balance", sa.Float(), server_default="0.0"),
            sa.Column("is_blocked", sa.Boolean(), server_default="false"),
            sa.Column("password_hash", sa.String(), nullable=True),
            sa.Column(
                "role_id", sa.Integer(), sa.ForeignKey("roles.id"), nullable=True
            ),
        )
    else:
        columns = [c["name"] for c in inspector.get_columns("users")]
        if "password_hash" not in columns:
            op.add_column(
                "users", sa.Column("password_hash", sa.String(), nullable=True)
            )
        if "role_id" not in columns:
            op.add_column("users", sa.Column("role_id", sa.Integer(), nullable=True))
            op.create_foreign_key(
                "fk_users_role", "users", "roles", ["role_id"], ["id"]
            )
            op.execute(
                "UPDATE users SET role_id = (SELECT id FROM roles WHERE name = 'student')"
            )

    # 3. Создаем или обновляем menu_items
    if "menu_items" not in tables:
        op.create_table(
            "menu_items",
            sa.Column("id", sa.Integer(), primary_key=True, index=True),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("price", sa.Float(), nullable=False),
            sa.Column("is_available", sa.Boolean(), server_default="true"),
            sa.Column("category_id", sa.Integer(), server_default="1", nullable=True),
        )
    else:
        columns = [c["name"] for c in inspector.get_columns("menu_items")]
        if "category_id" not in columns:
            op.add_column(
                "menu_items",
                sa.Column(
                    "category_id", sa.Integer(), server_default="1", nullable=True
                ),
            )

    # 4. Создаем orders, если её нет
    if "orders" not in tables:
        op.create_table(
            "orders",
            sa.Column("id", sa.Integer(), primary_key=True, index=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id")),
            sa.Column("item_id", sa.Integer(), sa.ForeignKey("menu_items.id")),
            sa.Column("quantity", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(), server_default="processing"),
        )

    # 5. Создаем deliveries, если её нет
    if "deliveries" not in tables:
        op.create_table(
            "deliveries",
            sa.Column("id", sa.Integer(), primary_key=True, index=True),
            sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id")),
            sa.Column(
                "courier_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True
            ),
            sa.Column("status", sa.String(), server_default="pending"),
        )

    # 6. Создаём таблицу refresh-токенов, если её нет
    if "refresh_tokens" not in tables:
        op.create_table(
            "refresh_tokens",
            sa.Column("id", sa.Integer(), primary_key=True, index=True),
            sa.Column(
                "user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False
            ),
            sa.Column("token_hash", sa.String(), unique=True, nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("is_revoked", sa.Boolean(), server_default="false"),
        )


def downgrade() -> None:
    op.drop_table("refresh_tokens")
    op.drop_constraint("fk_users_role", "users", type_="foreignkey")
    op.drop_column("users", "role_id")
    op.drop_column("users", "password_hash")
    op.drop_column("menu_items", "category_id")
    op.drop_table("roles")
