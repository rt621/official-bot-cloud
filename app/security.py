"""密码哈希、JWT、AppSecret 加密。"""

import base64
import datetime as dt
import secrets

import bcrypt
import jwt
from cryptography.fernet import Fernet, InvalidToken

from app.config import BASE_DIR, settings


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def create_token(user_id: int, is_admin: bool, days: int = 7) -> str:
    payload = {
        "sub": str(user_id),
        "adm": is_admin,
        "exp": dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=days),
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


def _load_master_key() -> bytes:
    if settings.master_key:
        return base64.urlsafe_b64encode(settings.master_key.encode().ljust(32)[:32])
    key_file = BASE_DIR / "data" / ".master_key"
    if key_file.exists():
        return key_file.read_bytes()
    key = Fernet.generate_key()
    key_file.write_bytes(key)
    return key


_fernet = Fernet(_load_master_key())


def encrypt_secret(plain: str) -> str:
    return _fernet.encrypt(plain.encode("utf-8")).decode("utf-8")


def decrypt_secret(token: str) -> str:
    try:
        return _fernet.decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        return ""


def mask_secret(plain: str) -> str:
    if len(plain) <= 6:
        return "******"
    return plain[:3] + "******" + plain[-3:]


def gen_api_key() -> str:
    return secrets.token_urlsafe(24)
