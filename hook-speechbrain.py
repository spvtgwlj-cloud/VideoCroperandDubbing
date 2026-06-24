"""
PyInstaller runtime hook — 修复 speechbrain 在打包环境中的目录扫描问题。
speechbrain.utils.importutils.find_imports 使用 os.listdir 扫描物理目录，
在 PyInstaller 打包后目录结构不保留，改为使用 pkgutil 遍历已加载模块。
"""

import os
import sys


def _patch_speechbrain():
    """用 pkgutil-based 实现替换 os.listdir 目录扫描"""
    try:
        from speechbrain.utils import importutils

        # 保存原始函数
        _original_find_imports = importutils.find_imports

        def _frozen_find_imports(module):
            """PyInstaller 兼容版：从 sys.modules 中查找子模块"""
            name = module.__name__
            prefix = name + "."
            submodules = []
            for key in sys.modules:
                if key.startswith(prefix) and "." not in key[len(prefix):]:
                    submodules.append(key)
            return sorted(submodules)

        importutils.find_imports = _frozen_find_imports

        # 同时修复 lazy_export_all 依赖的 __path__ 遍历
        _original_lazy_export_all = importutils.lazy_export_all

        def _frozen_lazy_export_all(module):
            """PyInstaller 兼容版：不依赖 __path__ 扫描"""
            name = module.__name__
            prefix = name + "."
            for key in sorted(sys.modules):
                if key.startswith(prefix):
                    sub_name = key[len(prefix):]
                    if "." not in sub_name:
                        try:
                            sub_module = sys.modules[key]
                            setattr(module, sub_name, sub_module)
                        except (KeyError, AttributeError):
                            pass

        importutils.lazy_export_all = _frozen_lazy_export_all

    except ImportError:
        pass


_patch_speechbrain()
