"""Auth domain errors, mapped to HTTP responses by ``app.main``."""

from __future__ import annotations


class AuthError(Exception):
    status_code = 400
    code = "auth_error"

    def __init__(self, message: str = "Authentication error") -> None:
        super().__init__(message)
        self.message = message


class InvalidCredentials(AuthError):
    status_code = 401
    code = "invalid_credentials"

    def __init__(self, message: str = "Invalid email or password.") -> None:
        super().__init__(message)


class AccountLocked(AuthError):
    status_code = 423
    code = "account_locked"

    def __init__(self, message: str = "Too many attempts. Try again later.") -> None:
        super().__init__(message)


class EmailNotVerified(AuthError):
    status_code = 403
    code = "email_not_verified"

    def __init__(self, message: str = "Verify your email address to continue.") -> None:
        super().__init__(message)


class MfaRequired(AuthError):
    status_code = 401
    code = "mfa_required"

    def __init__(self, mfa_token: str) -> None:
        super().__init__("A second factor is required.")
        self.mfa_token = mfa_token


class TokenInvalid(AuthError):
    status_code = 401
    code = "token_invalid"

    def __init__(self, message: str = "This link or token is invalid or has expired.") -> None:
        super().__init__(message)


class PolicyViolation(AuthError):
    status_code = 422
    code = "policy_violation"
