"""Create persistent Phase 9 research report metadata."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0002_phase9_reports"
down_revision = "0001_phase8_research"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    existing = set(inspect(bind).get_table_names())
    if "research_reports" not in existing:
        op.create_table(
            "research_reports",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("experiment_id", sa.String(36), nullable=False),
            sa.Column("title", sa.String(200), nullable=False),
            sa.Column("report_type", sa.String(24), nullable=False),
            sa.Column("status", sa.String(24), nullable=False, server_default="completed"),
            sa.Column("created_at", sa.String(40), nullable=False),
            sa.Column("filename", sa.String(80), nullable=False, unique=True),
            sa.Column("file_size", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("sections_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("detail_level", sa.String(24), nullable=False, server_default="technical"),
            sa.Column("experiment_version", sa.Integer(), nullable=False, server_default="1"),
        )
    inspector = inspect(bind)
    indexes = {i["name"] for i in inspector.get_indexes("research_reports")}
    for column in ("experiment_id", "report_type", "status", "created_at"):
        name = f"ix_research_reports_{column}"
        if name not in indexes:
            op.create_index(name, "research_reports", [column])


def downgrade():
    bind = op.get_bind()
    if "research_reports" in set(inspect(bind).get_table_names()):
        op.drop_table("research_reports")
