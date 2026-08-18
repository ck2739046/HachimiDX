import json
import os
import tempfile
import shutil
import threading
from copy import deepcopy
from typing import Any, Optional

from src.core.schemas.op_result import OpResult, ok, err
from src.core.schemas.settings_model import SettingsModel
from src.core.tools import validate_pydantic
from .path_manage import PathManage

# 创建本地别名，避免每次都写 PathManage.xxx
SETTINGS_PATH = PathManage.SETTINGS_PATH
TEMP_DIR = PathManage.TEMP_DIR
LOCALES_DIR = PathManage.LOCALES_DIR



# 管理器实现
class SettingsManage:

    _lock = threading.RLock()
    _config: Optional[SettingsModel] = None



    @classmethod
    def init(cls) -> OpResult[None]:
        result = cls._load_or_create()
        if result.is_ok:
            cls._config = result.value
            return ok()
        else:
            return err(
                "Critical Error: Failed to initialize SettingsManage.",
                inner = result
            )



    @classmethod
    def _load_or_create(cls) -> OpResult[SettingsModel]:
        """加载配置，如果不存在或损坏则重置"""

        def try_load_json() -> dict | None:
            if not SETTINGS_PATH.is_file():
                print("--Warning: configuration file not found.")
                return None
            try:
                with open(SETTINGS_PATH, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data
            except Exception as e:
                print(f"--Warning: failed to load configuration. "
                      f"Error:\n{str(e)}")
                return None
            
        with cls._lock:
            # 1. 文件存在：尝试读取并校验
            data = try_load_json()
            if data is not None:
                need_return = True
                has_changes, need_backup, new_data = cls._check_data(data)

                # 先备份损坏的配置文件
                if need_backup:
                    backup_path = str(SETTINGS_PATH) + ".bak"
                    try:
                        shutil.copy2(SETTINGS_PATH, backup_path)
                        print(f"--Notice: Corrupted config backed up to {backup_path}")
                    except Exception as e:
                        print(f"--Warning: Failed to backup corrupted config: {str(e)}")

                # 如果有变化，说明原数据有缺失或异常项
                # new_data 是修复后的数据，尝试写入文件
                if has_changes:
                    print("--Notice: configuration file updated with per-item normalization.")
                    save_result = cls._save_to_file(new_data)
                    if not save_result.is_ok:
                        print("--Warning: failed to save normalized configuration, fallback to recreate default config.")
                        print(f"Error:\n{save_result.error_msg}\n{str(save_result.error_raw)}")
                        need_return = False
                        
                # 无变化或者变化已成功保存，尝试返回校验后的模型
                if need_return:
                    result = validate_pydantic(SettingsModel, new_data)
                    if result.is_ok:
                        return ok(result.value)



            # 2. 文件不存在，或者文件存在但读取或校验失败：创建默认配置

            print(f"--Notice: create new configuration file at {SETTINGS_PATH}")
            if os.path.exists(SETTINGS_PATH):
                os.remove(SETTINGS_PATH)
            default_model = SettingsModel()
            result = cls._save_to_file(default_model.model_dump(mode='json'))
            if result.is_ok:
                return ok(default_model)
            else:
                return err(
                    "Critical Error: Failed to create new configuration file.",
                    inner = result
                )
    



    @staticmethod
    def _check_data(input_data) -> tuple[bool, bool, dict]:

        new_input_data = deepcopy(SettingsModel().model_dump(mode="json"))
        default_data = SettingsModel().model_dump(mode='json')
        has_changes = False
        need_backup = False

        if set(input_data) - set(default_data):
            has_changes = True

        for key, default_value in default_data.items():

            # 逐项检验：如果输入有缺失项，将此项设为默认值
            if key not in input_data:
                print(f"--Warning: missing required key '{key}', reset to default.")
                new_input_data[key] = default_value
                has_changes = True
                continue

            # 逐项校验：如果输入有异常项，将此项设为默认值
            candidate = deepcopy(new_input_data)
            candidate[key] = input_data[key]
            temp_result = validate_pydantic(SettingsModel, candidate)
            if not temp_result.is_ok:
                print(f"--Warning: invalid value for key '{key}', reset to default.")
                new_input_data[key] = default_value
                has_changes = True
                need_backup = True
                continue

            normalized_data = temp_result.value.model_dump(mode="json")
            new_input_data[key] = deepcopy(normalized_data[key])

        return has_changes, need_backup, new_input_data

        

    @staticmethod
    def _save_to_file(data: dict[str, Any]) -> OpResult[None]:
        """原子化保存字典到文件"""
        temp_path = None
        try:
            os.makedirs(TEMP_DIR, exist_ok=True)
            data_json = json.dumps(data, ensure_ascii=False, indent=4)
            
            with tempfile.NamedTemporaryFile(
                mode='w', encoding='utf-8', dir=TEMP_DIR,
                delete=False, suffix='.tmp', prefix='settings_'
            ) as tf:
                tf.write(data_json)
                temp_path = tf.name

            os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
            shutil.move(temp_path, SETTINGS_PATH)
            return ok()

        except Exception as e:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)
            return err(
                error_msg = "Failed to save configuration to file.",
                error_raw = e
            )
        


    @classmethod
    def reset(cls) -> OpResult[None]:
        """重置配置到默认值：删除配置文件并重新创建"""
        with cls._lock:
            # 删除现有的配置文件
            if os.path.exists(SETTINGS_PATH):
                os.remove(SETTINGS_PATH)
            # 创建默认配置
            default_model = SettingsModel()
            result = cls._save_to_file(default_model.model_dump(mode='json'))
            if not result.is_ok:
                return err("Failed to reset configuration.", inner = result)
            # 更新内存配置
            cls._config = default_model
            return ok()



    @classmethod
    def refresh(cls) -> OpResult[None]:
        """从文件重新加载配置，刷新内存中的配置"""
        with cls._lock:
            result = cls._load_or_create()
            if result.is_ok:
                cls._config = result.value
                return ok()
            else:
                return err(
                    "Failed to refresh configuration from file.",
                    inner = result
                )



    @classmethod
    def get(cls, key: str) -> OpResult[Any]:
        """获取配置项"""
        with cls._lock:
            # worker 子进程可能未走全局服务初始化，这里做懒初始化兜底。
            if cls._config is None:
                init_res = cls.init()
                if not init_res.is_ok:
                    return err("Failed to initialize settings before get", inner=init_res)

            try:
                val = getattr(cls._config, key)
                return ok(val)
            except AttributeError as e:
                return err(f"Config item '{key}' not found", error_raw = e)
            except Exception as e:
                return err(f"Error retrieving config", error_raw = e)


    @classmethod
    def get_many(cls, keys: tuple[str, ...]) -> OpResult[dict[str, Any]]:
        with cls._lock:
            if cls._config is None:
                init_res = cls.init()
                if not init_res.is_ok:
                    return err("Failed to initialize settings before get_many", inner=init_res)

            try:
                return ok({key: deepcopy(getattr(cls._config, key)) for key in keys})
            except AttributeError as e:
                return err("Config item not found", error_raw=e)
            except Exception as e:
                return err("Error retrieving config snapshot", error_raw=e)



    @classmethod
    def set(cls, key: str, value) -> OpResult[None]:
        """设置配置项（带校验和持久化）"""
        with cls._lock:
            if cls._config is None:
                init_result = cls.init()
                if not init_result.is_ok:
                    return err("Failed to initialize settings before set", inner=init_result)
            # 获取当前配置的副本
            current_data = cls._config.model_dump(mode="json")
            # 更新副本的值
            current_data[key] = deepcopy(value)
            # 尝试创建新模型（触发校验）
            result = validate_pydantic(SettingsModel, current_data)
            if result.is_ok:
                new_config = result.value
            else:
                return err("Failed to validate configuration.", inner = result)
            # 校验通过，保存到文件
            result = cls._save_to_file(new_config.model_dump(mode='json'))
            if not result.is_ok:
                return err("Failed to save configuration.", inner = result)
            # 更新内存中的配置
            cls._config = new_config
            return ok()
