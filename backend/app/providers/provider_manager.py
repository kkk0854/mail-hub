"""临时邮箱 Provider 注册管理器（v1.2.0 插件化）。

支持两种注册方式：
1. 内置 Provider 直接 register()
2. 第三方插件通过 entry-points（group=mailhub.tempmail_provider）自动发现
"""
from __future__ import annotations

import logging
from typing import Type

logger = logging.getLogger("mailhub.tempmail")

try:
    import importlib.metadata as importlib_metadata
except ImportError:  # pragma: no cover
    importlib_metadata = None

from .tempmail_base import TempMailProvider


class ProviderManager:
    _registry: dict[str, Type[TempMailProvider]] = {}
    _loaded = False

    @classmethod
    def register(cls, name: str, impl: Type[TempMailProvider]) -> None:
        cls._registry[name] = impl

    @classmethod
    def load_all(cls) -> None:
        """加载全部内置 Provider + entry-points 插件。幂等。"""
        if cls._loaded:
            return
        cls._loaded = True

        # 内置 Provider
        try:
            from .gptmail_provider import GPTMailProvider
            from .moemail_provider import MoemailProvider
            from .custom_http_provider import CustomHttpProvider

            cls.register(GPTMailProvider.name, GPTMailProvider)
            cls.register(MoemailProvider.name, MoemailProvider)
            cls.register(CustomHttpProvider.name, CustomHttpProvider)
            logger.info("tempmail providers loaded: %s", ", ".join(cls._registry))
        except Exception as exc:  # pragma: no cover
            logger.warning("failed to load builtin tempmail providers: %s", exc)

        # entry-points 插件（第三方）
        if importlib_metadata is not None:
            try:
                eps = importlib_metadata.entry_points(group="mailhub.tempmail_provider")
                for ep in eps:
                    try:
                        impl = ep.load()
                        if impl and hasattr(impl, "name"):
                            cls.register(impl.name, impl)
                            logger.info("registered tempmail plugin %s (%s)", impl.name, ep.value)
                    except Exception as exc:
                        logger.warning("failed to load tempmail plugin %s: %s", ep.value, exc)
            except Exception as exc:
                logger.debug("entry-points scan skipped: %s", exc)

    @classmethod
    def get(cls, name: str) -> Type[TempMailProvider] | None:
        cls.load_all()
        return cls._registry.get(name)

    @classmethod
    def list(cls) -> list[dict]:
        cls.load_all()
        return [
            {"name": n, "display_name": impl.display_name, "requires_config": impl.requires_config}
            for n, impl in sorted(cls._registry.items())
        ]

    @classmethod
    def names(cls) -> list[str]:
        cls.load_all()
        return sorted(cls._registry.keys())


# 兼容旧 API：函数式接口
def get_provider_class(name: str) -> Type[TempMailProvider] | None:
    return ProviderManager.get(name)


def list_providers() -> list[dict]:
    return ProviderManager.list()
