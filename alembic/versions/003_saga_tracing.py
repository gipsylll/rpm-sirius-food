"""Store trace propagation and one compensation per order."""

import sqlalchemy as sa

from alembic import op

revision = "003_saga_tracing"
down_revision = "002_events"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if "trace_context" not in [
        c["name"] for c in inspector.get_columns("outbox_events")
    ]:
        op.add_column(
            "outbox_events", sa.Column("trace_context", sa.String(), nullable=True)
        )
    if "order_compensations" not in inspector.get_table_names():
        op.create_table(
            "order_compensations",
            sa.Column(
                "order_id", sa.Integer, sa.ForeignKey("orders.id"), primary_key=True
            ),
            sa.Column("amount", sa.Float, nullable=False),
        )


def downgrade():
    op.drop_table("order_compensations")
    op.drop_column("outbox_events", "trace_context")
