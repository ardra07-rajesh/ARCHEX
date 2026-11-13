"""Persist reproducible research validation runs."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0004_phase13_validation"
down_revision = "0003_phase12_identity"
branch_labels = None
depends_on = None

def upgrade():
    bind = op.get_bind()
    if "validation_runs" not in set(inspect(bind).get_table_names()):
        op.create_table(
            "validation_runs",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("suite", sa.String(64), nullable=False),
            sa.Column("seed", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.String(40), nullable=False),
            sa.Column("duration_ms", sa.Float(), nullable=False),
            sa.Column("result_sha256", sa.String(64), nullable=False),
            sa.Column("manifest_json", sa.Text(), nullable=False),
            sa.Column("result_json", sa.Text(), nullable=False),
        )
    inspector = inspect(bind)
    indexes = {i["name"] for i in inspector.get_indexes("validation_runs")}
    for column in ("owner_id", "suite", "created_at", "result_sha256"):
        name = f"ix_validation_runs_{column}"
        if name not in indexes: op.create_index(name, "validation_runs", [column])

def downgrade():
    if "validation_runs" in set(inspect(op.get_bind()).get_table_names()):
        op.drop_table("validation_runs")
