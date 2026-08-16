import ctypes
import sys
import uuid

from .common import DeviceResult, check_torch_installed


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def from_string(cls, value: str):
        result = cls()
        raw = uuid.UUID(value).bytes_le
        ctypes.memmove(ctypes.byref(result), raw, len(raw))
        return result


class _DmlTensorDataTypeQuery(ctypes.Structure):
    _fields_ = [("DataType", ctypes.c_int)]


class _DmlTensorDataTypeSupport(ctypes.Structure):
    _fields_ = [("IsSupported", ctypes.c_int)]


def _com_method(pointer, index, restype, *argtypes):
    vtable = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    prototype = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)
    return prototype(restype, ctypes.c_void_p, *argtypes)(vtable[index])


def _release_com(pointer) -> None:
    if pointer and pointer.value:
        _com_method(pointer, 2, ctypes.c_ulong)(pointer)


def query_directml_fp16_support(adapter_index: int) -> bool:
    # 创建 DXGI/D3D12/DirectML 设备并查询 FLOAT16 数据类型能力
    # 不创建推理会话
    if sys.platform != "win32":
        return False

    factory = ctypes.c_void_p()
    adapter = ctypes.c_void_p()
    d3d_device = ctypes.c_void_p()
    dml_device = ctypes.c_void_p()
    try:
        dxgi = ctypes.WinDLL("dxgi.dll")
        d3d12 = ctypes.WinDLL("d3d12.dll")
        directml = ctypes.WinDLL("DirectML.dll")

        iid_factory = _GUID.from_string("770aae78-f26f-4dba-a829-253c83d1b387")
        iid_d3d_device = _GUID.from_string("189819f1-1db6-4b57-be54-1821339b85f7")
        iid_dml_device = _GUID.from_string("6dbd6437-96fd-423f-a98c-ae5e7c2a573f")

        create_factory = dxgi.CreateDXGIFactory1
        create_factory.argtypes = [ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p)]
        create_factory.restype = ctypes.c_long
        if create_factory(ctypes.byref(iid_factory), ctypes.byref(factory)) < 0:
            return False

        enum_adapters = _com_method(
            factory,
            12,
            ctypes.c_long,
            ctypes.c_uint,
            ctypes.POINTER(ctypes.c_void_p),
        )
        if enum_adapters(factory, adapter_index, ctypes.byref(adapter)) < 0:
            return False

        create_d3d_device = d3d12.D3D12CreateDevice
        create_d3d_device.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.POINTER(_GUID),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        create_d3d_device.restype = ctypes.c_long
        if create_d3d_device(
            adapter,
            0xB000,
            ctypes.byref(iid_d3d_device),
            ctypes.byref(d3d_device),
        ) < 0:
            return False

        create_dml_device = directml.DMLCreateDevice
        create_dml_device.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.POINTER(_GUID),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        create_dml_device.restype = ctypes.c_long
        if create_dml_device(
            d3d_device,
            0,
            ctypes.byref(iid_dml_device),
            ctypes.byref(dml_device),
        ) < 0:
            return False

        query = _DmlTensorDataTypeQuery(DataType=2)
        support = _DmlTensorDataTypeSupport()
        check_feature_support = _com_method(
            dml_device,
            7,
            ctypes.c_long,
            ctypes.c_int,
            ctypes.c_uint,
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_void_p,
        )
        result = check_feature_support(
            dml_device,
            0,
            ctypes.sizeof(query),
            ctypes.byref(query),
            ctypes.sizeof(support),
            ctypes.byref(support),
        )
        return result >= 0 and bool(support.IsSupported)
    except (AttributeError, OSError, ValueError):
        return False
    finally:
        _release_com(dml_device)
        _release_com(d3d_device)
        _release_com(adapter)
        _release_com(factory)






def check() -> list[DeviceResult] | None:

    ok, _ = check_torch_installed()
    if not ok:
        return None

    try:
        import onnxruntime as ort
        print(f"ONNX Runtime installed, version {ort.__version__}")
    except ImportError as e:
        print(f"ONNX Runtime is not installed: {e!r}")
        return None

    providers = ort.get_available_providers()
    print(f"Available providers: {providers}")
    if "DmlExecutionProvider" not in providers:
        print("DirectML execution provider is unavailable")
        return None
    print("DirectML execution provider is available")

    try:
        get_ep_devices = getattr(ort, "get_ep_devices", None)
        if not callable(get_ep_devices):
            print("ONNX Runtime does not support EP device enumeration")
            return None

        devices: list[DeviceResult] = []
        seen_indexes: set[int] = set()
        for ep_device in get_ep_devices():
            if getattr(ep_device, "ep_name", "") != "DmlExecutionProvider":
                continue

            hardware_device = getattr(ep_device, "device", None)
            metadata = getattr(hardware_device, "metadata", {}) or {}
            index_text = str(metadata.get("DxgiAdapterNumber", "")).strip()
            if not index_text.isdigit():
                print(f"DirectML device has no valid DXGI adapter number: {metadata}")
                continue

            index = int(index_text)
            if index in seen_indexes:
                continue
            seen_indexes.add(index)
            name = str(metadata.get("Description", "")).strip() or f"DirectML device {index}"
            devices.append(DeviceResult(
                f"dml:{index}",
                name,
                query_directml_fp16_support(index),
            ))

        if not devices:
            print("No available DirectML devices found")
            return None

        devices.sort(key=lambda item: int(item.device_id.partition(":")[2]))
        print("DirectML devices:")
        for device in devices:
            print(f"  - {device.device_id}: {device.name}, half={device.half}")
        return devices

    except Exception as e:
        print(f"Failed to read DirectML devices: {e}")
        return None
