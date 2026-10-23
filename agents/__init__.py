"""
Agents namespace package with automatic alias redirection from AGI_1_7 to IVA.
================================================================================
Ensures full backward compatibility for any submodules or third-party callers
attempting to import 'agents.AGI_1_7.*' by transparently redirecting to 'agents.IVA.*'.
================================================================================
"""

import sys
import importlib
import importlib.abc
import importlib.machinery

class _AliasLoader(importlib.abc.Loader):
    def __init__(self, target_name: str):
        self.target_name = target_name

    def create_module(self, spec):
        mod = importlib.import_module(self.target_name)
        sys.modules[spec.name] = mod
        return mod

    def exec_module(self, module):
        pass

class _AgentAliasFinder(importlib.abc.MetaPathFinder):
    """Transparently redirects legacy 'agents.AGI_1_7' imports to 'agents.IVA'."""
    def find_spec(self, fullname, path, target=None):
        if fullname == "agents.AGI_1_7" or fullname.startswith("agents.AGI_1_7."):
            redirected = "agents.IVA" + fullname[len("agents.AGI_1_7"):]
            try:
                target_spec = importlib.util.find_spec(redirected)
                if target_spec is None:
                    return None
                is_pkg = getattr(target_spec, "submodule_search_locations", None) is not None
                spec = importlib.machinery.ModuleSpec(
                    fullname,
                    _AliasLoader(redirected),
                    is_package=is_pkg
                )
                if is_pkg:
                    spec.submodule_search_locations = target_spec.submodule_search_locations
                return spec
            except Exception:
                return None
        return None

if not any(isinstance(f, _AgentAliasFinder) for f in sys.meta_path):
    sys.meta_path.insert(0, _AgentAliasFinder())
