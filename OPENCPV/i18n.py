"""Text displayed in video frames."""

STRINGS = {
    "title": ("开放协同感知可视化", "Open Collaborative Perception Visualization"),
    "vehicle_camera": ("车辆相机", "VEHICLE CAMERA"),
    "infrastructure_camera": ("基础设施相机", "INFRA CAMERA"),
    "vehicle_points": ("车辆点云", "VEHICLE LIDAR"),
    "infrastructure_points": ("基础设施点云", "INFRA LIDAR"),
    "result": ("俯视检测结果", "BEV DETECTION"),
    "unavailable": ("数据缺失", "Unavailable"),
    "point_count": ("{count:,} 点 | 网格 10 米", "{count:,} points | grid 10 m"),
    "empty_cloud": ("显示范围内无点云", "No points inside configured bounds"),
    "vehicle_id": ("车辆 {id}", "VEH {id}"),
    "infrastructure_id": ("路端 {id}", "INF {id}"),
    "split_index": ("验证集序号 {index}", "split index {index}"),
    "local_coordinates": ("点云：各传感器本地坐标系", "LiDAR: each sensor's local frame"),
    "vehicle_coordinates": ("点云：车辆坐标系", "LiDAR: vehicle frame"),
    "issues": ("{count} 项缺失或错误（详见报告）", "{count} missing/error (see report)"),
}


def text(key, language="bilingual", **values):
    zh, en = STRINGS[key]
    value = zh if language == "zh" else en if language == "en" else f"{zh} / {en}"
    return value.format(**values)
