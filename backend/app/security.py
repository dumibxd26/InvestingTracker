import secrets
from hashlib import sha256

from pwdlib import PasswordHash

password_hasher = PasswordHash.recommended()
_dummy_password_hash = password_hasher.hash(secrets.token_urlsafe(32))


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, stored_hash: str | None) -> bool:
    encoded_hash = stored_hash or _dummy_password_hash
    matches = password_hasher.verify(password, encoded_hash)
    return stored_hash is not None and matches


def create_access_token() -> str:
    return secrets.token_urlsafe(32)


def digest_access_token(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()
