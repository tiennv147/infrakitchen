"""add service bindings

Revision ID: f5a1d3c8b624
Revises: e3b7c95f2a18
Create Date: 2026-09-29 16:00:00.000000

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f5a1d3c8b624"
down_revision: str | None = "e3b7c95f2a18"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("environments", sa.Column("binding_sink", sa.JSON(), nullable=True))
    op.add_column("service_instances", sa.Column("binding_state", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("service_instances", "binding_state")
    op.drop_column("environments", "binding_sink")
