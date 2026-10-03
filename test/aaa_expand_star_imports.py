"""把 src/ 下所有 `from X import *` 展开为显式导入。

- 被导入模块若有 __all__，只展开 __all__ 里的名字，避免把 cv2 / dataclass
  这类依赖一并转发给调用方（否则调用方会出现 F811 重复定义）
- 不做"用没用到"的判断，交给后续的 ruff --fix 处理

用法::
    python test/aaa_expand_star_imports.py            # 空跑，只打印计划
    python test/aaa_expand_star_imports.py --apply    # 实际改写文件
"""

from __future__ import annotations

import ast
import pathlib
import sys

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
SCAN_DIRS = ["test", "src", "install"]


def module_to_path(mod: str, importer: pathlib.Path) -> pathlib.Path | None:
    """把 `from X import *` 的 X 解析成实际文件路径。"""
    level = len(mod) - len(mod.lstrip("."))
    name = mod.lstrip(".")
    base = importer.parent
    for _ in range(level - 1):
        base = base.parent

    if level == 0:  # 绝对导入，如 src.core.foo
        rel = name.replace(".", "/")
        for cand in (PROJECT_ROOT / f"{rel}.py", PROJECT_ROOT / rel / "__init__.py"):
            if cand.exists():
                return cand
        return None

    if name:  # 相对导入，如 ..detect.note_definition
        rel = name.replace(".", "/")
        for cand in (base / f"{rel}.py", base / rel / "__init__.py"):
            if cand.exists():
                return cand
        return None

    cand = base / "__init__.py"  # from . import *
    return cand if cand.exists() else None


def declared_all(path: pathlib.Path) -> set[str] | None:
    """返回模块显式声明的 __all__；没有声明则返回 None。"""
    if not path.exists():
        return None
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return None
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.value, (ast.List, ast.Tuple))
            and any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets)
        ):
            return {
                e.value
                for e in node.value.elts
                if isinstance(e, ast.Constant) and isinstance(e.value, str)
            }
    return None


def public_names(path: pathlib.Path) -> list[str]:
    """有 __all__ 用它；否则取顶层 def/class/赋值 + 显式导入的名字（跳过下划线开头）。"""
    names = declared_all(path)
    if names is not None:
        return sorted(names)
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, OSError):
        return []

    out: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(node.name)
        elif isinstance(node, ast.Import):
            for a in node.names:
                out.add(a.asname or a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                if a.name != "*":
                    out.add(a.asname or a.name)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            out.add(node.target.id)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    out.add(t.id)
    return sorted(n for n in out if not n.startswith("_"))


def expand(apply: bool) -> int:
    sites = 0
    changed_files = 0

    for scan_dir in SCAN_DIRS:
        root = PROJECT_ROOT / scan_dir
        if not root.is_dir():
            print(f"跳过（目录不存在）: {scan_dir}")
            continue
        print(f"扫描目录: {scan_dir}/")
        for path in sorted(root.rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            try:
                tree = ast.parse(source)
            except SyntaxError as exc:
                print(f"  跳过（语法错误）{path}: {exc}")
                continue

            star_nodes = [
                n
                for n in tree.body
                if isinstance(n, ast.ImportFrom) and any(a.name == "*" for a in n.names)
            ]
            if not star_nodes:
                continue

            lines = source.splitlines(keepends=True)
            edits: list[tuple[int, int, str]] = []
            rel = path.relative_to(PROJECT_ROOT)

            for node in star_nodes:
                mod = ("." * node.level) + (node.module or "")
                target = module_to_path(mod, path)
                names = public_names(target) if target else []
                if not names:
                    print(f"  {rel}:{node.lineno}  {mod}  !! 无法解析出名字，跳过")
                    continue
                body = ",\n".join(f"    {n}" for n in names)
                edits.append(
                    (
                        node.lineno - 1,
                        node.end_lineno,
                        f"from {mod} import (\n{body},\n)\n",
                    )
                )
                sites += 1
                print(f"  {rel}:{node.lineno}  {mod}  -> {len(names)} names")

            if edits and apply:
                for start, end, new in sorted(edits, key=lambda e: -e[0]):
                    lines[start:end] = [new]
                path.write_text("".join(lines), encoding="utf-8")
                changed_files += 1
        print()

    print(f"星号导入处数: {sites}")
    if apply:
        print(f"改写文件数  : {changed_files}")
    else:
        print("(空跑，未改动任何文件；加 --apply 才会写入)")
    return 0 if sites else 1


if __name__ == "__main__":
    raise SystemExit(expand(apply="--apply" in sys.argv))
