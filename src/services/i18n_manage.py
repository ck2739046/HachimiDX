import os

import i18n

from src.core.schemas.op_result import OpResult, err, ok

from .path_manage import PathManage
from .settings_manage import SettingsManage

SETTINGS_PATH = PathManage.SETTINGS_PATH
LOCALES_DIR = PathManage.LOCALES_DIR


class I18nManage:
    # worker 子进程通过该环境变量继承 UI 进程的语言设置 (QProcess 会继承父进程环境变量)
    LOCALE_ENV_VAR = "HACHIMIDX_LOCALE"

    @staticmethod
    def init() -> OpResult[None]:

        fallback_language = "en_US"

        # 从 settings 获取语言设置
        result = SettingsManage.get("language")
        if result.is_ok:
            language = result.value
        else:
            print(
                f"--Warning: I18nInit: Failed to get language setting from configuration, using fallback '{fallback_language}'."
            )
            language = fallback_language

        # 检查语言文件是否存在
        fallback_file = os.path.join(LOCALES_DIR, f"{fallback_language}.yaml")
        selected_file = os.path.join(LOCALES_DIR, f"{language}.yaml")

        if language != fallback_language:
            if not os.path.isfile(selected_file):
                print(
                    f"--Warning: I18nInit: Language file for '{language}' not found, falling back to '{fallback_language}'."
                )

        if not os.path.isfile(fallback_file):
            return err(
                f"Critical Error: I18nInit: Fallback language file not found: '{fallback_file}'."
            )

        # 初始化 i18n 模块
        i18n.load_path.append(LOCALES_DIR)
        i18n.set("filename_format", "{locale}.yaml")
        i18n.set("locale", language)
        i18n.set("fallback", "en_US")  # fallback

        # 导出给 worker 子进程继承
        os.environ[I18nManage.LOCALE_ENV_VAR] = language

        return ok()

    @staticmethod
    def init_headless() -> None:
        """
        worker 子进程用: 不依赖 SettingsManage, 只按环境变量里的 locale 初始化。

        环境变量缺失时回退 en_US (此时 i18n.t 会原样返回 key, 不会抛异常)。
        """

        language = os.environ.get(I18nManage.LOCALE_ENV_VAR, "").strip() or "en_US"

        i18n.load_path.append(LOCALES_DIR)
        i18n.set("filename_format", "{locale}.yaml")
        i18n.set("locale", language)
        i18n.set("fallback", "en_US")
