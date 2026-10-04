"""
行首拍号注释 (|| 23+1/96) 回归测试

对拍对象: src/core/auto_rechart/analyze/maidata_write.py 的
  - _format_bar_position()  行首位置 -> 注释文本
  - _LayoutEngine._emit()   注释插入 / 连续去重 / 整数行规则

规则:
  1. 注释格式: 整数行首写作 "|| 14.0"; 非整数行首写作 "|| 23+1/96" (加号后无空格)
  2. 第一行永远不写注释
  3. 谱面各行行首全是整数 -> 一条注释都不写 (不会出现 "|| 2.0")
  4. 出现小数行首之后, 行首小数部分与上一行不同就写注释;
     因此"小数行首之后遇到的整数行"会写作 "|| 9.0" / "|| 14.0", 最后一行同样按此规则写
  5. 连续多行小数部分完全一致时, 只有第一行写 (例: 4+1/2, 5+1/2 只写一次)
  6. 空行 / "||" 开头的行直接跳过: 不写注释, 也不参与连续判定

用法:
    python test/test_line_start_comment.py
"""

import re
import sys
import types as _types
from fractions import Fraction
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# stub 掉 shared_context 的重依赖 (cv2 等), 与 equiv_gap_configs.py 保持一致
_SHARED_CTX_MOD = "src.core.auto_rechart.analyze.shared_context"
sys.modules[_SHARED_CTX_MOD] = _types.ModuleType(_SHARED_CTX_MOD)

from src.core.auto_rechart.analyze.maidata_generate import MaidataItem
from src.core.auto_rechart.analyze.maidata_write import (
    _format_bar_position,
    _LayoutEngine,
)

_COMMENT_RE = re.compile(r"^\|\| ")


def _strip_comments(text: str) -> list[str]:
    """去掉行首拍号注释行, 返回剩余行"""
    return [ln for ln in text.split("\n") if not _COMMENT_RE.match(ln)]


def _comment_labels(text: str) -> list[str]:
    """返回按出现顺序排列的拍号注释文本 (不含 "|| " 前缀)"""
    return [ln[3:] for ln in text.split("\n") if _COMMENT_RE.match(ln)]


def _anchors_and_gaps(items: list[MaidataItem]):
    """
    复刻 _LayoutEngine.layout 的 anchor / gap 计算 (仅用于手工推导期望值)

    anchor = (time, bpm_text, note_text), 同 time 的音符用 "/" 连接;
    gap_list = [leading, anchor0->anchor1, ..., trailing]。
    """
    anchors = []
    for it in items:
        if anchors and anchors[-1][0] == it.time:
            time, bpm, note = anchors[-1]
            if it.is_bpm and not bpm:
                bpm = it.content
            elif not it.is_bpm:
                note = f"{note}/{it.content}" if note else it.content
            anchors[-1] = (time, bpm, note)
        else:
            anchors.append(
                (
                    it.time,
                    it.content if it.is_bpm else "",
                    "" if it.is_bpm else it.content,
                )
            )
    n = len(anchors)
    gap_list = [anchors[0][0]]
    for i in range(n - 1):
        gap_list.append(anchors[i + 1][0] - anchors[i][0])
    last = anchors[-1][0]
    gap_list.append(Fraction(last.numerator // last.denominator + 1) - last)
    return anchors, gap_list


class _Checker:
    def __init__(self, name: str):
        self.name = name
        self.total = 0
        self.failed = 0

    def check(self, cond: bool, detail: str) -> None:
        self.total += 1
        if not cond:
            self.failed += 1
            print(f"  FAIL: {detail}")


def _emit(anchors, gap_list, seg_map, line_ranges, line_starts) -> str:
    return _LayoutEngine._emit(anchors, gap_list, seg_map, line_ranges, line_starts)


def _synthetic_emit(positions: list[Fraction], text_by_idx: dict) -> str:
    """用给定的行首位置序列直接驱动 _emit (每行一个 anchor, 无 seg_map)"""
    anchors = [
        (pos, "", text_by_idx.get(i, chr(65 + i))) for i, pos in enumerate(positions)
    ]
    line_ranges = [(i, i) for i in range(len(positions))]
    gap_list = [Fraction(0)] * (len(positions) + 1)
    return _emit(anchors, gap_list, {}, line_ranges, positions)


def test_format_bar_position(c: _Checker) -> None:
    cases = [
        (Fraction(0), "0.0"),
        (Fraction(23), "23.0"),
        (Fraction(23) + Fraction(1, 96), "23+1/96"),
        (Fraction(23) + Fraction(4, 384), "23+1/96"),
        (Fraction(1, 384), "0+1/384"),
        (Fraction(3, 2), "1+1/2"),
        (Fraction(47, 8), "5+7/8"),
    ]
    for pos, expected in cases:
        got = _format_bar_position(pos)
        c.check(
            got == expected,
            f"_format_bar_position({pos}) = {got!r}, want {expected!r}",
        )


def test_all_integer_lines_no_comment(c: _Checker) -> None:
    """规则 2: 行首全是整数 -> 没有任何注释 (不会写出 "|| 2.0" 之类)"""
    positions = [Fraction(0), Fraction(1), Fraction(2), Fraction(5), Fraction(9)]
    body = _synthetic_emit(positions, {})
    expected = ["A", "B", "C", "D", "E", "{1},,,E"]
    c.check(
        body == "".join(m + "\n" for m in expected[:-1]) + "{1},,,E",
        f"all-integer chart must have no comment, got {body!r}",
    )
    c.check(_comment_labels(body) == [], "no comment label expected")


def test_user_example(c: _Checker) -> None:
    """
    用户给出的例子: 1, 2, 3, 4+1/2, 5+1/2, 7+1/8, 9, 10, 12+1/8, 14

    期望在 4+1/2, 7+1/8, 9, 12+1/8, 14 这 5 行打印注释。
    """
    positions = [
        Fraction(0),
        Fraction(1),
        Fraction(2),
        Fraction(9, 2),  # 4+1/2
        Fraction(11, 2),  # 5+1/2
        Fraction(57, 8),  # 7+1/8
        Fraction(9),
        Fraction(10),
        Fraction(97, 8),  # 12+1/8
        Fraction(14),
    ]
    body = _synthetic_emit(positions, {})
    labels = _comment_labels(body)
    c.check(
        labels == ["4+1/2", "7+1/8", "9.0", "12+1/8", "14.0"],
        f"user example labels mismatch: {labels}",
    )

    # 注释必须逐行紧跟在对应正文行之前
    lines = body.split("\n")
    expected_lines = [
        "A",  # 行首 0 (首行, 永不注释)
        "B",  # 行首 1 (整数, 与上一行同为整数: 不写)
        "C",  # 行首 2 (整数, 同上)
        "|| 4+1/2",
        "D",  # 行首 4+1/2 (首个小数行首)
        "E",  # 行首 5+1/2, 与上一行小数部分相同: 不重复
        "|| 7+1/8",
        "F",  # 行首 7+1/8, 小数部分变了
        "|| 9.0",  # 小数后遇到的整数行: 打印为 xxx.0
        "G",  # 行首 9
        "H",  # 行首 10, 小数部分与上一行同为 0: 不重复
        "|| 12+1/8",
        "I",  # 行首 12+1/8
        "|| 14.0",  # 末行也按规则写 (小数部分 0 != 1/8)
        "J",  # 行首 14
        "{1},,,E",
    ]
    c.check(
        lines == expected_lines,
        f"user example line layout mismatch:\n    got  = {lines!r}"
        f"\n    want = {expected_lines!r}",
    )


def test_frac_then_integer_rule(c: _Checker) -> None:
    """规则 3 的边界: 小数 -> 整数(写) -> 同小数连续(只写一次) -> 换小数(写) -> 末行整数(写)"""
    positions = [
        Fraction(0),  # 首行: 永不写
        Fraction(1, 2),  # 0+1/2 (首个小数)
        Fraction(1, 2),  # 同小数: 不写
        Fraction(1, 4),  # 0+1/4
        Fraction(1),  # 整数 1: 小数部分变了 -> 写 "1.0"
        Fraction(1),  # 上一行也是整数且小数相同: 不写
        Fraction(5, 4),  # 1+1/4
        Fraction(2),  # 末行整数: 也写 "2.0"
    ]
    labels = _comment_labels(_synthetic_emit(positions, {}))
    c.check(
        labels == ["0+1/2", "0+1/4", "1.0", "1+1/4", "2.0"],
        f"frac/integer rule labels mismatch: {labels}",
    )


def test_emit_skip_empty_and_comment_lines(c: _Checker) -> None:
    """
    空行 / "||" 开头的行必须被跳过

    跳过意味着: 该行本身不输出也不写注释, 也不参与"连续同小数"判定
    (即跳过它之后, 上一行的行首仍作为比较基准)。
    """
    positions = [
        Fraction(0),
        Fraction(1, 2),
        Fraction(1, 2),
        Fraction(1, 2),
        Fraction(3),
    ]
    line_ranges = [(i, i) for i in range(5)]
    gap_list = [Fraction(0)] * 6

    for skip_text in ("", "|| x"):
        anchors = [
            (Fraction(0), "", "A"),  # 正文首行: 不注释
            (Fraction(1, 2), "", skip_text),  # 被跳过的行
            (Fraction(1, 2), "", "B"),  # 行首 1/2: 与首行 0 不同 -> 写
            (Fraction(1, 2), "", "C"),  # 与上一行同小数: 不重复
            (Fraction(3), "", "D"),  # 行首 3: 与上一行小数不同 -> 写
        ]
        got = _emit(anchors, gap_list, {}, line_ranges, positions).split("\n")
        expected = ["A", "|| 0+1/2", "B", "C", "|| 3.0", "D", "{1},,,E"]
        c.check(
            got == expected,
            f"skip_text={skip_text!r} mismatch:\n    got  = {got!r}"
            f"\n    want = {expected!r}",
        )

    # 被跳过的空行本身不能出现在输出里; 之后仍以 B 的行首为基准
    body = _emit(
        [
            (Fraction(0), "", "A"),
            (Fraction(1, 2), "", "B"),
            (Fraction(1, 2), "", ""),  # 空行 (跳过), 其后没有正文行了
        ],
        [Fraction(0)] * 4,
        {},
        [(0, 0), (1, 1), (2, 2)],
        [Fraction(0), Fraction(1, 2), Fraction(1, 2)],
    )
    c.check(
        body == "A\n|| 0+1/2\nB\n{1},,,E",
        f"skipped empty line must not be emitted, got {body!r}",
    )


def test_emit_short_charts(c: _Checker) -> None:
    """单行谱面无注释; 两行谱面按"小数部分变化"规则判断"""
    # 单行: 位置是小数, 但它是首行 (也是末行)
    body = _emit(
        [(Fraction(3, 2), "", "A")],
        [Fraction(3, 2)],
        {},
        [(0, 0)],
        [Fraction(3, 2)],
    )
    c.check(
        body == "A\n{1},,,E",
        f"single line chart should have no comment, got {body!r}",
    )

    # 两行: 首行小数 1/2, 末行整数 3 -> 小数部分变化, 末行写注释 "3.0"
    positions = [Fraction(1, 2), Fraction(3)]
    anchors = [(positions[0], "", "A"), (positions[1], "", "B")]
    body = _emit(anchors, [Fraction(0)] * 3, {}, [(0, 0), (1, 1)], positions)
    c.check(
        body == "A\n|| 3.0\nB\n{1},,,E",
        f"two line chart layout mismatch, got {body!r}",
    )

    # 两行: 首行与末行都是整数 -> 一条注释都没有
    positions = [Fraction(0), Fraction(3)]
    anchors = [(positions[0], "", "A"), (positions[1], "", "B")]
    body = _emit(anchors, [Fraction(0)] * 3, {}, [(0, 0), (1, 1)], positions)
    c.check(
        body == "A\nB\n{1},,,E",
        f"integer-only two line chart must have no comment, got {body!r}",
    )


def test_end_to_end_layout(c: _Checker) -> None:
    """端到端: 手工推导 anchor/gap/行首, 与 layout 输出逐行对拍"""
    # 输入按时间排序 (真实数据来自 generate_maidata 的排序结果),
    # 大间隔让第 2/3 行从 9/2、15/2 换行 (小数行首)
    items = [
        MaidataItem(Fraction(0), "A"),
        MaidataItem(Fraction(1, 2), "B"),
        MaidataItem(Fraction(3), "C"),
        MaidataItem(Fraction(9, 2), "D"),
        MaidataItem(Fraction(5), "E"),
        MaidataItem(Fraction(15, 2), "F"),
        MaidataItem(Fraction(9), "G"),
    ]

    anchors, gap_list = _anchors_and_gaps(items)
    c.check(
        [a[0] for a in anchors]
        == [
            Fraction(0),
            Fraction(1, 2),
            Fraction(3),
            Fraction(9, 2),
            Fraction(5),
            Fraction(15, 2),
            Fraction(9),
        ],
        f"unexpected anchors: {anchors}",
    )
    c.check(
        gap_list
        == [
            Fraction(0),
            Fraction(1, 2),
            Fraction(5, 2),
            Fraction(3, 2),
            Fraction(1, 2),
            Fraction(5, 2),
            Fraction(3, 2),
            Fraction(1),
        ],
        f"unexpected gap list: {gap_list}",
    )
    # 行范围 [(0,0), (1,2), (3,4), (5,6)]
    #   -> 行首 [0, 1, 9/2, 15/2], 对应小数部分 [0, 0, 1/2, 1/2]
    #   -> 首行 (0) 不写
    #   -> 第 1 行 (行首 1) 小数 0 == 上一行 0 -> 不写
    #   -> 第 2 行 (行首 9/2) 小数 1/2 != 0 -> 写 "|| 4+1/2"
    #   -> 第 3 行 (行首 15/2) 小数同为 1/2 -> 不重复
    #   -> 第 4 行 (行首 9) 小数 0 != 1/2 -> 写 "|| 9.0"

    engine = _LayoutEngine()
    body = engine.layout(items)
    lines = body.split("\n")
    labels = _comment_labels(body)

    c.check(lines[-1] == "{1},,,E", f"missing terminator, got {lines[-1]!r}")
    c.check(
        labels == ["4+1/2", "9.0"],
        f"expected comment labels ['4+1/2', '9.0'], got {labels}",
    )
    c.check(
        lines
        == [
            "{2}A,B,{1},,",
            "{1}C,{2},",
            "|| 4+1/2",
            "{2}D,{1}E,,{2},",
            "{2}F,{1},",
            "|| 9.0",
            "{1}G,",
            "{1},,,E",
        ],
        f"unexpected body layout: {body!r}",
    )

    for label in labels:
        c.check(
            re.fullmatch(r"\d+\.0|\d+\+\d+/\d+", label) is not None,
            f"comment label malformed: {label!r}",
        )
    c.check(
        not _COMMENT_RE.match(lines[0]),
        "first body line must not be preceded by a comment",
    )
    body_only = _strip_comments(body)
    c.check(
        body_only[-1] == "{1},,,E",
        f"stripped body should keep terminator, got {body_only[-1]!r}",
    )
    c.check(
        sum(1 for ln in lines if ln) - len(labels) == len(body_only),
        "comment lines must not swallow or split body lines",
    )


def test_reachability_of_fractional_line_start(c: _Checker) -> None:
    """
    构造"首行之后以小数位置换行"的最小谱面, 确认注释落在正文行之前

    anchor 时间 [3/2, 5/2, 7/2], gap [3/2, 1, 1, 1/2]
      -> 行范围 [(0,0), (1,1), (2,2)], 行首 [3/2, 5/2, 7/2]
      -> 首行 (3/2) 永不写注释
      -> 第 1 行 5/2 = 2+1/2 小数 1/2 != 首行小数 1/2? 相同 -> 不写
      -> 末行 7/2 = 3+1/2 小数同为 1/2 -> 也不写
    即: 三行小数部分全是 1/2, 只有首行之后仍相同 -> 没有任何注释
    """
    items = [
        MaidataItem(Fraction(3, 2), "A"),
        MaidataItem(Fraction(5, 2), "B"),
        MaidataItem(Fraction(7, 2), "C"),
    ]
    engine = _LayoutEngine()
    body = engine.layout(items)
    print("\n[样例输出]")
    for ln in body.split("\n"):
        if ln:
            print(f"  {ln}")

    c.check(
        body == "{1},{2},{1}A,\n{1}B,\n{2}C,\n{1},,,E",
        f"unexpected reachability output: {body!r}",
    )
    c.check(
        _comment_labels(body) == [],
        f"all-equal fractional starts need no comment, got {_comment_labels(body)}",
    )

    # 换一个"小数部分会变化"的版本, 确认注释确实落在对应正文行之前
    # 行首 [3/2, 5/2, 15/4]: 首行 3/2 不写; 5/2 小数 1/2 与首行相同 -> 不写;
    # 15/4 小数 3/4 != 1/2 -> 写 "|| 3+3/4"
    items = [
        MaidataItem(Fraction(3, 2), "A"),
        MaidataItem(Fraction(5, 2), "B"),
        MaidataItem(Fraction(15, 4), "C"),
    ]
    body = engine.layout(items)
    print("\n[样例输出 2]")
    for ln in body.split("\n"):
        if ln:
            print(f"  {ln}")
    c.check(
        body == "{1},{2},{1}A,\n{4}B,,,,,\n|| 3+3/4\n{4}C,\n{1},,,E",
        f"unexpected second output: {body!r}",
    )
    c.check(
        _comment_labels(body) == ["3+3/4"],
        f"expected comment '3+3/4', got {_comment_labels(body)}",
    )
    lines = body.split("\n")
    comment_at = lines.index("|| 3+3/4")
    c.check(
        comment_at > 0 and not _COMMENT_RE.match(lines[comment_at + 1]),
        f"comment must precede a body line, got {lines[comment_at : comment_at + 2]!r}",
    )


def main() -> None:
    # 中文输出在 cp936 控制台下可能抛 UnicodeEncodeError
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    checkers = [
        (_Checker("_format_bar_position"), test_format_bar_position),
        (_Checker("全整数无注释"), test_all_integer_lines_no_comment),
        (_Checker("用户例子"), test_user_example),
        (_Checker("小数后整数行规则"), test_frac_then_integer_rule),
        (_Checker("_emit 跳过空行/注释行"), test_emit_skip_empty_and_comment_lines),
        (_Checker("_emit 单行/两行谱面"), test_emit_short_charts),
        (_Checker("layout 端到端"), test_end_to_end_layout),
        (_Checker("小数行首可达性"), test_reachability_of_fractional_line_start),
    ]

    total = 0
    failed = 0
    for checker, fn in checkers:
        print(f"\n=== {fn.__name__} ===")
        fn(checker)
        status = "PASS" if checker.failed == 0 else f"FAIL ({checker.failed})"
        print(f"  -> {status}  ({checker.total} checks)")
        total += checker.total
        failed += checker.failed

    print(f"\n{'=' * 50}")
    print(f"checks: {total}   failures: {failed}")
    if failed == 0:
        print("ALL PASS - (行首拍号注释)")
    else:
        print("FAIL")
        sys.exit(1)


if __name__ == "__main__":
    main()
