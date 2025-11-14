"""Encryption utilities for storing API keys securely"""

import os
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from base64 import urlsafe_b64encode, urlsafe_b64decode
from typing import Optional

# Use SECRET_KEY from auth or generate a stable key from environment
# For production, set ENCRYPTION_KEY in environment
# For development, derive from SECRET_KEY
def _get_encryption_key() -> bytes:
    """Get or generate encryption key"""
    encryption_key = os.getenv("ENCRYPTION_KEY")
    if encryption_key:
        # If ENCRYPTION_KEY is set, use it directly (should be base64-encoded Fernet key)
        try:
            return encryption_key.encode()
        except:
            # If not base64, generate key from it
            pass
    
    # Derive key from SECRET_KEY (or generate a stable key)
    secret_key = os.getenv("SECRET_KEY", "your-secret-key-change-in-production")
    
    # Use PBKDF2 to derive a stable key from SECRET_KEY
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b'rapid_reports_ai_salt',  # In production, use a unique salt per deployment
        iterations=100000,
    )
    key = urlsafe_b64encode(kdf.derive(secret_key.encode()))
    return key


def encrypt_api_key(plain_key: str) -> str:
    """Encrypt an API key"""
    if not plain_key or not plain_key.strip():
        return ""
    
    try:
        f = Fernet(_get_encryption_key())
        encrypted = f.encrypt(plain_key.encode())
        return urlsafe_b64encode(encrypted).decode()
    except Exception as e:
        print(f"Error encrypting API key: {e}")
        return ""


def decrypt_api_key(encrypted_key: str) -> Optional[str]:
    """Decrypt an API key"""
    if not encrypted_key or not encrypted_key.strip():
        return None
    
    try:
        f = Fernet(_get_encryption_key())
        encrypted_bytes = urlsafe_b64decode(encrypted_key.encode())
        decrypted = f.decrypt(encrypted_bytes)
        return decrypted.decode()
    except Exception as e:
        print(f"Error decrypting API key: {e}")
        return None


def get_system_api_key(key_type: str, fallback_env_var: str) -> Optional[str]:
    """
    Get API key from system environment variables only.
    Used for LLM API keys (Anthropic, Groq) which are now system-wide only.
    
    Args:
        key_type: Type of key ('anthropic', 'groq') - for logging/debugging only
        fallback_env_var: Environment variable name to read from (e.g., 'ANTHROPIC_API_KEY', 'GROQ_API_KEY')
    
    Returns:
        API key from environment or None
    """
    env_key = os.getenv(fallback_env_var)
    if env_key:
        return env_key
    
    return None


def get_user_api_key(user_settings: dict, key_type: str, fallback_env_var: str = None) -> Optional[str]:
    """
    Get API key from user settings with fallback to environment variable.
    Now only used for Deepgram API keys which remain user-configurable.
    
    Args:
        user_settings: User's settings dictionary
        key_type: Type of key ('deepgram')
        fallback_env_var: Environment variable name to fallback to (optional)
    
    Returns:
        Decrypted API key or None
    """
    if not user_settings:
        user_settings = {}
    
    # Try user's encrypted key first
    encrypted_key = user_settings.get(f'{key_type}_api_key')
    if encrypted_key:
        decrypted = decrypt_api_key(encrypted_key)
        if decrypted:
            return decrypted
    
    # Fallback to environment variable if provided
    if fallback_env_var:
        env_key = os.getenv(fallback_env_var)
        if env_key:
            return env_key
    
    return None

