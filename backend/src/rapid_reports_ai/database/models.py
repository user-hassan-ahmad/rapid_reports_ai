"""SQLAlchemy models for Rapid Reports AI"""

from sqlalchemy import Column, String, Text, Boolean, DateTime, JSON, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime, timezone
import uuid

# Create Base class
Base = declarative_base()


class User(Base):
    """Model for user accounts"""
    
    __tablename__ = "users"
    
    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    
    # User info
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(200), nullable=True)
    signature = Column(Text, nullable=True)  # Report signature for dynamic injection
    settings = Column(JSON, nullable=True)  # User preferences (default_model, auto_save, etc.)
    
    # Auth metadata
    is_active = Column(Boolean, default=True, nullable=False)
    is_verified = Column(Boolean, default=False, nullable=False)
    
    # Timestamps
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    last_login = Column(DateTime, nullable=True)
    
    # Relationships
    templates = relationship("Template", back_populates="user", cascade="all, delete-orphan")
    reset_tokens = relationship("PasswordResetToken", back_populates="user", cascade="all, delete-orphan")
    reports = relationship("Report", back_populates="user", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<User(id={self.id}, email='{self.email}')>"
    
    def to_dict(self):
        return {
            "id": str(self.id),
            "email": self.email,
            "full_name": self.full_name,
            "signature": self.signature,
            "settings": self.settings or {},
            "is_active": self.is_active,
            "is_verified": self.is_verified,
            "created_at": self.created_at.isoformat(),
            "last_login": self.last_login.isoformat() if self.last_login else None,
        }


class PasswordResetToken(Base):
    """Model for password reset and email verification tokens"""
    
    __tablename__ = "password_reset_tokens"
    
    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    
    # Foreign key
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Token info
    token = Column(String(255), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False, index=True)
    is_used = Column(Boolean, default=False, nullable=False)
    token_type = Column(String(20), default="password_reset", nullable=False)  # "password_reset" or "email_verification"
    
    # Timestamps
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    
    # Relationships
    user = relationship("User", back_populates="reset_tokens")
    
    def __repr__(self):
        return f"<PasswordResetToken(id={self.id}, type='{self.token_type}')>"


class Template(Base):
    """Model for custom report templates"""
    
    __tablename__ = "templates"
    
    # Primary key
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True
    )
    
    # Template metadata
    name = Column(String(200), nullable=False, index=True)
    description = Column(Text, nullable=True)
    tags = Column(JSON, nullable=True)  # Array of tag strings
    
    # Template content and variables
    template_content = Column(Text, nullable=False)  # The template with {{variables}}
    variables = Column(JSON, nullable=True)  # Simple array of variable names
    variable_config = Column(JSON, nullable=True)  # Advanced config (for future)
    
    # Instructions and compatibility
    master_prompt_instructions = Column(Text, nullable=True)
    model_compatibility = Column(JSON, nullable=True)  # ["claude", "gemini"]
    
    # Foreign key to user
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Relationship
    user = relationship("User", back_populates="templates")
    versions = relationship("TemplateVersion", back_populates="template", cascade="all, delete-orphan")
    
    # Metadata
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    
    # Usage statistics
    usage_count = Column(Integer, default=0, nullable=False)
    last_used_at = Column(DateTime, nullable=True)
    
    # Pin status
    is_pinned = Column(Boolean, default=False, nullable=False, index=True)
    
    def __repr__(self):
        return f"<Template(id={self.id}, name='{self.name}')>"
    
    def to_dict(self):
        """Convert template to dictionary"""
        return {
            "id": str(self.id),
            "user_id": str(self.user_id),
            "name": self.name,
            "description": self.description,
            "tags": self.tags or [],
            "template_content": self.template_content,
            "variables": self.variables or [],
            "variable_config": self.variable_config,
            "master_prompt_instructions": self.master_prompt_instructions,
            "model_compatibility": self.model_compatibility or ["claude", "gemini"],
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "is_active": self.is_active,
            "usage_count": self.usage_count or 0,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "is_pinned": self.is_pinned or False,
        }


class TemplateVersion(Base):
    """Model for template version history"""
    
    __tablename__ = "template_versions"
    
    # Primary key
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True
    )
    
    # Foreign key
    template_id = Column(
        UUID(as_uuid=True),
        ForeignKey("templates.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    
    # Snapshot of template fields at this version
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    tags = Column(JSON, nullable=True)
    template_content = Column(Text, nullable=False)
    variables = Column(JSON, nullable=True)
    master_prompt_instructions = Column(Text, nullable=True)
    model_compatibility = Column(JSON, nullable=True)
    
    # Version metadata
    version_number = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    
    # Relationship
    template = relationship("Template", back_populates="versions")
    
    # Unique constraint to ensure proper version ordering per template
    __table_args__ = (
        UniqueConstraint('template_id', 'version_number', name='uq_template_version'),
    )
    
    def __repr__(self):
        return f"<TemplateVersion(id={self.id}, template_id={self.template_id}, version={self.version_number})>"
    
    def to_dict(self):
        """Convert version to dictionary"""
        return {
            "id": str(self.id),
            "template_id": str(self.template_id),
            "name": self.name,
            "description": self.description,
            "tags": self.tags or [],
            "template_content": self.template_content,
            "variables": self.variables or [],
            "master_prompt_instructions": self.master_prompt_instructions,
            "model_compatibility": self.model_compatibility or [],
            "version_number": self.version_number,
            "created_at": self.created_at.isoformat(),
        }


class Report(Base):
    """Model for storing generated reports"""
    
    __tablename__ = "reports"
    
    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    
    # Report type and metadata
    report_type = Column(String(50), nullable=False, index=True)  # "auto" or "templated"
    use_case = Column(String(200), nullable=True)  # For auto reports
    model_used = Column(String(50), nullable=False)  # "claude" or "gemini"
    
    # Report content
    input_data = Column(JSON, nullable=True)  # Variables/message used
    report_content = Column(Text, nullable=False)  # Generated report
    description = Column(String(500), nullable=True)  # Brief contextual description for history display
    
    # Foreign keys
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    template_id = Column(UUID(as_uuid=True), ForeignKey("templates.id", ondelete="SET NULL"), nullable=True, index=True)
    
    # Timestamps
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    
    # Relationships
    user = relationship("User", back_populates="reports")
    template = relationship("Template", foreign_keys=[template_id])
    versions = relationship(
        "ReportVersion",
        back_populates="report",
        cascade="all, delete-orphan",
        order_by="ReportVersion.version_number"
    )
    
    def __repr__(self):
        return f"<Report(id={self.id}, type='{self.report_type}')>"
    
    def to_dict(self):
        """Convert report to dictionary"""
        return {
            "id": str(self.id),
            "user_id": str(self.user_id),
            "report_type": self.report_type,
            "use_case": self.use_case,
            "template_id": str(self.template_id) if self.template_id else None,
            "model_used": self.model_used,
            "input_data": self.input_data,
            "report_content": self.report_content,
            "description": self.description,
            "created_at": self.created_at.isoformat(),
        }


class ReportVersion(Base):
    """Version history for reports"""

    __tablename__ = "report_versions"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True
    )
    report_id = Column(
        UUID(as_uuid=True),
        ForeignKey("reports.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    version_number = Column(Integer, nullable=False)
    report_content = Column(Text, nullable=False)
    actions_applied = Column(JSON, nullable=True)
    notes = Column(Text, nullable=True)
    model_used = Column(String(50), nullable=True)
    is_current = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)

    report = relationship("Report", back_populates="versions")

    __table_args__ = (
        UniqueConstraint('report_id', 'version_number', name='uq_report_version'),
    )

    def to_dict(self):
        return {
            "id": str(self.id),
            "report_id": str(self.report_id),
            "version_number": self.version_number,
            "report_content": self.report_content,
            "actions_applied": self.actions_applied or [],
            "notes": self.notes,
            "model_used": self.model_used,
            "is_current": self.is_current,
            "created_at": self.created_at.isoformat()
        }

