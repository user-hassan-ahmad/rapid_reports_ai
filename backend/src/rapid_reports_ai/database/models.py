"""SQLAlchemy models for Rapid Reports AI"""

from sqlalchemy import Column, String, Text, Boolean, DateTime, JSON, ForeignKey, Integer, UniqueConstraint, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy import TypeDecorator
from datetime import datetime, timezone
import uuid
import json

# Create Base class
Base = declarative_base()


# JSONB type that works for both PostgreSQL and SQLite
class JSONBType(TypeDecorator):
    """JSONB type that falls back to JSON for SQLite."""
    impl = JSON
    cache_ok = True
    
    def load_dialect_impl(self, dialect):
        if dialect.name == 'postgresql':
            return dialect.type_descriptor(JSONB())
        else:
            return dialect.type_descriptor(JSON())


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
    
    # Template configuration (structured JSON)
    template_config = Column(JSON, nullable=True)  # Complete template configuration
    
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
        template_config = self.template_config or {}
        
        # Extract variables from template_config.sections
        # Variables are sections with has_input_field=True and included=True
        # Preserve the order from the sections' order field
        variables = []
        if isinstance(template_config, dict):
            sections = template_config.get('sections', [])
            if isinstance(sections, list):
                # Sort sections by order field to maintain structure order
                sorted_sections = sorted(
                    [s for s in sections if isinstance(s, dict)],
                    key=lambda s: s.get('order', 999)  # Default to 999 if order missing
                )
                
                for section in sorted_sections:
                    # Check if section has input field and is included
                    if section.get('has_input_field') and section.get('included'):
                        section_name = section.get('name')
                        if section_name:
                            variables.append(section_name)
        
        # Remove duplicates while preserving order
        seen = set()
        unique_variables = []
        for var in variables:
            if var not in seen:
                seen.add(var)
                unique_variables.append(var)
        
        return {
            "id": str(self.id),
            "user_id": str(self.user_id),
            "name": self.name,
            "description": self.description,
            "tags": self.tags or [],
            "template_config": template_config,
            "variables": unique_variables,  # Add extracted variables
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
    template_config = Column(JSON, nullable=True)  # Complete template configuration snapshot
    
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
        template_config = self.template_config or {}
        
        # Extract variables from template_config.sections
        # Variables are sections with has_input_field=True and included=True
        # Preserve the order from the sections' order field
        variables = []
        if isinstance(template_config, dict):
            sections = template_config.get('sections', [])
            if isinstance(sections, list):
                # Sort sections by order field to maintain structure order
                sorted_sections = sorted(
                    [s for s in sections if isinstance(s, dict)],
                    key=lambda s: s.get('order', 999)  # Default to 999 if order missing
                )
                
                for section in sorted_sections:
                    # Check if section has input field and is included
                    if section.get('has_input_field') and section.get('included'):
                        section_name = section.get('name')
                        if section_name:
                            variables.append(section_name)
        
        # Remove duplicates while preserving order
        seen = set()
        unique_variables = []
        for var in variables:
            if var not in seen:
                seen.add(var)
                unique_variables.append(var)
        
        return {
            "id": str(self.id),
            "template_id": str(self.template_id),
            "name": self.name,
            "description": self.description,
            "tags": self.tags or [],
            "template_config": template_config,
            "variables": unique_variables,  # Add extracted variables
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
    validation_status = Column(JSON, nullable=True)  # Async validation status: {status, violations_count, started_at, completed_at, error}
    
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
            "validation_status": self.validation_status,
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


class EnhancementCacheEntry(Base):
    """Model for persistent enhancement pipeline cache"""
    
    __tablename__ = "enhancement_cache"
    
    # Primary key - cache_key format: "type:findings_hash:finding_idx:hash"
    cache_key = Column(String(500), primary_key=True, index=True)
    
    # Analytics fields
    findings_hash = Column(String(64), index=True)  # For grouping by findings
    cache_type = Column(String(50), index=True)     # 'query_gen', 'perplexity_search', etc.
    
    # Cached data (JSONB for PostgreSQL, JSON for SQLite)
    cached_value = Column(JSONBType(), nullable=False)
    
    # Timestamps
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    last_accessed = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    
    # Usage tracking
    access_count = Column(Integer, default=1, nullable=False)
    
    # TTL management
    expires_at = Column(DateTime, nullable=False, index=True)
    
    # Composite indexes for common queries
    __table_args__ = (
        Index('idx_findings_hash_type', 'findings_hash', 'cache_type'),
        Index('idx_expires_at', 'expires_at'),
    )
    
    def __repr__(self):
        return f"<EnhancementCacheEntry(cache_key='{self.cache_key[:50]}...', type='{self.cache_type}')>"

