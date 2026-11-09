"""易支付套餐、订单与回调接口。"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import secrets
from decimal import Decimal, InvalidOperation
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import bearer
from app.database import get_db
from app.models import PaymentOrder, PaymentPlan, User
from app.registration_security import get_registration_security
from app.security import decode_token
from app.user_state import as_utc

router = APIRouter(prefix="/api/payment", tags=["payment"])


async def _payment_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Expired users may renew; disabled users may not create orders."""
    if creds is None:
        raise HTTPException(401, "未登录")
    payload = decode_token(creds.credentials)
    if not payload:
        raise HTTPException(401, "登录已过期")
    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(401, "登录已过期")
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(401, "用户不存在")
    if user.disabled:
        raise HTTPException(403, "账号已被停用，请联系平台管理员")
    return user


def epay_sign(params: dict[str, object], secret: str) -> str:
    """易支付 MD5: sorted non-empty key=value pairs plus merchant key."""
    pairs = []
    for key in sorted(params):
        if key in {"sign", "sign_type"}:
            continue
        value = params[key]
        if value is None or str(value) == "":
            continue
        pairs.append(f"{key}={value}")
    return hashlib.md5(("&".join(pairs) + secret).encode("utf-8")).hexdigest()


def verify_epay_sign(params: dict[str, object], secret: str) -> bool:
    supplied = str(params.get("sign", "")).lower()
    if not supplied or str(params.get("sign_type", "MD5")).upper() != "MD5":
        return False
    return hmac.compare_digest(supplied, epay_sign(params, secret))


def _gateway_url(gateway: str, params: dict[str, str]) -> str:
    if not gateway:
        raise HTTPException(503, "易支付网关尚未配置")
    parts = urlsplit(gateway)
    if not parts.scheme or not parts.netloc:
        raise HTTPException(503, "易支付网关地址无效")
    query = dict(parse_qs(parts.query, keep_blank_values=True))
    query = {key: values[-1] for key, values in query.items()}
    query.update(params)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _money_text(cents: int) -> str:
    return f"{Decimal(cents) / Decimal(100):.2f}"


def _amount_matches(raw: object, expected_cents: int) -> bool:
    try:
        amount = Decimal(str(raw))
        return amount.is_finite() and int(amount * 100) == expected_cents and amount * 100 == expected_cents
    except (InvalidOperation, TypeError, ValueError):
        return False


@router.get("/plans")
async def list_plans(
    _user: User = Depends(_payment_user), db: AsyncSession = Depends(get_db)
) -> dict:
    rows = (
        await db.execute(
            select(PaymentPlan)
            .where(PaymentPlan.enabled.is_(True))
            .order_by(PaymentPlan.duration_days, PaymentPlan.id)
        )
    ).scalars().all()
    return {
        "items": [
            {
                "id": plan.id,
                "name": plan.name,
                "duration_days": plan.duration_days,
                "price_cents": plan.price_cents,
                "price": _money_text(plan.price_cents),
            }
            for plan in rows
        ]
    }


class CreateOrderIn(BaseModel):
    plan_id: int = Field(gt=0)
    payment_type: str = Field(default="alipay", pattern=r"^(alipay|wxpay)$")


@router.post("/orders")
async def create_order(
    body: CreateOrderIn,
    user: User = Depends(_payment_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    config = await get_registration_security(db)
    if not config["epay_enabled"] or not config["epay_pid"] or not config["epay_secret"]:
        raise HTTPException(503, "在线支付暂未启用")
    plan = await db.get(PaymentPlan, body.plan_id)
    if not plan or not plan.enabled:
        raise HTTPException(404, "套餐不存在或已下架")
    if plan.duration_days <= 0 or plan.price_cents <= 0:
        raise HTTPException(400, "套餐配置无效")

    out_trade_no = f"P{dt.datetime.now(dt.timezone.utc):%Y%m%d%H%M%S}{secrets.token_hex(6)}"
    order = PaymentOrder(
        out_trade_no=out_trade_no,
        user_id=user.id,
        plan_id=plan.id,
        plan_name=plan.name,
        duration_days=plan.duration_days,
        amount_cents=plan.price_cents,
    )
    db.add(order)
    await db.flush()

    params = {
        "pid": config["epay_pid"],
        "type": body.payment_type,
        "out_trade_no": out_trade_no,
        "notify_url": config["epay_notify_url"],
        "return_url": config["epay_return_url"],
        "name": plan.name,
        "money": _money_text(plan.price_cents),
    }
    params["sign"] = epay_sign(params, config["epay_secret"])
    params["sign_type"] = "MD5"
    try:
        pay_url = _gateway_url(config["epay_gateway"], params)
    except Exception:
        await db.rollback()
        raise
    await db.commit()
    return {"out_trade_no": out_trade_no, "status": order.status, "pay_url": pay_url}


@router.get("/orders/{out_trade_no}")
async def get_order(
    out_trade_no: str,
    user: User = Depends(_payment_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    order = await db.scalar(
        select(PaymentOrder).where(
            PaymentOrder.out_trade_no == out_trade_no,
            PaymentOrder.user_id == user.id,
        )
    )
    if not order:
        raise HTTPException(404, "订单不存在")
    return {
        "out_trade_no": order.out_trade_no,
        "plan_name": order.plan_name,
        "duration_days": order.duration_days,
        "amount_cents": order.amount_cents,
        "status": order.status,
        "paid_at": order.paid_at,
        "expires_at": order.expires_at,
    }


@router.get("/return")
async def payment_return(
    out_trade_no: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Gateway return is informational only; notify_url performs fulfillment."""
    order = await db.scalar(
        select(PaymentOrder).where(PaymentOrder.out_trade_no == out_trade_no)
    )
    if not order:
        raise HTTPException(404, "订单不存在")
    return {"out_trade_no": order.out_trade_no, "status": order.status, "paid_at": order.paid_at}


@router.api_route("/notify", methods=["GET", "POST"])
async def payment_notify(request: Request, db: AsyncSession = Depends(get_db)) -> Response:
    try:
        params = dict(request.query_params)
        if request.method == "POST":
            raw_body = await request.body()
            parsed = parse_qs(raw_body.decode("utf-8"), keep_blank_values=True, strict_parsing=False)
            params.update({key: values[-1] for key, values in parsed.items()})
    except (UnicodeDecodeError, ValueError):
        return Response("fail", media_type="text/plain")
    config = await get_registration_security(db)
    await db.commit()  # Clear the read transaction before the fulfillment transaction.
    if not config["epay_enabled"] or not config["epay_secret"]:
        return Response("fail", media_type="text/plain")
    if not verify_epay_sign(params, config["epay_secret"]):
        return Response("fail", media_type="text/plain")
    if params.get("pid", "") != config["epay_pid"] or params.get("trade_status", "") != "TRADE_SUCCESS":
        return Response("fail", media_type="text/plain")
    if not params.get("trade_no"):
        return Response("fail", media_type="text/plain")
    out_trade_no = params.get("out_trade_no", "")
    if not out_trade_no:
        return Response("fail", media_type="text/plain")

    try:
        async with db.begin():
            order = await db.scalar(
                select(PaymentOrder).where(PaymentOrder.out_trade_no == out_trade_no).with_for_update()
            )
            if not order or not _amount_matches(params.get("money"), order.amount_cents):
                return Response("fail", media_type="text/plain")
            if order.status == "paid":
                return Response("success", media_type="text/plain")
            if order.status != "pending":
                return Response("fail", media_type="text/plain")

            now = dt.datetime.now(dt.timezone.utc)
            user = await db.scalar(select(User).where(User.id == order.user_id).with_for_update())
            if not user:
                return Response("fail", media_type="text/plain")
            if user.disabled:
                return Response("fail", media_type="text/plain")
            current_expiry = as_utc(user.expires_at) if user.expires_at else None
            base = current_expiry if current_expiry and current_expiry > now else now
            expiry = base + dt.timedelta(days=order.duration_days)

            claimed = await db.execute(
                update(PaymentOrder)
                .where(PaymentOrder.id == order.id, PaymentOrder.status == "pending")
                .values(
                    status="paid",
                    gateway_trade_no=str(params.get("trade_no", ""))[:128],
                    paid_at=now,
                    expires_at=expiry,
                )
            )
            if claimed.rowcount != 1:
                return Response("success", media_type="text/plain")
            user.expires_at = expiry
    except Exception:  # noqa: BLE001
        await db.rollback()
        return Response("fail", media_type="text/plain")
    supervisor = getattr(request.app.state, "supervisor", None)
    if supervisor is not None:
        try:
            await supervisor.enforce_expirations()
        except Exception:  # noqa: BLE001
            # The periodic supervisor pass will retry recovery without risking a lost payment ack.
            pass
    return Response("success", media_type="text/plain")
