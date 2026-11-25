"""Add transactional outbox and consumer state."""

import sqlalchemy as sa

from alembic import op

revision = "002_events"
down_revision = "001_auth_roles"
branch_labels = None
depends_on = None


def upgrade():
    existing = sa.inspect(op.get_bind()).get_table_names()
    if "outbox_events" not in existing:
        op.create_table(
            "outbox_events",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("routing_key", sa.String(80), nullable=False),
            sa.Column("payload", sa.String, nullable=False),
            sa.Column("correlation_id", sa.String(128), nullable=False),
            sa.Column(
                "published", sa.Boolean, nullable=False, server_default=sa.false()
            ),
        )
    if "processed_events" not in existing:
        op.create_table(
            "processed_events",
            sa.Column("consumer", sa.String(40), primary_key=True),
            sa.Column("event_id", sa.String(36), primary_key=True),
        )
    if "kitchen_orders" not in existing:
        op.create_table(
            "kitchen_orders",
            sa.Column(
                "order_id", sa.Integer, sa.ForeignKey("orders.id"), primary_key=True
            ),
            sa.Column("status", sa.String(32), nullable=False),
        )


def downgrade():
    op.drop_table("kitchen_orders")
    op.drop_table("processed_events")
    op.drop_table("outbox_events")
