"""Optional bearer access control for a privately hosted single-league app."""
import hmac
import os


def authorized(authorization):
    expected = os.getenv('NBA_API_TOKEN', '')
    if not expected:
        return True
    supplied = authorization.removeprefix('Bearer ') if authorization.startswith('Bearer ') else ''
    return hmac.compare_digest(supplied.encode(), expected.encode())
