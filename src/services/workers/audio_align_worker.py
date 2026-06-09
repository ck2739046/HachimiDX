import sys
import traceback
from pathlib import Path
import io

# 解决 Windows 控制台 Unicode 编码问题
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', write_through=True)
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace', write_through=True)



if len(sys.argv) <= 1:
    print("No root args provided. Exiting.")
    sys.exit(1)

# 第一个参数是项目根目录
# 确保能正确使用间接导入
root = str(Path(sys.argv[1]).resolve())
if root not in sys.path:
    sys.path.insert(0, root)


from src.core.audio.detect_click_start import main as detect_click_start_main
from src.core.audio.align_audio import main as align_audio_main
from src.core.audio.draw_audio_wave import main as draw_audio_wave_main

from src.core.schemas.op_result import print_op_result



def main(args: list[str]) -> bool:
    """
    1. 先调用 detect_click_start_main 检测启动拍时间
    2. 再调用 align_audio_main 计算对齐结果
    3. 最后调用 draw_audio_wave_main 绘制波形图
    
    输入:
        - is_simply_align (str): 是否仅对齐，"true" / "false"
        - reference_file (str): 基准文件路径（包含完整启动拍）
        - target_file (str): 待对齐文件路径
        - bpm (float): 启动拍的BPM值
        - click_count (int): 启动拍数量
        - click_start_time (float): 启动拍在 reference_file 中大致开始时间（秒）

    返回:
        offset_time (float): 目标文件的偏移值
                             正值: 目标比基准文件更早，需要向后移动 (加延迟)
                             负值: 目标比基准文件更晚，需要向前移动 (减延迟)
    """

    try:
        # parse args
        is_simply_align = args[0]
        reference_file = args[1]
        target_file = args[2]

        if is_simply_align.strip().lower() == "false":
            if len(args) < 6:
                print("Not enough args for non-simply align mode, exiting.")
                return False
            bpm = float(args[3])
            click_count = int(args[4])
            click_start_time = float(args[5])



        print("    Calculating...", end='\r')
        
        # 1. 调用 align_audio 分析文件对齐
        res = align_audio_main(reference_file, target_file)
        if not res.is_ok:
            # 特例: NoBackendError 仅打印 msg
            if res.error_msg.startswith("NoBackendError"):
                print(f"[AUDIO_ALIGN_WORKER] [ERROR] {res.error_msg}")
            else:
                print("[AUDIO_ALIGN_WORKER] [ERROR] Error in align_audio")
                print(print_op_result(res))
            return False
        
        target_match_offset = res.value['offset_ms']
        reference_audio = res.value['reference_audio']
        target_audio = res.value['target_audio']



        # 不执行后续动作了
        if is_simply_align.strip().lower() == "true":
            if abs(target_match_offset) < 10:
                print("Audio files are perfectly aligned (offset < 10 ms)")
            elif target_match_offset > 0:
                print(f"Target file needs delay {round(target_match_offset)} ms")
            else:
                print(f"Target file needs trim {abs(round(target_match_offset))} ms")
            return True



        # 2. 调用 detect_click_start 分析启动拍时间
        res = detect_click_start_main(reference_file, bpm, click_count, click_start_time)
        if not res.is_ok:
            print("[AUDIO_ALIGN_WORKER] [ERROR] Error in detect_click_start")
            print(print_op_result(res))
            return False
        
        template_match_offset = res.value['match_time']
        generated_click_template_audio = res.value['generated_click_template_audio']
        graph_range_start = res.value['graph_range_start']
        graph_range_end = res.value['graph_range_end']



        # if target_match_offset == 0:
        #     final_str = "reference equals target"
        # elif target_match_offset > 0:
        #     final_str = "target is earlier than reference"
        # else:
        #     final_str = "target is later than reference"
        # print(f"offset: {target_match_offset:.2f} ms ({final_str})")


        # 3. 计算最终结果
        final_offset = template_match_offset - target_match_offset

        # print(f"\n")
        # print(f"在基准文件中，启动拍从 {template_match_offset:.2f} ms 开始")
        # print(f"在基准文件中，目标文件从 {target_match_offset:.2f} ms 开始")

        if abs(final_offset) < 10:
            print("Audio files are perfectly aligned (offset < 10 ms)")
        elif final_offset > 0:
            print(f"Target file needs trim {round(final_offset)} ms")
        else:
            print(f"Target file needs delay {abs(round(final_offset))} ms")


        # 4. 生成音频波形图
        res = draw_audio_wave_main(
                reference_audio,
                generated_click_template_audio,
                target_audio,
                template_match_offset,
                target_match_offset,
                graph_range_start,
                graph_range_end
              )
        if not res.is_ok:
            print("[AUDIO_ALIGN_WORKER] [ERROR] Error in draw_audio_wave")
            print(print_op_result(res))
            return False
        
        audio_wave_image_path = res.value
        # print(f"Audio wave image saved at: {str(audio_wave_image_path)}")
        return True

    except Exception as e:
        print(f"Error in drawing audio wave: {e}")
        traceback.print_exc()
        return False



if __name__ == "__main__":

    if len(sys.argv) < 5: # 至少要5个
        print("plz provide root, is_simply_align, reference_file, (target_file, bpm, click_count, click_start_time), exiting.")
        sys.exit(1)

    result = main(sys.argv[2:])
    sys.exit(0 if result else 1)
