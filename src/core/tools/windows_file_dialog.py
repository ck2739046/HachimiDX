from __future__ import annotations

import ctypes
import os
import uuid
from ctypes import wintypes


if os.name != "nt":
    raise OSError("Windows common file dialogs are only available on Windows")


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def from_string(cls, value: str) -> "_GUID":
        return cls.from_buffer_copy(uuid.UUID(value).bytes_le)


class _COMDLG_FILTERSPEC(ctypes.Structure):
    _fields_ = [("pszName", wintypes.LPCWSTR), ("pszSpec", wintypes.LPCWSTR)]


_CLSID_FILE_OPEN_DIALOG = _GUID.from_string("DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7")
_IID_FILE_OPEN_DIALOG = _GUID.from_string("D57C7288-D4AD-4768-BE02-9D969532D960")
_CLSCTX_INPROC_SERVER = 0x1
_COINIT_APARTMENTTHREADED = 0x2
_RPC_E_CHANGED_MODE = ctypes.c_long(0x80010106).value
_ERROR_CANCELLED_HRESULT = ctypes.c_long(0x800704C7).value

_FOS_PICKFOLDERS = 0x20
_FOS_FORCEFILESYSTEM = 0x40
_FOS_ALLOWMULTISELECT = 0x200
_FOS_PATHMUSTEXIST = 0x800
_FOS_FILEMUSTEXIST = 0x1000
_SIGDN_FILESYSPATH = 0x80058000

_ole32 = ctypes.OleDLL("ole32")
_ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
_ole32.CoInitializeEx.restype = ctypes.c_long
_ole32.CoUninitialize.argtypes = []
_ole32.CoUninitialize.restype = None
_ole32.CoCreateInstance.argtypes = [
    ctypes.POINTER(_GUID),
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(_GUID),
    ctypes.POINTER(ctypes.c_void_p),
]
_ole32.CoCreateInstance.restype = ctypes.c_long
_ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
_ole32.CoTaskMemFree.restype = None


def _failed(result: int) -> bool:
    return result < 0


def _check_hresult(result: int, action: str) -> None:
    if _failed(result):
        raise OSError(f"{action} failed (HRESULT 0x{result & 0xFFFFFFFF:08X})")


def _method(interface: ctypes.c_void_p, index: int, restype, *argtypes):
    vtable = ctypes.cast(interface, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    prototype = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)
    return prototype(vtable[index])


def _release(interface: ctypes.c_void_p | None) -> None:
    if interface and interface.value:
        _method(interface, 2, wintypes.ULONG)(interface)


def _shell_item_path(item: ctypes.c_void_p) -> str:
    raw_path = ctypes.c_void_p()
    get_display_name = _method(
        item,
        5,
        ctypes.c_long,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_void_p),
    )
    _check_hresult(
        get_display_name(item, _SIGDN_FILESYSPATH, ctypes.byref(raw_path)),
        "GetDisplayName",
    )
    try:
        return ctypes.wstring_at(raw_path)
    finally:
        _ole32.CoTaskMemFree(raw_path)


def open_windows_path_dialog(
    owner_hwnd: int,
    title: str,
    *,
    select_folders: bool,
    allow_multiple: bool,
    filter_name: str = "Text Files (*.txt)",
) -> list[str]:
    init_result = _ole32.CoInitializeEx(None, _COINIT_APARTMENTTHREADED)
    should_uninitialize = not _failed(init_result)
    if _failed(init_result) and init_result != _RPC_E_CHANGED_MODE:
        _check_hresult(init_result, "CoInitializeEx")

    dialog = ctypes.c_void_p()
    results = ctypes.c_void_p()
    try:
        _check_hresult(
            _ole32.CoCreateInstance(
                ctypes.byref(_CLSID_FILE_OPEN_DIALOG),
                None,
                _CLSCTX_INPROC_SERVER,
                ctypes.byref(_IID_FILE_OPEN_DIALOG),
                ctypes.byref(dialog),
            ),
            "CoCreateInstance",
        )

        options = wintypes.DWORD()
        get_options = _method(dialog, 10, ctypes.c_long, ctypes.POINTER(wintypes.DWORD))
        set_options = _method(dialog, 9, ctypes.c_long, wintypes.DWORD)
        _check_hresult(get_options(dialog, ctypes.byref(options)), "GetOptions")
        value = options.value | _FOS_FORCEFILESYSTEM | _FOS_PATHMUSTEXIST
        if allow_multiple:
            value |= _FOS_ALLOWMULTISELECT
        if select_folders:
            value = (value | _FOS_PICKFOLDERS) & ~_FOS_FILEMUSTEXIST
        else:
            value |= _FOS_FILEMUSTEXIST
        _check_hresult(set_options(dialog, value), "SetOptions")

        set_title = _method(dialog, 17, ctypes.c_long, wintypes.LPCWSTR)
        _check_hresult(set_title(dialog, title), "SetTitle")

        filter_specs = None
        if not select_folders:
            filter_specs = (_COMDLG_FILTERSPEC * 1)(
                _COMDLG_FILTERSPEC(filter_name, "*.txt")
            )
            set_file_types = _method(
                dialog,
                4,
                ctypes.c_long,
                wintypes.UINT,
                ctypes.POINTER(_COMDLG_FILTERSPEC),
            )
            _check_hresult(set_file_types(dialog, 1, filter_specs), "SetFileTypes")

        show = _method(dialog, 3, ctypes.c_long, wintypes.HWND)
        show_result = show(dialog, owner_hwnd)
        if show_result == _ERROR_CANCELLED_HRESULT:
            return []
        _check_hresult(show_result, "Show")

        get_results = _method(
            dialog,
            27,
            ctypes.c_long,
            ctypes.POINTER(ctypes.c_void_p),
        )
        _check_hresult(get_results(dialog, ctypes.byref(results)), "GetResults")

        count = wintypes.DWORD()
        get_count = _method(results, 7, ctypes.c_long, ctypes.POINTER(wintypes.DWORD))
        get_item_at = _method(
            results,
            8,
            ctypes.c_long,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.c_void_p),
        )
        _check_hresult(get_count(results, ctypes.byref(count)), "GetCount")

        paths: list[str] = []
        for index in range(count.value):
            item = ctypes.c_void_p()
            _check_hresult(get_item_at(results, index, ctypes.byref(item)), "GetItemAt")
            try:
                paths.append(_shell_item_path(item))
            finally:
                _release(item)
        return paths
    finally:
        _release(results)
        _release(dialog)
        if should_uninitialize:
            _ole32.CoUninitialize()


def select_windows_files(
    owner_hwnd: int,
    title: str,
    *,
    filter_name: str = "Text Files (*.txt)",
) -> list[str]:
    return open_windows_path_dialog(
        owner_hwnd,
        title,
        select_folders=False,
        allow_multiple=True,
        filter_name=filter_name,
    )


def select_windows_folders(owner_hwnd: int, title: str, *, multiple: bool = True) -> list[str]:
    return open_windows_path_dialog(
        owner_hwnd,
        title,
        select_folders=True,
        allow_multiple=multiple,
    )
