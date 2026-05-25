from typing import Any

from src.core.build_auto_convert_cmd import build_auto_convert_cmd
from src.core.schemas.auto_convert_model import AutoConvertModel
from src.core.schemas.op_result import OpResult, err, ok
from src.core.tools import validate_pydantic

from .. import task_scheduler_api
from ..task_scheduler import TaskType


class AutoConvertPipeline:
    _is_registered: bool = False

    @classmethod
    def init(cls) -> OpResult[None]:
        try:
            task_scheduler_api.register(
                TaskType.AUTO_CONVERT,
                concurrency=1,
            )
            cls._is_registered = True
            return ok()
        except Exception as exc:
            return err("Failed to initialize AutoConvertPipeline", error_raw=exc)






    @staticmethod
    def validate(raw_data: dict[str, Any]) -> OpResult[AutoConvertModel]:
        res = validate_pydantic(AutoConvertModel, raw_data)
        if not res.is_ok:
            return err("AutoConvertModel validation failed", inner=res)
        model = res.value
        if not isinstance(model, AutoConvertModel):
            return err("Validated model has unexpected type", error_raw=type(model))
        return ok(model)



    @staticmethod
    def build_cmd(config: Any) -> OpResult[list[str]]:
        if not isinstance(config, AutoConvertModel):
            return err("AUTO_CONVERT task config must be AutoConvertModel", error_raw=type(config))
        return build_auto_convert_cmd(config)








    @classmethod
    def submit_task(cls, raw_data: dict[str, Any], task_name: str = "") -> OpResult[tuple[str, list[str]]]:
        
        if not cls._is_registered:
            return err("AutoConvertPipeline is not initialized (not registered)")
        
        v_res = cls.validate(raw_data)
        if not v_res.is_ok:
            return err("Failed to validate auto convert task input", inner=v_res)

        cmd_res = cls.build_cmd(v_res.value)
        if not cmd_res.is_ok:
            return err("Failed to build auto convert command", inner=cmd_res)

        rid_res = task_scheduler_api.submit_task(
            TaskType.AUTO_CONVERT,
            cmd_res.value,
            task_name=task_name or v_res.value.song_name,
        )
        if not rid_res.is_ok:
            return err("Failed to submit task to scheduler", inner=rid_res)

        return ok((rid_res.value, cmd_res.value))
