# OPENCPV

Open Collaborative Perception Visualization

[English](README.md) · [简体中文](README.zh-CN.md)

**OPENCPV** 是一个可独立运行的协同感知可视化工具。它将 DAIR-V2X-C 中配对的车端、路端相机图像与 LiDAR 点云，以及对应的 BEV 检测结果集成到同一画面。项目可在纯CPU环境中运行，支持浅色与深色主题、中文与英文标签，可导出 PNG 预览图和 MP4 视频。

https://github.com/user-attachments/assets/67579e22-2a6f-4db6-aee4-1a25ab9d80c2
<!-- <video src="docs/assets/OPENCPV_mini_axes.mp4" poster="docs/assets/preview.jpg" controls muted playsinline preload="metadata" width="100%"></video> -->

[观看示例视频](docs/assets/OPENCPV_mini_axes.mp4) · 使用随项目提供的 DAIR-V2X mini 数据，展示两端相机、点云及 BEV 检测结果。

## 快速开始

安装 **Python 3.10 或更高版本**，在项目根目录运行：

```bash
python -m pip install -r requirements.txt # 安装依赖
python run.py preview --config config.mini.json --count 3 # 预览模式
python run.py render --config config.mini.json # 渲染模式
```

以上命令先安装依赖，生成 3 张预览图，再导出视频。当前 [mini 配置](config.mini.json) 使用随项目提供的 10 个真实样本，输出为 `exports/OPENCPV_mini_axes.mp4`，分辨率为 1080p、帧率为 30 FPS、总时长为 8 秒。覆盖已有输出时，在命令末尾添加 `--overwrite`。

## 使用自己的数据

将 [config.example.json](config.example.json) 复制为 `config.local.json`，填写数据集、检测结果图片和验证集列表的路径。`results.directory` 指向已有的 BEV 检测结果图片目录，例如 OpenCOOD 或 CoAlign 导出的 `vis_intermediate` 目录：

```json
{
  "dataset_root": "/data/DAIR-V2X-C/cooperative-vehicle-infrastructure",
  "results": {
    "directory": "/data/experiments/vis_intermediate",
    "split_file": "/data/DAIR-V2X-C/cooperative-vehicle-infrastructure/val.json"
  },
  "video": {
    "output": "exports/result.mp4"
  }
}
```

保存配置后，运行：
```bash
python run.py render --config config.local.json
```

也可以通过 Python 模块启动，两种方式等效：
```bash
python -m OPENCPV render --config config.local.json
```

配置中的相对路径以配置文件所在目录为基准，也支持绝对路径。默认使用 `auto` 模式：先根据图片名中的编号定位验证集样本，再读取车路配对关系。例如，`bev_00010.png` 对应 `val.json[10]`，其车辆帧 ID 用于查询 `cooperative/data_info.json`。验证集列表应与推理时保持相同顺序。

## 详细说明

数据匹配、显示效果和导出设置见下方折叠说明。表中列出程序默认值，具体运行时以配置文件中的设置为准。

<details>
<summary><strong>数据目录与帧匹配</strong></summary>

保留 DAIR-V2X 原有目录结构即可：

```text
cooperative-vehicle-infrastructure/
├── cooperative/data_info.json
├── vehicle-side/
│   ├── image/
│   └── velodyne/
└── infrastructure-side/
    ├── image/
    └── velodyne/
```

`dataset_root` 可指向该目录或其上一级目录。程序从 `cooperative/data_info.json` 读取车路配对关系及文件路径。点云支持 ASCII、Binary、Binary Compressed 三种 PCD 格式，以及 N×3、N×4 的 NPY 文件。

### 帧匹配

默认 `auto` 模式扫描 `bev_*.png`，提取文件名中的编号，作为推理所用验证集列表的索引：

```text
bev_00010.png
  → val.json[10] = "000876"
  → cooperative/data_info.json 中车辆 "000876" 的记录
  → 车辆相机／点云 "000876"
  → 基础设施相机／点云 "005764"
```

图片按编号从小到大处理，索引计算方式为「文件名编号 − `index_base`」，默认 `index_base: 0`。如果推理时每隔 10 帧保存一次结果，编号 `0、10、20、…` 仍对应完整验证集中的相应位置，无需另设保存间隔或手动填写 `indices`。

验证集列表须保留**推理时的原始顺序**，支持直接存储字符串 ID 的列表，也支持 `{"val": [...]}` 形式，后者通过 `split_key` 指定列表名称。帧 ID 的前导零会被保留。同一车辆 ID 有多条协同记录时，与 CoAlign 的加载逻辑一致，使用最后一条记录。`auto` 模式下，多个结果文件若对应同一索引，程序会报错并提示。

| 模式 | 图片编号含义 | 所需配置 |
|---|---|---|
| `auto`（默认） | 推理序号，例如 `bev_00010.png` | `split_file` |
| `index` | 推理序号，用于兼容原有配置 | `split_file` |
| `frame_id` | 车辆原始帧 ID | `glob` 和 `id_regex` |
| `csv` | CSV 指定的映射关系，按行顺序播放 | `mapping_csv` |

在 `auto` 和 `index` 模式下，可用 `results.indices` 指定要展示的验证集索引及播放顺序。`limit` 或 `--limit N` 可限制处理数量；设为 `limit: null` 时，处理所有选中的样本。

图片名为 `000123.png` 时，可使用 `frame_id`，设置 `glob: "*.png"` 和 `id_regex: "^(\\d+)\\.png$"`。自定义映射格式见 [examples/mapping.csv](examples/mapping.csv)：

```csv
result_image,vehicle_frame_id,infrastructure_frame_id
bev_00000.png,000211,007410
bev_00010.png,000876,005764
```

CSV 中的图片路径相对于 `results.directory`。路端 ID 可以省略，由程序查询对应关系；填写后则使用指定的车路配对。

</details>

<details>
<summary><strong>外观、BEV 裁剪与视频参数</strong></summary>

```json
{
  "title": null,
  "language": "zh",
  "theme": "light",
  "layout": {
    "mode": "four_plus_bev",
    "left_fraction": 0.65,
    "panel_padding": 16,
    "show_frame_info": false
  },
  "results": {
    "crop_margins": [0.16666666666666666, 0, 0.16666666666666666, 0],
    "rotation": 90
  }
}
```

| 参数 | 默认值 | 说明 |
|---|---|---|
| `theme` | `light` | 浅色主题，文字与点云配色随之调整；`dark` 为深色主题 |
| `language` | `bilingual` | 英文 `en`、中文 `zh` 或双语 `bilingual` |
| `title` | `null` | 按语言显示项目标题；可填写自定义标题 |
| `layout.mode` | `four_plus_bev` | 两端相机、点云与 BEV；也可选择相机 + BEV（`cameras_plus_bev`）或点云 + BEV（`clouds_plus_bev`） |
| `layout.left_fraction` | `0.65` | 左侧传感器面板的宽度占比 |
| `layout.panel_padding` | `16` | 内容最小边距，以 1080p 像素计，随输出高度缩放 |
| `layout.show_frame_info` | `false` | 是否显示帧 ID、验证集索引、坐标系、点数和网格说明 |
| `video.size` | `[1920,1080]` | 输出宽高，使用偶数尺寸 |
| `video.fps` | `30` | 输出视频帧率 |
| `video.seconds_per_sample` | `0.8` | 每个样本的展示时长，单位秒 |
| `video.crf` / `video.preset` | `18` / `medium` | H.264 画质和编码速度 |
| `results.crop` | `null` | 像素裁剪区域 `[left,top,right,bottom]` |
| `results.crop_margins` | `[0,0,0,0]` | 按比例裁掉左、上、右、下边缘 |
| `results.rotation` | `0` | 逆时针旋转角度，90 的整数倍 |
| `on_missing` | `placeholder` | 传感器数据缺失时显示占位面板（`placeholder`）、跳过样本（`skip`）或终止运行（`error`） |

BEV 图片依次经过像素裁剪、比例裁剪、旋转，最后等比例缩放至面板内。附带配置将图片左右各裁掉 1/6，再逆时针旋转 90°；例如，2520 × 1000 的图片处理后为 1000 × 1680。将裁剪比例和旋转角度均设为零，可按原始方向显示完整图片。

语言和主题设置用于面板标题、点云及其他由程序绘制的内容，原始图片中的文字和颜色保持不变。显示中文需要系统中有可用的中文字体，也可通过 `font` 指定字体文件。`show_frame_info` 同时控制底部帧信息、点数与网格说明，设为 `false` 即可全部隐藏。

</details>

<details>
<summary><strong>点云视图与标定</strong></summary>

默认设置为 `point_cloud.coordinates: "local"`，车端和路端点云分别在各自的 LiDAR 坐标系中显示。mini 配置也采用这一设置。

| 参数 | 默认值 | 说明 |
|---|---|---|
| `point_cloud.bounds` | `[-30,-40,-4,90,40,8]` | `[xmin,ymin,zmin,xmax,ymax,zmax]`，单位米 |
| `point_cloud.azimuth` / `elevation` | `-60` / `55` | 观察方位角与仰角，单位度；仰角为 90 时为俯视图 |
| `point_cloud.zoom` | `1.3` | 固定显示倍率；设为 `1.0` 可完整容纳配置的显示范围 |
| `point_cloud.max_points` | `100000` | 每幅点云最多绘制的点数 |
| `point_cloud.point_size` | `1` | 点大小：1、3 或 5 |
| `point_cloud.color_by` | `height` | 按高度 `height`、强度 `intensity` 或传感器 `sensor` 着色 |

默认倍率为 `1.3`，适当放大点云以减少面板留白，播放时保持取景中心和倍率不变。继续增大倍率可能使部分点超出面板；如需调整实际展示的空间范围，请修改以米为单位的 `bounds`。

原点处的坐标轴采用描边箭头，X／Y／Z 标签位于箭头外侧，并带有底色，便于与点云区分。投影后过短的轴会适当延长；坐标轴用于指示方向，距离尺度可参考网格。

将 `coordinates` 设为 `vehicle` 可把路端点云转换到车辆坐标系，需要提供对应帧的标定文件：

```text
vehicle-side/calib/lidar_to_novatel/
vehicle-side/calib/novatel_to_world/
infrastructure-side/calib/virtuallidar_to_world/
```

`point_cloud.apply_system_error_offset` 默认开启，用于应用配对记录中的 `delta_x`／`delta_y` 位置补偿。如果标定结果已包含这部分补偿，可将其关闭。

</details>

<details>
<summary><strong>命令、输出报告与测试</strong></summary>

以下命令均可通过 `python run.py` 或 `python -m OPENCPV` 运行：

```bash
python -m OPENCPV inspect --config config.local.json
python -m OPENCPV preview --config config.local.json --count 5
python -m OPENCPV render --config config.local.json --overwrite
```

| 命令 | 输出 |
|---|---|
| `inspect --config …` | 检查输入与帧匹配，写入 JSON 报告 |
| `preview --config … --count 5` | PNG 图片，保存到 `<output_stem>_previews/` |
| `render --config …` | MP4 视频，保存到 `video.output` |

每次运行还会在视频输出目录生成 `<output_stem>.<command>.report.json`，记录输入路径、帧匹配结果和发现的问题。其中 `output_stem` 为输出视频的文件名，不含扩展名。视频导出完成前会校验实际编码帧数。

imageio-ffmpeg 在常见平台上的安装包已包含 FFmpeg。如需使用本机安装的版本，可通过环境变量 `IMAGEIO_FFMPEG_EXE` 指定其路径。

### 测试

```bash
python -m unittest discover -s tests -v
```

测试涵盖帧匹配、坐标变换、PCD 解析、文字绘制、图像处理和视频导出，集成测试使用随项目提供的 mini 数据。

</details>

## 引用

如果本项目对你的研究有所帮助，欢迎引用我们的论文：

```bibtex
@article{wei2026paracomm,
  title = {Rethinking What to Communicate for Collaborative Perception: A Parameter-Centric Perspective},
  author = {Wei, Quanmin and Dai, Penglin and Li, Wei and Wu, Xiao and Chen, Chao and Yu, Zhaofei},
  journal = {IEEE Transactions on Mobile Computing},
  year = {2026}
}
```

## 致谢

本项目使用 [DAIR-V2X](https://air.tsinghua.edu.cn/DAIR-V2X/cheluduan.html) 数据集，数据加载逻辑参考了 [CoAlign](https://github.com/yifanlu0227/CoAlign)。感谢相关项目的开源贡献。
