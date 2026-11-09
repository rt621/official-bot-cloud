"""Email verification, SMTP delivery and Cloudflare Turnstile validation."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import smtplib
import ssl
from email.message import EmailMessage

import httpx
from fastapi import HTTPException

from app.config import settings
from app.security import decrypt_secret, encrypt_secret


async def get_registration_security(db) -> dict:
    from app.sysconf import get_setting

    keys = (
        "mail_host", "mail_port", "mail_user", "mail_password_enc", "mail_sender",
        "mail_starttls", "turnstile_enabled", "turnstile_site_key", "turnstile_secret_enc",
        "epay_enabled", "epay_gateway", "epay_pid", "epay_secret_enc", "epay_notify_url",
        "epay_return_url",
    )
    raw = {key: await get_setting(db, f"registration.{key}") for key in keys}
    raw["mail_password"] = decrypt_secret(raw.pop("mail_password_enc")) if raw.get("mail_password_enc") else ""
    raw["turnstile_secret"] = decrypt_secret(raw.pop("turnstile_secret_enc")) if raw.get("turnstile_secret_enc") else ""
    raw["epay_secret"] = decrypt_secret(raw.pop("epay_secret_enc")) if raw.get("epay_secret_enc") else ""
    raw["mail_port"] = int(raw["mail_port"] or 587)
    raw["mail_starttls"] = raw["mail_starttls"] != "false"
    raw["turnstile_enabled"] = raw["turnstile_enabled"] == "true"
    raw["epay_enabled"] = raw["epay_enabled"] == "true"
    return raw


def secret_digest(code: str) -> str:
    return hmac.new(settings.secret_key.encode(), code.encode(), hashlib.sha256).hexdigest()


def _send_email_sync(config: dict, to_email: str, code: str) -> None:
    host = config.get("mail_host", "").strip()
    sender = config.get("mail_sender", "").strip() or config.get("mail_user", "").strip()
    if not host or not sender:
        raise RuntimeError("SMTP 邮件服务尚未配置")
    msg = EmailMessage()
    msg["Subject"] = "官机云平台注册验证码"
    msg["From"] = sender
    msg["To"] = to_email
    msg.set_content(f"你的注册验证码是：{code}\n验证码 10 分钟内有效，请勿转发给他人。")
    with smtplib.SMTP(host, config["mail_port"], timeout=15) as server:
        if config["mail_starttls"]:
            server.starttls(context=ssl.create_default_context())
        if config.get("mail_user"):
            server.login(config["mail_user"], config["mail_password"])
        server.send_message(msg)


async def send_email(config: dict, to_email: str, code: str) -> None:
    import asyncio

    await asyncio.to_thread(_send_email_sync, config, to_email, code)


async def verify_turnstile(config: dict, token: str, remote_ip: str = "", expected_hostname: str = "") -> None:
    if not config["turnstile_enabled"]:
        return
    secret = config.get("turnstile_secret", "")
    if not secret or not token:
        raise HTTPException(400, "请完成人机验证")
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.post(
                "https://challenges.cloudflare.com/turnstile/v0/siteverify",
                data={"secret": secret, "response": token, "remoteip": remote_ip or None},
            )
            result = resp.json()
    except (httpx.HTTPError, ValueError):
        raise HTTPException(503, "人机验证暂不可用，请稍后重试")
    if not result.get("success"):
        raise HTTPException(400, "人机验证未通过，请重试")
    hostname = str(result.get("hostname", "")).lower().rstrip(".")
    if expected_hostname and hostname != expected_hostname.lower().rstrip("."):
        raise HTTPException(400, "人机验证来源不匹配，请重试")


def encrypt_optional_secret(value: str) -> str:
    return encrypt_secret(value) if value else ""
