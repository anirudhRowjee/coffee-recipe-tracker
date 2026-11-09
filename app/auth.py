"""
Passwords and session tokens, using only the standard library.

Passwords are stored as "scrypt$n$r$p$salt$hash". Session tokens are random;
the browser holds the token and the database only its SHA-256, so a copy of the
database (a backup, say) can't be used to sign in.
"""
import hashlib
import hmac
import secrets

MIN_PASSWORD_LENGTH = 8

_N, _R, _P = 2 ** 14, 8, 1
_KEY_BYTES = 32


def _derive(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, dklen=_KEY_BYTES)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${_derive(password, salt, _N, _R, _P).hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, expected = stored.split("$")
        if scheme != "scrypt":
            return False
        actual = _derive(password, bytes.fromhex(salt), int(n), int(r), int(p))
        return hmac.compare_digest(actual, bytes.fromhex(expected))
    except (ValueError, TypeError):
        return False


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def session_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def temporary_password() -> str:
    """Easy to read out or paste into a message; the holder must replace it at first sign-in."""
    return secrets.token_urlsafe(9)
