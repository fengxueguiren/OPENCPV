"""Input loading, frame previews and streaming MP4 export."""

import copy
import json
import math
import re
from pathlib import Path

import imageio_ffmpeg

from .dataset import DAIRDataset, read_json, resolve_items, transform_points
from .pcd import read_points
from .render import Compositor, open_rgb, transform_result


DEFAULTS = {
    "title": None,
    "language": "bilingual",
    "theme": "light",
    "on_missing": "placeholder",
    "limit": None,
    "results": {"mode": "auto", "glob": "bev_*.png", "id_regex": r"^bev_(\d+)\.png$",
                "split_key": "val", "index_base": 0, "indices": None, "crop": None,
                "crop_margins": [0, 0, 0, 0], "rotation": 0},
    "layout": {"mode": "four_plus_bev", "left_fraction": .65, "show_frame_info": False,
               "panel_padding": 16},
    "video": {"output": "exports/dair_result.mp4", "size": [1920, 1080], "fps": 30,
              "seconds_per_sample": .8, "crf": 18, "preset": "medium"},
    "point_cloud": {"coordinates": "local", "apply_system_error_offset": True,
                    "bounds": [-30, -40, -4, 90, 40, 8], "azimuth": -60,
                    "elevation": 55, "zoom": 1.3, "max_points": 100000, "point_size": 1,
                    "color_by": "height", "height_range": [-2, 4], "intensity_max": 255},
}


def merge(base, update):
    result = copy.deepcopy(base)
    for key, value in update.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path):
    path = Path(path).resolve()
    config = merge(DEFAULTS, read_json(path))
    for group, key in [(config, "dataset_root"), (config, "font"),
                       (config["results"], "directory"), (config["results"], "split_file"),
                       (config["results"], "mapping_csv"), (config["video"], "output")]:
        if group.get(key):
            target = Path(group[key]).expanduser()
            group[key] = str((path.parent / target).resolve())
    validate(config)
    return config


def validate(config):
    if config["theme"] not in ("light", "dark"):
        raise ValueError("theme must be light or dark")
    if config["language"] not in ("bilingual", "zh", "en"):
        raise ValueError("language must be bilingual, zh, or en")
    if config["title"] is not None and not isinstance(config["title"], str):
        raise ValueError("title must be null or a string")
    if not config.get("dataset_root") or not config["results"].get("directory"):
        raise ValueError("Set dataset_root and results.directory in config JSON")
    results = config["results"]
    margins = results.get("crop_margins", [0, 0, 0, 0])
    if (not isinstance(margins, list) or len(margins) != 4
            or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v < 1
                   for v in margins)
            or margins[0] + margins[2] >= 1 or margins[1] + margins[3] >= 1):
        raise ValueError("results.crop_margins needs [left,top,right,bottom] fractions; opposite sides must sum to < 1")
    if type(results.get("rotation", 0)) is not int or results.get("rotation", 0) % 90:
        raise ValueError("results.rotation must be an integer multiple of 90 (positive = counterclockwise)")
    if results["mode"] not in ("auto", "index", "frame_id", "csv"):
        raise ValueError("results.mode must be auto, index, frame_id, or csv")
    if results["mode"] == "csv":
        if not results.get("mapping_csv"):
            raise ValueError("CSV mode needs results.mapping_csv")
    else:
        try:
            pattern = re.compile(results["id_regex"])
        except re.error as exc:
            raise ValueError(f"Invalid results.id_regex: {exc}") from exc
        if pattern.groups < 1:
            raise ValueError("results.id_regex needs a capture group containing the ID/index")
    if type(results["index_base"]) is not int:
        raise ValueError("results.index_base must be an integer")
    indices = results.get("indices")
    if indices is not None:
        if results["mode"] not in ("auto", "index"):
            raise ValueError("results.indices is available in auto/index mode")
        if (not isinstance(indices, list) or not indices
                or any(type(i) is not int or i < 0 for i in indices)
                or len(set(indices)) != len(indices)):
            raise ValueError("results.indices must be a nonempty list of unique nonnegative split indices")
    if config.get("font") and not Path(config["font"]).is_file():
        raise ValueError(f"Configured font does not exist: {config['font']}")
    video, cloud = config["video"], config["point_cloud"]
    size = video["size"]
    if len(size) != 2 or any(type(v) is not int or v % 2 for v in size) or size[0] < 640 or size[1] < 360:
        raise ValueError("video.size needs even integer dimensions, at least 640x360")
    for key in ("fps", "seconds_per_sample"):
        if isinstance(video[key], bool) or not math.isfinite(float(video[key])) or float(video[key]) <= 0:
            raise ValueError(f"video.{key} must be positive and finite")
    if video["fps"] * video["seconds_per_sample"] < 1:
        raise ValueError("seconds_per_sample * fps must be >= 1")
    if not 0 <= video["crf"] <= 51:
        raise ValueError("video.crf must be 0..51")
    if video["preset"] not in ("ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"):
        raise ValueError("Unknown H.264 preset")
    if Path(video["output"]).suffix.lower() != ".mp4":
        raise ValueError("video.output must end with .mp4")
    if config["on_missing"] not in ("placeholder", "skip", "error"):
        raise ValueError("on_missing must be placeholder, skip, or error")
    if config["layout"]["mode"] not in ("four_plus_bev", "cameras_plus_bev", "clouds_plus_bev"):
        raise ValueError("Unknown layout.mode")
    if not .4 <= config["layout"]["left_fraction"] <= .8:
        raise ValueError("layout.left_fraction must be 0.4..0.8")
    if type(config["layout"]["show_frame_info"]) is not bool:
        raise ValueError("layout.show_frame_info must be true or false")
    padding = config["layout"]["panel_padding"]
    if type(padding) is not int or not 0 <= padding <= 48:
        raise ValueError("layout.panel_padding must be an integer from 0 to 48 (at 1080p)")
    if cloud["coordinates"] not in ("local", "vehicle"):
        raise ValueError("point_cloud.coordinates must be local or vehicle")
    bounds = cloud["bounds"]
    if len(bounds) != 6 or not all(math.isfinite(float(v)) for v in bounds) or any(
            bounds[i] >= bounds[i + 3] for i in range(3)):
        raise ValueError("point_cloud.bounds needs [xmin,ymin,zmin,xmax,ymax,zmax]")
    if (len(cloud["height_range"]) != 2 or not all(math.isfinite(float(v)) for v in cloud["height_range"])
            or not cloud["height_range"][0] < cloud["height_range"][1]):
        raise ValueError("point_cloud.height_range must increase")
    if not 0 < cloud["elevation"] <= 90 or not math.isfinite(float(cloud["azimuth"])):
        raise ValueError("Point cloud elevation must be (0,90], azimuth finite")
    if type(cloud["zoom"]) not in (int, float) or not math.isfinite(cloud["zoom"]) or cloud["zoom"] <= 0:
        raise ValueError("point_cloud.zoom must be a positive finite number")
    if type(cloud["max_points"]) is not int or cloud["max_points"] < 1:
        raise ValueError("max_points must be a positive integer")
    if type(cloud["point_size"]) is not int or cloud["point_size"] not in (1, 3, 5):
        raise ValueError("point_size must be 1, 3, or 5")
    if (cloud["color_by"] not in ("height", "intensity", "sensor") or cloud["intensity_max"] <= 0
            or not math.isfinite(float(cloud["intensity_max"]))):
        raise ValueError("Invalid color_by or intensity_max")
    if config["limit"] is not None and (type(config["limit"]) is not int or config["limit"] < 1):
        raise ValueError("limit must be null or a positive integer")


def save_report(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def source_path(item, name):
    return item.result if name == "result" else getattr(item.pair, name.replace("_camera", "_image"))


def load_content(item, dataset, config, compositor):
    content, issues = {}, []
    for name in compositor.boxes():
        path = source_path(item, name)
        try:
            if name.endswith("points"):
                value = read_points(path)
                if name == "infrastructure_points" and config["point_cloud"]["coordinates"] == "vehicle":
                    matrix = dataset.infrastructure_to_vehicle(
                        item.pair, config["point_cloud"]["apply_system_error_offset"])
                    value = transform_points(value, matrix)
                content[name] = value
            else:
                value = open_rgb(path)
                if name == "result":
                    # Inspect validates the same image transforms used for export.
                    transform_result(value, config["results"])
                content[name] = value
        except (OSError, ValueError, KeyError, UnicodeError) as exc:
            issues.append({"panel": name, "path": str(path), "error": str(exc)})
            content[name] = None
    return content, issues


def run(config, command, preview_count=5, overwrite=False):
    output = Path(config["video"]["output"])
    report_path = output.with_name(output.stem + f".{command}.report.json")
    preview_dir = output.parent / (output.stem + "_previews")
    if command == "render" and output.exists() and not overwrite:
        raise ValueError(f"Output exists: {output}. Use --overwrite to replace it.")
    if command == "preview" and preview_dir.exists() and any(preview_dir.glob("*.png")) and not overwrite:
        raise ValueError(f"Preview images exist: {preview_dir}. Use --overwrite to replace matching previews.")
    dataset = DAIRDataset(Path(config["dataset_root"]))
    items, mapping_errors = resolve_items(dataset, config)
    report = {"command": command, "status": "running",
              "dataset_root": str(dataset.root),
              "config": config, "mapping_errors": mapping_errors, "frames": [],
              "matched_samples": len(items), "written_samples": 0, "video_frames": 0}
    save_report(report_path, report)
    if mapping_errors or not items:
        report["status"] = "failed_mapping"
        save_report(report_path, report)
        raise ValueError(f"Frame mapping failed; inspect {report_path}")
    if command == "preview":
        items = items[:preview_count]
        preview_dir.mkdir(parents=True, exist_ok=True)
    compositor = Compositor(config)
    writer = None
    temporary = output.with_name(output.stem + ".partial.mp4")
    frames_per_sample = max(1, round(config["video"]["fps"] * config["video"]["seconds_per_sample"]))
    try:
        if command == "render":
            output.parent.mkdir(parents=True, exist_ok=True)
            if temporary.exists():
                raise ValueError(f"Temporary output exists: {temporary}; rename/remove it before retrying")
            writer = imageio_ffmpeg.write_frames(
                str(temporary), tuple(config["video"]["size"]), fps=config["video"]["fps"],
                codec="libx264", pix_fmt_out="yuv420p", macro_block_size=1,
                quality=None, ffmpeg_log_level="error",
                output_params=["-crf", str(config["video"]["crf"]), "-preset", config["video"]["preset"],
                               "-movflags", "+faststart"])
            writer.send(None)
        for number, item in enumerate(items, 1):
            content, issues = load_content(item, dataset, config, compositor)
            record = {"result_image": str(item.result), "source_token": item.token,
                      "split_index": item.split_index,
                      "vehicle_frame_id": item.pair.vehicle_id,
                      "infrastructure_frame_id": item.pair.infrastructure_id,
                      "sources": {name: str(source_path(item, name))
                                  for name in compositor.boxes()},
                      "issues": issues, "status": "checked"}
            report["frames"].append(record)
            # A missing detection image never becomes an apparently valid result frame.
            if issues and (config["on_missing"] == "error" or
                           (content.get("result") is None and config["on_missing"] == "placeholder")):
                raise ValueError(f"Input error for {item.result.name}; see report")
            if issues and config["on_missing"] == "skip":
                record["status"] = "skipped"
                print(f"[{number}/{len(items)}] skipped {item.result.name}", flush=True)
                continue
            if command != "inspect":
                frame = compositor.compose(item, content, number, len(items), issues)
                if command == "preview":
                    target = preview_dir / f"{number:04d}_{item.pair.vehicle_id}.png"
                    frame.save(target)
                    record["preview"] = str(target)
                else:
                    payload = frame.tobytes()
                    for _ in range(frames_per_sample):
                        writer.send(payload)
                    report["video_frames"] += frames_per_sample
                report["written_samples"] += 1
                record["status"] = "written_with_placeholders" if issues else "written"
            print(f"[{number}/{len(items)}] {item.result.name} -> "
                  + (f"split[{item.split_index}] -> " if item.split_index is not None else "")
                  + f"VEH {item.pair.vehicle_id} / "
                  f"INF {item.pair.infrastructure_id}" + (f" ({len(issues)} issues)" if issues else ""), flush=True)
            if number % 20 == 0:
                save_report(report_path, report)
        if writer is not None:
            writer.close()
            writer = None
            if not report["video_frames"]:
                raise ValueError("No frames written; all inputs were skipped")
            count, duration = imageio_ffmpeg.count_frames_and_secs(str(temporary))
            if count != report["video_frames"]:
                raise ValueError(f"Encoded frame count mismatch: {count} != {report['video_frames']}")
            report["duration_seconds"] = duration
            report["verified_encoded_frames"] = count
            temporary.replace(output)
            report["output"] = str(output)
        report["status"] = "complete_with_issues" if any(r["issues"] for r in report["frames"]) else "complete"
    except BaseException as exc:
        report["status"] = "failed"
        report["error"] = str(exc)
        raise
    finally:
        try:
            if writer is not None:
                writer.close()
        finally:
            save_report(report_path, report)
    print(f"Report: {report_path}")
    if command == "preview":
        print(f"Previews: {preview_dir}")
    elif command == "render":
        print(f"Video: {output} ({report['video_frames']} frames, {report['duration_seconds']:.2f}s)")
    return report
