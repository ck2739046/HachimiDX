"""循环导入检查：对 src/ 建模导入图，用 Tarjan 求强连通分量，打印所有循环。

用法: python test/aaa_check_import_cycles.py [-v]
退出码: 0 = 无循环；1 = 存在循环、自我导入，或有文件无法解析。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

SRC_DIR = PROJECT_ROOT / "src"


def module_name_of(path: Path) -> str:
    """src/a/b.py -> src.a.b"""
    return ".".join(path.relative_to(PROJECT_ROOT).with_suffix("").parts)


def resolve_relative(module: str, node: ast.ImportFrom) -> str:
    """把相对导入解析成绝对模块名。"""
    if not node.level:
        return node.module or ""
    package = module.split(".")[:-1]  # 去掉模块自身，得到所在包
    up = node.level - 1
    anchor = package[: len(package) - up] if up else package
    return ".".join(anchor + ([node.module] if node.module else []))


def build_graph() -> tuple[dict[str, set[str]], list[str]]:
    """返回 (导入图, 无法解析的文件)。图里只保留仓库内部 src.* 的边。"""
    graph: dict[str, set[str]] = {}
    errors: list[str] = []
    for path in sorted(SRC_DIR.rglob("*.py")):
        module = module_name_of(path)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError) as exc:
            errors.append(f"{module}: {exc}")
            graph[module] = set()
            continue
        deps: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                deps.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                resolved = resolve_relative(module, node)
                if resolved:
                    deps.add(resolved)
        graph[module] = {d for d in deps if d.startswith("src.")}
    return graph, errors


def find_cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    """Tarjan 求强连通分量，返回长度 > 1 的分量（即循环）。"""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    cycles: list[list[str]] = []
    counter = 0

    # 显式栈实现，避免深层依赖链触发 Python 递归上限
    for root in graph:
        if root in index:
            continue
        work: list[tuple[str, int]] = [(root, 0)]
        while work:
            node, child_idx = work[-1]
            if child_idx == 0:
                index[node] = low[node] = counter
                counter += 1
                stack.append(node)
                on_stack.add(node)

            children = sorted(c for c in graph.get(node, ()) if c in graph)
            if child_idx < len(children):
                work[-1] = (node, child_idx + 1)
                child = children[child_idx]
                if child not in index:
                    work.append((child, 0))
                elif child in on_stack:
                    low[node] = min(low[node], index[child])
                continue

            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[node])
            if low[node] == index[node]:
                component: list[str] = []
                while True:
                    popped = stack.pop()
                    on_stack.discard(popped)
                    component.append(popped)
                    if popped == node:
                        break
                if len(component) > 1:
                    cycles.append(sorted(component))

    return sorted(cycles)


def check(verbose: bool = False) -> int:
    graph, errors = build_graph()
    cycles = find_cycles(graph)
    self_imports = sorted(m for m, deps in graph.items() if m in deps)

    print(f"扫描目录: {SRC_DIR}")
    print(
        f"模块总数: {len(graph)}    导入边总数: {sum(len(v) for v in graph.values())}"
    )
    print()

    if errors:
        print("有文件无法解析，先修语法:")
        for item in errors:
            print(f"  {item}")
        print()

    print(f"检测到循环引用: {len(cycles)}")
    for cycle in cycles:
        print("  " + " <-> ".join(cycle))

    if self_imports:
        print(f"\n自我导入: {len(self_imports)}")
        for module in self_imports:
            print(f"  {module}")

    if verbose:
        print("\n依赖最多的模块:")
        for module, deps in sorted(graph.items(), key=lambda kv: -len(kv[1]))[:15]:
            print(f"  {len(deps):3}  {module}")

    print()
    if cycles or self_imports or errors:
        print("结果: 失败")
        return 1
    print("结果: 通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(check(verbose="-v" in sys.argv or "--verbose" in sys.argv))
