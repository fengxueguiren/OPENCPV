"""Behavior tests for DAIR geometry, sample identity and PCD encodings."""

import copy
import csv
import json
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import imageio_ffmpeg
import numpy as np
from PIL import ImageColor, ImageDraw

from OPENCPV.dataset import DAIRDataset, read_json, resolve_items, rigid_matrix, transform_points
from OPENCPV.pcd import decompress_lzf, read_points
from OPENCPV.pipeline import load_config, load_content, run, validate
from OPENCPV.render import Compositor, crop_result, open_rgb, transform_result
from OPENCPV.themes import get_theme


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


class PCDTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_all_encodings_with_mixed_fields_and_count(self):
        # Reordered fields, mixed scalar sizes, a multi-component descriptor, NaN filtering.
        dtype = np.dtype([("intensity", "<u2"), ("normal", "<f4", (3,)),
                          ("z", "<f8"), ("x", "<f4"), ("y", "<f4")])
        records = np.zeros(3, dtype=dtype)
        records["intensity"] = [12, 240, 1]
        records["normal"] = [[0, 0, 1]] * 3
        records["x"], records["y"], records["z"] = [1, -8, np.nan], [2, 6, 3], [3, -.5, 4]
        header = ("VERSION .7\nFIELDS intensity normal z x y\nSIZE 2 4 8 4 4\n"
                  "TYPE U F F F F\nCOUNT 1 3 1 1 1\nWIDTH 3\nHEIGHT 1\nPOINTS 3\nDATA ")
        soa = b"".join(records[name].tobytes() for name in records.dtype.names)
        lzf = b"".join(bytes([len(soa[i:i + 32]) - 1]) + soa[i:i + 32] for i in range(0, len(soa), 32))
        bodies = {"ascii": b"12 0 0 1 3 1 2\n240 0 0 1 -.5 -8 6\n1 0 0 1 4 nan 3\n",
                  "binary": records.tobytes(),
                  "binary_compressed": struct.pack("<II", len(lzf), len(soa)) + lzf}
        for mode, body in bodies.items():
            with self.subTest(mode=mode):
                path = self.root / f"{mode}.pcd"
                path.write_bytes((header + mode + "\n").encode() + body)
                np.testing.assert_allclose(read_points(path), [[1, 2, 3, 12], [-8, 6, -.5, 240]])
        # Real DAIR compressed PCDs have unused bytes after the declared block.
        padded = self.root / "binary_compressed.pcd"
        padded.write_bytes(padded.read_bytes() + bytes(3900))
        np.testing.assert_allclose(read_points(padded), [[1, 2, 3, 12], [-8, 6, -.5, 240]])
        padded.write_bytes((header + "binary_compressed\n").encode() + bodies["binary_compressed"][:-1])
        with self.assertRaisesRegex(ValueError, "payload size mismatch"):
            read_points(padded)

    def test_lzf_overlapping_reference(self):
        self.assertEqual(decompress_lzf(b"\x00A\xe0\x02\x00", 12), b"A" * 12)

    def test_corrupt_lzf_and_binary_are_rejected(self):
        for data, length in [(b"\x03ab", 4), (b"\x20\x00", 3), (b"\xe0", 3), (b"\x00x", 2)]:
            with self.subTest(data=data), self.assertRaises(ValueError):
                decompress_lzf(data, length)
        path = self.root / "truncated.pcd"
        path.write_bytes(b"FIELDS x y z\nSIZE 4 4 4\nTYPE F F F\nPOINTS 2\nDATA binary\n1234")
        with self.assertRaises(ValueError):
            read_points(path)

    def test_empty_pcd_and_npy(self):
        path = self.root / "empty.pcd"
        path.write_text("FIELDS x y z\nSIZE 4 4 4\nTYPE F F F\nWIDTH 0\nHEIGHT 1\nDATA ascii\n")
        self.assertEqual(read_points(path).shape, (0, 4))
        path = self.root / "points.npy"
        np.save(path, [[1, 2, 3]])
        np.testing.assert_equal(read_points(path), [[1, 2, 3, 0]])


class DatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        project = Path(__file__).resolve().parents[1]
        source_config = load_config(project / "config.mini.json")
        source_dataset = DAIRDataset(Path(source_config["dataset_root"]))
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.path = cls.root / "config.json"
        dataset_root = cls.root / "dataset"
        records = []
        for vehicle in ("000211", "000876"):
            pair = source_dataset.pair(vehicle)
            record = copy.deepcopy(pair.info)
            for name in ("vehicle_image_path", "infrastructure_image_path",
                         "vehicle_pointcloud_path", "infrastructure_pointcloud_path"):
                record[name] = str(source_dataset.root / record[name])
            records.append(record)
        write_json(dataset_root / "cooperative/data_info.json", records)
        results = cls.root / "results"
        results.mkdir()
        for name in ("bev_00000.png", "bev_00010.png"):
            shutil.copyfile(Path(source_config["results"]["directory"]) / name, results / name)
        config = copy.deepcopy(source_config)
        config["dataset_root"] = str(dataset_root)
        config["results"].update(directory=str(results), indices=None)
        config["video"]["output"] = str(cls.root / "result.mp4")
        config["on_missing"] = "placeholder"
        write_json(cls.path, config)
        cls.config = load_config(cls.path)
        cls.dataset = DAIRDataset(Path(cls.config["dataset_root"]))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_sparse_indices_follow_split_not_file_ordinal(self):
        items, errors = resolve_items(self.dataset, self.config)
        self.assertFalse(errors)
        self.assertEqual([i.token for i in items], ["00000", "00010"])
        self.assertEqual([i.pair.vehicle_id for i in items], ["000211", "000876"])
        self.assertEqual([i.pair.infrastructure_id for i in items], ["007410", "005764"])

    def test_auto_mode_is_default_and_rejects_duplicate_inference_indices(self):
        config = read_json(self.path)
        config["results"].pop("mode")
        path = self.root / "auto.json"
        write_json(path, config)
        config = load_config(path)
        self.assertEqual(config["results"]["mode"], "auto")
        items, errors = resolve_items(self.dataset, config)
        self.assertFalse(errors)
        self.assertEqual([i.split_index for i in items], [0, 10])
        self.assertEqual([i.pair.vehicle_id for i in items], ["000211", "000876"])
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            for name in ("bev_00010.png", "bev_10.png"):
                shutil.copyfile(Path(config["results"]["directory"]) / "bev_00010.png", directory / name)
            config["results"]["directory"] = str(directory)
            items, errors = resolve_items(self.dataset, config)
            self.assertEqual(len(items), 1)
            self.assertIn("Multiple result images", errors[0]["error"])

    def test_video_language_covers_titles_clouds_and_frame_information(self):
        config = copy.deepcopy(self.config)
        config["title"] = None
        config["layout"]["show_frame_info"] = True
        item = resolve_items(self.dataset, config)[0][0]
        content, issues = load_content(item, self.dataset, config, Compositor(config))
        original = ImageDraw.ImageDraw.text
        for language in ("zh", "en", "bilingual"):
            with self.subTest(language=language):
                config["language"] = language
                labels = []
                def record(draw, xy, value, *args, **kwargs):
                    labels.append(str(value))
                    return original(draw, xy, value, *args, **kwargs)
                with patch.object(ImageDraw.ImageDraw, "text", record):
                    frame = Compositor(config).compose(item, content, 1, 2, issues)
                has_chinese = lambda value: any("\u4e00" <= char <= "\u9fff" for char in value)
                self.assertEqual(any(has_chinese(value) for value in labels), language != "en")
                self.assertEqual(any("VEHICLE CAMERA" in value for value in labels), language != "zh")
                self.assertEqual(any("points | grid" in value for value in labels), language != "zh")
                self.assertEqual(any("各传感器本地坐标系" in value for value in labels), language != "en")
                box = Compositor(config).boxes()["result"]
                middle = (box[0] + box[2]) // 2
                # Both strips stay clear even when the BEV is limited by panel height.
                panel_color = ImageColor.getrgb(get_theme(config["theme"])["panel"])
                self.assertEqual(frame.getpixel((middle, box[1] + 53)), panel_color)
                self.assertEqual(frame.getpixel((middle, box[3] - 2)), panel_color)

    def test_frame_information_switch_controls_point_counts_and_footer(self):
        config = copy.deepcopy(self.config)
        config["language"] = "en"
        item = resolve_items(self.dataset, config)[0][0]
        content, issues = load_content(item, self.dataset, config, Compositor(config))
        original = ImageDraw.ImageDraw.text
        for enabled in (False, True):
            with self.subTest(enabled=enabled):
                config["layout"]["show_frame_info"] = enabled
                labels = []
                def record(draw, xy, value, *args, **kwargs):
                    labels.append(str(value))
                    return original(draw, xy, value, *args, **kwargs)
                with patch.object(ImageDraw.ImageDraw, "text", record):
                    Compositor(config).compose(item, content, 1, 2, issues)
                self.assertEqual(sum("points | grid" in value for value in labels), 2 if enabled else 0)
                self.assertEqual(any("VEH 000211" in value for value in labels), enabled)

    def test_direct_entrypoint_renders_from_another_directory(self):
        script = Path(__file__).resolve().parents[1] / "run.py"
        config = read_json(self.path)
        config["dataset_root"] = self.config["dataset_root"]
        config["results"] = self.config["results"]
        output = self.root / "direct_entry.mp4"
        config["video"].update(output=str(output), size=[640, 360], fps=5,
                               seconds_per_sample=.4, preset="ultrafast")
        config_path = self.root / "direct_entry.json"
        write_json(config_path, config)
        process = subprocess.run(
            [sys.executable, str(script), "render", "--config", str(config_path), "--limit", "1"],
            cwd=self.root, capture_output=True, text=True, timeout=60)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        report = read_json(output.with_suffix(".render.report.json"))
        self.assertEqual(report["status"], "complete")
        self.assertEqual(report["verified_encoded_frames"], 2)
        self.assertTrue(output.is_file())

    def test_module_entrypoint_inspects_inputs(self):
        project = Path(__file__).resolve().parents[1]
        process = subprocess.run(
            [sys.executable, "-m", "OPENCPV", "inspect", "--config", str(self.path)],
            cwd=project, capture_output=True, text=True, timeout=60)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        output = Path(self.config["video"]["output"])
        report = read_json(output.with_name(output.stem + ".inspect.report.json"))
        self.assertEqual(report["status"], "complete")
        self.assertEqual(report["matched_samples"], 2)

    def test_frame_id_and_csv_mapping_keep_leading_zeros(self):
        rows = read_json(Path(self.config["dataset_root"]) / "cooperative/data_info.json")
        rows[0]["vehicle_image_path"] = "vehicle-side/image/000123.jpg"
        root = self.root / "leading"
        write_json(root / "cooperative/data_info.json", rows[:1])
        dataset = DAIRDataset(root)
        results = self.root / "leading_results"
        results.mkdir(exist_ok=True)
        (results / "bev_000123.png").touch()
        config = copy.deepcopy(self.config)
        config["results"].update(directory=str(results), mode="frame_id")
        items, errors = resolve_items(dataset, config)
        self.assertFalse(errors)
        self.assertEqual(items[0].pair.vehicle_id, "000123")
        mapping = results / "mapping.csv"
        with mapping.open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.writer(stream)
            writer.writerow(["result_image", "vehicle_frame_id", "infrastructure_frame_id"])
            writer.writerow(["arbitrary-name.png", "000123", "007410"])
        config["results"].update(mode="csv", mapping_csv=str(mapping))
        items, errors = resolve_items(dataset, config)
        self.assertFalse(errors)
        self.assertEqual(items[0].pair.vehicle_id, "000123")

    def test_missing_split_and_wrong_index_fail_explicitly(self):
        config = copy.deepcopy(self.config)
        config["results"].pop("split_file")
        with self.assertRaisesRegex(ValueError, "exact inference split"):
            resolve_items(self.dataset, config)
        config = copy.deepcopy(self.config)
        config["results"]["index_base"] = 100
        items, errors = resolve_items(self.dataset, config)
        self.assertFalse(items)
        self.assertEqual(len(errors), 2)

    def test_duplicate_pairs_use_last_record_like_OPENCPV(self):
        rows = read_json(Path(self.config["dataset_root"]) / "cooperative/data_info.json")
        alternate = copy.deepcopy(rows[0])
        alternate["infrastructure_image_path"] = "infrastructure-side/image/999999.jpg"
        root = self.root / "duplicate"
        write_json(root / "cooperative/data_info.json", rows + [alternate])
        dataset = DAIRDataset(root)
        self.assertEqual(dataset.pair("000211").infrastructure_id, "999999")
        self.assertEqual(dataset.pair("000211", "007410").infrastructure_id, "007410")
        self.assertEqual(dataset.pair("000211", "999999").infrastructure_id, "999999")

    def test_rotated_calibration_composition_and_error_offset(self):
        pair = copy.deepcopy(self.dataset.pair("000211"))
        pair.info["system_error_offset"] = {"delta_x": 2, "delta_y": -3}
        root = self.root / "calibrated"
        rotation = [[0, -1, 0], [1, 0, 0], [0, 0, 1]]
        write_json(root / "cooperative/data_info.json", [pair.info])
        a = {"rotation": rotation, "translation": [1, 2, 3]}
        b = {"rotation": np.eye(3).tolist(), "translation": [[10], [20], [30]]}
        c = {"rotation": np.eye(3).tolist(), "translation": [[11], [22], [33]]}
        write_json(root / "vehicle-side/calib/lidar_to_novatel/000211.json", {"transform": a})
        write_json(root / "vehicle-side/calib/novatel_to_world/000211.json", b)
        write_json(root / "infrastructure-side/calib/virtuallidar_to_world/007410.json", c)
        dataset = DAIRDataset(root)
        matrix = dataset.infrastructure_to_vehicle(pair, True)
        point = np.array([[1., 2., 3., 99.]])
        # Infrastructure world: (14,21,36); vehicle world origin (11,22,33), yaw +90.
        np.testing.assert_allclose(transform_points(point, matrix), [[-1, -3, 3, 99]], atol=1e-6)
        np.testing.assert_allclose(transform_points(transform_points(point, matrix), np.linalg.inv(matrix)), point)
        no_offset = dataset.infrastructure_to_vehicle(pair, False)
        np.testing.assert_allclose(no_offset[:3, 3], [0, 0, 0], atol=1e-6)

    def test_nonrigid_calibration_rejected(self):
        with self.assertRaises(ValueError):
            rigid_matrix({"rotation": np.zeros((3, 3)), "translation": [0, 0, 0]})

    def test_real_h264_encode_decode_count_and_dimensions(self):
        config = copy.deepcopy(self.config)
        config["video"].update(output=str(self.root / "video.mp4"), size=[640, 360], fps=5,
                               seconds_per_sample=.4, preset="ultrafast")
        report = run(config, "render")
        self.assertEqual(report["status"], "complete")
        self.assertEqual(report["verified_encoded_frames"], 4)
        self.assertAlmostEqual(report["duration_seconds"], .8, places=2)
        reader = imageio_ffmpeg.read_frames(config["video"]["output"])
        try:
            metadata = next(reader)
            self.assertEqual(metadata["size"], (640, 360))
            self.assertEqual(metadata["codec"], "h264")
            self.assertEqual(len(list(reader)), 4)
        finally:
            reader.close()
        with self.assertRaisesRegex(ValueError, "Output exists"):
            run(config, "render")

    def test_camera_only_layout_does_not_require_cloud_files(self):
        config = copy.deepcopy(self.config)
        config["layout"]["mode"] = "cameras_plus_bev"
        config["video"]["output"] = str(self.root / "camera-only.mp4")
        rows = read_json(Path(config["dataset_root"]) / "cooperative/data_info.json")
        for row in rows:
            row["vehicle_pointcloud_path"] = "nonexistent.pcd"
            row["infrastructure_pointcloud_path"] = "also_missing.pcd"
        root = self.root / "cameras"
        # Absolute source paths remain usable in a subset dataset metadata file.
        for row in rows:
            for key in ("vehicle_image_path", "infrastructure_image_path"):
                row[key] = str(Path(config["dataset_root"]) / row[key])
        write_json(root / "cooperative/data_info.json", rows)
        config["dataset_root"] = str(root)
        report = run(config, "inspect")
        self.assertEqual(report["status"], "complete")

    def test_missing_panels_placeholder_skip_and_error(self):
        config = copy.deepcopy(self.config)
        rows = read_json(Path(config["dataset_root"]) / "cooperative/data_info.json")
        for row in rows:
            for key in ("vehicle_image_path", "infrastructure_image_path", "vehicle_pointcloud_path", "infrastructure_pointcloud_path"):
                row[key] = str(Path(config["dataset_root"]) / row[key])
        rows[0]["vehicle_image_path"] = str(self.root / "missing/000211.jpg")
        root = self.root / "missing"
        write_json(root / "cooperative/data_info.json", rows)
        config["dataset_root"] = str(root)
        config["video"].update(output=str(self.root / "missing.mp4"), size=[640, 360])
        report = run(config, "preview", preview_count=1)
        self.assertEqual(report["status"], "complete_with_issues")
        self.assertTrue(Path(report["frames"][0]["preview"]).is_file())
        config["on_missing"] = "skip"
        report = run(config, "inspect")
        self.assertEqual(report["frames"][0]["status"], "skipped")
        config["on_missing"] = "error"
        with self.assertRaisesRegex(ValueError, "Input error"):
            run(config, "inspect")
        self.assertEqual(read_json(self.root / "missing.inspect.report.json")["status"], "failed")

    def test_layouts_have_valid_nonoverlapping_panels_and_result_crop(self):
        for mode in ("four_plus_bev", "cameras_plus_bev", "clouds_plus_bev"):
            for size in ([640, 360], [1920, 1080]):
                config = copy.deepcopy(self.config)
                config["layout"]["mode"] = mode
                config["video"]["size"] = size
                compositor = Compositor(config)
                boxes = list(compositor.boxes().values())
                for i, (x0, y0, x1, y1) in enumerate(boxes):
                    self.assertTrue(0 <= x0 < x1 <= size[0] and 0 <= y0 < y1 <= size[1])
                    self.assertTrue(all(v > 0 for v in compositor.panel_content_size(boxes[i])))
                    for a, b, c, d in boxes[i + 1:]:
                        self.assertTrue(x1 <= a or c <= x0 or y1 <= b or d <= y0)
        result = open_rgb(Path(self.config["results"]["directory"]) / "bev_00000.png")
        self.assertEqual(crop_result(result, [0, 0, 50, 50]).size, (50, 50))
        with self.assertRaises(ValueError):
            crop_result(result, [0, 0, 9999, 9999])

    def test_invalid_config_values(self):
        for group, key, value in [("video", "fps", 0), ("video", "size", [641, 360]),
                                  ("point_cloud", "height_range", [4, 4]),
                                  ("point_cloud", "zoom", 0),
                                  ("point_cloud", "zoom", -1),
                                  ("point_cloud", "zoom", True),
                                  ("point_cloud", "zoom", float("nan")),
                                  ("point_cloud", "bounds", [0, 0, 0, 0, 1, 1]),
                                  ("results", "id_regex", "no-capture"),
                                  ("results", "id_regex", "[invalid"),
                                  ("results", "mode", "guess"),
                                  ("results", "indices", [0, 0]),
                                  ("results", "indices", [-1]),
                                  ("results", "indices", [True]),
                                  ("results", "indices", []),
                                  ("results", "crop_margins", None),
                                  ("results", "crop_margins", [0, 0]),
                                  ("results", "crop_margins", [-.1, 0, 0, 0]),
                                  ("results", "crop_margins", [.5, 0, .5, 0]),
                                  ("results", "crop_margins", [0, .6, 0, .5]),
                                  ("results", "crop_margins", [True, 0, 0, 0]),
                                  ("results", "crop_margins", [float("nan"), 0, 0, 0]),
                                  ("results", "rotation", 45),
                                  ("results", "rotation", 90.0),
                                  ("results", "rotation", True),
                                  ("layout", "panel_padding", -1),
                                  ("layout", "panel_padding", 49),
                                  ("layout", "panel_padding", True)]:
            config = copy.deepcopy(self.config)
            config[group][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate(config)
        for language in (None, "chinese", 1):
            config = copy.deepcopy(self.config)
            config["language"] = language
            with self.subTest(language=language), self.assertRaises(ValueError):
                validate(config)

    def test_result_crop_and_rotation_preserve_pixels_and_direction(self):
        source = open_rgb(Path(self.config["results"]["directory"]) / "bev_00000.png")
        pixels = np.asarray(source)
        transformed = transform_result(source, {"crop_margins": [1/6, 0, 1/6, 0], "rotation": 90})
        self.assertEqual(transformed.size, (1000, 1680))
        np.testing.assert_array_equal(transformed, np.rot90(pixels[:, 420:2100]))
        # Pixel crop precedes relative margins; negative rotation is clockwise.
        transformed = transform_result(source, {"crop": [120, 100, 2400, 900],
                                                "crop_margins": [.25, 0, .25, 0], "rotation": -90})
        np.testing.assert_array_equal(transformed, np.rot90(pixels[100:900, 690:1830], k=-1))
        self.assertIs(transform_result(source, {}), source)
        for angle in (0, 90, 180, 270, 360):
            with self.subTest(angle=angle):
                np.testing.assert_array_equal(transform_result(source, {"rotation": angle}),
                                              np.rot90(pixels, k=angle // 90))


class MiniDatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.project = Path(__file__).resolve().parents[1]
        config_path = cls.project / "config.mini.json"
        if not (cls.project / "examples/DAIR-V2X-mini/cooperative-vehicle-infrastructure/val.json").is_file():
            raise unittest.SkipTest("DAIR-V2X-mini not present")
        cls.config = load_config(config_path)
        cls.dataset = DAIRDataset(Path(cls.config["dataset_root"]))

    def test_exact_validation_indices_and_vehicle_infrastructure_mapping(self):
        items, errors = resolve_items(self.dataset, self.config)
        self.assertFalse(errors)
        self.assertEqual([item.split_index for item in items], list(range(0, 100, 10)))
        expected = [("000211", "007410"), ("000876", "005764"), ("000916", "005805"),
                    ("000927", "005816"), ("000937", "005826"), ("000947", "005836"),
                    ("000958", "005847"), ("000978", "005867"), ("000999", "005889"),
                    ("001012", "005902")]
        self.assertEqual([(item.pair.vehicle_id, item.pair.infrastructure_id) for item in items], expected)
        split = read_json(self.config["results"]["split_file"])
        self.assertEqual(len(split), 1789)
        for item in items:
            self.assertEqual(item.pair.vehicle_id, split[item.split_index])
            self.assertEqual(item.result.name, f"bev_{item.split_index:05d}.png")
            for path in (item.result, item.pair.vehicle_image, item.pair.infrastructure_image,
                         item.pair.vehicle_points, item.pair.infrastructure_points):
                self.assertTrue(path.is_file(), path)

    def test_wrapper_and_dataset_root_resolve_to_same_records(self):
        direct = DAIRDataset(self.dataset.root)
        self.assertEqual(direct.root, self.dataset.root)
        self.assertEqual(direct.pair("000211"), self.dataset.pair("000211"))

    def test_complete_metadata_keeps_OPENCPV_last_record_for_duplicates(self):
        rows = read_json(self.dataset.root / "cooperative/data_info.json")
        expected = {}
        for row in rows:
            expected[Path(row["vehicle_image_path"]).stem] = row
        self.assertGreater(len(rows), len(expected))
        for vehicle, row in expected.items():
            self.assertEqual(self.dataset.pair(vehicle).info, row)

    def test_all_selected_real_point_clouds_decode(self):
        items, _ = resolve_items(self.dataset, self.config)
        for item in items:
            for path in (item.pair.vehicle_points, item.pair.infrastructure_points):
                with self.subTest(path=path.name, side=path.parent.parent.name):
                    points = read_points(path)
                    self.assertGreater(len(points), 10000)
                    self.assertEqual(points.shape[1], 4)
                    self.assertTrue(np.isfinite(points).all())

    def test_selection_preserves_full_split_offsets_and_explicit_order(self):
        config = copy.deepcopy(self.config)
        config["results"]["indices"] = [90, 10]
        items, errors = resolve_items(self.dataset, config)
        self.assertFalse(errors)
        self.assertEqual([i.pair.vehicle_id for i in items], ["001012", "000876"])
        self.assertEqual([i.split_index for i in items], [90, 10])
        config["limit"] = 1
        items, errors = resolve_items(self.dataset, config)
        self.assertFalse(errors)
        self.assertEqual([i.split_index for i in items], [90])

    def test_selected_result_must_exist(self):
        config = copy.deepcopy(self.config)
        config["results"]["indices"] = [0, 999]
        items, errors = resolve_items(self.dataset, config)
        self.assertEqual(len(items), 1)
        self.assertEqual(errors[0]["split_index"], 999)


if __name__ == "__main__":
    unittest.main()
