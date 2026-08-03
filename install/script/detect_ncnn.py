import ctypes
from dataclasses import dataclass

from .op_result import OpResult, err, ok


VK_SUCCESS = 0
VK_INCOMPLETE = 5
VK_STRUCTURE_TYPE_APPLICATION_INFO = 0
VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO = 1
VK_QUEUE_COMPUTE_BIT = 0x00000002
VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU = 1
VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU = 2
VK_MAX_PHYSICAL_DEVICE_NAME_SIZE = 256
VK_UUID_SIZE = 16
LOAD_LIBRARY_SEARCH_SYSTEM32 = 0x00000800


VkInstance = ctypes.c_void_p
VkPhysicalDevice = ctypes.c_void_p
VkResult = ctypes.c_int32


@dataclass(slots=True)
class ncnn_gpu_info:
    index: int
    gpu_name: str
    device_type: str
    api_version: tuple[int, int, int]
    vendor_id: int
    device_id: int


class _VkApplicationInfo(ctypes.Structure):
    _fields_ = [
        ("sType", ctypes.c_uint32),
        ("pNext", ctypes.c_void_p),
        ("pApplicationName", ctypes.c_char_p),
        ("applicationVersion", ctypes.c_uint32),
        ("pEngineName", ctypes.c_char_p),
        ("engineVersion", ctypes.c_uint32),
        ("apiVersion", ctypes.c_uint32),
    ]


class _VkInstanceCreateInfo(ctypes.Structure):
    _fields_ = [
        ("sType", ctypes.c_uint32),
        ("pNext", ctypes.c_void_p),
        ("flags", ctypes.c_uint32),
        ("pApplicationInfo", ctypes.POINTER(_VkApplicationInfo)),
        ("enabledLayerCount", ctypes.c_uint32),
        ("ppEnabledLayerNames", ctypes.c_void_p),
        ("enabledExtensionCount", ctypes.c_uint32),
        ("ppEnabledExtensionNames", ctypes.c_void_p),
    ]


class _VkPhysicalDeviceProperties(ctypes.Structure):
    # Only the stable prefix is read; this buffer receives the remaining Vulkan 1.0 fields.
    _fields_ = [
        ("apiVersion", ctypes.c_uint32),
        ("driverVersion", ctypes.c_uint32),
        ("vendorID", ctypes.c_uint32),
        ("deviceID", ctypes.c_uint32),
        ("deviceType", ctypes.c_uint32),
        ("deviceName", ctypes.c_char * VK_MAX_PHYSICAL_DEVICE_NAME_SIZE),
        ("pipelineCacheUUID", ctypes.c_uint8 * VK_UUID_SIZE),
        ("_remaining", ctypes.c_uint8 * 1024),
    ]


class _VkExtent3D(ctypes.Structure):
    _fields_ = [
        ("width", ctypes.c_uint32),
        ("height", ctypes.c_uint32),
        ("depth", ctypes.c_uint32),
    ]


class _VkQueueFamilyProperties(ctypes.Structure):
    _fields_ = [
        ("queueFlags", ctypes.c_uint32),
        ("queueCount", ctypes.c_uint32),
        ("timestampValidBits", ctypes.c_uint32),
        ("minImageTransferGranularity", _VkExtent3D),
    ]


def _make_version(major: int, minor: int, patch: int) -> int:
    return (major << 22) | (minor << 12) | patch


def _parse_version(version: int) -> tuple[int, int, int]:
    return version >> 22, (version >> 12) & 0x3FF, version & 0xFFF


def _configure_vulkan_functions(vulkan) -> None:
    vulkan.vkCreateInstance.argtypes = [
        ctypes.POINTER(_VkInstanceCreateInfo),
        ctypes.c_void_p,
        ctypes.POINTER(VkInstance),
    ]
    vulkan.vkCreateInstance.restype = VkResult

    vulkan.vkDestroyInstance.argtypes = [VkInstance, ctypes.c_void_p]
    vulkan.vkDestroyInstance.restype = None

    vulkan.vkEnumeratePhysicalDevices.argtypes = [
        VkInstance,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.POINTER(VkPhysicalDevice),
    ]
    vulkan.vkEnumeratePhysicalDevices.restype = VkResult

    vulkan.vkGetPhysicalDeviceProperties.argtypes = [
        VkPhysicalDevice,
        ctypes.POINTER(_VkPhysicalDeviceProperties),
    ]
    vulkan.vkGetPhysicalDeviceProperties.restype = None

    vulkan.vkGetPhysicalDeviceQueueFamilyProperties.argtypes = [
        VkPhysicalDevice,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.POINTER(_VkQueueFamilyProperties),
    ]
    vulkan.vkGetPhysicalDeviceQueueFamilyProperties.restype = None


def _create_instance(vulkan) -> VkInstance:
    app_info = _VkApplicationInfo(
        sType=VK_STRUCTURE_TYPE_APPLICATION_INFO,
        pNext=None,
        pApplicationName=b"HachimiDX Installer",
        applicationVersion=_make_version(1, 0, 0),
        pEngineName=None,
        engineVersion=0,
        apiVersion=_make_version(1, 0, 0),
    )
    create_info = _VkInstanceCreateInfo(
        sType=VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO,
        pNext=None,
        flags=0,
        pApplicationInfo=ctypes.pointer(app_info),
        enabledLayerCount=0,
        ppEnabledLayerNames=None,
        enabledExtensionCount=0,
        ppEnabledExtensionNames=None,
    )
    instance = VkInstance()
    result = vulkan.vkCreateInstance(ctypes.byref(create_info), None, ctypes.byref(instance))
    if result != VK_SUCCESS or not instance:
        raise RuntimeError(f"vkCreateInstance failed with VkResult {result}")
    return instance


def _enumerate_physical_devices(vulkan, instance: VkInstance) -> list[VkPhysicalDevice]:
    for _ in range(3):
        count = ctypes.c_uint32(0)
        result = vulkan.vkEnumeratePhysicalDevices(instance, ctypes.byref(count), None)
        if result != VK_SUCCESS:
            raise RuntimeError(f"vkEnumeratePhysicalDevices(count) failed with VkResult {result}")
        if count.value == 0:
            return []

        devices = (VkPhysicalDevice * count.value)()
        actual_count = ctypes.c_uint32(count.value)
        result = vulkan.vkEnumeratePhysicalDevices(instance, ctypes.byref(actual_count), devices)
        if result == VK_SUCCESS:
            return list(devices[:actual_count.value])
        if result != VK_INCOMPLETE:
            raise RuntimeError(f"vkEnumeratePhysicalDevices(list) failed with VkResult {result}")

    raise RuntimeError("Vulkan physical device list kept changing during enumeration")


def _has_compute_queue(vulkan, device: VkPhysicalDevice) -> bool:
    count = ctypes.c_uint32(0)
    vulkan.vkGetPhysicalDeviceQueueFamilyProperties(device, ctypes.byref(count), None)
    if count.value == 0:
        return False

    properties = (_VkQueueFamilyProperties * count.value)()
    vulkan.vkGetPhysicalDeviceQueueFamilyProperties(device, ctypes.byref(count), properties)
    return any(
        queue.queueCount > 0 and queue.queueFlags & VK_QUEUE_COMPUTE_BIT
        for queue in properties[:count.value]
    )


def _device_type_name(device_type: int) -> str:
    if device_type == VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU:
        return "integrated"
    if device_type == VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU:
        return "discrete"
    return "unsupported"


def _get_vulkan_gpu_info(T) -> OpResult[list[ncnn_gpu_info]]:
    try:
        vulkan = ctypes.WinDLL("vulkan-1.dll", winmode=LOAD_LIBRARY_SEARCH_SYSTEM32)
    except OSError as e:
        return err(T.detect_ncnn.loader_unavailable, error_raw=e)

    try:
        _configure_vulkan_functions(vulkan)
    except AttributeError as e:
        return err(T.detect_ncnn.api_unavailable, error_raw=e)

    instance = VkInstance()
    try:
        instance = _create_instance(vulkan)
        devices = _enumerate_physical_devices(vulkan, instance)
        if not devices:
            return err(T.detect_ncnn.no_physical_devices)

        gpus = []
        for index, device in enumerate(devices):
            properties = _VkPhysicalDeviceProperties()
            vulkan.vkGetPhysicalDeviceProperties(device, ctypes.byref(properties))

            if properties.deviceType not in {
                VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU,
                VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU,
            }:
                continue
            if not _has_compute_queue(vulkan, device):
                continue

            gpu_name = bytes(properties.deviceName).split(b"\0", 1)[0].decode("utf-8", errors="replace")
            gpus.append(
                ncnn_gpu_info(
                    index=index,
                    gpu_name=gpu_name,
                    device_type=_device_type_name(properties.deviceType),
                    api_version=_parse_version(properties.apiVersion),
                    vendor_id=properties.vendorID,
                    device_id=properties.deviceID,
                )
            )

        if not gpus:
            return err(T.detect_ncnn.no_compute_gpu)
        return ok(gpus)
    except Exception as e:
        return err(T.detect_ncnn.check_failed, error_raw=e)
    finally:
        if instance:
            vulkan.vkDestroyInstance(instance, None)


def detect_ncnn_availability(T) -> OpResult[list[ncnn_gpu_info]]:
    print(f"\n-----\n\n{T.detect_ncnn.start}\n")

    result = _get_vulkan_gpu_info(T)
    if not result.is_ok:
        return result

    print(T.detect_ncnn.gpu_detected_title)
    for gpu in result.value:
        api_version = ".".join(str(part) for part in gpu.api_version)
        device_type = T.detect_ncnn.device_types.get(gpu.device_type, gpu.device_type)
        print(
            T.detect_ncnn.gpu_info.format(
                index=gpu.index,
                gpu_name=gpu.gpu_name,
                device_type=device_type,
                api_version=api_version,
                vendor_id=gpu.vendor_id,
                device_id=gpu.device_id,
            )
        )

    return result
