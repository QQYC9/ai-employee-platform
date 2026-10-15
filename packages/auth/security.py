from __future__ import annotations

import hashlib
import hmac
import secrets


DEFAULT_ITERATIONS = 200_000
ALGORITHM = "sha256"


def hash_password(password: str, iterations: int = DEFAULT_ITERATIONS) -> str:
    """
    Hash a plaintext password using PBKDF2-HMAC-SHA256 with a cryptographically
    secure 16-byte random salt and recommended iteration count.

    Format: pbkdf2:sha256:<iterations>$<salt_hex>$<hash_hex>
    """
    if not isinstance(password, str) or not password:
        raise ValueError("Password must be a non-empty string")

    salt = secrets.token_bytes(16)
    key = hashlib.pbkdf2_hmac(
        hash_name=ALGORITHM,
        password=password.encode("utf-8"),
        salt=salt,
        iterations=iterations,
    )
    return f"pbkdf2:{ALGORITHM}:{iterations}${salt.hex()}${key.hex()}"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plaintext password against a stored PBKDF2 hash using
    constant-time comparison to prevent timing attacks.
    """
    if not plain_password or not hashed_password:
        return False

    try:
        parts = hashed_password.split("$")
        if len(parts) != 3:
            return False

        header, salt_hex, expected_hash_hex = parts
        prefix, algo, iters_str = header.split(":")

        if prefix != "pbkdf2" or algo != ALGORITHM:
            return False

        iterations = int(iters_str)
        salt = bytes.fromhex(salt_hex)
        expected_hash = bytes.fromhex(expected_hash_hex)

        computed_key = hashlib.pbkdf2_hmac(
            hash_name=algo,
            password=plain_password.encode("utf-8"),
            salt=salt,
            iterations=iterations,
        )

        return hmac.compare_digest(computed_key, expected_hash)
    except Exception:
        return False
