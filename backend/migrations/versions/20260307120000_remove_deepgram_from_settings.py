"""remove_deepgram_from_settings

Revision ID: 20260307120000
Revises: 20260228120000
Create Date: 2026-03-07 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision: str = '20260307120000'
down_revision: Union[str, Sequence[str], None] = '20260228120000'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Remove deepgram_api_key from user settings JSON.
    
    Deepgram is now central via DEEPGRAM_API_KEY environment variable only.
    """
    import json

    connection = op.get_bind()
    result = connection.execute(text("SELECT id, settings FROM users WHERE settings IS NOT NULL"))

    for user_id, settings_json in result:
        if settings_json:
            try:
                settings = json.loads(settings_json) if isinstance(settings_json, str) else settings_json
                settings.pop('deepgram_api_key', None)
                connection.execute(
                    text("UPDATE users SET settings = :settings WHERE id = :user_id"),
                    {"settings": json.dumps(settings), "user_id": user_id}
                )
            except Exception as e:
                print(f"Error processing user {user_id}: {e}")
                continue


def downgrade() -> None:
    """Downgrade is a no-op as we cannot restore deleted API keys."""
    pass
