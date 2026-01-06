"""CRUD operations for templates, users, and password reset tokens"""

from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from datetime import datetime, timezone
import uuid

from .models import (
    Template,
    User,
    PasswordResetToken,
    Report,
    TemplateVersion,
    ReportVersion,
    WritingStylePreset,
)


# ============ User CRUD ============

def create_user(
    db: Session,
    email: str,
    password_hash: str,
    full_name: Optional[str] = None,
) -> User:
    """Create a new user"""
    user = User(
        email=email,
        password_hash=password_hash,
        full_name=full_name,
        is_active=True,
        is_verified=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_user_by_email(db: Session, email: str) -> Optional[User]:
    """Get a user by email"""
    return db.query(User).filter(User.email == email).first()


def get_user_by_id(db: Session, user_id: str) -> Optional[User]:
    """Get a user by ID"""
    try:
        if isinstance(user_id, str):
            user_id = uuid.UUID(user_id)
    except ValueError:
        return None
    return db.query(User).filter(User.id == user_id).first()


def update_last_login(db: Session, user_id: str) -> None:
    """Update user's last login timestamp"""
    try:
        if isinstance(user_id, str):
            user_id = uuid.UUID(user_id)
    except ValueError:
        return None
    user = db.query(User).filter(User.id == user_id).first()
    if user:
        user.last_login = datetime.now(timezone.utc)
        db.commit()


# ============ Password Reset Token CRUD ============

def create_reset_token(
    db: Session,
    user_id: str,
    token: str,
    expires_at: datetime,
    token_type: str = "password_reset",
) -> PasswordResetToken:
    """Create a password reset or email verification token"""
    reset_token = PasswordResetToken(
        user_id=uuid.UUID(user_id) if isinstance(user_id, str) else user_id,
        token=token,
        expires_at=expires_at,
        token_type=token_type,
    )
    db.add(reset_token)
    db.commit()
    db.refresh(reset_token)
    return reset_token


def get_valid_reset_token(db: Session, token: str) -> Optional[PasswordResetToken]:
    """Get a valid (unused, non-expired) reset token"""
    return db.query(PasswordResetToken).filter(
        and_(
            PasswordResetToken.token == token,
            PasswordResetToken.is_used == False,
            PasswordResetToken.expires_at > datetime.now(timezone.utc),
        )
    ).first()


def mark_token_used(db: Session, token: str) -> None:
    """Mark a reset token as used"""
    reset_token = db.query(PasswordResetToken).filter(
        PasswordResetToken.token == token
    ).first()
    if reset_token:
        reset_token.is_used = True
        db.commit()


# ============ Template CRUD ============

def create_template(
    db: Session,
    name: str,
    user_id: str,
    template_config: Optional[dict] = None,
    description: Optional[str] = None,
    tags: Optional[list] = None,
    is_pinned: Optional[bool] = False,
) -> Template:
    """Create a new template for a user"""
    template = Template(
        name=name,
        description=description,
        tags=tags or [],
        template_config=template_config or {},
        user_id=uuid.UUID(user_id) if isinstance(user_id, str) else user_id,
        is_active=True,
        is_pinned=is_pinned or False,
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    
    # Create version 1 immediately upon template creation for consistency
    create_template_version(db, template)
    
    return template


def get_template(db: Session, template_id: str, user_id: Optional[str] = None) -> Optional[Template]:
    """Get a template by ID, optionally filtered by user"""
    # Convert string UUID to UUID object if needed
    try:
        if isinstance(template_id, str):
            template_id = uuid.UUID(template_id)
    except ValueError:
        return None
    
    query = db.query(Template).filter(
        and_(Template.id == template_id, Template.is_active == True)
    )
    
    # Filter by user if provided (ownership check)
    if user_id:
        try:
            user_uuid = uuid.UUID(user_id) if isinstance(user_id, str) else user_id
            query = query.filter(Template.user_id == user_uuid)
        except ValueError:
            return None
    
    return query.first()


def get_templates(
    db: Session,
    user_id: str,
    skip: int = 0,
    limit: int = 100,
    tags: Optional[List[str]] = None,
) -> List[Template]:
    """Get all active templates for a user, optionally filtered by tags (OR logic - any matching tag)"""
    try:
        user_uuid = uuid.UUID(user_id) if isinstance(user_id, str) else user_id
    except ValueError:
        return []
    
    query = db.query(Template).filter(
        and_(
            Template.user_id == user_uuid,
            Template.is_active == True
        )
    )
    
    if tags and len(tags) > 0:
        # Filter templates that contain ANY of the provided tags
        # Load templates and filter in Python for cross-database compatibility
        # This works with both SQLite and PostgreSQL
        all_templates = query.all()
        filtered = []
        for template in all_templates:
            template_tags = template.tags or []
            # Check if any of the requested tags exists in template's tags (case-insensitive)
            template_tags_lower = [t.lower() if isinstance(t, str) else str(t).lower() for t in template_tags]
            requested_tags_lower = [t.lower() if isinstance(t, str) else str(t).lower() for t in tags]
            if any(req_tag in template_tags_lower for req_tag in requested_tags_lower):
                filtered.append(template)
        return filtered[skip:skip+limit]
    
    return query.offset(skip).limit(limit).all()


def get_all_tags(db: Session, user_id: str) -> List[str]:
    """Get all unique tags across all user's templates"""
    try:
        user_uuid = uuid.UUID(user_id) if isinstance(user_id, str) else user_id
    except ValueError:
        return []
    
    templates = db.query(Template).filter(
        and_(
            Template.user_id == user_uuid,
            Template.is_active == True
        )
    ).all()
    
    # Collect all tags from all templates
    all_tags = set()
    for template in templates:
        if template.tags:
            for tag in template.tags:
                all_tags.add(tag)
    
    # Return sorted list with original casing preserved
    return sorted(list(all_tags))


def rename_tag(db: Session, user_id: str, old_tag: str, new_tag: str) -> bool:
    """Rename a tag across all user's templates and preserve color mapping in user settings"""
    try:
        user_uuid = uuid.UUID(user_id) if isinstance(user_id, str) else user_id
    except ValueError:
        return False
    
    # Get user to update tag color mappings in settings
    user = db.query(User).filter(User.id == user_uuid).first()
    if not user:
        return False
    
    templates = db.query(Template).filter(
        and_(
            Template.user_id == user_uuid,
            Template.is_active == True
        )
    ).all()
    
    updated_count = 0
    for template in templates:
        if template.tags:
            updated = False
            new_tags = []
            for tag in template.tags:
                # Case-insensitive comparison
                if isinstance(tag, str) and tag.lower() == old_tag.lower():
                    new_tags.append(new_tag)  # Use new tag name
                    updated = True
                else:
                    new_tags.append(tag)
            
            if updated:
                template.tags = new_tags
                updated_count += 1
    
    # Preserve tag color mapping when renaming
    if updated_count > 0:
        settings = dict(user.settings or {})
        tag_colors = settings.get('tag_colors', {})
        
        # Find and transfer color mapping from old_tag to new_tag (case-insensitive)
        old_tag_lower = old_tag.lower()
        color_to_transfer = None
        old_key_to_remove = None
        
        for key, color in tag_colors.items():
            if key.lower() == old_tag_lower:
                color_to_transfer = color
                old_key_to_remove = key
                break
        
        if color_to_transfer:
            # Remove old mapping and add new one
            tag_colors.pop(old_key_to_remove, None)
            tag_colors[new_tag] = color_to_transfer
            settings['tag_colors'] = tag_colors
            # Create a new dict to ensure SQLAlchemy detects the change
            from copy import deepcopy
            user.settings = deepcopy(settings)
    
    if updated_count > 0:
        db.commit()
    return updated_count > 0


def delete_tag(db: Session, user_id: str, tag_to_delete: str) -> bool:
    """Remove a tag from all user's templates and remove color mapping"""
    try:
        user_uuid = uuid.UUID(user_id) if isinstance(user_id, str) else user_id
    except ValueError:
        return False
    
    # Get user to remove tag color mapping from settings
    user = db.query(User).filter(User.id == user_uuid).first()
    if not user:
        return False
    
    templates = db.query(Template).filter(
        and_(
            Template.user_id == user_uuid,
            Template.is_active == True
        )
    ).all()
    
    updated_count = 0
    for template in templates:
        if template.tags:
            original_length = len(template.tags)
            # Filter out the tag (case-insensitive)
            template.tags = [
                tag for tag in template.tags 
                if not (isinstance(tag, str) and tag.lower() == tag_to_delete.lower())
            ]
            if len(template.tags) < original_length:
                updated_count += 1
    
    # Remove tag color mapping from user settings
    if user.settings:
        settings = dict(user.settings)
        tag_colors = settings.get('tag_colors', {})
        tag_to_delete_lower = tag_to_delete.lower()
        
        # Find and remove color mapping (case-insensitive)
        key_to_remove = None
        for key in tag_colors.keys():
            if key.lower() == tag_to_delete_lower:
                key_to_remove = key
                break
        
        if key_to_remove:
            tag_colors.pop(key_to_remove, None)
            settings['tag_colors'] = tag_colors
            user.settings = settings
    
    if updated_count > 0:
        db.commit()
    return updated_count > 0


def update_template(
    db: Session,
    template_id: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    tags: Optional[list] = None,
    template_config: Optional[dict] = None,
    is_active: Optional[bool] = None,
    user_id: Optional[str] = None,
) -> Optional[Template]:
    """Update a template, optionally checking ownership. Creates version snapshot after update to ensure latest version matches current state."""
    # Get existing template before any changes
    template = get_template(db, template_id, user_id=user_id)
    if not template:
        return None
    
    # Check if this is a meaningful update
    should_create_version = False
    if template.template_config or template.name:
        has_changes = (
            (name is not None and name != template.name) or
            (description is not None and description != template.description) or
            (tags is not None and tags != (template.tags or [])) or
            (template_config is not None and template_config != (template.template_config or {}))
        )
        should_create_version = has_changes
    
    # Proceed with normal update
    if name is not None:
        template.name = name
    if description is not None:
        template.description = description
    if tags is not None:
        template.tags = tags
    if template_config is not None:
        template.template_config = template_config
    if is_active is not None:
        template.is_active = is_active
    
    db.commit()
    db.refresh(template)
    
    # Create version snapshot of new state after update (so latest version matches current state)
    # This ensures get_current_version_id() can find a matching version
    if should_create_version:
        create_template_version(db, template)
    
    return template


def delete_template(db: Session, template_id: str, user_id: Optional[str] = None) -> bool:
    """Soft delete a template (set is_active=False), optionally checking ownership"""
    # Convert string UUID to UUID object if needed
    try:
        if isinstance(template_id, str):
            template_id = uuid.UUID(template_id)
    except ValueError:
        return False
    
    template = get_template(db, str(template_id), user_id=user_id)
    if not template:
        return False
    
    template.is_active = False
    db.commit()
    return True


# ============ Template Version CRUD ============

def _template_equals_version(template: Template, version: TemplateVersion) -> bool:
    """Check if template current state matches a version snapshot"""
    return (
        template.name == version.name and
        template.description == version.description and
        template.tags == version.tags and
        template.template_config == version.template_config
    )


def create_template_version(db: Session, template: Template, skip_if_unchanged: bool = False) -> Optional[TemplateVersion]:
    """Create a version snapshot of a template before update"""
    try:
        # Get all existing versions for this template
        all_versions = db.query(TemplateVersion).filter(
            TemplateVersion.template_id == template.id
        ).order_by(TemplateVersion.version_number.desc()).all()
        
        # If skip_if_unchanged is True, check if current state matches any existing version
        if skip_if_unchanged and all_versions:
            for existing_version in all_versions:
                if _template_equals_version(template, existing_version):
                    # Current state matches an existing version, skip creating duplicate
                    return existing_version
        
        # Get the maximum version number for next version
        max_version = all_versions[0] if all_versions else None
        next_version = (max_version.version_number + 1) if max_version else 1
        
        # Create version snapshot
        version = TemplateVersion(
            template_id=template.id,
            name=template.name,
            description=template.description,
            tags=template.tags,
            template_config=template.template_config,
            version_number=next_version,
        )
        
        db.add(version)
        db.commit()
        db.refresh(version)
        
        # Cleanup old versions after creating new one
        cleanup_old_versions(db, str(template.id))
        
        return version
    except Exception as e:
        db.rollback()
        print(f"Error creating template version: {e}")
        return None


def cleanup_old_versions(db: Session, template_id: str) -> None:
    """Keep only the 10 most recent versions for a template"""
    try:
        if isinstance(template_id, str):
            template_id = uuid.UUID(template_id)
    except ValueError:
        return
    
    # Get all versions ordered by created_at desc
    all_versions = db.query(TemplateVersion).filter(
        TemplateVersion.template_id == template_id
    ).order_by(TemplateVersion.created_at.desc()).all()
    
    # If more than 10, delete the oldest ones
    if len(all_versions) > 10:
        versions_to_delete = all_versions[10:]  # Keep first 10, delete the rest
        for version in versions_to_delete:
            db.delete(version)
        db.commit()


def get_template_versions(db: Session, template_id: str, user_id: Optional[str] = None) -> List[TemplateVersion]:
    """Get all versions for a template, optionally filtered by user ownership"""
    try:
        if isinstance(template_id, str):
            template_id = uuid.UUID(template_id)
    except ValueError:
        return []
    
    # Verify ownership if user_id provided
    if user_id:
        template = get_template(db, str(template_id), user_id=user_id)
        if not template:
            return []
    
    versions = db.query(TemplateVersion).filter(
        TemplateVersion.template_id == template_id
    ).order_by(TemplateVersion.created_at.desc()).limit(10).all()
    
    return versions


def get_template_version(db: Session, version_id: str, user_id: Optional[str] = None) -> Optional[TemplateVersion]:
    """Get a specific version by ID, optionally verifying ownership"""
    try:
        if isinstance(version_id, str):
            version_id = uuid.UUID(version_id)
    except ValueError:
        return None
    
    version = db.query(TemplateVersion).filter(TemplateVersion.id == version_id).first()
    
    if not version:
        return None
    
    # Verify ownership via template
    if user_id:
        template = get_template(db, str(version.template_id), user_id=user_id)
        if not template:
            return None
    
    return version


def get_current_version_id(db: Session, template: Template) -> Optional[str]:
    """Find which version (if any) matches the current template state"""
    versions = db.query(TemplateVersion).filter(
        TemplateVersion.template_id == template.id
    ).order_by(TemplateVersion.version_number.asc()).all()
    
    # If there's only 1 version (version 1), it's automatically the current version
    # since it represents the baseline state
    if len(versions) == 1:
        return str(versions[0].id)
    
    # Otherwise, find which version matches the current template state
    for version in versions:
        if _template_equals_version(template, version):
            return str(version.id)
    
    return None


def renumber_template_versions(db: Session, template_id: str) -> None:
    """Renumber all versions for a template sequentially (1, 2, 3, ...) based on creation date"""
    try:
        # Convert template_id to UUID if needed
        if isinstance(template_id, str):
            template_id = uuid.UUID(template_id)
    except ValueError:
        return
    
    try:
        # Get all remaining versions, sorted by creation date (oldest first)
        all_versions = db.query(TemplateVersion).filter(
            TemplateVersion.template_id == template_id
        ).order_by(TemplateVersion.created_at.asc()).all()
        
        # If no versions left, nothing to renumber
        if not all_versions:
            return
        
        # First, set all version numbers to temporary high values to avoid unique constraint violations
        temp_offset = 10000
        for idx, version in enumerate(all_versions):
            version.version_number = temp_offset + idx
        
        db.flush()  # Flush to database without committing
        
        # Now set them to sequential numbers starting from 1
        for idx, version in enumerate(all_versions, start=1):
            version.version_number = idx
        
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"Error renumbering template versions: {e}")
        raise


def delete_template_version(db: Session, version_id: str, user_id: str) -> bool:
    """Delete a specific template version and renumber remaining versions"""
    try:
        try:
            if isinstance(version_id, str):
                version_id = uuid.UUID(version_id)
        except ValueError:
            return False
        
        # Get the version and verify ownership via template
        version = db.query(TemplateVersion).filter(TemplateVersion.id == version_id).first()
        if not version:
            return False
        
        template = get_template(db, str(version.template_id), user_id=user_id)
        if not template:
            return False
        
        # Store template_id before deletion
        template_id_for_renumbering = version.template_id
        
        # Delete the version
        db.delete(version)
        db.commit()
        
        # Renumber remaining versions to eliminate gaps
        try:
            renumber_template_versions(db, str(template_id_for_renumbering))
        except Exception as e:
            print(f"Warning: Failed to renumber versions after deletion: {e}")
            # Don't fail the deletion if renumbering fails
        
        return True
    except Exception as e:
        db.rollback()
        print(f"Error deleting template version: {e}")
        return False


def restore_template_version(
    db: Session,
    template_id: str,
    version_id: str,
    user_id: str
) -> Optional[Template]:
    """Restore a template to a specific version"""
    # Verify ownership
    template = get_template(db, template_id, user_id=user_id)
    if not template:
        return None
    
    # Get the version to restore
    version = get_template_version(db, version_id, user_id=user_id)
    if not version:
        return None
    
    # Verify version belongs to template
    if str(version.template_id) != str(template_id):
        return None
    
    # Create version snapshot of current state BEFORE restore
    # Only create if current state differs from latest version (avoid duplicates)
    create_template_version(db, template, skip_if_unchanged=True)
    
    # Restore template to version state
    template.name = version.name
    template.description = version.description
    template.tags = version.tags
    template.template_config = version.template_config
    
    db.commit()
    db.refresh(template)
    
    return template


def increment_template_usage(db: Session, template_id: str) -> bool:
    """Increment usage count and update last_used_at for a template"""
    try:
        if isinstance(template_id, str):
            template_id = uuid.UUID(template_id)
    except ValueError:
        return False
    
    template = db.query(Template).filter(
        Template.id == template_id,
        Template.is_active == True
    ).first()
    
    if not template:
        return False
    
    template.usage_count = (template.usage_count or 0) + 1
    template.last_used_at = datetime.now(timezone.utc)
    
    db.commit()
    return True


def toggle_template_pin(db: Session, template_id: str, user_id: str) -> Optional[Template]:
    """Toggle the pinned status of a template, verifying user ownership"""
    template = get_template(db, template_id, user_id=user_id)
    if not template:
        return None
    
    template.is_pinned = not template.is_pinned
    db.commit()
    db.refresh(template)
    return template


# ============ Report CRUD ============

def create_report(
    db: Session,
    user_id: str,
    report_type: str,
    report_content: str,
    model_used: str,
    input_data: Optional[dict] = None,
    use_case: Optional[str] = None,
    template_id: Optional[str] = None,
    description: Optional[str] = None,
) -> Report:
    """Create a new report"""
    report = Report(
        user_id=uuid.UUID(user_id) if isinstance(user_id, str) else user_id,
        report_type=report_type,
        report_content=report_content,
        model_used=model_used,
        input_data=input_data,
        use_case=use_case,
        template_id=uuid.UUID(template_id) if template_id and isinstance(template_id, str) else template_id,
        description=description,
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    db.add(report)
    db.commit()
    db.refresh(report)

    # Create initial version snapshot
    try:
        create_report_version(
            db,
            report=report,
            actions_applied=None,
            notes="Initial generation"
        )
    except Exception as exc:
        print(f"Warning: failed to create initial report version for {report.id}: {exc}")

    return report


def get_report(db: Session, report_id: str, user_id: Optional[str] = None) -> Optional[Report]:
    """Get a report by ID, optionally filtered by user"""
    try:
        if isinstance(report_id, str):
            report_id = uuid.UUID(report_id)
    except ValueError:
        return None
    
    query = db.query(Report).filter(Report.id == report_id)
    
    if user_id:
        try:
            user_uuid = uuid.UUID(user_id) if isinstance(user_id, str) else user_id
            query = query.filter(Report.user_id == user_uuid)
        except ValueError:
            return None
    
    return query.first()


def get_user_reports(
    db: Session,
    user_id: str,
    skip: int = 0,
    limit: int = 100,
    report_type: Optional[str] = None,
    model_used: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    search: Optional[str] = None,
) -> List[Report]:
    """Get all reports for a user with optional filters"""
    try:
        user_uuid = uuid.UUID(user_id) if isinstance(user_id, str) else user_id
    except ValueError:
        return []
    
    query = db.query(Report).filter(Report.user_id == user_uuid)
    
    if report_type:
        query = query.filter(Report.report_type == report_type)
    
    if model_used:
        query = query.filter(Report.model_used == model_used)
    
    if start_date:
        query = query.filter(Report.created_at >= start_date)
    
    if end_date:
        query = query.filter(Report.created_at <= end_date)
    
    if search:
        # Search across multiple fields: report_type, use_case, model_used, and report_content
        search_filter = or_(
            Report.report_type.ilike(f'%{search}%'),
            Report.use_case.ilike(f'%{search}%'),
            Report.model_used.ilike(f'%{search}%'),
            Report.report_content.ilike(f'%{search}%')
        )
        query = query.filter(search_filter)
    
    return query.order_by(Report.created_at.desc()).offset(skip).limit(limit).all()


def delete_report(db: Session, report_id: str, user_id: Optional[str] = None) -> bool:
    """Delete a report, optionally checking ownership"""
    report = get_report(db, report_id, user_id=user_id)
    if not report:
        return False
    
    db.delete(report)
    db.commit()
    return True


def get_report_versions(
    db: Session,
    report_id: str,
    user_id: Optional[str] = None,
    limit: int = 50,
) -> List[ReportVersion]:
    """Return version history for a report"""
    report = get_report(db, report_id, user_id=user_id)
    if not report:
        return []
    return (
        db.query(ReportVersion)
        .filter(ReportVersion.report_id == report.id)
        .order_by(ReportVersion.version_number.desc())
        .limit(limit)
        .all()
    )


def create_report_version(
    db: Session,
    report: Report,
    actions_applied: Optional[list] = None,
    notes: Optional[str] = None,
) -> ReportVersion:
    """Persist a new version snapshot for the report"""
    # Determine next version number
    latest = (
        db.query(ReportVersion)
        .filter(ReportVersion.report_id == report.id)
        .order_by(ReportVersion.version_number.desc())
        .first()
    )
    next_version = 1
    if latest:
        next_version = latest.version_number + 1
    
    # Mark all existing versions as not current
    db.query(ReportVersion).filter(
        ReportVersion.report_id == report.id
    ).update({"is_current": False})

    version = ReportVersion(
        report_id=report.id,
        version_number=next_version,
        report_content=report.report_content,
        actions_applied=actions_applied,
        notes=notes,
        model_used=report.model_used,
        is_current=True,
    )
    db.add(version)
    db.commit()
    db.refresh(version)
    return version


def get_report_version(
    db: Session,
    report_id: str,
    version_id: str,
    user_id: Optional[str] = None,
) -> Optional[ReportVersion]:
    """Fetch a specific report version if the report belongs to the user."""
    report = get_report(db, report_id, user_id=user_id)
    if not report:
        return None
    try:
        version_uuid = uuid.UUID(version_id) if isinstance(version_id, str) else version_id
    except ValueError:
        return None
    return (
        db.query(ReportVersion)
            .filter(
                ReportVersion.report_id == report.id,
                ReportVersion.id == version_uuid
            )
            .first()
    )


def set_current_report_version(
    db: Session,
    report_id: str,
    version_id: str,
    user_id: Optional[str] = None,
) -> bool:
    """Set a specific version as the current version without creating a new snapshot."""
    report = get_report(db, report_id, user_id=user_id)
    if not report:
        return False
    
    try:
        version_uuid = uuid.UUID(version_id) if isinstance(version_id, str) else version_id
    except ValueError:
        return False
    
    # First, unmark all versions as current
    db.query(ReportVersion).filter(
        ReportVersion.report_id == report.id
    ).update({"is_current": False})
    
    # Then mark the specified version as current
    result = db.query(ReportVersion).filter(
        ReportVersion.report_id == report.id,
        ReportVersion.id == version_uuid
    ).update({"is_current": True})
    
    db.commit()
    return result > 0


# ============ Validation Status CRUD ============

def update_validation_status(
    db: Session,
    report_id: str,
    status: str,
    violations_count: Optional[int] = None,
    error: Optional[str] = None
) -> bool:
    """
    Update validation status for a report.
    
    Args:
        db: Database session
        report_id: Report UUID string
        status: One of "pending", "passed", "fixed", "error"
        violations_count: Number of violations found (if any)
        error: Error message if status is "error"
    
    Returns:
        True if update successful, False if report not found
    """
    try:
        report_uuid = uuid.UUID(report_id) if isinstance(report_id, str) else report_id
    except ValueError:
        return False
    
    report = db.query(Report).filter(Report.id == report_uuid).first()
    if not report:
        return False
    
    from datetime import datetime, timezone
    
    # Get current status or initialize
    current_status = report.validation_status or {}
    
    # Update status
    new_status = {
        "status": status,
        "violations_count": violations_count if violations_count is not None else current_status.get("violations_count", 0),
        "started_at": current_status.get("started_at") or datetime.now(timezone.utc).isoformat(),
        "completed_at": datetime.now(timezone.utc).isoformat() if status != "pending" else None,
        "error": error if error else current_status.get("error")
    }
    
    report.validation_status = new_status
    db.commit()
    db.refresh(report)
    return True


def get_validation_status(
    db: Session,
    report_id: str,
    user_id: Optional[str] = None
) -> Optional[dict]:
    """
    Get validation status for a report.
    
    Args:
        db: Database session
        report_id: Report UUID string
        user_id: Optional user ID to verify ownership
    
    Returns:
        Validation status dict or None if report not found
    """
    report = get_report(db, report_id, user_id=user_id)
    if not report:
        return None
    
    return report.validation_status


# ============ Writing Style Preset CRUD ============

def create_writing_style_preset(
    db: Session,
    user_id: uuid.UUID,
    name: str,
    settings: dict,
    section_type: str = 'findings',
    icon: str = '⭐',
    description: Optional[str] = None
) -> WritingStylePreset:
    """Create a new writing style preset"""
    preset = WritingStylePreset(
        user_id=user_id,
        name=name,
        settings=settings,
        section_type=section_type,
        icon=icon,
        description=description
    )
    db.add(preset)
    db.commit()
    db.refresh(preset)
    return preset


def get_user_writing_style_presets(
    db: Session,
    user_id: uuid.UUID,
    section_type: Optional[str] = None
) -> List[WritingStylePreset]:
    """Get all writing style presets for a user, optionally filtered by section type"""
    query = db.query(WritingStylePreset).filter(WritingStylePreset.user_id == user_id)
    if section_type:
        query = query.filter(WritingStylePreset.section_type == section_type)
    return query.order_by(WritingStylePreset.created_at.desc()).all()


def get_writing_style_preset(
    db: Session,
    preset_id: uuid.UUID,
    user_id: uuid.UUID
) -> Optional[WritingStylePreset]:
    """Get a specific writing style preset by ID, ensuring it belongs to the user"""
    return db.query(WritingStylePreset).filter(
        WritingStylePreset.id == preset_id,
        WritingStylePreset.user_id == user_id
    ).first()


def update_writing_style_preset(
    db: Session,
    preset_id: uuid.UUID,
    user_id: uuid.UUID,
    **updates
) -> Optional[WritingStylePreset]:
    """Update a writing style preset"""
    preset = get_writing_style_preset(db, preset_id, user_id)
    if not preset:
        return None
    
    for key, value in updates.items():
        if hasattr(preset, key):
            setattr(preset, key, value)
    
    preset.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(preset)
    return preset


def delete_writing_style_preset(
    db: Session,
    preset_id: uuid.UUID,
    user_id: uuid.UUID
) -> bool:
    """Delete a writing style preset"""
    preset = get_writing_style_preset(db, preset_id, user_id)
    if preset:
        db.delete(preset)
        db.commit()
        return True
    return False


def increment_preset_usage(
    db: Session,
    preset_id: uuid.UUID
) -> bool:
    """Increment usage count and update last_used_at timestamp"""
    preset = db.query(WritingStylePreset).filter(WritingStylePreset.id == preset_id).first()
    if preset:
        preset.usage_count += 1
        preset.last_used_at = datetime.now(timezone.utc)
        db.commit()
        return True
    return False

