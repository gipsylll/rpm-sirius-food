"""Promo codes, loyalty ledger and order financial fields."""

import sqlalchemy as sa

from alembic import op

revision = "004_promos_loyalty"
down_revision = "003_saga_tracing"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    tables = inspector.get_table_names()
    columns = {c["name"] for c in inspector.get_columns("orders")}
    for name, typ in (
        ("original_amount", sa.Numeric(12, 2)),
        ("discount_amount", sa.Numeric(12, 2)),
        ("final_amount", sa.Numeric(12, 2)),
        ("promo_code", sa.String(64)),
    ):
        if name not in columns:
            op.add_column(
                "orders",
                sa.Column(
                    name,
                    typ,
                    nullable=name == "promo_code",
                    server_default=None if name == "promo_code" else "0",
                ),
            )
    if "loyalty_points_spent" not in columns:
        op.add_column(
            "orders",
            sa.Column(
                "loyalty_points_spent", sa.Integer, nullable=False, server_default="0"
            ),
        )
    if "promo_codes" not in tables:
        op.create_table(
            "promo_codes",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("code", sa.String(64), unique=True, nullable=False),
            sa.Column("discount_type", sa.String(16), nullable=False),
            sa.Column("discount_value", sa.Numeric(12, 2), nullable=False),
            sa.Column("valid_from", sa.DateTime(timezone=True)),
            sa.Column("valid_until", sa.DateTime(timezone=True)),
            sa.Column("max_uses", sa.Integer),
            sa.Column("current_uses", sa.Integer, nullable=False, server_default="0"),
            sa.Column(
                "min_order_amount",
                sa.Numeric(12, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "is_active", sa.Boolean, nullable=False, server_default=sa.true()
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )
    if "promo_code_usages" not in tables:
        op.create_table(
            "promo_code_usages",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
            sa.Column(
                "promo_code_id",
                sa.Integer,
                sa.ForeignKey("promo_codes.id"),
                nullable=False,
            ),
            sa.Column(
                "order_id", sa.Integer, sa.ForeignKey("orders.id"), nullable=False
            ),
            sa.Column("discount_amount", sa.Numeric(12, 2), nullable=False),
            sa.Column("compensation_key", sa.String(128), unique=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.UniqueConstraint("user_id", "promo_code_id", name="uq_promo_user_code"),
            sa.UniqueConstraint("order_id", name="uq_promo_order"),
        )
    if "promo_compensations" not in tables:
        op.create_table(
            "promo_compensations",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("compensation_key", sa.String(128), unique=True, nullable=False),
            sa.Column(
                "order_id", sa.Integer, sa.ForeignKey("orders.id"), nullable=False
            ),
            sa.Column(
                "promo_code_id",
                sa.Integer,
                sa.ForeignKey("promo_codes.id"),
                nullable=False,
            ),
            sa.Column("restored", sa.Boolean, nullable=False, server_default=sa.true()),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )
    if "loyalty_accounts" not in tables:
        op.create_table(
            "loyalty_accounts",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column(
                "user_id",
                sa.Integer,
                sa.ForeignKey("users.id"),
                unique=True,
                nullable=False,
            ),
            sa.Column("balance", sa.Integer, nullable=False, server_default="0"),
            sa.Column("total_earned", sa.Integer, nullable=False, server_default="0"),
            sa.Column("level", sa.String(16), nullable=False, server_default="Bronze"),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )
    if "loyalty_transactions" not in tables:
        op.create_table(
            "loyalty_transactions",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
            sa.Column("amount", sa.Integer, nullable=False),
            sa.Column("transaction_type", sa.String(16), nullable=False),
            sa.Column("order_id", sa.Integer, sa.ForeignKey("orders.id")),
            sa.Column("idempotency_key", sa.String(160), unique=True, nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )
    if op.get_bind().dialect.name == "postgresql":
        op.alter_column("users", "balance", type_=sa.Numeric(12, 2), postgresql_using="balance::numeric")
        op.alter_column("menu_items", "price", type_=sa.Numeric(12, 2), postgresql_using="price::numeric")
        op.alter_column("order_compensations", "amount", type_=sa.Numeric(12, 2), postgresql_using="amount::numeric")


def downgrade():
    for table in (
        "loyalty_transactions",
        "loyalty_accounts",
        "promo_compensations",
        "promo_code_usages",
        "promo_codes",
    ):
        op.drop_table(table)
    for name in (
        "loyalty_points_spent",
        "promo_code",
        "final_amount",
        "discount_amount",
        "original_amount",
    ):
        op.drop_column("orders", name)
