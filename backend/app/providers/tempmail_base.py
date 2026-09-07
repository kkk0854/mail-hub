"""临时邮箱 Provider 统一基类（v1.2.0 插件化架构）。

与 MailProvider（长期邮箱拉取/推送适配）不同，TempMailProvider 面向"按需申请-使用-销毁"的
临时邮箱生命周期，供邮箱池动态创建临时邮箱使用。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional


class TempMailError(Exception):
    def __init__(self, message: str, error_code: str = "TEMPMAIL_ERROR"):
        super().__init__(message)
        self.error_code = error_code


class TempMailProvider(ABC):
    """临时邮箱 Provider 统一抽象。新增源只需实现本接口并注册。"""

    # 唯一标识（如 gptmail / moemail / custom_http）
    name: str = "base"
    # 展示名称
    display_name: str = "Base"
    # 是否需要配置（未配置时在管理界面显示未启用）
    requires_config: bool = True

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}

    # ---------------------------------------------------------------- 生命周期
    @abstractmethod
    async def create_email(self, domain: str | None = None) -> dict:
        """申请一个临时邮箱地址。

        返回：{"email": str, "password": str|None, "extra": dict}
        """

    @abstractmethod
    async def get_messages(self, email: str, password: str | None = None) -> list[dict]:
        """获取邮箱的消息列表。

        返回：[{"id": str, "from": str, "subject": str, "text": str, "received_at": str|None}, ...]
        """

    async def delete_email(self, email: str, password: str | None = None) -> None:
        """销毁临时邮箱（可选实现）。"""

    @abstractmethod
    def get_config_schema(self) -> dict:
        """返回前端渲染配置表单的 JSON Schema。

        示例：{"properties": {"api_key": {"type": "string", "title": "API Key"}}, "required": []}
        """

    def validate_config(self, config: dict) -> tuple[bool, str]:
        """校验配置是否完整。返回 (是否有效, 错误信息)。"""
        return True, ""
