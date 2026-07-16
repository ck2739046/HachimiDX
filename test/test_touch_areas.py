import cv2
import numpy as np

def get_touch_areas(std_video_size, std_video_cx, std_video_cy):
    """从 shared_context.py 复制"""
    # 1080p的触摸区域中心坐标
    std_touch_areas = {
        # A
        'A1': (693, 171), 'A2': (909, 388), 'A3': (908, 693), 'A4': (692, 910),
        'A5': (387, 909), 'A6': (170, 694), 'A7': (170, 388), 'A8': (386, 170),
        # B
        'B1': (624, 336), 'B2': (745, 456), 'B3': (744, 626), 'B4': (624, 745),
        'B5': (455, 745), 'B6': (335, 626), 'B7': (335, 456), 'B8': (454, 336),
        # C
        'C1': (540, 540),
        # D
        'D1': (540, 117), 'D2': (840, 241), 'D3': (963, 542), 'D4': (839, 840),
        'D5': (540, 964), 'D6': (241, 840), 'D7': (116, 540), 'D8': (239, 241),
        # E
        'E1': (540, 229), 'E2': (760, 320), 'E3': (852, 540), 'E4': (760, 761),
        'E5': (539, 853), 'E6': (319, 760), 'E7': (228, 540), 'E8': (319, 321),
    }
    new_touch_areas = {}
    for area_label, (x, y) in std_touch_areas.items():
        scaled_x = round((x - 540) * std_video_size / 1080 + std_video_cx)
        scaled_y = round((y - 540) * std_video_size / 1080 + std_video_cy)
        new_touch_areas[area_label] = (scaled_x, scaled_y)
    return new_touch_areas

def draw_voronoi_with_scipy(canvas, points):
    """使用scipy绘制Voronoi图（中垂线网格）"""
    try:
        from scipy.spatial import Voronoi
        
        # 计算Voronoi图
        vor = Voronoi(points)
        
        # 获取画布尺寸
        height, width = canvas.shape[:2]
        
        # 绘制Voronoi边（脊）
        for ridge_idx, ridge in enumerate(vor.ridge_vertices):
            # 跳过两个顶点都无效的情况
            if ridge[0] == -1 and ridge[1] == -1:
                continue
            
            # 获取形成这条脊的两个点
            ridge_point1, ridge_point2 = vor.ridge_points[ridge_idx]
            p1 = np.array(points[ridge_point1])
            p2 = np.array(points[ridge_point2])
            
            if ridge[0] >= 0 and ridge[1] >= 0:
                # 两个顶点都在有限区域内
                v1 = vor.vertices[ridge[0]]
                v2 = vor.vertices[ridge[1]]
                # 转换为整数坐标
                x1, y1 = int(v1[0]), int(v1[1])
                x2, y2 = int(v2[0]), int(v2[1])
                # 绘制蓝色线段
                cv2.line(canvas, (x1, y1), (x2, y2), (255, 0, 0), 1)
            else:
                # 处理无限脊（有一个顶点在无限远处）
                # 找到有限顶点
                finite_idx = ridge[0] if ridge[0] >= 0 else ridge[1]
                if finite_idx < 0:
                    continue
                
                finite_vertex = vor.vertices[finite_idx]
                
                # 计算脊的方向（两个点的中垂线方向）
                # 计算两点连线的垂直方向
                mid_point = (p1 + p2) / 2
                direction = np.array([-(p2[1] - p1[1]), p2[0] - p1[0]])  # 垂直向量
                norm = np.linalg.norm(direction)
                if norm == 0:
                    continue
                direction = direction / norm
                
                # 确定方向：从有限顶点向外
                # 检查有限顶点到中点的向量与方向是否一致
                to_mid = mid_point - finite_vertex
                if np.dot(to_mid, direction) < 0:
                    direction = -direction
                
                # 将脊延伸到画布边界
                # 计算从有限顶点沿方向到画布边界的交点
                t_values = []
                
                # 检查与画布左边界(x=0)的交点
                if direction[0] != 0:
                    t = (0 - finite_vertex[0]) / direction[0]
                    if t > 0:
                        y = finite_vertex[1] + t * direction[1]
                        if 0 <= y < height:
                            t_values.append(t)
                
                # 检查与画布右边界(x=width-1)的交点
                if direction[0] != 0:
                    t = (width - 1 - finite_vertex[0]) / direction[0]
                    if t > 0:
                        y = finite_vertex[1] + t * direction[1]
                        if 0 <= y < height:
                            t_values.append(t)
                
                # 检查与画布上边界(y=0)的交点
                if direction[1] != 0:
                    t = (0 - finite_vertex[1]) / direction[1]
                    if t > 0:
                        x = finite_vertex[0] + t * direction[0]
                        if 0 <= x < width:
                            t_values.append(t)
                
                # 检查与画布下边界(y=height-1)的交点
                if direction[1] != 0:
                    t = (height - 1 - finite_vertex[1]) / direction[1]
                    if t > 0:
                        x = finite_vertex[0] + t * direction[0]
                        if 0 <= x < width:
                            t_values.append(t)
                
                if t_values:
                    t = min(t_values)  # 最近的交点
                    end_point = finite_vertex + direction * t
                    
                    # 绘制线段
                    x1, y1 = int(finite_vertex[0]), int(finite_vertex[1])
                    x2, y2 = int(end_point[0]), int(end_point[1])
                    cv2.line(canvas, (x1, y1), (x2, y2), (255, 0, 0), 1)
        
        return True
    except ImportError:
        print("scipy未安装，无法绘制Voronoi图")
        return False
    except Exception as e:
        print(f"绘制Voronoi图时出错: {e}")
        return False

def draw_perpendicular_bisectors(canvas, points, threshold=200):
    """绘制点之间的中垂线（简单实现）"""
    n = len(points)
    for i in range(n):
        for j in range(i+1, n):
            x1, y1 = points[i]
            x2, y2 = points[j]
            # 计算两点距离
            dist = np.sqrt((x2-x1)**2 + (y2-y1)**2)
            if dist > threshold:
                continue  # 只绘制距离较近的点对
            
            # 计算中点
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2
            # 计算连线方向向量
            dx, dy = x2 - x1, y2 - y1
            # 垂直向量（顺时针旋转90度）
            perp_dx, perp_dy = dy, -dx
            # 归一化
            norm = np.sqrt(perp_dx**2 + perp_dy**2)
            if norm == 0:
                continue
            perp_dx, perp_dy = perp_dx/norm, perp_dy/norm
            
            # 中垂线长度设为两点距离的一半
            length = dist * 0.6
            # 计算线段端点
            x_start = int(mx - perp_dx * length)
            y_start = int(my - perp_dy * length)
            x_end = int(mx + perp_dx * length)
            y_end = int(my + perp_dy * length)
            
            # 绘制线段
            cv2.line(canvas, (x_start, y_start), (x_end, y_end), (0, 255, 255), 1)

def main():
    # 画布大小
    canvas_size = 1080
    center = canvas_size // 2  # 540
    radius = 480
    
    # 创建黑色画布
    canvas = np.zeros((canvas_size, canvas_size, 3), dtype=np.uint8)
    
    # 画一个白色圆圈，圆心为画布中心，半径480
    cv2.circle(canvas, (center, center), radius, (255, 255, 255), thickness=2)
    
    # 获取触摸区域坐标（对于1080p，无需缩放）
    touch_areas = get_touch_areas(canvas_size, center, center)
    
    # 提取点坐标和标签
    labels = list(touch_areas.keys())
    points = list(touch_areas.values())
    
    # 尝试使用scipy绘制Voronoi图（中垂线网格）
    voronoi_drawn = draw_voronoi_with_scipy(canvas, points)
    if voronoi_drawn:
        print("使用scipy Voronoi图方法...")
    
    # 如果Voronoi绘制失败，使用简单的中垂线方法
    if not voronoi_drawn:
        print("使用简单中垂线方法...")
        draw_perpendicular_bisectors(canvas, points, threshold=250)
    
    # 绘制每个触摸点
    for label, (x, y) in touch_areas.items():
        # 画一个红色圆点
        cv2.circle(canvas, (x, y), 10, (0, 0, 255), thickness=-1)  # 填充圆
        # 添加标签文本
        cv2.putText(canvas, label, (x - 15, y - 15), cv2.FONT_HERSHEY_SIMPLEX, 
                    0.5, (0, 255, 255), 1, cv2.LINE_AA)
    
    # 显示图像
    cv2.imshow('Touch Areas Visualization with Voronoi Grid', canvas)
    print("按任意键关闭窗口...")
    cv2.waitKey(0)
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
