"""内置插件热加载器：扫描 plugins 目录，改动后自动重新加载。

- 放入新的 .py 插件文件（定义 Plugin 子类）即被自动识别，无需重启
- 目录 mtime 变化才会真正重新 import，平时开销为零
- 排序：按插件类上的 order 属性（小者先执行），同序按类名
"""

import importlib
import inspect
import logging
import pkgutil
import sys
from pathlib import Path

from app.runtime.plugins.base import Plugin

log = logging.getLogger("runtime.plugins")

PLUGIN_DIR = Path(__file__).resolve().parent
_PKG = "app.runtime.plugins"
_RESERVED = {"base", "__init__", "loader"}


class PluginLoader:
    def __init__(self) -> None:
        self._mtime: float = -1.0
        self._plugins: list[Plugin] = []
        self._names: list[str] = []

    def _dir_mtime(self) -> float:
        latest = PLUGIN_DIR.stat().st_mtime
        for f in PLUGIN_DIR.glob("*.py"):
            latest = max(latest, f.stat().st_mtime)
        return latest

    def get_plugins(self) -> list[Plugin]:
        mtime = self._dir_mtime()
        if mtime != self._mtime or not self._plugins:
            self._load_all()
            self._mtime = mtime
        return self._plugins

    def reload(self) -> list[str]:
        """强制重扫（管理接口用），返回当前加载的插件名。"""
        self._load_all()
        self._mtime = self._dir_mtime()
        return self._names

    def _load_all(self) -> None:
        plugins: list[Plugin] = []
        for mod_info in pkgutil.iter_modules([str(PLUGIN_DIR)]):
            name = mod_info.name
            if name in _RESERVED:
                continue
            fullname = f"{_PKG}.{name}"
            try:
                if fullname in sys.modules:
                    module = importlib.reload(sys.modules[fullname])
                else:
                    module = importlib.import_module(fullname)
            except Exception as exc:  # noqa: BLE001
                log.error("加载插件模块 %s 失败: %s", name, exc)
                continue
            for _, cls in inspect.getmembers(module, inspect.isclass):
                if (
                    issubclass(cls, Plugin)
                    and cls is not Plugin
                    and cls.__module__ == fullname
                ):
                    try:
                        plugins.append(cls())
                    except Exception as exc:  # noqa: BLE001
                        log.error("实例化插件 %s 失败: %s", cls.__name__, exc)
        plugins.sort(key=lambda p: (getattr(p, "order", 100), p.name))
        self._plugins = plugins
        self._names = [type(p).__name__ for p in plugins]
        log.info("插件加载完成: %s", ", ".join(self._names))


plugin_loader = PluginLoader()
