from ultralytics import YOLO
import sys
import os


def convert_to_tensorRT(model_path, task, batch):
    
    try:
        batch = int(batch)
        if batch < 1:
            print("Batch size must be at least 1.")
            return
        
        print(f"Converting to TensorRT with batch size {batch}...")

        model = YOLO(model_path, task=task)
        model.export(format="engine",
                    imgsz=960,
                    half=True,
                    dynamic=True,
                    simplify=True,
                    workspace=None,
                    batch=batch)
        
        return True
        
    except Exception as e:
        print(f"Error during TensorRT conversion: {e}")
        return False



def convert_to_onnx(model_path, task, batch):

    try:
        batch = int(batch)
        if batch < 1:
            print("Batch size must be at least 1.")
            return
        
        print(f"Converting to ONNX with batch size {batch}...")

        model = YOLO(model_path, task=task)
        model.export(format="onnx",
                    opset=20,
                    half=True,
                    dynamic=True,
                    simplify=True,
                    batch=batch)
        
        return True
        
    except Exception as e:
        print(f"Error during ONNX conversion: {e}")
        return False        
    
        


if __name__ == "__main__":
    
    model_path = r"D:\git\aaa-HachimiDX-Convert\src\resources\models\detect.pt"
    task = "detect"
    batch = 4

    # 笔记本 12700h + rtx 3060 6g, ram 40g

    # detect > engine
    # batch 1 3.5g 2.9g
    # batch 2 3.8g 3.3g
    # batch 4 4.4g 5.2g 偶尔tactics失败
    # batch 6 5.6g 5.5g 经常tactics失败

    # obb > engine
    # batch 1 2.2g 2.0g
    # batch 2 2.5g 2.3g
    # batch 4 2.8g 2.8g
    # batch 6 3.8g 3.6g


    convert_to_onnx(model_path, task, batch)


# [03/13/2026-13:17:50] [TRT] [W] Requested amount of GPU memory (2833252352 bytes) could not be allocated. There may not be enough free memory for allocation to succeed.
# [03/13/2026-13:17:50] [TRT] [W] UNSUPPORTED_STATE: Skipping tactic 28 due to insufficient memory on requested size of 2833252352 detected for tactic 0x0000000204040736.
# [03/13/2026-13:17:50] [TRT] [E] [virtualMemoryBuffer.cpp::nvinfer1::StdVirtualMemoryBufferImpl::resizePhysical::154] Error Code 2: OutOfMemory (Requested size was 2833252352 bytes.)
# [03/13/2026-13:17:50] [TRT] [E] [virtualMemoryBuffer.cpp::nvinfer1::StdVirtualMemoryBufferImpl::resizePhysical::154] Error Code 2: OutOfMemory (Requested size was 2833252352 bytes.)       

# [03/13/2026-13:19:13] [TRT] [W] Requested amount of GPU memory (3541041152 bytes) could not be allocated. There may not be enough free memory for allocation to succeed.
# [03/13/2026-13:19:13] [TRT] [W] UNSUPPORTED_STATE: Skipping tactic 233 due to insufficient memory on requested size of 3541041152 detected for tactic 0x000000020a0a02c0.
# [03/13/2026-13:19:13] [TRT] [E] [virtualMemoryBuffer.cpp::nvinfer1::StdVirtualMemoryBufferImpl::resizePhysical::154] Error Code 2: OutOfMemory (Requested size was 3541041152 bytes.)
# [03/13/2026-13:19:13] [TRT] [E] [virtualMemoryBuffer.cpp::nvinfer1::StdVirtualMemoryBufferImpl::resizePhysical::141] Error Code 1: Cuda Driver (In nvinfer1::StdVirtualMemoryBufferImpl::resizePhysical at optimizer/builder/virtualMemoryBuffer.cpp:141)


'''
[03/24/2026-21:58:56] [TRT] [I] Loaded engine size: 14 MiB

[03/24/2026-21:58:56] [TRT] [I] [MemUsageChange] TensorRT-managed allocation in IExecutionContext creation: CPU +0, GPU +116, now: CPU 0, GPU 126 (MiB)

[03/24/2026-21:58:57] [TRT] [W] WARNING The logger passed into createInferRuntime differs from one already registered for an existing builder, runtime, or refitter. So the current new logger is ignored, and TensorRT will use the existing one which is returned by nvinfer1::getLogger() instead.

[03/24/2026-21:58:57] [TRT] [I] Loaded engine size: 14 MiB

[03/24/2026-21:58:57] [TRT] [I] [MemUsageChange] TensorRT-managed allocation in IExecutionContext creation: CPU +0, GPU +121, now: CPU 0, GPU 258 (MiB)
'''
