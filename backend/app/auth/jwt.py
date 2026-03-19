"""
Supabase JWT verification for FastAPI.

Validates the JWT issued by Supabase Auth on every incoming request.
Extracts the user_id (sub claim) for use in authorization checks.

Uses PyJWT with the JWKS endpoint to verify tokens signed with the
project's asymmetric signing key (ES256 / P-256). The public key is
fetched from Supabase's well-known JWKS endpoint and cached in memory
by PyJWKClient (default: 5 minutes). No shared secret is stored in
the backend — only the public key is used for verification.

Migration context:
  Supabase launched asymmetric JWT signing keys (July 2025).
  See: https://github.com/orgs/supabase/discussions/29289
  See: https://supabase.com/docs/guides/auth/signing-keys

  Previously this file used HS256 + SUPABASE_JWT_SECRET (legacy).
  Now we use the JWKS endpoint, which:
    - Eliminates the need to store a shared secret
    - Supports zero-downtime key rotation
    - Auto-discovers the current public key
"""

import ssl

import certifi
import jwt
from jwt import PyJWKClient
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings

# HTTPBearer extracts the token from "Authorization: Bearer <token>" and
# returns 403 automatically if the header is missing or malformed.
_bearer_scheme = HTTPBearer()

# Build an SSL context that trusts the certifi CA bundle.
# macOS Python installations often lack system CA certs, which causes
# urllib (used internally by PyJWKClient) to fail SSL verification.
_ssl_context = ssl.create_default_context(cafile=certifi.where())

# PyJWKClient fetches and caches the public key(s) from the JWKS endpoint.
# The cache lifetime (lifespan) controls how often we re-fetch.
# Supabase's edge caches the JWKS endpoint for ~10 minutes, so 300s is safe.
_jwks_url = f"{settings.supabase_url}/auth/v1/.well-known/jwks.json"
_jwks_client = PyJWKClient(
    _jwks_url,
    cache_keys=True,
    lifespan=300,  # re-fetch public keys every 5 minutes
    ssl_context=_ssl_context,
)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> str:
    """
    FastAPI dependency that authenticates the caller.

    Returns the Supabase user UUID (str) on success.
    Raises HTTP 401 if the token is expired, invalid, or missing
    the required claims.

    Verification flow:
      1. Extract the token from the Authorization header
      2. Use PyJWKClient to look up the signing key from the JWKS endpoint
         (matched by the 'kid' header in the JWT)
      3. Decode and verify the token using the public key
      4. Validate audience = "authenticated"
      5. Extract and return the 'sub' claim (user UUID)
    """
    token = credentials.credentials

    try:
        # Get the signing key that matches this token's 'kid' header
        signing_key = _jwks_client.get_signing_key_from_jwt(token)
    except jwt.exceptions.PyJWKClientConnectionError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to fetch signing keys from Supabase",
        )
    except (jwt.exceptions.PyJWKClientError, jwt.InvalidTokenError):
        # PyJWKClientError: no matching 'kid' in the JWKS
        # InvalidTokenError (includes DecodeError): malformed JWT
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or unverifiable token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256", "RS256"],
            audience="authenticated",
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidAudienceError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token audience",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id: str | None = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing sub claim",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user_id
