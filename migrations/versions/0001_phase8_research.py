"""Create persistent Phase 8 experiment, execution and activity tables."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0001_phase8_research"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    bind = op.get_bind()
    existing = set(inspect(bind).get_table_names())
    if "experiments" not in existing:
        op.create_table(
            "experiments",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("name", sa.String(160), nullable=False),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("category", sa.String(40), nullable=False),
            sa.Column("simulation", sa.String(40), nullable=False),
            sa.Column("created_at", sa.String(40), nullable=False),
            sa.Column("updated_at", sa.String(40), nullable=False),
            sa.Column("status", sa.String(24), nullable=False, server_default="draft"),
            sa.Column("config_json", sa.Text(), nullable=False),
            sa.Column("result_json", sa.Text(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=False, server_default=""),
            sa.Column("tags_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        )
    if "experiment_executions" not in existing:
        op.create_table(
            "experiment_executions",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("experiment_id", sa.String(36), nullable=False),
            sa.Column("created_at", sa.String(40), nullable=False),
            sa.Column("status", sa.String(24), nullable=False),
            sa.Column("config_json", sa.Text(), nullable=False),
            sa.Column("result_json", sa.Text(), nullable=True),
            sa.Column("error", sa.Text(), nullable=False, server_default=""),
            sa.Column("duration_ms", sa.Float(), nullable=True),
            sa.Column("software_version", sa.String(32), nullable=False, server_default="0.7.0"),
            sa.Column("replay_of", sa.String(36), nullable=True),
        )
    if "activity_events" not in existing:
        op.create_table(
            "activity_events",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("created_at", sa.String(40), nullable=False),
            sa.Column("category", sa.String(40), nullable=False),
            sa.Column("severity", sa.String(16), nullable=False, server_default="info"),
            sa.Column("message", sa.String(500), nullable=False),
            sa.Column("experiment_id", sa.String(36), nullable=True),
            sa.Column("data_json", sa.Text(), nullable=False, server_default="{}"),
        )
    # Idempotent index creation for databases initialized by SQLAlchemy create_all.
    inspector = inspect(bind)
    for table, columns in (("experiments", ["name", "category", "simulation", "created_at", "status"]),
                           ("experiment_executions", ["experiment_id", "created_at", "status", "replay_of"]),
                           ("activity_events", ["created_at", "category", "experiment_id"])):
        indexes = {i["name"] for i in inspector.get_indexes(table)}
        for column in columns:
            index_name = f"ix_{table}_{column}"
            if index_name not in indexes:
                op.create_index(index_name, table, [column])

def downgrade():
    bind = op.get_bind()
    existing = set(inspect(bind).get_table_names())
    for table in ("activity_events", "experiment_executions", "experiments"):
        if table in existing:
            op.drop_table(table)
