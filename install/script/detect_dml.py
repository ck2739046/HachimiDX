import ctypes
import uuid
from ctypes import wintypes
from dataclasses import dataclass

from .op_result import OpResult, err, ok


D3D_FEATURE_LEVEL_11_0 = 0xB000
DXGI_ADAPTER_FLAG_SOFTWARE = 0x00000002
DXGI_ERROR_NOT_FOUND = 0x887A0002
LOAD_LIBRARY_SEARCH_SYSTEM32 = 0x00000800

HRESULT = ctypes.c_long


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class _LUID(ctypes.Structure):
    _fields_ = [
        ("LowPart", wintypes.DWORD),
        ("HighPart", wintypes.LONG),
    ]


class _DXGI_ADAPTER_DESC1(ctypes.Structure):
    _fields_ = [
        ("Description", wintypes.WCHAR * 128),
        ("VendorId", wintypes.UINT),
        ("DeviceId", wintypes.UINT),
        ("SubSysId", wintypes.UINT),
        ("Revision", wintypes.UINT),
        ("DedicatedVideoMemory", ctypes.c_size_t),
        ("DedicatedSystemMemory", ctypes.c_size_t),
        ("SharedSystemMemory", ctypes.c_size_t),
        ("AdapterLuid", _LUID),
        ("Flags", wintypes.UINT),
    ]


IID_IDXGIFactory1 = _GUID.from_buffer_copy(
    uuid.UUID("770aae78-f26f-4dba-a829-253c83d1b387").bytes_le
)
IID_ID3D12Device = _GUID.from_buffer_copy(
    uuid.UUID("189819f1-1db6-4b57-be54-1821339b85f7").bytes_le
)


@dataclass(slots=True)
class dml_gpu_info:
    index: int
    gpu_name: str
    vendor_id: int
    device_id: int
    dedicated_video_memory_mib: int
    shared_system_memory_mib: int


def _hresult_code(result: int) -> int:
    return ctypes.c_uint32(result).value


def _failed(result: int) -> bool:
    return result < 0


def _get_com_method(instance, index: int, restype, *argtypes):
    vtable = ctypes.cast(
        instance,
        ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)),
    ).contents
    method_address = vtable[index]
    if not method_address:
        raise RuntimeError(f"COM vtable method {index} is unavailable")
    prototype = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)
    return prototype(method_address)


def _release_com_object(instance: ctypes.c_void_p) -> None:
    if not instance:
        return
    release = _get_com_method(instance, 2, wintypes.ULONG)
    release(instance)
    instance.value = None


def _configure_functions(dxgi, d3d12) -> None:
    dxgi.CreateDXGIFactory1.argtypes = [
        ctypes.POINTER(_GUID),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    dxgi.CreateDXGIFactory1.restype = HRESULT

    d3d12.D3D12CreateDevice.argtypes = [
        ctypes.c_void_p,
        wintypes.UINT,
        ctypes.POINTER(_GUID),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    d3d12.D3D12CreateDevice.restype = HRESULT


def _create_dxgi_factory(dxgi) -> ctypes.c_void_p:
    factory = ctypes.c_void_p()
    result = dxgi.CreateDXGIFactory1(
        ctypes.byref(IID_IDXGIFactory1),
        ctypes.byref(factory),
    )
    if _failed(result) or not factory:
        raise RuntimeError(
            f"CreateDXGIFactory1 failed with HRESULT 0x{_hresult_code(result):08X}"
        )
    return factory


def _get_adapter_desc(adapter: ctypes.c_void_p) -> _DXGI_ADAPTER_DESC1:
    get_desc1 = _get_com_method(
        adapter,
        10,
        HRESULT,
        ctypes.POINTER(_DXGI_ADAPTER_DESC1),
    )
    desc = _DXGI_ADAPTER_DESC1()
    result = get_desc1(adapter, ctypes.byref(desc))
    if _failed(result):
        raise RuntimeError(
            f"IDXGIAdapter1::GetDesc1 failed with HRESULT 0x{_hresult_code(result):08X}"
        )
    return desc


def _supports_d3d12(d3d12, adapter: ctypes.c_void_p) -> bool:
    result = d3d12.D3D12CreateDevice(
        adapter,
        D3D_FEATURE_LEVEL_11_0,
        ctypes.byref(IID_ID3D12Device),
        None,
    )
    return not _failed(result)


def _enumerate_d3d12_gpus(dxgi, d3d12) -> tuple[list[dml_gpu_info], bool]:
    factory = _create_dxgi_factory(dxgi)
    try:
        enum_adapters1 = _get_com_method(
            factory,
            12,
            HRESULT,
            wintypes.UINT,
            ctypes.POINTER(ctypes.c_void_p),
        )
        gpus = []
        hardware_adapter_seen = False
        index = 0

        while True:
            adapter = ctypes.c_void_p()
            result = enum_adapters1(factory, index, ctypes.byref(adapter))
            if _hresult_code(result) == DXGI_ERROR_NOT_FOUND:
                break
            if _failed(result) or not adapter:
                raise RuntimeError(
                    f"IDXGIFactory1::EnumAdapters1 failed at index {index} "
                    f"with HRESULT 0x{_hresult_code(result):08X}"
                )

            adapter_index = index
            index += 1
            try:
                desc = _get_adapter_desc(adapter)
                if desc.Flags & DXGI_ADAPTER_FLAG_SOFTWARE:
                    continue

                hardware_adapter_seen = True
                if not _supports_d3d12(d3d12, adapter):
                    continue

                gpus.append(
                    dml_gpu_info(
                        index=adapter_index,
                        gpu_name=desc.Description.rstrip("\0"),
                        vendor_id=desc.VendorId,
                        device_id=desc.DeviceId,
                        dedicated_video_memory_mib=desc.DedicatedVideoMemory // (1024 * 1024),
                        shared_system_memory_mib=desc.SharedSystemMemory // (1024 * 1024),
                    )
                )
            finally:
                _release_com_object(adapter)

        return gpus, hardware_adapter_seen
    finally:
        _release_com_object(factory)


def _get_dml_gpu_info(T) -> OpResult[list[dml_gpu_info]]:
    try:
        dxgi = ctypes.WinDLL("dxgi.dll", winmode=LOAD_LIBRARY_SEARCH_SYSTEM32)
        d3d12 = ctypes.WinDLL("d3d12.dll", winmode=LOAD_LIBRARY_SEARCH_SYSTEM32)
    except OSError as e:
        return err(T.detect_dml.loader_unavailable, error_raw=e)

    try:
        _configure_functions(dxgi, d3d12)
    except AttributeError as e:
        return err(T.detect_dml.api_unavailable, error_raw=e)

    try:
        gpus, hardware_adapter_seen = _enumerate_d3d12_gpus(dxgi, d3d12)
        if not hardware_adapter_seen:
            return err(T.detect_dml.no_hardware_adapters)
        if not gpus:
            return err(T.detect_dml.no_d3d12_gpu)
        return ok(gpus)
    except Exception as e:
        return err(T.detect_dml.check_failed, error_raw=e)


def detect_dml_availability(T) -> OpResult[list[dml_gpu_info]]:
    print(f"\n-----\n\n{T.detect_dml.start}\n")

    result = _get_dml_gpu_info(T)
    if not result.is_ok:
        return result

    print(T.detect_dml.gpu_detected_title)
    for gpu in result.value:
        print(
            T.detect_dml.gpu_info.format(
                index=gpu.index,
                gpu_name=gpu.gpu_name,
                dedicated_video_memory_mib=gpu.dedicated_video_memory_mib,
                shared_system_memory_mib=gpu.shared_system_memory_mib,
                vendor_id=gpu.vendor_id,
                device_id=gpu.device_id,
            )
        )

    return result
