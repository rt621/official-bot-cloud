from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    # SQLite 默认便于本地开发；部署时设为 postgresql+asyncpg://...
    database_url: str = f"sqlite+aiosqlite:///{BASE_DIR / 'data' / 'app.db'}"
    # JWT 签名密钥
    secret_key: str = "dev-only-change-me"
    # AppSecret 加密主密钥（Fernet）。留空则自动生成并存 data/.master_key
    master_key: str = ""
    # 平台注册开放开关（公益自用可关闭防止陌生人注册）
    open_registration: bool = True
    # 每用户最多绑定的机器人数量
    max_instances_per_user: int = 3

    qq_api_base: str = "https://api.bot.qq.com"

    # 运行时行为
    instance_reconnect_max_delay: int = 60
    status_broadcast_interval: float = 5.0


settings = Settings()
