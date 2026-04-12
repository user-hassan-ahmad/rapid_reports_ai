"""SQLAlchemy models for Rapid Reports AI"""

from sqlalchemy import Column, String, Text, Boolean, DateTime, JSON, ForeignKey, Integer, UniqueConstraint, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID, JSONB, TSVECTOR
from sqlalchemy import TypeDecorator
from datetime import datetime, timezone
import uuid
import json

try:
    from pgvector.sqlalchemy import Vector
except ImportError:
    Vector = None

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
    settings = Column(JSON, nullable=True)  # User preferences (auto_save, tag_colors, etc.)
    
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
        
        # Extract variables from template_config
        variables = []
        if isinstance(template_config, dict):
            if template_config.get('generation_mode') == 'skill_sheet_guided':
                variables = ['CLINICAL_HISTORY', 'FINDINGS']
            else:
                sections = template_config.get('sections', [])
                if isinstance(sections, list):
                    sorted_sections = sorted(
                        [s for s in sections if isinstance(s, dict)],
                        key=lambda s: s.get('order', 999)
                    )
                    for section in sorted_sections:
                        if section.get('has_input_field') and section.get('included'):
                            section_name = section.get('name')
                            if section_name:
                                variables.append(section_name)

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
        
        # Extract variables from template_config
        variables = []
        if isinstance(template_config, dict):
            if template_config.get('generation_mode') == 'skill_sheet_guided':
                variables = ['CLINICAL_HISTORY', 'FINDINGS']
            else:
                sections = template_config.get('sections', [])
                if isinstance(sections, list):
                    sorted_sections = sorted(
                        [s for s in sections if isinstance(s, dict)],
                        key=lambda s: s.get('order', 999)
                    )
                    for section in sorted_sections:
                        if section.get('has_input_field') and section.get('included'):
                            section_name = section.get('name')
                            if section_name:
                                variables.append(section_name)

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
    enhancement_json = Column(JSONBType(), nullable=True)  # Full enhance output for workspace history reload
    
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
    audits = relationship("ReportAudit", back_populates="report", cascade="all, delete-orphan")
    
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


class ReportAudit(Base):
    """Model for storing report audit/QA results"""
    
    __tablename__ = "report_audits"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    report_id = Column(UUID(as_uuid=True), ForeignKey("reports.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    overall_status = Column(String(10), nullable=False, index=True)  # "pass"|"flag"|"warning"
    scan_type = Column(String(200), nullable=True, index=True)
    model_used = Column(String(50), nullable=False)
    clinical_history = Column(Text, nullable=True)
    summary = Column(Text, nullable=False)
    report_version_id = Column(UUID(as_uuid=True), ForeignKey("report_versions.id", ondelete="SET NULL"), nullable=True)
    is_reviewed = Column(Boolean, default=False, nullable=False)
    reviewed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    prefetch_used = Column(Boolean, nullable=True)  # Analytics: True when audit was seeded by prefetch KB
    
    # Relationships
    report = relationship("Report", back_populates="audits")
    criteria = relationship("ReportAuditCriterion", back_populates="audit", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<ReportAudit(id={self.id}, status='{self.overall_status}')>"
    
    def _criterion_to_dict(self, c):
        """Serialize a criterion, expanding flags_json for clinical_flagging."""
        d = {
            "criterion": c.criterion,
            "status": c.status,
            "rationale": c.rationale,
            "recommendation": c.recommendation,
            "highlighted_spans": c.highlighted_spans or [],
            "acknowledged": c.acknowledged,
            "acknowledged_at": c.acknowledged_at.isoformat() if c.acknowledged_at else None,
            "resolution_method": c.resolution_method,
        }
        if c.criterion == "clinical_flagging" and c.flags_json:
            if isinstance(c.flags_json, list):
                d["flags_identified"] = c.flags_json
                d["suggested_banners"] = []
            elif isinstance(c.flags_json, dict):
                d["flags_identified"] = c.flags_json.get("flags_identified")
                d["suggested_banners"] = c.flags_json.get("suggested_banners") or []
            else:
                d["flags_identified"] = None
                d["suggested_banners"] = []
        else:
            d["flags_identified"] = None
            d["suggested_banners"] = []
        return d
    
    def to_dict(self):
        """Convert audit to dictionary for API response"""
        return {
            "id": str(self.id),
            "report_id": str(self.report_id),
            "overall_status": self.overall_status,
            "scan_type": self.scan_type,
            "model_used": self.model_used,
            "summary": self.summary,
            "is_reviewed": self.is_reviewed,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
            "created_at": self.created_at.isoformat(),
            "criteria": [self._criterion_to_dict(c) for c in self.criteria]
        }


class ReportAuditCriterion(Base):
    """Model for individual audit criterion results"""
    
    __tablename__ = "report_audit_criteria"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    audit_id = Column(UUID(as_uuid=True), ForeignKey("report_audits.id", ondelete="CASCADE"), nullable=False, index=True)
    criterion = Column(String(50), nullable=False, index=True)  # one of 9 criterion names
    status = Column(String(10), nullable=False, index=True)  # "pass"|"flag"|"warning"
    rationale = Column(Text, nullable=False)
    recommendation = Column(Text, nullable=True)
    highlighted_spans = Column(JSONBType, nullable=True)  # List[str] — verbatim substrings
    flags_json = Column(JSONBType, nullable=True)  # clinical_flagging only: List[AuditCriterionFlag]
    acknowledged = Column(Boolean, default=False, nullable=False)
    acknowledged_at = Column(DateTime, nullable=True)
    resolution_method = Column(String(20), nullable=True)  # "manual"|"ai_assisted"|"dismissed"
    
    # Relationship
    audit = relationship("ReportAudit", back_populates="criteria")
    
    def __repr__(self):
        return f"<ReportAuditCriterion(criterion='{self.criterion}', status='{self.status}')>"


class PrefetchResult(Base):
    """Persistent cache for prefetch pipeline outputs, keyed by findings_hash.

    Replaces both EnhancementCacheEntry and GuidelineCache. Stores the full
    PrefetchOutput JSON for cross-session and post-restart reuse (7-day TTL).
    """

    __tablename__ = "prefetch_results"

    findings_hash = Column(String(64), primary_key=True, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    output_json = Column(JSONBType(), nullable=False)
    pipeline_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    expires_at = Column(DateTime, nullable=False, index=True)

    user = relationship("User")

    def __repr__(self):
        return f"<PrefetchResult(hash='{self.findings_hash[:12]}…')>"


class TnmStaging(Base):
    """UICC TNM 9th Edition staging reference data with hybrid search support.

    Each row represents one tumour type with full T/N/M category definitions,
    stage grouping, and pre-computed embeddings for semantic search.
    BM25 search is powered by the tsvector column with a GIN index;
    semantic search uses pgvector HNSW on the embedding column.
    """

    __tablename__ = "tnm_staging"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tumour = Column(String(200), unique=True, nullable=False, index=True)
    icd_o = Column(String(200), nullable=True)
    edition_uicc = Column(String(10), nullable=False, default="9th")
    edition_ajcc = Column(String(10), nullable=True)
    rules = Column(Text, nullable=True)
    tnm_json = Column(JSONBType(), nullable=False)
    stage_grouping = Column(JSONBType(), nullable=True)
    search_text = Column(Text, nullable=False)
    search_vector = Column(TSVECTOR)
    embedding = Column(Vector(1536)) if Vector else Column(JSON, nullable=True)

    __table_args__ = (
        Index("ix_tnm_staging_search_vector", "search_vector", postgresql_using="gin"),
    )

    def __repr__(self):
        return f"<TnmStaging(tumour='{self.tumour}')>"

