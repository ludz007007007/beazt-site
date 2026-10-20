"""Shared password policy (VAL-AUTH-002/004, VAL-ACC-005).

One rule everywhere an account password is set or changed: signup, the
forgot-password reset flow, and the profile page.
"""

MIN_PASSWORD_LENGTH = 8


def password_error(password):
    """Return the policy error message for ``password``, or ``None`` if valid.

    Kept as a single source so client hints, route validation and error copy
    can never drift apart.
    """
    if not password or len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    return None
