import hashlib
import hmac

from cryptography.fernet import Fernet
from django.conf import settings


def _fernet() -> Fernet:
    return Fernet(settings.FIELD_ENCRYPTION_KEY.encode())


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()


def keyed_hash(value: str) -> str:
    """Deterministic HMAC so equal values can be matched without storing them."""
    return hmac.new(settings.HASH_PEPPER.encode(), value.encode(), hashlib.sha256).hexdigest()
