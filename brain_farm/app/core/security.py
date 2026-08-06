import base64
import hashlib
from cryptography.fernet import Fernet
from brain_farm.app.core.config import settings

def get_fernet_key(raw_key: str) -> bytes:
    """Derive a valid 32-byte Fernet key from any string key using SHA-256."""
    sha256_hash = hashlib.sha256(raw_key.encode()).digest()
    return base64.urlsafe_b64encode(sha256_hash)

# Initialize Fernet adapter
_key = get_fernet_key(settings.ENCRYPTION_KEY)
_cipher = Fernet(_key)

def encrypt_data(data: str) -> str:
    """Encrypts clear text using the cipher suite."""
    if not data:
        return ""
    encrypted_bytes = _cipher.encrypt(data.encode())
    return encrypted_bytes.decode()

def decrypt_data(token: str) -> str:
    """Decrypts cipher text back into clear text."""
    if not token:
        return ""
    try:
        decrypted_bytes = _cipher.decrypt(token.encode())
        return decrypted_bytes.decode()
    except Exception:
        # Fallback in case of corruption or key mismatches
        return ""
