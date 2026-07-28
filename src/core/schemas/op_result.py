import inspect
import sys
import traceback
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Optional, TypeVar, Generic

T = TypeVar('T') # 带泛型是为了让 data 有类型提示


@dataclass(slots=True)
class OpResult(Generic[T]):
    """
    全局结果对象，类似 rust 的 Result 类型。
    该对象用于表示操作的成功或失败状态，并携带相应的数据或错误信息。

    Attributes:
        is_ok (bool)
        source (str): 来源 "文件名: 函数名"
        value (Optional[T]): 成功时返回的数据（泛型）
        error_msg (str): 错误信息（面向用户/日志）
        error_raw (any): 原始错误信息（存放 Exception, 字符串, 状态码等）
        inner (Optional['OpResult[Any]']): 内部嵌套的 OpResult
    """

    # 通用
    is_ok: bool
    source: str = ""
    # 成功
    value: Optional[T] = None
    # 错误
    error_msg: str = ""
    error_raw: Any = None
    inner: Optional['OpResult[Any]'] = None


    
def _get_caller_context() -> str:
    """
    返回str 文件名: 函数名
    """
    try:
        # stack[0] 是 _get_caller_context
        # stack[1] 是 ok() 或 err()
        # stack[2] 是业务函数
        frame = inspect.stack()[2]
        return f"{frame.filename}, line {frame.lineno}, {frame.function}()"
    except Exception:
        return "unknown:unknown"



def _normalize_error_raw(error_raw: Any) -> Any:
    """
    将 exception traceback 转为字符串
    """
    if isinstance(error_raw, BaseException):
        return "".join(
            traceback.format_exception(
                type(error_raw),
                error_raw,
                error_raw.__traceback__,
            )
        ).rstrip()

    if error_raw is None:
        exc_type, exc_value, exc_tb = sys.exc_info()
        if exc_value is not None:
            return "".join(
                traceback.format_exception(exc_type, exc_value, exc_tb)
            ).rstrip()

    return error_raw



def ok(value: Optional[T] = None) -> OpResult[T]:
    """
    创建一个表示成功的 Result 对象。

    Args:
        value (Optional[T]): 成功时返回的数据

    Returns:
        OpResult[T]: 表示成功的 Result 对象
    """
    return OpResult(
        is_ok=True, 
        source=_get_caller_context(),
        value=value
    )



def err(error_msg: str = "", 
        error_raw: Any = None, 
        inner: Optional[OpResult[Any]] = None) -> OpResult[Any]:
    """
    创建一个表示失败的 Result 对象。

    Args:
        error_msg (str): 错误信息（面向用户/日志）
        error_raw (any): 原始错误信息（存放 Exception, 字符串, 状态码等）
        inner (Optional[OpResult[Any]]): 内部嵌套的 OpResult

    Returns:
        OpResult[Any]: 表示失败的 Result 对象
    """
    return OpResult(
        is_ok=False,
        source=_get_caller_context(),
        error_msg=error_msg,
        error_raw=_normalize_error_raw(error_raw),
        inner=inner
    )



def print_op_result(result: OpResult[Any], only_parse_last: bool = False) -> str:
    """
    构造 OpResult 对象的详细信息的字符串表示。
    如果有嵌套的 inner result，会递归构造。

    Args:
        result (OpResult[Any]): 要构造字符串的 OpResult 对象
        only_parse_last (bool): 是否只解析最内层的 OpResult，默认 False

    Returns:
        str: OpResult 的详细字符串表示
    """
    
    def _build_recursive(res: OpResult[Any], level: int) -> str:
        # 定义缩进，每一层增加 2 个空格
        indent = " " * 2 * level
        
        # 构建字符串
        lines = []
        
        # 视觉分割线，显示层级和简要状态
        status_icon = "✓" if res.is_ok else "✗"
        lines.append(f"{indent}{status_icon} [OpResult Level {level}]")
        
        # 添加基础属性
        lines.append(f"{indent}    - source   : {res.source}")
        lines.append(f"{indent}    - is_ok    : {res.is_ok}")
        
        # 添加所有参数
        lines.append(f"{indent}    - value    : {res.value}")
        lines.append(f"{indent}    - error_msg: {res.error_msg}")
        lines.append(f"{indent}    - error_raw: {res.error_raw}")
        
        # 处理嵌套逻辑
        if res.inner:
            lines.append(f"{indent}    - inner    : (Nested below)")
            lines.append(_build_recursive(res.inner, level + 1))
        else:
            lines.append(f"{indent}    - inner    : None")
            
        return "\n".join(lines)
    

    def _find_deepest(res: OpResult[Any]) -> OpResult[Any]:
        """找到最内层的 OpResult"""
        current = res
        while current.inner:
            current = current.inner
        return current
            

    # 如果 only_parse_last 为 True，只解析最内层的 OpResult
    if only_parse_last:
        deepest = _find_deepest(result)
        return _build_recursive(deepest, 0)
    
    
    # 开始构建字符串，初始层级为 0
    return _build_recursive(result, 0)
