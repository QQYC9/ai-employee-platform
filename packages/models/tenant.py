import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from packages.core.database import Base


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )

    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    slug: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
        index=True,
    )

    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="active",
        server_default="active",
    )

    interview_required: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )

    interview_threshold: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=80.0,
        server_default=text("80.0"),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
