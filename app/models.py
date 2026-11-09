"""数据库模型：用户、机器人实例、各功能配置、统计与审计。"""

import datetime as dt

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    email: Mapped[str | None] = mapped_column(String(254), unique=True, nullable=True, index=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BotInstance(Base):
    """一个绑定的官方机器人 = 一个实例。"""

    __tablename__ = "bot_instances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    appid: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    secret_enc: Mapped[str] = mapped_column(String(256))
    name: Mapped[str] = mapped_column(String(64), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)  # 期望运行状态
    # online / connecting / offline / error / disabled
    status: Mapped[str] = mapped_column(String(16), default="offline")
    status_detail: Mapped[str] = mapped_column(String(512), default="")
    last_online_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class KeywordRule(Base):
    __tablename__ = "keyword_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_instance_id: Mapped[int] = mapped_column(ForeignKey("bot_instances.id"), index=True)
    group_openid: Mapped[str] = mapped_column(String(64), default="*")  # '*'=所有群
    pattern: Mapped[str] = mapped_column(String(256))  # 支持多个关键词用 | 分隔
    reply_type: Mapped[str] = mapped_column(String(16), default="text")  # text / image
    reply_content: Mapped[str] = mapped_column(Text)  # 文本内容或图片 URL
    trigger_scope: Mapped[str] = mapped_column(String(16), default="all")  # all=全量消息 at=仅@触发
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class AiConfig(Base):
    __tablename__ = "ai_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_instance_id: Mapped[int] = mapped_column(ForeignKey("bot_instances.id"), unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    api_base: Mapped[str] = mapped_column(String(256), default="https://api.z.ai/api/paas/v4")
    api_key_enc: Mapped[str] = mapped_column(String(256), default="")
    model: Mapped[str] = mapped_column(String(64), default="glm-4-flash")
    system_prompt: Mapped[str] = mapped_column(Text, default="你是一个友好的群聊助手，回答简洁准确。")
    # 触发方式：at=仅@提问 keyword=关键词唤醒
    trigger_mode: Mapped[str] = mapped_column(String(16), default="at")
    trigger_keywords: Mapped[str] = mapped_column(String(256), default="问答,问问")
    daily_limit_per_user: Mapped[int] = mapped_column(Integer, default=20)
    max_history: Mapped[int] = mapped_column(Integer, default=6)
    # 全局 AI 人设：对话与审核各自独立（可按群覆盖）
    persona_name: Mapped[str] = mapped_column(String(64), default="")
    persona_desc: Mapped[str] = mapped_column(Text, default="")
    audit_persona_name: Mapped[str] = mapped_column(String(64), default="")
    audit_persona_desc: Mapped[str] = mapped_column(Text, default="")
    # 群规/FAQ 知识库：拼进 system prompt，让 AI 按群规回答
    group_rules_text: Mapped[str] = mapped_column(Text, default="")


class AiGroupPersona(Base):
    """按群覆盖的 AI 人设：字段为空 = 沿用全局对应值。"""

    __tablename__ = "ai_group_personas"
    __table_args__ = (UniqueConstraint("bot_instance_id", "group_openid"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_instance_id: Mapped[int] = mapped_column(ForeignKey("bot_instances.id"), index=True)
    group_openid: Mapped[str] = mapped_column(String(64))
    chat_persona_name: Mapped[str] = mapped_column(String(64), default="")
    chat_persona_desc: Mapped[str] = mapped_column(Text, default="")
    audit_persona_name: Mapped[str] = mapped_column(String(64), default="")
    audit_persona_desc: Mapped[str] = mapped_column(Text, default="")


class WelcomeConfig(Base):
    __tablename__ = "welcome_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_instance_id: Mapped[int] = mapped_column(ForeignKey("bot_instances.id"), unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # 变量：{at}=AT新人 {user}=用户标识 {group}=群标识
    template: Mapped[str] = mapped_column(Text, default="欢迎 {at} 加入本群！")
    # 纯文本 text / markdown
    msg_format: Mapped[str] = mapped_column(String(16), default="text")
    # 自动艾特新成员（在文案前插入 @）
    at_member: Mapped[bool] = mapped_column(Boolean, default=False)


class WelcomeGroupConfig(Base):
    """按群覆盖的欢迎配置；未配置的群走全局默认。"""

    __tablename__ = "welcome_group_configs"
    __table_args__ = (UniqueConstraint("bot_instance_id", "group_openid"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_instance_id: Mapped[int] = mapped_column(ForeignKey("bot_instances.id"), index=True)
    group_openid: Mapped[str] = mapped_column(String(64))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    msg_format: Mapped[str] = mapped_column(String(16), default="text")
    at_member: Mapped[bool] = mapped_column(Boolean, default=False)
    template: Mapped[str] = mapped_column(Text, default="欢迎 {at} 加入本群！")


class AutomationRule(Base):
    """自定义自动化规则：触发条件 → 执行动作。group_openid='*' 表示所有群。"""

    __tablename__ = "automation_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_instance_id: Mapped[int] = mapped_column(ForeignKey("bot_instances.id"), index=True)
    name: Mapped[str] = mapped_column(String(64), default="未命名规则")
    group_openid: Mapped[str] = mapped_column(String(64), default="*")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    # keyword / link / spam
    trigger_type: Mapped[str] = mapped_column(String(16), default="keyword")
    # {keywords:[], match_mode:"contains"|"regex", spam_window:int, spam_max:int, whitelist_openids:[]}
    trigger_params: Mapped[dict] = mapped_column(JSON, default=dict)
    # 有序列表：[{type:"recall"} {type:"mute",minutes} {type:"kick",blacklist:bool}
    #           {type:"blacklist",op:"add"} {type:"notify",target} {type:"reply",content} {type:"log"}]
    actions: Mapped[list] = mapped_column(JSON, default=list)
    # 综合规则：{触发类型: {enabled, params, actions}}——一行存多个触发类型的独立配置；
    # 为空(Null)时走上面的单类型字段（旧行为），两者由引擎统一兼容。
    type_configs: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GroupAdminConfig(Base):
    """群管总开关与指令管理员名单（每实例一份）。"""

    __tablename__ = "group_admin_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_instance_id: Mapped[int] = mapped_column(ForeignKey("bot_instances.id"), unique=True)
    # 总开关：关闭后所有自动化规则停跑（手动管理指令不受影响）
    master_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    admin_openids: Mapped[str] = mapped_column(Text, default="")  # 每行一个
    default_notify_group: Mapped[str] = mapped_column(String(64), default="")


class ModerationConfig(Base):
    """广告/诈骗监控与处置链。"""

    __tablename__ = "moderation_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_instance_id: Mapped[int] = mapped_column(ForeignKey("bot_instances.id"), unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    keywords: Mapped[str] = mapped_column(Text, default="")  # 每行一个关键词
    block_links: Mapped[bool] = mapped_column(Boolean, default=True)
    spam_window_seconds: Mapped[int] = mapped_column(Integer, default=10)
    spam_max_messages: Mapped[int] = mapped_column(Integer, default=5)
    # 处置动作开关
    auto_recall: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_mute_minutes: Mapped[int] = mapped_column(Integer, default=0)  # 0=不禁言
    auto_blacklist: Mapped[bool] = mapped_column(Boolean, default=False)
    notify_group_openid: Mapped[str] = mapped_column(String(64), default="")  # 通知的管理群
    whitelist_openids: Mapped[str] = mapped_column(Text, default="")  # 每行一个，管理员/白名单


class ApprovalConfig(Base):
    __tablename__ = "approval_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_instance_id: Mapped[int] = mapped_column(ForeignKey("bot_instances.id"), unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # auto: 命中官方自动审批策略；manual: 通知管理员人工审批
    mode: Mapped[str] = mapped_column(String(16), default="manual")
    notify_group_openid: Mapped[str] = mapped_column(String(64), default="")
    # 页面端自动审批关键词：申请填写的答案包含关键词则通过（平台侧辅助）
    auto_approve_keywords: Mapped[str] = mapped_column(Text, default="")


class ApprovalGroupConfig(Base):
    """群级自动审批关键词；空关键词表示继承全局配置。"""

    __tablename__ = "approval_group_configs"
    __table_args__ = (UniqueConstraint("bot_instance_id", "group_openid"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_instance_id: Mapped[int] = mapped_column(ForeignKey("bot_instances.id"), index=True)
    group_openid: Mapped[str] = mapped_column(String(64))
    auto_approve_keywords: Mapped[str] = mapped_column(Text, default="")


class ScheduleTask(Base):
    __tablename__ = "schedule_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_instance_id: Mapped[int] = mapped_column(ForeignKey("bot_instances.id"), index=True)
    name: Mapped[str] = mapped_column(String(64), default="定时任务")
    cron: Mapped[str] = mapped_column(String(64), default="0 9 * * *")
    target_group_openid: Mapped[str] = mapped_column(String(64), default="")
    task_type: Mapped[str] = mapped_column(String(16), default="text")  # text / image
    content: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_run_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ReportConfig(Base):
    __tablename__ = "report_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_instance_id: Mapped[int] = mapped_column(ForeignKey("bot_instances.id"), unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    notify_group_openid: Mapped[str] = mapped_column(String(64), default="")


class FunConfig(Base):
    __tablename__ = "fun_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_instance_id: Mapped[int] = mapped_column(ForeignKey("bot_instances.id"), unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    fortune: Mapped[bool] = mapped_column(Boolean, default=True)  # 抽签
    dice: Mapped[bool] = mapped_column(Boolean, default=True)  # 骰子
    lottery: Mapped[bool] = mapped_column(Boolean, default=True)  # 抽奖（限时报名）


class SigninConfig(Base):
    __tablename__ = "signin_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_instance_id: Mapped[int] = mapped_column(ForeignKey("bot_instances.id"), unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    reward_template: Mapped[str] = mapped_column(Text, default="签到成功！已连续签到 {days} 天")


class AiMessage(Base):
    """AI 对话上下文（短保留）。"""

    __tablename__ = "ai_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_instance_id: Mapped[int] = mapped_column(ForeignKey("bot_instances.id"), index=True)
    user_openid: Mapped[str] = mapped_column(String(64), index=True)
    role: Mapped[str] = mapped_column(String(16))  # user / assistant
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UsageCounter(Base):
    """每日额度计数：主动消息、AI 次数等。"""

    __tablename__ = "usage_counters"
    __table_args__ = (UniqueConstraint("bot_instance_id", "day", "scope", "scope_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_instance_id: Mapped[int] = mapped_column(ForeignKey("bot_instances.id"), index=True)
    day: Mapped[str] = mapped_column(String(10))  # 2026-10-04
    scope: Mapped[str] = mapped_column(String(32))  # ai_user / group_active / proactively_sent
    scope_key: Mapped[str] = mapped_column(String(64), default="")
    count: Mapped[int] = mapped_column(Integer, default=0)


class DailyStat(Base):
    """群活跃统计（只存统计结果，不存聊天内容）。"""

    __tablename__ = "daily_stats"
    __table_args__ = (UniqueConstraint("bot_instance_id", "day", "group_openid", "user_openid"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_instance_id: Mapped[int] = mapped_column(ForeignKey("bot_instances.id"), index=True)
    day: Mapped[str] = mapped_column(String(10), index=True)
    group_openid: Mapped[str] = mapped_column(String(64))
    user_openid: Mapped[str] = mapped_column(String(64))
    user_name: Mapped[str] = mapped_column(String(128), default="")
    msg_count: Mapped[int] = mapped_column(Integer, default=0)


class SigninRecord(Base):
    __tablename__ = "signin_records"
    __table_args__ = (UniqueConstraint("bot_instance_id", "day", "user_openid"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_instance_id: Mapped[int] = mapped_column(ForeignKey("bot_instances.id"), index=True)
    day: Mapped[str] = mapped_column(String(10))
    user_openid: Mapped[str] = mapped_column(String(64))
    user_name: Mapped[str] = mapped_column(String(128), default="")
    streak: Mapped[int] = mapped_column(Integer, default=1)


class LotteryEntry(Base):
    """抽奖报名。"""

    __tablename__ = "lottery_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_instance_id: Mapped[int] = mapped_column(ForeignKey("bot_instances.id"), index=True)
    group_openid: Mapped[str] = mapped_column(String(64))
    message_id: Mapped[str] = mapped_column(String(64), default="")
    user_openid: Mapped[str] = mapped_column(String(64))
    user_name: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ModerationHit(Base):
    """监控命中记录。"""

    __tablename__ = "moderation_hits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_instance_id: Mapped[int] = mapped_column(ForeignKey("bot_instances.id"), index=True)
    rule_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rule_name: Mapped[str] = mapped_column(String(64), default="")
    group_openid: Mapped[str] = mapped_column(String(64))
    user_openid: Mapped[str] = mapped_column(String(64))
    user_name: Mapped[str] = mapped_column(String(128), default="")
    reason: Mapped[str] = mapped_column(String(256), default="")
    excerpt: Mapped[str] = mapped_column(String(256), default="")  # 命中内容摘要（截断）
    actions: Mapped[dict] = mapped_column(JSON, default=dict)  # {"recall": true, "mute": 30, ...}
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PendingJoinRequest(Base):
    __tablename__ = "pending_join_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_instance_id: Mapped[int] = mapped_column(ForeignKey("bot_instances.id"), index=True)
    group_openid: Mapped[str] = mapped_column(String(64))
    member_openid: Mapped[str] = mapped_column(String(64))
    user_name: Mapped[str] = mapped_column(String(128), default="")
    answer: Mapped[str] = mapped_column(String(512), default="")
    risk_tips: Mapped[str] = mapped_column(String(256), default="")
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending/approved/declined
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FeatureGroupConfig(Base):
    """功能 × 群 的开关（group_openid='*' 表示该功能的全局默认覆盖）。"""

    __tablename__ = "feature_group_configs"
    __table_args__ = (UniqueConstraint("bot_instance_id", "feature", "group_openid"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_instance_id: Mapped[int] = mapped_column(ForeignKey("bot_instances.id"), index=True)
    feature: Mapped[str] = mapped_column(String(32))
    group_openid: Mapped[str] = mapped_column(String(64), default="*")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class KnownGroup(Base):
    """实例已发现的群（自动发现插件落库），供页面下拉选择。"""

    __tablename__ = "known_groups"
    __table_args__ = (UniqueConstraint("bot_instance_id", "group_openid"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_instance_id: Mapped[int] = mapped_column(ForeignKey("bot_instances.id"), index=True)
    group_openid: Mapped[str] = mapped_column(String(64))
    group_name: Mapped[str] = mapped_column(String(128), default="")
    first_seen: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bot_instance_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    action: Mapped[str] = mapped_column(String(64))
    detail: Mapped[str] = mapped_column(String(512), default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RuntimeLog(Base):
    """运行日志：连接、发送失败等，供页面查看。"""

    __tablename__ = "runtime_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_instance_id: Mapped[int] = mapped_column(ForeignKey("bot_instances.id"), index=True)
    level: Mapped[str] = mapped_column(String(8), default="info")  # info/warn/error
    message: Mapped[str] = mapped_column(String(1024))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LoginLog(Base):
    """登录记录（运营后台用）。"""

    __tablename__ = "login_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    ip: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class InviteCode(Base):
    """邀请码：注册模式为 invite 时必须持有未使用的邀请码。"""

    __tablename__ = "invite_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    used_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EmailVerification(Base):
    """Single-use email verification code; only a keyed hash is stored."""

    __tablename__ = "email_verifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(254), index=True)
    code_hash: Mapped[str] = mapped_column(String(128))
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    request_ip: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PaymentPlan(Base):
    """Admin-managed validity plan, prices stored as integer cents."""

    __tablename__ = "payment_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    duration_days: Mapped[int] = mapped_column(Integer)
    price_cents: Mapped[int] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PaymentOrder(Base):
    """Local order snapshot; notifications must match amount and merchant order."""

    __tablename__ = "payment_orders"
    __table_args__ = (UniqueConstraint("out_trade_no"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    out_trade_no: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    plan_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    plan_name: Mapped[str] = mapped_column(String(64))
    duration_days: Mapped[int] = mapped_column(Integer)
    amount_cents: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    gateway_trade_no: Mapped[str] = mapped_column(String(128), default="")
    paid_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SystemSetting(Base):
    """平台级系统设置（key-value，覆盖 .env 默认值）。"""

    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


# 解绑/删除用户时的级联清理清单：所有带 bot_instance_id 的业务表。
# 注意：unbind_instance 原实现漏了 AutomationRule/GroupAdminConfig/KnownGroup/
# WelcomeGroupConfig/AiGroupPersona/FeatureGroupConfig，统一走这份清单。
INSTANCE_CASCADE_MODELS = (
    AiConfig, ApprovalConfig, ApprovalGroupConfig, FunConfig, ModerationConfig, ReportConfig,
    SigninConfig, WelcomeConfig, KeywordRule, ScheduleTask, AiMessage,
    DailyStat, LotteryEntry, ModerationHit, PendingJoinRequest,
    RuntimeLog, UsageCounter, SigninRecord, AutomationRule,
    GroupAdminConfig, KnownGroup, WelcomeGroupConfig, AiGroupPersona,
    FeatureGroupConfig,
)
