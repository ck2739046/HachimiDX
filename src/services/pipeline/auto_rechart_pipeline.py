from typing import Any

from src.core.build_auto_rechart_cmd import build_auto_rechart_cmd
from src.core.schemas.auto_rechart_model import AutoRechartModel
from src.core.schemas.op_result import OpResult, err, ok
from src.core.tools import validate_pydantic

from .. import task_scheduler_api
from ..task_scheduler import TaskType


class AutoRechartPipeline:
    _is_registered: bool = False

    @classmethod
    def init(cls) -> OpResult[None]:
        try:
            task_scheduler_api.register(
                TaskType.AUTO_RECHART,
                concurrency=1,
            )
            cls._is_registered = True
            return ok()
        except Exception as exc:
            return err("Failed to initialize AutoRechartPipeline", error_raw=exc)






    @staticmethod
    def validate(raw_data: dict[str, Any]) -> OpResult[AutoRechartModel]:
        res = validate_pydantic(AutoRechartModel, raw_data)
        if not res.is_ok:
            return err("AutoRechartModel validation failed", inner=res)
        model = res.value
        if not isinstance(model, AutoRechartModel):
            return err("Validated model has unexpected type", error_raw=type(model))
        return ok(model)



    @staticmethod
    def build_cmd(config: Any) -> OpResult[list[str]]:
        if not isinstance(config, AutoRechartModel):
            return err("AUTO_RECHART task config must be AutoRechartModel", error_raw=type(config))
        return build_auto_rechart_cmd(config)








    @classmethod
    def submit_task(cls, raw_data: dict[str, Any], task_name: str = "") -> OpResult[tuple[str, list[str]]]:
        
        if not cls._is_registered:
            return err("AutoRechartPipeline is not initialized (not registered)")
        
        v_res = cls.validate(raw_data)
        if not v_res.is_ok:
            return err("Failed to validate auto rechart task input", inner=v_res)

        cmd_res = cls.build_cmd(v_res.value)
        if not cmd_res.is_ok:
            return err("Failed to build auto rechart command", inner=cmd_res)

        rid_res = task_scheduler_api.submit_task(
            TaskType.AUTO_RECHART,
            cmd_res.value,
            task_name=task_name or v_res.value.song_name,
        )
        if not rid_res.is_ok:
            return err("Failed to submit task to scheduler", inner=rid_res)

        return ok((rid_res.value, cmd_res.value))
