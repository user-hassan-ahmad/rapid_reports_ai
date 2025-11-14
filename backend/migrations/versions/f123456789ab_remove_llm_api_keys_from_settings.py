"""remove_llm_api_keys_from_settings

Revision ID: f123456789ab
Revises: e21c4d8be0f2
Create Date: 2025-01-15 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision: str = 'f123456789ab'
down_revision: Union[str, Sequence[str], None] = 'e21c4d8be0f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Remove LLM API keys from user settings JSON.
    
    Removes: anthropic_api_key, google_api_key, groq_api_key
    Keeps: default_model, auto_save, deepgram_api_key, tag_colors
    """
    import json
    from sqlalchemy import select, update
    from sqlalchemy.orm import Session
    
    connection = op.get_bind()
    session = Session(bind=connection)
    
    # Get all users with settings
    result = connection.execute(text("SELECT id, settings FROM users WHERE settings IS NOT NULL"))
    
    for user_id, settings_json in result:
        if settings_json:
            try:
                # Parse JSON
                settings = json.loads(settings_json) if isinstance(settings_json, str) else settings_json
                
                # Remove LLM API keys
                keys_to_remove = ['anthropic_api_key', 'google_api_key', 'groq_api_key']
                for key in keys_to_remove:
                    settings.pop(key, None)
                
                # Update with cleaned settings
                connection.execute(
                    text("UPDATE users SET settings = :settings WHERE id = :user_id"),
                    {"settings": json.dumps(settings), "user_id": user_id}
                )
            except Exception as e:
                print(f"Error processing user {user_id}: {e}")
                continue
    
    session.commit()


def downgrade() -> None:
    """Downgrade is a no-op as we cannot restore deleted API keys."""
    pass

