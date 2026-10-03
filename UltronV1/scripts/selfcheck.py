"""Static self-check for the Ultron app package.

1. Parses every module (catches syntax errors).
2. Audits each class for references to ``self._attr`` that are never
   assigned and not defined as a method — the exact class of bug that
   crashed the first build (a bus subscription to a missing handler).
3. Validates cross-object attribute usage (``service.x``, ``hud.x``,
   ``speaker.x``, ...) against the real APIs of those classes, so a
   typo'd call between components fails the check instead of the user.

Pure AST/regex, zero imports of the app: safe to run anywhere, including
CI before packaging.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"

# Attributes owned by tkinter/stdlib base classes that our code may
# legitimately reference (we intentionally only audit our underscore
# convention for self, so this list stays tiny).
INHERITED_OK = {"_w", "_name", "_tclCommands", "_options"}

# Public tkinter/widget API used on GUI objects and their children.
TK_PUBLIC = {
    "title", "geometry", "minsize", "overrideredirect", "configure", "cget",
    "protocol", "iconbitmap", "update_idletasks", "update", "after",
    "after_cancel", "after_idle", "destroy", "withdraw", "deiconify",
    "mainloop", "transient", "grab_set", "grab_release", "resizable", "bind",
    "unbind", "pack", "pack_forget", "pack_propagate", "place", "grid",
    "winfo_screenwidth", "winfo_screenheight", "winfo_width", "winfo_height",
    "winfo_x", "winfo_y", "lift", "lower", "focus_set", "attributes",
    "bell", "state", "see", "insert", "delete", "get", "curselection",
    "selection", "tag_configure", "winfo_children", "onQuitPlaceholder",
}

LOGGER_OK = {"get", "debug", "info", "warning", "error", "exception", "critical"}
# Module-level functions of app/log.py callable as ``log.<fn>``
LOG_MODULE_OK = {"setup", "get"}

# object-variable name -> (module, class) whose API it must satisfy
OBJECT_REGISTRY = {
    "bus": ("bus.py", "EventBus"),
    "cfg": ("config.py", "Config"),
    "service": ("service.py", "AssistantService"),
    "speaker": ("tts.py", "Speaker"),
    "llm": ("llm.py", "OllamaBrain"),
    "executor": ("executor.py", "Executor"),
    "stt": ("stt.py", "SpeechEngine"),
    "hud": ("gui.py", "UltronHUD"),
    "synth": ("tts_sapi.py", "SapiSynth"),
}

# Names that are parameters of a different type in some scopes; skip them.
OBJECT_SKIP = {"cfg"}  # 'cfg' param in SapiSynth.synth is a Config -> same type; keep? we keep it.

_XREF_RE = re.compile(
    r"\b(bus|cfg|service|speaker|llm|executor|stt|hud|synth)\.([A-Za-z_][A-Za-z0-9_]*)"
)
_LOG_RE = re.compile(r"\blog\.([A-Za-z_][A-Za-z0-9_]*)")


def class_api(cls: ast.ClassDef) -> tuple[set[str], set[str]]:
    """Return (methods, assigned_attrs) for a class."""
    methods = {
        n.name
        for n in cls.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assigned: set[str] = set()

    class Visitor(ast.NodeVisitor):
        def visit_Attribute(self, node: ast.Attribute) -> None:
            if (
                isinstance(node.value, ast.Name)
                and node.value.id == "self"
                and isinstance(node.ctx, ast.Store)
            ):
                assigned.add(node.attr)
            self.generic_visit(node)

    for n in cls.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            Visitor().visit(n)
    return methods, assigned


def audit_self_refs(cls: ast.ClassDef, path: Path) -> list[str]:
    methods, assigned = class_api(cls)
    referenced: dict[str, int] = {}

    class Visitor(ast.NodeVisitor):
        def visit_Attribute(self, node: ast.Attribute) -> None:
            if isinstance(node.value, ast.Name) and node.value.id == "self":
                if isinstance(node.ctx, ast.Store):
                    assigned.add(node.attr)
                elif isinstance(node.ctx, ast.Load):
                    referenced.setdefault(node.attr, node.lineno)
            self.generic_visit(node)

    for n in cls.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            Visitor().visit(n)

    problems = []
    for attr, lineno in sorted(referenced.items(), key=lambda kv: kv[1]):
        if (
            attr.startswith("_")
            and not attr.startswith("__")
            and attr not in assigned
            and attr not in methods
            and attr not in INHERITED_OK
        ):
            problems.append(
                f"{path.relative_to(ROOT)}:{lineno}: class '{cls.name}' uses "
                f"self.{attr} but it is never assigned and no such method exists"
            )
    return problems


def strip_comments_and_strings(src: str) -> str:
    """Crude but effective: remove line comments, docstrings and string
    literals so the cross-reference scan does not match prose."""
    src = re.sub(r"#[^\n]*", "", src)
    src = re.sub(r"'''(?:.|\n)*?'''", "''''''", src)
    src = re.sub(r'"""(?:.|\n)*?"""', '""""""', src)
    src = re.sub(r"'(?:\\.|[^'\\\n])*'", "''", src)
    src = re.sub(r'"(?:\\.|[^"\\\n])*"', '""', src)
    return src


def main() -> int:
    if not APP.is_dir():
        print(f"app package not found at {APP}")
        return 1

    failures: list[str] = []
    files = sorted(APP.rglob("*.py"))
    trees: dict[Path, ast.Module] = {}

    for path in files:
        source = path.read_text(encoding="utf-8")
        try:
            trees[path] = ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            failures.append(f"{path.relative_to(ROOT)}: syntax error: {exc}")

    # ---- per-class self._attr audit -------------------------------------
    apis: dict[tuple[str, str], set[str]] = {}
    for path, tree in trees.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                failures.extend(audit_self_refs(node, path))
                methods, assigned = class_api(node)
                apis[(path.name, node.name)] = methods | assigned

    # ---- cross-object reference audit ------------------------------------
    for path in files:
        code = strip_comments_and_strings(path.read_text(encoding="utf-8"))
        rel = path.relative_to(ROOT)
        for match in _XREF_RE.finditer(code):
            var, attr = match.group(1), match.group(2)
            api = apis.get(OBJECT_REGISTRY[var])
            if api is None:
                continue
            extra = TK_PUBLIC if OBJECT_REGISTRY[var] == ("gui.py", "UltronHUD") else set()
            if attr not in api and attr not in extra:
                lineno = code[: match.start()].count("\n") + 1
                failures.append(
                    f"{rel}:{lineno}: '{var}.{attr}' does not exist on "
                    f"{OBJECT_REGISTRY[var][1]}"
                )
        for match in _LOG_RE.finditer(code):
            fn = match.group(1)
            if fn not in LOGGER_OK and fn not in LOG_MODULE_OK:
                lineno = code[: match.start()].count("\n") + 1
                failures.append(f"{rel}:{lineno}: 'log.{fn}' is not a Logger method or log-module function")

    if failures:
        print("SELF-CHECK FAILED")
        for f in failures:
            print("  -", f)
        return 1

    print(f"self-check OK — {len(files)} modules; all self/cross object references resolve")
    return 0


if __name__ == "__main__":
    sys.exit(main())
