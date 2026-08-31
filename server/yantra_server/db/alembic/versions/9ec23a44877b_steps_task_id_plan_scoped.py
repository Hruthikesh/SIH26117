"""steps.task_id becomes plan-scoped (no FK to tasks; TaskRow keys are run-scoped)

Revision ID: 9ec23a44877b
Revises: 83f0810c8ea0
Create Date: 2026-08-31
"""

from __future__ import annotations

from alembic import op

revision = "9ec23a44877b"
down_revision = "83f0810c8ea0"
branch_labels = None
depends_on = None

# The original FK was created unnamed; give the reflected copy a deterministic name so
# SQLite batch-recreate can drop it.
NAMING = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}


def upgrade() -> None:
    with op.batch_alter_table("steps", schema=None, naming_convention=NAMING) as batch_op:
        batch_op.drop_constraint("fk_steps_task_id_tasks", type_="foreignkey")


def downgrade() -> None:
    with op.batch_alter_table("steps", schema=None, naming_convention=NAMING) as batch_op:
        batch_op.create_foreign_key("fk_steps_task_id_tasks", "tasks", ["task_id"], ["id"])
