# OPENCPV

Open Collaborative Perception Visualization

[English](README.md) · [简体中文](README.zh-CN.md)

**OPENCPV** is a standalone tool for visualizing collaborative perception. It brings paired vehicle and infrastructure camera images, LiDAR point clouds, and BEV detection results from DAIR-V2X-C into a single view for comparison. It runs on the CPU, with light and dark themes, English and Chinese labels, PNG previews, and MP4 export.

<video src="docs/assets/OPENCPV_mini_axes.mp4" poster="docs/assets/preview.jpg" controls muted playsinline preload="metadata" width="100%"></video>

[Watch the example video](docs/assets/OPENCPV_mini_axes.mp4) · Cameras, point clouds, and BEV detections using the included DAIR-V2X mini dataset.

## Quick start

With **Python 3.10+**, run from the project directory:

```bash
python -m pip install -r requirements.txt
python run.py preview --config config.mini.json --count 3
python run.py render --config config.mini.json
```

These commands generate three preview images, then export a video. The current [mini configuration](config.mini.json) uses ten real dataset samples and writes `exports/OPENCPV_mini_axes.mp4`: 1080p, 30 FPS, eight seconds. Add `--overwrite` to replace an existing output.

## Use your own data

Copy [config.example.json](config.example.json) to `config.local.json` and set the paths to your dataset, detection images, and validation split. `results.directory` should point to existing BEV detection images, such as a `vis_intermediate` directory exported by OpenCOOD or CoAlign:

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

Save the configuration and run:

```bash
python run.py render --config config.local.json
```

The equivalent module command is:

```bash
python -m OPENCPV render --config config.local.json
```

Relative paths are resolved from the configuration file's directory; absolute paths also work. The default `auto` mode uses each image's filename index to find a validation sample, then looks up its vehicle/infrastructure pair. For example, `bev_00010.png` maps to `val.json[10]`, whose vehicle frame ID is used to query `cooperative/data_info.json`. Keep the validation split in the same order used for inference.

## Reference

Expand the sections below for data matching, display, and export settings. Tables list application defaults; values in your configuration file take precedence.

<details>
<summary><strong>Dataset layout and frame matching</strong></summary>

Keep the original DAIR-V2X directory structure:

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

`dataset_root` can point to this directory or its parent. Sensor image and point-cloud paths come from `cooperative/data_info.json`. Point-cloud inputs support ASCII, binary, and binary-compressed PCD, plus Nx3/Nx4 NPY files.

### Frame matching

The default `auto` mode scans `bev_*.png`, extracts each numeric filename ID, and uses it as an index into the inference split:

```text
bev_00010.png
  → val.json[10] = "000876"
  → cooperative/data_info.json: vehicle "000876"
  → vehicle camera / LiDAR "000876"
  → infrastructure camera / LiDAR "005764"
```

Files are sorted numerically. The index is `filename ID - index_base`, where `index_base` defaults to zero. A saving interval of ten produces IDs `0, 10, 20, …`; those IDs directly index the complete split. You do not need to specify the saving interval or an `indices` list.

Use the **same ordered split file used for inference**. It may contain a list of string IDs or an object such as `{"val": [...]}`; use `split_key` to select the list in an object. Leading zeros in frame IDs are preserved. When a vehicle ID has multiple cooperative metadata records, the last record is used, following CoAlign's loading logic. In `auto` mode, multiple result files mapping to the same index produce an error.

| Mode | Filename meaning | Configuration |
|---|---|---|
| `auto` (default) | Inference index, e.g. `bev_00010.png` | `split_file` |
| `index` | Inference index; retained for existing configurations | `split_file` |
| `frame_id` | Original vehicle frame ID | `glob` and `id_regex` |
| `csv` | Explicit image-to-sensor mapping, in CSV row order | `mapping_csv` |

Use `results.indices` to select validation indices and their playback order in `auto` or `index` mode. `limit` or `--limit N` restricts the number of samples processed. Set `limit` to `null` to process all selected samples.

For filenames such as `000123.png`, use `frame_id` with `glob: "*.png"` and `id_regex: "^(\\d+)\\.png$"`. For custom mappings, see [examples/mapping.csv](examples/mapping.csv):

```csv
result_image,vehicle_frame_id,infrastructure_frame_id
bev_00000.png,000211,007410
bev_00010.png,000876,005764
```

CSV image paths are relative to `results.directory`. The infrastructure ID is optional; when provided, it selects that cooperative pair.

</details>

<details>
<summary><strong>Appearance, BEV cropping and video settings</strong></summary>

```json
{
  "title": null,
  "language": "en",
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

| Setting | Default | Description |
|---|---|---|
| `theme` | `light` | White background with coordinated text and point-cloud colors; `dark` selects the dark palette |
| `language` | `bilingual` | `en`, `zh`, or `bilingual` for generated labels |
| `title` | `null` | Localized project title; a string supplies a custom title |
| `layout.mode` | `four_plus_bev` | Both cameras and point clouds alongside BEV; also supports cameras + BEV (`cameras_plus_bev`) and point clouds + BEV (`clouds_plus_bev`) |
| `layout.left_fraction` | `0.65` | Width allocated to the sensor panels |
| `layout.panel_padding` | `16` | Minimum content padding, in pixels at 1080p; scales with output height |
| `layout.show_frame_info` | `false` | Show frame IDs, split index, coordinates, point counts, and grid captions |
| `video.size` | `[1920,1080]` | Output width and height; use even dimensions |
| `video.fps` | `30` | Output frame rate |
| `video.seconds_per_sample` | `0.8` | Display duration per sample, in seconds |
| `video.crf` / `video.preset` | `18` / `medium` | H.264 quality and encoding-speed settings |
| `results.crop` | `null` | Pixel crop rectangle `[left,top,right,bottom]` |
| `results.crop_margins` | `[0,0,0,0]` | Fractions removed from the left, top, right, and bottom |
| `results.rotation` | `0` | Degrees counterclockwise, in multiples of 90 |
| `on_missing` | `placeholder` | Show a placeholder panel (`placeholder`), skip the sample (`skip`), or stop (`error`) when sensor data is missing |

Processing order is pixel crop → fractional crop → rotation → aspect-preserving fit. The supplied configurations crop one sixth from each horizontal edge and rotate 90° counterclockwise. A 2520 × 1000 image becomes 1000 × 1680. Set margins and rotation to zero to show the full image in its original orientation.

Language and theme settings apply to panel titles, point clouds, and other generated content. Source images retain their existing text and colors. Chinese labels require an installed font with Chinese character support; you can also set `font` to a font file path. `show_frame_info` controls the frame-information footer, point counts, and grid captions together; set it to `false` to hide them all.

</details>

<details>
<summary><strong>Point-cloud view and calibration</strong></summary>

Each sensor uses its own LiDAR coordinate system by default (`point_cloud.coordinates: "local"`). The mini configuration uses this setting too.

| Setting | Default | Description |
|---|---|---|
| `point_cloud.bounds` | `[-30,-40,-4,90,40,8]` | `[xmin,ymin,zmin,xmax,ymax,zmax]`, in meters |
| `point_cloud.azimuth` / `elevation` | `-60` / `55` | View azimuth and elevation in degrees; elevation 90 gives a top view |
| `point_cloud.zoom` | `1.3` | Fixed display magnification; use `1.0` to fit the complete configured bounds |
| `point_cloud.max_points` | `100000` | Maximum points drawn per panel |
| `point_cloud.point_size` | `1` | Point size: 1, 3, or 5 |
| `point_cloud.color_by` | `height` | Color by `height`, `intensity`, or `sensor` |

The default zoom of `1.3` enlarges the point-cloud views to reduce empty space, keeping the same center and scale throughout playback. Higher values may clip points at the panel edges. To change the spatial region being displayed, adjust `bounds`, in meters.

The origin triad uses outlined arrows and separate X/Y/Z label badges to distinguish it from point colors. Labels sit beyond the arrow tips; short projected axes are extended for readability. The triad indicates orientation, while grid spacing provides the metric scale.

To transform infrastructure points into vehicle coordinates, set `coordinates` to `vehicle` and provide the corresponding calibration files under:

```text
vehicle-side/calib/lidar_to_novatel/
vehicle-side/calib/novatel_to_world/
infrastructure-side/calib/virtuallidar_to_world/
```

`point_cloud.apply_system_error_offset` defaults to `true` and applies the pair's `delta_x` / `delta_y` correction. Disable it for calibration that already includes the correction.

</details>

<details>
<summary><strong>Commands, output reports and tests</strong></summary>

All commands work with either `python run.py` or `python -m OPENCPV`:

```bash
python -m OPENCPV inspect --config config.local.json
python -m OPENCPV preview --config config.local.json --count 5
python -m OPENCPV render --config config.local.json --overwrite
```

| Command | Output |
|---|---|
| `inspect --config …` | Input and mapping checks, with a JSON report |
| `preview --config … --count 5` | PNG frames in `<output_stem>_previews/` |
| `render --config …` | MP4 at `video.output` |

Each run also writes `<output_stem>.<command>.report.json` next to the configured video output, recording input paths, frame matches, and any issues found. `output_stem` is the output video's filename without its extension. Video export verifies the encoded frame count before finalizing the output.

imageio-ffmpeg wheels for common platforms include FFmpeg. Set `IMAGEIO_FFMPEG_EXE` to use a system executable.

### Tests

```bash
python -m unittest discover -s tests -v
```

The tests cover DAIR frame matching, calibration transforms, PCD decoding, overlays, image transforms, and video export. Integration tests use the included mini dataset.

</details>

## Citation

If this project is useful to your research, please consider citing our paper:

```bibtex
@article{wei2026paracomm,
  title = {Rethinking What to Communicate for Collaborative Perception: A Parameter-Centric Perspective},
  author = {Wei, Quanmin and Dai, Penglin and Li, Wei and Wu, Xiao and Chen, Chao and Yu, Zhaofei},
  journal = {IEEE Transactions on Mobile Computing},
  year = {2026}
}
```

## Acknowledgments

This project uses the [DAIR-V2X](https://air.tsinghua.edu.cn/DAIR-V2X/cheluduan.html) dataset, with data-loading logic adapted from [CoAlign](https://github.com/yifanlu0227/CoAlign). We thank both projects for their open-source contributions.
