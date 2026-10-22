"""Read DAIR pairing metadata without importing a training framework."""

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def data_path(root: Path, value: str) -> Path:
    # DAIR metadata paths are POSIX relative paths, including on Windows.
    return root / Path(str(value).replace("\\", "/"))


def frame_id(value) -> str:
    return Path(str(value).replace("\\", "/")).stem


@dataclass(frozen=True)
class Pair:
    vehicle_id: str
    infrastructure_id: str
    info: dict
    vehicle_image: Path
    infrastructure_image: Path
    vehicle_points: Path
    infrastructure_points: Path


@dataclass(frozen=True)
class Item:
    result: Path
    pair: Pair
    token: str
    split_index: int | None = None


class DAIRDataset:
    def __init__(self, root: Path):
        self.root = Path(root)
        if not (self.root / "cooperative/data_info.json").is_file():
            nested = self.root / "cooperative-vehicle-infrastructure"
            if (nested / "cooperative/data_info.json").is_file():
                self.root = nested
        rows = read_json(self.root / "cooperative" / "data_info.json")
        if not isinstance(rows, list):
            raise ValueError("cooperative/data_info.json must be a list")
        self.by_vehicle = {}
        for info in rows:
            pair = Pair(
                frame_id(info["vehicle_image_path"]),
                frame_id(info["infrastructure_image_path"]), info,
                data_path(self.root, info["vehicle_image_path"]),
                data_path(self.root, info["infrastructure_image_path"]),
                data_path(self.root, info["vehicle_pointcloud_path"]),
                data_path(self.root, info["infrastructure_pointcloud_path"]),
            )
            self.by_vehicle.setdefault(pair.vehicle_id, []).append(pair)

    def pair(self, vehicle: str, infrastructure: str = "") -> Pair:
        candidates = self.by_vehicle.get(vehicle, [])
        if infrastructure:
            candidates = [p for p in candidates if p.infrastructure_id == infrastructure]
        if not candidates:
            raise ValueError(
                f"No cooperative mapping for vehicle {vehicle!r}"
                + (f" / infrastructure {infrastructure!r}" if infrastructure else "")
            )
        # OPENCPV builds co_data[vehicle_id] in file order: the last record wins.
        return candidates[-1]

    def load_split(self, path: Path, key: str) -> list[str]:
        """Preserve the complete inference split order, including unavailable mini frames."""
        split = read_json(path)
        if isinstance(split, dict):
            if key not in split:
                raise ValueError(f"Split key {key!r} missing; available: {list(split)}")
            split = split[key]
        if not isinstance(split, list) or any(not isinstance(x, str) for x in split):
            raise ValueError("Split must contain string frame IDs (keep leading zeros)")
        return split

    def infrastructure_to_vehicle(self, pair: Pair, apply_offset: bool) -> np.ndarray:
        """T_v_i = inverse(T_world_vehicle) @ T_world_infrastructure.

        File layout and system_error_offset convention follow the supplied loader.
        Full float64 rigid matrices are composed directly, without Euler round trips.
        """
        vehicle_calib = self.root / "vehicle-side" / "calib"
        infrastructure_calib = self.root / "infrastructure-side" / "calib"
        lidar_to_novatel = rigid_matrix(read_json(
            vehicle_calib / "lidar_to_novatel" / f"{pair.vehicle_id}.json"))
        novatel_to_world = rigid_matrix(read_json(
            vehicle_calib / "novatel_to_world" / f"{pair.vehicle_id}.json"))
        infrastructure_world = rigid_matrix(read_json(
            infrastructure_calib / "virtuallidar_to_world" / f"{pair.infrastructure_id}.json"))
        if apply_offset:
            if "system_error_offset" not in pair.info:
                raise ValueError("system_error_offset missing; explicitly disable apply_system_error_offset "
                                 "if the data has no correction")
            offset = pair.info["system_error_offset"]
            infrastructure_world[:2, 3] += [float(offset["delta_x"]), float(offset["delta_y"])]
        return np.linalg.solve(novatel_to_world @ lidar_to_novatel, infrastructure_world)


def rigid_matrix(value: dict) -> np.ndarray:
    value = value.get("transform", value)
    rotation = np.asarray(value["rotation"], dtype=np.float64).reshape(3, 3)
    translation = np.asarray(value["translation"], dtype=np.float64).reshape(3)
    if not np.isfinite(rotation).all() or not np.isfinite(translation).all():
        raise ValueError("Nonfinite calibration")
    if not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-3) or not np.isclose(
            np.linalg.det(rotation), 1, atol=1e-3):
        raise ValueError("Calibration rotation is not a rigid rotation")
    result = np.eye(4)
    result[:3, :3], result[:3, 3] = rotation, translation
    return result


def transform_points(points: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    result = points.copy()
    result[:, :3] = points[:, :3].astype(np.float64) @ matrix[:3, :3].T + matrix[:3, 3]
    return result


def resolve_items(dataset: DAIRDataset, config: dict):
    """Map results explicitly, never infer a sample stride or zero padding."""
    results = config["results"]
    directory = Path(results["directory"])
    mode = results.get("mode", "auto")
    errors, items = [], []
    if mode == "csv":
        with Path(results["mapping_csv"]).open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if not {"result_image", "vehicle_frame_id"}.issubset(reader.fieldnames or []):
                raise ValueError("Mapping CSV requires result_image,vehicle_frame_id")
            records = [(data_path(directory, row["result_image"]), row) for row in reader]
    else:
        files = list(directory.glob(results.get("glob", "bev_*.png")))
        pattern = re.compile(results.get("id_regex", r"^bev_(\d+)\.png$"))
        records = []
        for path in files:
            match = pattern.fullmatch(path.name)
            if not match:
                errors.append({"result_image": str(path), "error": "Filename does not match id_regex"})
            else:
                records.append((path, {"token": match.group(1)}))
        # Numeric sequence order, preserving the original ID string for lookup.
        records.sort(key=lambda entry: ((0, int(entry[1]["token"])) if entry[1]["token"].isdigit()
                                       else (1, entry[1]["token"])))
    selected = results.get("indices")
    if selected is not None:
        # Select original inference indices; never enumerate a compacted mini list.
        available = {}
        for path, row in records:
            try:
                index = int(row["token"]) - int(results.get("index_base", 0))
                available.setdefault(index, []).append((path, row))
            except ValueError:
                errors.append({"result_image": str(path), "error": "Inference index must be an integer"})
        records = []
        for index in selected:
            matches = available.get(index, [])
            if not matches:
                errors.append({"split_index": index, "error": "No result image for selected inference index"})
            elif len(matches) > 1:
                errors.append({"split_index": index, "error": "Multiple result images for inference index"})
            else:
                records.append(matches[0])
    split = None
    if mode in ("auto", "index"):
        if not results.get("split_file"):
            raise ValueError("Auto/index mode needs the exact inference split_file; frame order cannot be guessed")
        split = dataset.load_split(results["split_file"], results.get("split_key", "val"))
    elif mode not in ("frame_id", "csv"):
        raise ValueError(f"Unknown results.mode: {mode}")
    if not records and not errors:
        raise ValueError("No result images found; check results.directory / glob / mapping_csv")
    limit = config.get("limit")
    if limit is not None:
        records = records[:int(limit)]
    seen = set()
    seen_indices = set()
    for path, row in records:
        try:
            index = None
            if path.resolve() in seen:
                raise ValueError("Duplicate result_image in mapping")
            seen.add(path.resolve())
            token = row.get("token", row.get("vehicle_frame_id", ""))
            if mode in ("auto", "index"):
                index = int(token) - int(results.get("index_base", 0))
                if index < 0 or index >= len(split):
                    raise ValueError(f"Inference index {token} outside split of length {len(split)}")
                if mode == "auto" and index in seen_indices:
                    raise ValueError(f"Multiple result images for inference index {index}")
                seen_indices.add(index)
                vehicle = split[index]
            elif mode == "csv":
                vehicle = row["vehicle_frame_id"].strip()
            else:
                vehicle = token
            pair = dataset.pair(vehicle, row.get("infrastructure_frame_id", "").strip())
            items.append(Item(path, pair, token, split_index=index))
        except (ValueError, KeyError) as exc:
            errors.append({"result_image": str(path), "error": str(exc)})
    return items, errors
