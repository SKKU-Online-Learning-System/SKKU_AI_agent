"""Create the stage 2 database schema.

Revision ID: 20260710_0001
Revises:
Create Date: 2026-07-10
"""

from typing import Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260710_0001"
down_revision: Optional[str] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

user_role = sa.Enum(
    "student",
    "professor",
    "admin",
    name="user_role",
    native_enum=False,
    create_constraint=True,
)
course_material_status = sa.Enum(
    "pending",
    "processing",
    "completed",
    "failed",
    name="course_material_status",
    native_enum=False,
    create_constraint=True,
)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("external_auth_id", sa.String(length=255), nullable=True),
        sa.Column("school_id", sa.String(length=80), nullable=True),
        sa.Column("role", user_role, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "password_hash IS NOT NULL OR external_auth_id IS NOT NULL",
            name="ck_users_auth_identity",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index(
        "ix_users_external_auth_id",
        "users",
        ["external_auth_id"],
        unique=True,
    )
    op.create_index("ix_users_school_id", "users", ["school_id"], unique=True)

    op.create_table(
        "courses",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("semester", sa.String(length=40), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("professor_id", sa.String(length=36), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["professor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_courses_professor_id", "courses", ["professor_id"], unique=False)
    op.create_index("ix_courses_semester", "courses", ["semester"], unique=False)

    op.create_table(
        "course_access",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("course_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column(
            "access_role",
            sa.String(length=40),
            server_default="student",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "course_id",
            "user_id",
            name="uq_course_access_course_user",
        ),
    )
    op.create_index(
        "ix_course_access_course_id",
        "course_access",
        ["course_id"],
        unique=False,
    )
    op.create_index(
        "ix_course_access_user_id",
        "course_access",
        ["user_id"],
        unique=False,
    )

    op.create_table(
        "course_materials",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("course_id", sa.String(length=36), nullable=False),
        sa.Column("uploaded_by", sa.String(length=36), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("original_file_name", sa.String(length=255), nullable=False),
        sa.Column("file_type", sa.String(length=40), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("processing_status", course_material_status, nullable=False),
        sa.Column("processing_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "file_size >= 0",
            name="ck_course_materials_file_size_non_negative",
        ),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_course_materials_course_id",
        "course_materials",
        ["course_id"],
        unique=False,
    )
    op.create_index(
        "ix_course_materials_uploaded_by",
        "course_materials",
        ["uploaded_by"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_course_materials_uploaded_by", table_name="course_materials")
    op.drop_index("ix_course_materials_course_id", table_name="course_materials")
    op.drop_table("course_materials")
    op.drop_index("ix_course_access_user_id", table_name="course_access")
    op.drop_index("ix_course_access_course_id", table_name="course_access")
    op.drop_table("course_access")
    op.drop_index("ix_courses_semester", table_name="courses")
    op.drop_index("ix_courses_professor_id", table_name="courses")
    op.drop_table("courses")
    op.drop_index("ix_users_school_id", table_name="users")
    op.drop_index("ix_users_external_auth_id", table_name="users")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
