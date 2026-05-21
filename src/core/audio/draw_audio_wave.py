import matplotlib.pyplot as plt
import numpy as np
import os
from pathlib import Path


from ..schemas.op_result import OpResult, ok, err

from src.services import PathManage
from src.app.ui_style import UI_Style


def main(reference_audio,
         template_click_audio,
         target_audio,
         template_match_offset,
         target_match_offset,
         graph_range_start,
         graph_range_end) -> OpResult[Path]:
    """
    绘制三行音频波形图
    
    参数:
        reference_audio: 基准音频数据 (44100Hz)
        template_click_audio: 生成模板音频数据 (44100Hz)
        target_audio: 目标音频数据 (44100Hz)
        template_match_offset: 模板与基准音频的匹配时间 (ms)
        target_match_offset: 目标与基准音频的对齐时间 (ms)
        graph_range_start: 波形图显示的起始时间 (ms)
        graph_range_end: 波形图显示的结束时间 (ms)

    返回：
        OpResult[Path]: 生成的波形图路径
    """
    
    try:
        # 设置采样率
        sr = 44100
        
        # 计算显示时间范围
        start_time = graph_range_start
        end_time = graph_range_end
        
        # 创建画布
        fig = plt.figure(figsize=(8, 2), dpi=100)  # 800px × 200px
        
        # 设置背景颜色
        fig.patch.set_facecolor(UI_Style.COLORS['grey'])
        
        # 创建4个子图 (3行波形 + 1行时间轴)
        gs = plt.GridSpec(4, 1, height_ratios=[1, 1, 1, 0.01], hspace=0.15)
        
        # 第一行：基准音频波形
        ax1 = plt.subplot(gs[0])
        _plot_audio_waveform(ax1, reference_audio, sr, start_time, end_time, 0, "base")
        
        # 第二行：生成模板波形
        ax2 = plt.subplot(gs[1])
        _plot_audio_waveform(ax2, template_click_audio, sr, start_time, end_time, template_match_offset, "click")
        
        # 第三行：目标文件波形
        ax3 = plt.subplot(gs[2])
        _plot_audio_waveform(ax3, target_audio, sr, start_time, end_time, target_match_offset, "target")

        # 第四行：时间轴
        ax4 = plt.subplot(gs[3])
        _plot_time_axis(ax4, start_time, end_time)
        
        # 在所有子图中添加两条垂直线
        for ax in [ax1, ax2, ax3, ax4]:
            # template_match_offset 虚线
            ax.axvline(x=template_match_offset, color='red', linestyle='--', alpha=1, linewidth=1)
            # target_match_offset 虚线
            ax.axvline(x=target_match_offset, color='green', linestyle='--', alpha=1, linewidth=1)
        
        # 保存图片
        output_path = PathManage.TEMP_WAV_IMAGE_PATH
        if os.path.exists(output_path):
            os.remove(output_path)
        plt.savefig(output_path, dpi=116, bbox_inches='tight', pad_inches=0.1)
        plt.close()
        
        return ok(output_path)
        
    except Exception as e:
        return err("Error while drawing audio wave", error_raw=e)




def _plot_audio_waveform(ax, audio_data, sr, start_time, end_time, offset_time, title):
    """
    绘制单个音频波形图
    
    参数:
        ax: matplotlib 轴对象
        audio_data: 音频数据
        sr: 采样率
        start_time: 显示开始时间 (ms)
        end_time: 显示结束时间 (ms)
        offset_time: 音频相对于时间轴的偏移 (ms)
        title: 波形图标题
    """
    # 计算时间范围（转换为秒）
    start_sec = (start_time - offset_time) / 1000.0
    end_sec = (end_time - offset_time) / 1000.0
    
    # 计算样本索引范围
    start_sample = int(start_sec * sr)
    end_sample = int(end_sec * sr)
    
    # 处理边界情况
    audio_length = len(audio_data)
    
    if start_sample < 0:
        # 左侧超出边界，用静音填充
        left_padding = -start_sample
        start_sample = 0
        # 创建填充的音频数据
        if end_sample > audio_length:
            # 右侧也超出边界
            right_padding = end_sample - audio_length
            padded_audio = np.concatenate([
                np.zeros(left_padding),
                audio_data,
                np.zeros(right_padding)
            ])
        else:
            # 只有左侧超出边界
            padded_audio = np.concatenate([
                np.zeros(left_padding),
                audio_data[:end_sample]
            ])
    elif end_sample > audio_length:
        # 只有右侧超出边界
        right_padding = end_sample - audio_length
        padded_audio = np.concatenate([
            audio_data[start_sample:],
            np.zeros(right_padding)
        ])
    else:
        # 正常情况
        padded_audio = audio_data[start_sample:end_sample]
    
    # 创建时间轴（毫秒）
    time_axis = np.linspace(start_time, end_time, len(padded_audio))
    
    # 绘制波形
    ax.plot(time_axis, padded_audio, color=UI_Style.COLORS['accent'], linewidth=0.5)
    #ax.fill_between(time_axis, padded_audio, 0, alpha=0.3, color=UI_Style.COLORS['accent'])
    
    # 设置坐标轴
    ax.set_xlim(start_time, end_time)
    ax.set_ylim(-1, 1)
    ax.set_ylabel(title, rotation=0, ha='right', va='center', color=UI_Style.COLORS['text_primary'])
    
    # 设置背景颜色
    ax.set_facecolor(UI_Style.COLORS['grey'])
    
    # 隐藏xy轴刻度
    ax.set_xticks([])
    ax.set_yticks([])
    
    # 设置坐标轴颜色
    ax.spines['top'].set_color(UI_Style.COLORS['text_secondary'])
    ax.spines['bottom'].set_color(UI_Style.COLORS['text_secondary'])
    ax.spines['left'].set_color(UI_Style.COLORS['text_secondary'])
    ax.spines['right'].set_color(UI_Style.COLORS['text_secondary'])
    ax.tick_params(colors=UI_Style.COLORS['text_secondary'])
    
    # 添加网格
    ax.grid(True, alpha=0.3)




def _plot_time_axis(ax, start_time, end_time):
    """
    绘制时间轴
    
    参数:
        ax: matplotlib 轴对象
        start_time: 开始时间 (ms)
        end_time: 结束时间 (ms)
    """
    # 设置时间轴范围
    ax.set_xlim(start_time, end_time)
    ax.set_ylim(0, 1)

    # 隐藏y轴刻度
    ax.set_yticks([])
    
    # 设置时间x刻度（每300ms一格，显示标签）
    major_tick_interval = 300
    
    # 生成主要x刻度位置
    major_ticks = np.arange(start_time, end_time + major_tick_interval, major_tick_interval)
    
    # 设置主要x刻度
    ax.set_xticks(major_ticks)
    
    # 设置x刻度标签
    tick_labels = [f'{tick:.0f}' for tick in major_ticks]
    ax.set_xticklabels(tick_labels, fontsize=6, color=UI_Style.COLORS['text_primary'])
    
    # 设置次要x刻度（每100ms一格，不显示标签）
    minor_tick_interval = 100
    minor_ticks = np.arange(start_time, end_time + minor_tick_interval, minor_tick_interval)
    ax.set_xticks(minor_ticks, minor=True)
    
    # 设置背景颜色
    ax.set_facecolor(UI_Style.COLORS['grey'])
    
    # 设置坐标轴颜色
    ax.spines['top'].set_color(UI_Style.COLORS['text_secondary'])
    ax.spines['bottom'].set_color(UI_Style.COLORS['text_secondary'])
    ax.spines['left'].set_color(UI_Style.COLORS['text_secondary'])
    ax.spines['right'].set_color(UI_Style.COLORS['text_secondary'])
    ax.tick_params(colors=UI_Style.COLORS['text_secondary'])
