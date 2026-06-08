"""
UI Style Configuration
提供统一的ui风格
"""

class UI_Style:

    # 配色方案
    COLORS = {
        'bg': "#303030",
        'text_primary': "#E8E8E8",
        'text_secondary': "#8D99AE",

        'light_grey': "#707070",
        'grey': "#454545",
        'grey_hover': "#505050",

        'surface': "#17203D",
        'surface_hover': "#212C47",
        
        'accent': "#2770E4",
        'accent_hover': "#3A86FF",

        'stop': "#B61D2D",
        'stop_hover': "#DC3545",

        # Task status colors (Tasks page)
        'task_pending': "#005F66",   # cyan
        'task_running': "#1F6F3D",   # green
        'task_ended': "#3D3D3D",     # gray
    }

    widget_spacing = 10
    element_height = 25
    default_text_size = 13

    output_log_widget_height = 320
    main_navbar_height = 50
    sub_navbar_height = 35
