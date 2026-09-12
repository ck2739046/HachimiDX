from typing import Any, Dict, Optional, Type
from pydantic import BaseModel, ValidationError
from ..schemas.op_result import OpResult, ok, err



def validate_pydantic(model_class: Type[BaseModel],
                      raw_data: Dict[str, Any],
                      context: Optional[Dict[str, Any]] = None
                     ) -> OpResult[BaseModel]:
    
    """
    执行验证逻辑
    
    Args:
        model_class: Pydantic 模型类
        raw_data: 待验证的原始字典数据
        context: (可选) 传递给 Pydantic validator 的上下文信息: ValidationInfo.context

    Returns:
        OpResult[BaseModel]: 模型实例
    """
    
    def format_error(error_input: ValidationError) -> str:
        return '\n'.join(
            f"[{'.'.join(str(loc) for loc in error['loc'])}] {error['msg']}"
            for error in error_input.errors()
        )

    
    try:
        # 如果 context 为 None，Pydantic 内部会按无上下文处理
        instance = model_class.model_validate(raw_data, context=context)
        return ok(instance)
    except ValidationError as e:
        # Pydantic 验证错误
        return err(
            error_msg = "Pydantic validation failed",
            error_raw = format_error(e)
        )
    except Exception as e:
        # 其他异常
        return err(
            error_msg = "Unexpected error during pydantic validation",
            error_raw = e
        )
