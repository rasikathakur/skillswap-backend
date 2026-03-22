from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr
from supabase import create_client, Client
import os
from dotenv import load_dotenv
from argon2 import PasswordHasher
from datetime import datetime, timezone, timedelta
import base64
import hashlib
import hmac
import json
import smtplib
from email.message import EmailMessage
from urllib.parse import quote
from urllib import request as urllib_request
from urllib import error as urllib_error

load_dotenv()

# Password hashing with Argon2 (no 72-byte limit)
pwd_hasher = PasswordHasher()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("SUPABASE_URL and SUPABASE_KEY environment variables are required")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


def _is_service_role_key(jwt_key: str) -> bool:
    """Best-effort JWT role check; returns False for malformed keys."""
    try:
        parts = jwt_key.split(".")
        if len(parts) != 3:
            return False
        padding = "=" * (-len(parts[1]) % 4)
        payload_bytes = base64.urlsafe_b64decode(parts[1] + padding)
        payload = json.loads(payload_bytes.decode("utf-8"))
        return payload.get("role") == "service_role"
    except Exception:
        return False


SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
SUPABASE_ADMIN_KEY = SUPABASE_SERVICE_ROLE_KEY

# If SUPABASE_KEY is already service role, reuse it for admin operations.
if not SUPABASE_ADMIN_KEY and _is_service_role_key(SUPABASE_KEY):
    SUPABASE_ADMIN_KEY = SUPABASE_KEY

supabase_admin: Client | None = (
    create_client(SUPABASE_URL, SUPABASE_ADMIN_KEY) if SUPABASE_ADMIN_KEY else None
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

RESET_TOKEN_TTL_SECONDS = 10 * 60
RESET_TOKEN_SECRET = os.getenv("RESET_TOKEN_SECRET") or SUPABASE_KEY


class SignUpRequest(BaseModel):
    email: str
    password: str
    name: str


class SignInRequest(BaseModel):
    email: str
    password: str


class AuthResponse(BaseModel):
    access_token: str
    refresh_token: str | None = None
    user_id: str
    email: str
    message: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


class MessageResponse(BaseModel):
    message: str


def _base64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _build_reset_token(user_id: str, email: str) -> str:
    payload = {
        "uid": user_id,
        "email": email,
        "exp": int((datetime.now(timezone.utc) + timedelta(seconds=RESET_TOKEN_TTL_SECONDS)).timestamp())
    }
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    signature = hmac.new(RESET_TOKEN_SECRET.encode("utf-8"), payload_bytes, hashlib.sha256).digest()
    return f"{_base64url_encode(payload_bytes)}.{_base64url_encode(signature)}"


def _verify_reset_token(token: str) -> dict:
    try:
        payload_part, signature_part = token.split(".", 1)
        payload_bytes = _base64url_decode(payload_part)
        provided_signature = _base64url_decode(signature_part)
    except Exception as exc:
        raise ValueError("Invalid reset token format") from exc

    expected_signature = hmac.new(RESET_TOKEN_SECRET.encode("utf-8"), payload_bytes, hashlib.sha256).digest()
    if not hmac.compare_digest(provided_signature, expected_signature):
        raise ValueError("Invalid reset token signature")

    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except Exception as exc:
        raise ValueError("Invalid reset token payload") from exc

    exp = payload.get("exp")
    if not isinstance(exp, int) or exp < int(datetime.now(timezone.utc).timestamp()):
        raise ValueError("Reset token has expired")

    if not payload.get("uid") or not payload.get("email"):
        raise ValueError("Reset token is missing required fields")

    return payload


def _send_reset_email(to_email: str, reset_link: str):
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_username = os.getenv("SMTP_USERNAME")
    smtp_password = os.getenv("SMTP_PASSWORD")
    smtp_from_email = os.getenv("SMTP_FROM_EMAIL")
    smtp_from_name = os.getenv("SMTP_FROM_NAME", "Peer-to-Peer Learning")
    smtp_use_ssl = os.getenv("SMTP_USE_SSL", "false").lower() == "true"
    smtp_use_starttls = os.getenv("SMTP_USE_STARTTLS", "true").lower() == "true"

    if not smtp_host or not smtp_from_email:
        raise ValueError("SMTP_HOST and SMTP_FROM_EMAIL are required")

    message = EmailMessage()
    message["Subject"] = "Reset your password"
    message["From"] = f"{smtp_from_name} <{smtp_from_email}>"
    message["To"] = to_email
    message.set_content(
        "We received a password reset request for your account.\n\n"
        f"Use the link below (valid for 10 minutes):\n{reset_link}\n\n"
        "If you did not request this, you can safely ignore this email."
    )
    message.add_alternative(
        f"""
        <html>
          <body>
            <p>We received a password reset request for your account.</p>
            <p>
              <a href=\"{reset_link}\">Click here to reset your password</a><br/>
              This link is valid for 10 minutes.
            </p>
            <p>If you did not request this, you can safely ignore this email.</p>
          </body>
        </html>
        """,
        subtype="html"
    )

    if smtp_use_ssl:
        with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
            if smtp_username and smtp_password:
                server.login(smtp_username, smtp_password)
            server.send_message(message)
    else:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            if smtp_use_starttls:
                server.starttls()
            if smtp_username and smtp_password:
                server.login(smtp_username, smtp_password)
            server.send_message(message)


def _update_auth_password_with_service_key(user_id: str, new_password: str):
    if not SUPABASE_ADMIN_KEY:
        raise ValueError("SUPABASE_SERVICE_ROLE_KEY is missing")

    # Prevent common misconfiguration: publishable or anon keys cannot access admin endpoints.
    if SUPABASE_ADMIN_KEY.startswith("sb_publishable_"):
        raise ValueError("SUPABASE_SERVICE_ROLE_KEY is invalid: received a publishable key")

    if SUPABASE_ADMIN_KEY.count(".") == 2 and not _is_service_role_key(SUPABASE_ADMIN_KEY):
        raise ValueError("SUPABASE_SERVICE_ROLE_KEY is invalid: JWT role is not service_role")

    endpoint = f"{SUPABASE_URL}/auth/v1/admin/users/{user_id}"
    body = json.dumps({"password": new_password}).encode("utf-8")
    req = urllib_request.Request(
        endpoint,
        data=body,
        method="PUT",
        headers={
            "apikey": SUPABASE_ADMIN_KEY,
            "Authorization": f"Bearer {SUPABASE_ADMIN_KEY}",
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib_request.urlopen(req, timeout=15) as response:
            # Any 2xx means success.
            _ = response.read()
    except urllib_error.HTTPError as exc:
        try:
            raw = exc.read().decode("utf-8")
            parsed = json.loads(raw) if raw else {}
            message = parsed.get("msg") or parsed.get("message") or raw
        except Exception:
            message = f"HTTP {exc.code}"
        raise ValueError(f"Supabase admin password update failed: {message}") from exc
    except Exception as exc:
        raise ValueError(f"Supabase admin password update failed: {str(exc)}") from exc


@router.post("/signup", response_model=AuthResponse)
async def signup(request: SignUpRequest):
    """
    Sign up a new user with email and password.
    Creates entry in Supabase auth and custom users table.
    """
    try:
        # Truncate password to 72 bytes (bcrypt limit) before any operations
        truncated_password = request.password[:72]
        
        # Create user with email and password in Supabase auth
        # Use the correct Supabase v2 API syntax
        res = supabase.auth.sign_up({
            "email": request.email,
            "password": truncated_password
        })
        
        if res.user is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Sign up failed. Please check your email and password."
            )
        
        # Hash password for custom users table using Argon2 (no byte limit)
        password_hash = pwd_hasher.hash(request.password)
        
        # 1. Insert/Upsert into custom users table
        try:
            user_data = {
                'id': res.user.id,
                'email': request.email,
                'password_hash': password_hash,
                'created_at': datetime.now(timezone.utc).isoformat()
            }
            # Use upsert to be safe
            supabase.table('users').upsert(user_data).execute()
        except Exception as db_error:
            print(f"Error inserting into users table: {str(db_error)}")
            # If we can't create the user record, we shouldn't proceed
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to create user record: {str(db_error)}"
            )
            
        # 2. Insert initial record into myprofile table
        try:
            profile_data = {
                'user_id': res.user.id,
                'name': request.name,
                'email': request.email,
                'created_at': datetime.now(timezone.utc).isoformat(),
                'updated_at': datetime.now(timezone.utc).isoformat()
            }
            supabase.table('myprofile').insert(profile_data).execute()
        except Exception as db_error:
            print(f"Error inserting into myprofile table: {str(db_error)}")
            # This is critical because profile is needed for login check
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to create profile record: {str(db_error)}"
            )
        
        return AuthResponse(
            access_token=res.session.access_token if res.session else "",
            refresh_token=res.session.refresh_token if res.session else None,
            user_id=res.user.id,
            email=res.user.email,
            message="Sign up successful. Please check your email to confirm your account."
        )
    
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Sign up failed: {str(e)}"
        )


@router.post("/signin", response_model=AuthResponse)
async def signin(request: SignInRequest):
    """
    Sign in an existing user with email and password.
    Returns access token and updates last_sign_in_at timestamp.
    """
    try:
        # Authenticate user using the correct Supabase v2 API syntax
        res = supabase.auth.sign_in_with_password({
            "email": request.email,
            "password": request.password
        })
        
        if res.session is None or res.user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password"
            )
        
        # Update last_sign_in_at in custom users table
        try:
            supabase.table('users').update({
                'last_sign_in_at': datetime.now(timezone.utc).isoformat()
            }).eq('id', res.user.id).execute()
        except Exception as db_error:
            # If update fails, log but don't fail signin
            print(f"Warning: Failed to update last_sign_in_at: {str(db_error)}")
        
        return AuthResponse(
            access_token=res.session.access_token,
            refresh_token=res.session.refresh_token,
            user_id=res.user.id,
            email=res.user.email,
            message="Sign in successful"
        )
    
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Sign in failed: {str(e)}"
        )


@router.post("/logout")
async def logout():
    """
    Logout the current user.
    Client should remove the access token after this call.
    """
    return {"message": "Logout successful. Please remove your access token on the client side."}


class RefreshRequest(BaseModel):
    refresh_token: str


@router.post("/refresh", response_model=AuthResponse)
async def refresh_token(request: RefreshRequest):
    """
    Refresh the access token using a refresh token.
    """
    try:
        res = supabase.auth.refresh_session(request.refresh_token)
        
        if res.session is None or res.user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired refresh token"
            )
            
        return AuthResponse(
            access_token=res.session.access_token,
            refresh_token=res.session.refresh_token,
            user_id=res.user.id,
            email=res.user.email,
            message="Token refreshed successfully"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Refresh failed: {str(e)}"
        )


@router.post("/request-password-reset", response_model=MessageResponse)
async def request_password_reset(request: ForgotPasswordRequest):
    """
    Sends a password reset email if the account exists.
    Always returns a generic success message to avoid email enumeration.
    """
    generic_message = "If the email exists, a password reset link has been sent."

    try:
        res = supabase.table("users").select("id,email").eq("email", request.email).limit(1).execute()
        if not res.data:
            return MessageResponse(message=generic_message)

        user = res.data[0]
        reset_token = _build_reset_token(user["id"], user["email"])

        reset_password_url = os.getenv("RESET_PASSWORD_URL", "http://localhost:5173/reset-password")
        reset_link = f"{reset_password_url}?token={quote(reset_token, safe='')}"
        _send_reset_email(user["email"], reset_link)

        return MessageResponse(message=generic_message)
    except Exception as e:
        print(f"Password reset email failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process password reset request"
        )


@router.post("/reset-password", response_model=MessageResponse)
async def reset_password(request: ResetPasswordRequest):
    """
    Resets password using a signed token that expires in 10 minutes.
    """
    try:
        if len(request.new_password) < 8:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="New password must be at least 8 characters long"
            )

        token_payload = _verify_reset_token(request.token)
        user_id = token_payload["uid"]
        token_email = token_payload["email"]

        user_res = supabase.table("users").select("id,email").eq("id", user_id).eq("email", token_email).limit(1).execute()
        if not user_res.data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired reset token"
            )

        if supabase_admin is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Password reset is not configured: set SUPABASE_SERVICE_ROLE_KEY in backend .env"
            )

        # Supabase auth update follows bcrypt backend limits.
        truncated_password = request.new_password[:72]
        _update_auth_password_with_service_key(user_id, truncated_password)

        password_hash = pwd_hasher.hash(request.new_password)
        supabase.table("users").update({
            "password_hash": password_hash
        }).eq("id", user_id).execute()

        return MessageResponse(message="Password reset successful")
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Password reset failed: {str(e)}"
        )
