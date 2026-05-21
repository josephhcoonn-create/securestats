import bcrypt


def hash_password(plain_password: str) -> str:
    """Return a bcrypt hash of the given password."""
    return bcrypt.hashpw(plain_password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Return True if plain_password matches the stored hash."""
    return bcrypt.checkpw(plain_password.encode(), hashed_password.encode())
