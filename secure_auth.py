import hashlib


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def verify_password_hash(input_password: str, stored_hash: str) -> bool:
    return hash_password(input_password) == stored_hash