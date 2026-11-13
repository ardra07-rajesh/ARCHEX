"""Add Phase 12 identity, audit records and resource ownership."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0003_phase12_identity"
down_revision = "0002_phase9_reports"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    if "analysis_records" not in tables:
        op.create_table(
            "analysis_records",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("created_at", sa.String(40), nullable=False),
            sa.Column("scenario", sa.String(40), nullable=False),
            sa.Column("seed", sa.Integer(), nullable=False),
            sa.Column("classification", sa.String(20), nullable=False),
            sa.Column("anomaly_score", sa.Float(), nullable=False),
            sa.Column("result_json", sa.Text(), nullable=False),
        )
    if "users" not in tables:
        op.create_table(
            "users",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("email", sa.String(254), nullable=False),
            sa.Column("display_name", sa.String(80), nullable=False),
            sa.Column("password_hash", sa.String(256), nullable=False),
            sa.Column("role", sa.String(20), nullable=False, server_default="researcher"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.String(40), nullable=False),
            sa.Column("updated_at", sa.String(40), nullable=False),
            sa.UniqueConstraint("email", name="uq_users_email"),
        )
        op.create_index("ix_users_email", "users", ["email"])
        op.create_index("ix_users_role", "users", ["role"])
    if "security_audit_events" not in tables:
        op.create_table(
            "security_audit_events",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.String(36), nullable=True),
            sa.Column("action", sa.String(80), nullable=False),
            sa.Column("resource_type", sa.String(50), nullable=False, server_default=""),
            sa.Column("resource_id", sa.String(80), nullable=False, server_default=""),
            sa.Column("ip_address", sa.String(64), nullable=False, server_default=""),
            sa.Column("created_at", sa.String(40), nullable=False),
        )
        for col in ("user_id", "action", "created_at"):
            op.create_index(f"ix_security_audit_events_{col}", "security_audit_events", [col])
    for table in ("analysis_records", "experiments", "assistant_conversations", "research_reports"):
        if table not in set(inspect(bind).get_table_names()):
            continue
        cols = {c["name"] for c in inspect(bind).get_columns(table)}
        if "owner_id" not in cols:
            with op.batch_alter_table(table) as batch:
                batch.add_column(sa.Column("owner_id", sa.String(36), nullable=True))
                batch.create_foreign_key(f"fk_{table}_owner_id_users", "users", ["owner_id"], ["id"], ondelete="SET NULL")
            op.create_index(f"ix_{table}_owner_id", table, ["owner_id"])


def downgrade():
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    for table in ("analysis_records", "experiments", "assistant_conversations", "research_reports"):
        if table in tables and "owner_id" in {c["name"] for c in inspect(bind).get_columns(table)}:
            op.drop_index(f"ix_{table}_owner_id", table_name=table)
            with op.batch_alter_table(table) as batch:
                batch.drop_column("owner_id")
    if "security_audit_events" in tables:
        op.drop_table("security_audit_events")
    if "users" in tables:
        op.drop_table("users")
