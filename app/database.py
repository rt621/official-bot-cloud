"""数据库引擎与会话。"""

import contextlib
import json
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import BASE_DIR, settings

(BASE_DIR / "data").mkdir(exist_ok=True)

engine: AsyncEngine = create_async_engine(settings.database_url, echo=False)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def init_db() -> None:
    from app.models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # 轻量迁移：为已存在的旧表补列（create_all 不会加列）
        from sqlalchemy import text

        for stmt in (
            "ALTER TABLE moderation_hits ADD COLUMN rule_id INTEGER",
            "ALTER TABLE moderation_hits ADD COLUMN rule_name VARCHAR(64) DEFAULT ''",
            "ALTER TABLE welcome_configs ADD COLUMN msg_format VARCHAR(16) DEFAULT 'text'",
            "ALTER TABLE welcome_configs ADD COLUMN at_member BOOLEAN DEFAULT 0",
            "ALTER TABLE ai_configs ADD COLUMN group_rules_text TEXT DEFAULT ''",
            "ALTER TABLE ai_configs ADD COLUMN persona_name VARCHAR(64) DEFAULT ''",
            "ALTER TABLE ai_configs ADD COLUMN persona_desc TEXT DEFAULT ''",
            "ALTER TABLE ai_configs ADD COLUMN audit_persona_name VARCHAR(64) DEFAULT ''",
            "ALTER TABLE ai_configs ADD COLUMN audit_persona_desc TEXT DEFAULT ''",
            "ALTER TABLE known_groups ADD COLUMN group_name VARCHAR(128) DEFAULT ''",
            "ALTER TABLE keyword_rules ADD COLUMN group_openid VARCHAR(64) DEFAULT '*'",
            "ALTER TABLE users ADD COLUMN disabled BOOLEAN DEFAULT 0",
            "ALTER TABLE users ADD COLUMN expires_at DATETIME",
            "ALTER TABLE users ADD COLUMN email VARCHAR(254)",
            "ALTER TABLE automation_rules ADD COLUMN type_configs JSON",
        ):
            with contextlib.suppress(Exception):
                await conn.execute(text(stmt))
        await _migrate_moderation_to_rules(conn)
        # 回填已知群：从历史统计里恢复 known_groups（表新建前的群不会丢）
        await conn.execute(text(
            "INSERT OR IGNORE INTO known_groups (bot_instance_id, group_openid, first_seen, last_seen) "
            "SELECT DISTINCT bot_instance_id, group_openid, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP "
            "FROM daily_stats WHERE group_openid != ''"
        ))


async def _migrate_moderation_to_rules(conn) -> None:
    """旧 ModerationConfig（启用中且有内容的）迁移为一条 '*' 群默认规则。"""
    from sqlalchemy import text

    rows = (await conn.execute(text("SELECT bot_instance_id, keywords, block_links, spam_window_seconds, spam_max_messages, auto_recall, auto_mute_minutes, auto_blacklist, notify_group_openid, whitelist_openids FROM moderation_configs"))).mappings().all()
    for row in rows:
        # 从未配置过的默认配置不迁移
        if not row["keywords"]:
            continue
        exists = (
            await conn.execute(
                text("SELECT COUNT(*) FROM automation_rules WHERE bot_instance_id=:i AND name='广告监控（迁移）'"),
                {"i": row["bot_instance_id"]},
            )
        ).scalar()
        if exists:
            continue
        actions: list[dict] = []
        if row["auto_recall"]:
            actions.append({"type": "recall"})
        if row["auto_mute_minutes"]:
            actions.append({"type": "mute", "minutes": row["auto_mute_minutes"]})
        if row["auto_blacklist"]:
            actions.append({"type": "blacklist", "op": "add"})
        if row["notify_group_openid"]:
            actions.append({"type": "notify", "target": row["notify_group_openid"]})
        actions.append({"type": "log"})
        params: dict = {"whitelist_openids": [s for s in (row["whitelist_openids"] or "").splitlines() if s.strip()]}
        if row["keywords"]:
            params["keywords"] = [s for s in row["keywords"].splitlines() if s.strip()]
        if row["block_links"]:
            params["block_links"] = True
        if row["spam_max_messages"]:
            params["spam_window"] = row["spam_window_seconds"]
            params["spam_max"] = row["spam_max_messages"]
        await conn.execute(
            text("INSERT INTO automation_rules (bot_instance_id, name, group_openid, enabled, priority, trigger_type, trigger_params, actions, created_at) VALUES (:i, '广告监控（迁移）', '*', 1, 100, 'keyword', :p, :a, CURRENT_TIMESTAMP)"),
            {"i": row["bot_instance_id"], "p": json.dumps(params, ensure_ascii=False), "a": json.dumps(actions, ensure_ascii=False)},
        )
