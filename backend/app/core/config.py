"""应用配置。敏感密钥独立于数据库存储在 data/ 下的密钥文件中（§20）。"""
from __future__ import annotations

import secrets
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # backend/
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


def _ensure_file(path: Path, generator) -> str:
    """读取密钥文件；不存在则生成并写入（权限独立的密钥存储）。"""
    if path.exists():
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value
    value = generator()
    path.write_text(value, encoding="utf-8")
    return value


def _gen_fernet_key() -> str:
    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode()


DEFAULT_ADMIN_PASSWORD = "admin123"  # 内置默认口令；生产必须用环境变量覆盖，首登强制改密。


class Settings(BaseSettings):
    app_name: str = "MAIL HUB"
    version: str = "1.2.0"
    debug: bool = False

    database_url: str = f"sqlite+aiosqlite:///{(DATA_DIR / 'mailhub.db').as_posix()}"

    # 密钥（留空则自动生成并持久化到 data/ 下）
    secret_key: str = ""        # JWT 签名密钥
    encryption_key: str = ""    # 凭据字段加密密钥 (Fernet)
    webhook_secret: str = ""    # Webhook HMAC 签名密钥
    api_key: str = ""           # 外部系统调用 API Key

    auth_enabled: bool = True
    admin_username: str = "admin"
    admin_password: str = DEFAULT_ADMIN_PASSWORD

    embed_workers: bool = True  # API 进程内嵌 Worker；分离部署时设为 false
    worker_concurrency: int = 2
    sync_interval_seconds: int = 60
    health_check_interval_seconds: int = 300
    task_default_timeout: int = 300
    webhook_max_attempts: int = 5
    rate_limit_per_minute: int = 600

    static_dir: str = str(BASE_DIR.parent / "frontend" / "dist")
    # 允许的跨域来源（逗号分隔）。留空 = 不开放跨域（安全默认），仅放行本机开发源（见 main.py）
    cors_origins: str = ""

    # 通知通道配置（留空则不启用该通道）
    notify_telegram_bot_token: str = ""
    notify_telegram_chat_id: str = ""
    notify_dingtalk_webhook: str = ""
    notify_dingtalk_secret: str = ""
    notify_webhook_url: str = ""
    notify_webhook_secret: str = ""

    # 一键更新（Watchtower）
    watchtower_api_url: str = "http://watchtower:8080"
    watchtower_api_token: str = ""
    github_repo: str = "kkk0854/mail-hub"  # 用于检查最新版本

    # LLM 验证码兜底（v1.2.0，可选，不配置默认关闭）
    llm_fallback_enable: bool = False
    llm_api_base: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_confidence_threshold: float = 0.65
    llm_fallback_timeout: int = 20
    llm_max_consecutive_failures: int = 5

    model_config = SettingsConfigDict(env_prefix="MAILHUB_", env_file=str(BASE_DIR / ".env"), extra="ignore")


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        s = Settings()
        s.secret_key = s.secret_key or _ensure_file(DATA_DIR / ".jwt_secret", lambda: secrets.token_hex(32))
        s.encryption_key = s.encryption_key or _ensure_file(DATA_DIR / ".secret_key", _gen_fernet_key)
        s.webhook_secret = s.webhook_secret or _ensure_file(DATA_DIR / ".webhook_secret", lambda: secrets.token_hex(24))
        s.api_key = s.api_key or _ensure_file(DATA_DIR / ".api_key", lambda: "mh_" + secrets.token_hex(20))
        _settings = s
    return _settings


_settings: Settings | None = None


settings = get_settings()
