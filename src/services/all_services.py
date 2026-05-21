import os

from src.core.schemas.op_result import OpResult, ok, err

from .path_manage import PathManage
from .settings_manage import SettingsManage
from .i18n_manage import I18nManage
from .pipeline.auto_convert_pipeline import AutoConvertPipeline
from .pipeline.media_pipeline import MediaPipeline
from .majdata_sync_server import VideoSyncServer
import i18n


class AllServices:

    _is_pre_initialized = False
    _is_post_initialized = False

    @classmethod
    def pre_initialize(cls) -> OpResult[None]:
        """阶段1: 前初始化（在 QApplication 创建之前调用）"""

        if cls._is_pre_initialized:
            return ok()
        
        print("Initializing all services...") # 此时i18n尚未初始化，只能英语


        # PathManage
        # 后续其他组件都依赖它提供的路径，因此必须最先初始化
        result = PathManage.init()
        if result.is_ok:
            print("PathManage initialization completed.")
        else:
            return err("Failed to initialize PathManage.", inner=result)


        # SettingsManage
        result = SettingsManage.init()
        if result.is_ok:
            print("SettingsManage initialization completed.")
        else:
            return err("Failed to initialize SettingsManager.", inner=result)
        # 应用 UI 缩放（必须在 QApplication 创建之前设置环境变量，100 = 不做处理）
        scale_result = SettingsManage.get("main_app_ui_scale")
        if scale_result.is_ok and scale_result.value != 100:
            os.environ["QT_SCALE_FACTOR"] = str(scale_result.value / 100)
        

        # I18nManage
        # 依赖 SettingsManage 获取语言设置，因此必须在 SettingsManage 之后初始化
        result = I18nManage.init()
        if result.is_ok:
            print("I18nManage initialization completed.")
        else:
            return err("Failed to initialize I18nManage.", inner=result)
        

        # Majdata sync server (global singleton)
        try:
            VideoSyncServer.get_instance()
            print("Majdata sync server initialization completed.")
        except Exception as e:
            return err(f"Failed to initialize Majdata sync server: {e}")


        cls._is_pre_initialized = True
        return ok()





    @classmethod
    def post_initialize(cls) -> OpResult[None]:
        """阶段2: 后初始化（在 QApplication 创建之后调用）"""

        if cls._is_post_initialized:
            return ok()


        # pipeline 必须在创建 QApplication 之后初始化
        # 因为内部用到了 QTimer, 依赖于 QApplication 的事件调度器
        result = MediaPipeline.init()
        if result.is_ok:
            print("MediaPipeline initialization completed.")
        else:
            return err("Failed to initialize MediaPipeline.", inner=result)

        result = AutoConvertPipeline.init()
        if result.is_ok:
            print("AutoConvertPipeline initialization completed.")
        else:
            return err("Failed to initialize AutoConvertPipeline.", inner=result)


        print(i18n.t("all_services.notice_all_initialized"))
        cls._is_post_initialized = True
        return ok()





    @classmethod
    def shutdown_all(cls) -> None:

        if not cls._is_post_initialized:
            return

        print(i18n.t("all_services.notice_shutting_down_all"))

        # 关闭顺序要反着来

        # Stop Majdata sync server
        try:
            VideoSyncServer.shutdown_instance()
        except Exception:
            pass

        print(i18n.t("all_services.notice_all_shutdown"))
        cls._is_post_initialized = False
        cls._is_pre_initialized = False
