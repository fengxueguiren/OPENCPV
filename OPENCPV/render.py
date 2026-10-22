"""Deterministic CPU point-cloud rasterization and fixed video layouts."""

import math
import os
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

from .i18n import text
from .themes import get_theme


@lru_cache(maxsize=64)
def get_font(size, custom=None):
    candidates = [custom] if custom else []
    candidates += [
        str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "msyh.ttc"),
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/PingFang.ttc",
    ]
    for path in candidates:
        if path and Path(path).is_file():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default(size)


def fit_text(draw, value, font, max_width):
    value = str(value)
    if draw.textlength(value, font=font) <= max_width:
        return value
    while value and draw.textlength(value + "...", font=font) > max_width:
        value = value[:-1]
    return value + "..."


def open_rgb(path):
    with Image.open(path) as image:
        image = ImageOps.exif_transpose(image)
        if image.mode in ("RGBA", "LA") or "transparency" in image.info:
            image = image.convert("RGBA")
            background = Image.new("RGBA", image.size, "white")
            image = Image.alpha_composite(background, image)
        return image.convert("RGB")


def crop_result(image, box):
    if box is None:
        return image
    if len(box) != 4:
        raise ValueError("results.crop must be [left,top,right,bottom] in source pixels")
    left, top, right, bottom = map(int, box)
    if not (0 <= left < right <= image.width and 0 <= top < bottom <= image.height):
        raise ValueError(f"Result crop {box} outside image {image.size}")
    return image.crop((left, top, right, bottom))


def transform_result(image, config):
    """Apply pixel crop, fractional margins, then counterclockwise rotation."""
    image = crop_result(image, config.get("crop"))
    left, top, right, bottom = config.get("crop_margins", [0, 0, 0, 0])
    box = (round(image.width * left), round(image.height * top),
           image.width - round(image.width * right),
           image.height - round(image.height * bottom))
    if box[0] >= box[2] or box[1] >= box[3]:
        raise ValueError(f"results.crop_margins leaves no pixels in image {image.size}")
    if box != (0, 0, image.width, image.height):
        image = image.crop(box)
    rotation = config.get("rotation", 0) % 360
    if rotation:
        operation = {90: Image.Transpose.ROTATE_90, 180: Image.Transpose.ROTATE_180,
                     270: Image.Transpose.ROTATE_270}[rotation]
        image = image.transpose(operation)
    return image


def placeholder(size, label, font, theme="light"):
    colors = get_theme(theme)
    image = Image.new("RGB", size, colors["panel"])
    draw = ImageDraw.Draw(image)
    width, height = size
    draw.line((width * .4, height * .3, width * .6, height * .5), fill=colors["placeholder"], width=2)
    draw.line((width * .6, height * .3, width * .4, height * .5), fill=colors["placeholder"], width=2)
    value = fit_text(draw, label, font, width - 30)
    draw.text((width / 2, height * .65), value, fill=colors["muted"], font=font, anchor="mm")
    return image


def draw_axes(image, projected, palette, custom_font=None):
    """Draw an outlined orientation triad with labels beyond the arrow tips."""
    width, height = image.size
    unit = max(.55, min(width / 563, height / 371))
    draw = ImageDraw.Draw(image)
    font = get_font(max(11, round(15 * unit)), custom_font)
    origin = projected[0]
    if not np.all((origin >= 0) & (origin < [width, height])):
        return
    line_width = max(2, round(3 * unit))
    halo_width = line_width + max(2, round(4 * unit))
    halo = palette["background"]
    axes = []
    for endpoint, color, name in zip(projected[1:], palette["axes"], ("X", "Y", "Z")):
        vector = endpoint - origin
        length = np.linalg.norm(vector)
        if length < 1e-6:
            continue
        direction = vector / length
        # Short projected Z axes still need enough room for an arrow and label.
        tip = origin + direction * max(length, 26 * unit)
        if not np.all((tip >= 2) & (tip < [width - 2, height - 2])):
            continue
        normal = np.array([-direction[1], direction[0]])
        arrow_length = max(4, 7 * unit)
        triangle = [tuple(tip), tuple(tip - direction * arrow_length + normal * arrow_length * .5),
                    tuple(tip - direction * arrow_length - normal * arrow_length * .5)]
        segment = [tuple(origin), tuple(tip)]
        draw.line(segment, fill=halo, width=halo_width)
        draw.polygon(triangle, fill=halo)
        draw.line(triangle + triangle[:1], fill=halo, width=max(2, round(3 * unit)))
        draw.line(segment, fill=color, width=line_width)
        draw.polygon(triangle, fill=color)
        axes.append((tip, direction, color, name))
    radius = max(2, round(3 * unit))
    draw.ellipse((origin[0] - radius, origin[1] - radius, origin[0] + radius, origin[1] + radius),
                 fill=palette["text"], outline=halo, width=1)
    occupied = []
    samples = [origin + np.linspace(0, 1, 48)[:, None] * (tip - origin) for tip, _, _, _ in axes]
    for tip, direction, color, name in axes:
        bbox = draw.textbbox((0, 0), name, font=font, anchor="mm")
        half = np.array([(bbox[2] - bbox[0]) / 2 + 4 * unit,
                         (bbox[3] - bbox[1]) / 2 + 3 * unit])
        distance = np.linalg.norm(half) + 5 * unit
        for _ in range(16):
            center = np.clip(tip + direction * distance, half + 2, [width - 2, height - 2] - half)
            low, high = center - half, center + half
            labels_overlap = any(np.all(high + 3 * unit > a) and np.all(low - 3 * unit < b)
                                 for a, b in occupied)
            lines_overlap = any(np.any(np.all((line >= low - 2) & (line <= high + 2), axis=1))
                                for line in samples)
            if not labels_overlap and not lines_overlap:
                break
            distance += 5 * unit
        occupied.append((low, high))
        draw.rounded_rectangle(tuple(low) + tuple(high), radius=max(2, round(3 * unit)),
                               fill=halo, outline=color, width=1)
        # Center the glyph's actual bounding box, including its baseline offset.
        position = center - np.array([(bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2])
        draw.text(tuple(position), name, font=font, fill=color, anchor="mm")


def render_cloud(points, size, config, accent):
    """Fixed orthographic viewpoint; bounds and scale never depend on a frame.

    Depth-sorted pixels give a stable, lightweight pseudo-3D view. This is a
    visualization renderer, not a perspective camera or a sensor projection.
    """
    width, height = size
    palette = get_theme(config.get("theme", "light"))
    image = Image.new("RGB", size, palette["panel"])
    bounds = np.asarray(config["bounds"], dtype=float).reshape(2, 3)
    points = points[np.all((points[:, :3] >= bounds[0]) & (points[:, :3] <= bounds[1]), axis=1)]
    if len(points) > config["max_points"]:
        indices = np.linspace(0, len(points) - 1, config["max_points"], dtype=int)
        points = points[indices]
    yaw = math.radians(config["azimuth"])
    elevation = math.radians(config["elevation"])
    horizontal = np.array([-math.sin(yaw), math.cos(yaw), 0])
    vertical = np.array([-math.sin(elevation) * math.cos(yaw),
                         -math.sin(elevation) * math.sin(yaw), math.cos(elevation)])
    depth_axis = np.cross(horizontal, vertical)
    center = (bounds[0] + bounds[1]) / 2
    corners = np.array([[x, y, z] for x in bounds[:, 0] for y in bounds[:, 1] for z in bounds[:, 2]])
    corner_uv = np.column_stack(((corners - center) @ horizontal, (corners - center) @ vertical))
    low, high = corner_uv.min(axis=0), corner_uv.max(axis=0)
    scale = min((width - 30) / (high[0] - low[0]), (height - 30) / (high[1] - low[1]))
    scale *= config.get("zoom", 1.3)
    middle = (low + high) / 2

    def project(xyz):
        uv = np.column_stack(((xyz - center) @ horizontal, (xyz - center) @ vertical)) - middle
        return np.column_stack((width / 2 + uv[:, 0] * scale, height / 2 - uv[:, 1] * scale))

    draw = ImageDraw.Draw(image)
    ground_z = max(bounds[0, 2], min(0, bounds[1, 2]))
    for x in np.arange(math.ceil(bounds[0, 0] / 10) * 10, bounds[1, 0] + .1, 10):
        grid = project(np.array([[x, bounds[0, 1], ground_z], [x, bounds[1, 1], ground_z]]))
        draw.line([tuple(p) for p in grid], fill=palette["grid"])
    for y in np.arange(math.ceil(bounds[0, 1] / 10) * 10, bounds[1, 1] + .1, 10):
        grid = project(np.array([[bounds[0, 0], y, ground_z], [bounds[1, 0], y, ground_z]]))
        draw.line([tuple(p) for p in grid], fill=palette["grid"])
    if len(points):
        order = np.argsort(points[:, :3] @ depth_axis)
        points = points[order]
        pixels = np.rint(project(points[:, :3])).astype(int)
        if config["color_by"] == "height":
            t = np.clip((points[:, 2] - config["height_range"][0]) /
                        (config["height_range"][1] - config["height_range"][0]), 0, 1)
            stops = np.array(palette["height_colors"])
            colors = np.column_stack([np.interp(t, [0, .35, .7, 1], stops[:, c]) for c in range(3)])
        elif config["color_by"] == "intensity":
            t = np.clip(points[:, 3] / config["intensity_max"], 0, 1)
            low, high = palette["intensity_range"]
            colors = np.repeat((low + (high - low) * t)[:, None], 3, axis=1)
        else:
            color = tuple(int(accent[i:i + 2], 16) for i in (1, 3, 5))
            colors = np.tile(color, (len(points), 1))
        colors = colors.astype(np.uint8)
        raster = np.asarray(image).copy()
        # Each pixel gets the nearest point deterministically, including duplicate pixels.
        radius = int(config["point_size"]) // 2
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                x, y = pixels[:, 0] + dx, pixels[:, 1] + dy
                valid = (x >= 0) & (x < width) & (y >= 0) & (y < height)
                flat = y[valid] * width + x[valid]
                if len(flat):
                    _, from_end = np.unique(flat[::-1], return_index=True)
                    selected = len(flat) - 1 - from_end
                    raster.reshape(-1, 3)[flat[selected]] = colors[valid][selected]
        image = Image.fromarray(raster)
    origin = np.array([[0, 0, 0], [8, 0, 0], [0, 8, 0], [0, 0, 4]])
    draw_axes(image, project(origin), palette, config.get("font"))
    draw = ImageDraw.Draw(image)
    font = get_font(max(11, height // 24), config.get("font"))
    if config.get("show_frame_info", False):
        label = text("point_count" if len(points) else "empty_cloud",
                     config.get("language", "bilingual"), count=len(points))
        label = fit_text(draw, label, font, width - 24)
        draw.text((12, height - 12), label, font=font, fill=palette["muted"], anchor="ls")
    return image


class Compositor:
    def __init__(self, config):
        self.config = config
        self.colors = get_theme(config.get("theme", "light"))
        self.width, self.height = config["video"]["size"]
        self.unit = self.height / 1080
        self.font = get_font(max(12, round(24 * self.unit)), config.get("font"))
        self.small = get_font(max(10, round(18 * self.unit)), config.get("font"))
        self.title = get_font(max(16, round(31 * self.unit)), config.get("font"))

    def boxes(self):
        w, h, u = self.width, self.height, self.unit
        margin, gap = round(24 * u), round(16 * u)
        top = round(90 * u)
        bottom = h - round((64 if self.config["layout"]["show_frame_info"] else 24) * u)
        right = margin + round((w - margin * 2 - gap) * self.config["layout"]["left_fraction"]) + gap
        left_end = right - gap
        mid = margin + (left_end - margin - gap) // 2
        layout = self.config["layout"]["mode"]
        if layout == "four_plus_bev":
            middle_y = top + (bottom - top - gap) // 2
            return {
                "vehicle_camera": (margin, top, mid, middle_y),
                "infrastructure_camera": (mid + gap, top, left_end, middle_y),
                "vehicle_points": (margin, middle_y + gap, mid, bottom),
                "infrastructure_points": (mid + gap, middle_y + gap, left_end, bottom),
                "result": (right, top, w - margin, bottom),
            }
        suffix = "camera" if layout == "cameras_plus_bev" else "points"
        return {f"vehicle_{suffix}": (margin, top, mid, bottom),
                f"infrastructure_{suffix}": (mid + gap, top, left_end, bottom),
                "result": (right, top, w - margin, bottom)}

    def panel_content_box(self, box):
        x0, y0, x1, y1 = box
        padding = max(2, round(self.config["layout"]["panel_padding"] * self.unit))
        return x0 + padding, y0 + round(52 * self.unit) + padding, x1 - padding, y1 - padding

    def panel_content_size(self, box):
        x0, y0, x1, y1 = self.panel_content_box(box)
        return x1 - x0, y1 - y0

    def compose(self, item, content, number, total, issues):
        config = self.config
        colors = self.colors
        image = Image.new("RGB", (self.width, self.height), colors["background"])
        draw = ImageDraw.Draw(image)
        u = self.unit
        margin = round(24 * u)
        language = config["language"]
        title = config["title"] or text("title", language)
        draw.text((margin, round(25 * u)), fit_text(draw, title, self.title, self.width - margin * 2),
                  font=self.title, fill=colors["text"])
        labels = {
            "vehicle_camera": (text("vehicle_camera", language), colors["vehicle"]),
            "infrastructure_camera": (text("infrastructure_camera", language), colors["infrastructure"]),
            "vehicle_points": (text("vehicle_points", language), colors["vehicle"]),
            "infrastructure_points": (text("infrastructure_points", language), colors["infrastructure"]),
            "result": (text("result", language), colors["result"]),
        }
        for key, box in self.boxes().items():
            x0, y0, x1, y1 = box
            label, accent = labels[key]
            draw.rounded_rectangle(box, radius=round(9 * u), fill=colors["panel"],
                                   outline=colors["border"], width=1)
            draw.line((x0 + 1, y0 + 1, x1 - 1, y0 + 1), fill=accent, width=max(2, round(3 * u)))
            draw.text((x0 + round(12 * u), y0 + round(14 * u)),
                      fit_text(draw, label, self.font, x1 - x0 - 24 * u), fill=accent, font=self.font)
            size = self.panel_content_size(box)
            source = content.get(key)
            if source is None:
                source = placeholder(size, text("unavailable", language), self.small, config.get("theme", "light"))
            elif key.endswith("points"):
                source = render_cloud(source, size, {**config["point_cloud"], "font": config.get("font"),
                                                     "language": language, "theme": config.get("theme", "light"),
                                                     "show_frame_info": config["layout"]["show_frame_info"]}, accent)
            elif key == "result":
                source = transform_result(source, config["results"])
            fitted = ImageOps.contain(source, size, Image.Resampling.LANCZOS)
            content_left, content_top, _, _ = self.panel_content_box(box)
            left = content_left + (size[0] - fitted.width) // 2
            upper = content_top + (size[1] - fitted.height) // 2
            image.paste(fitted, (left, upper))
        draw = ImageDraw.Draw(image)
        if config["layout"]["show_frame_info"]:
            footer_y = self.height - round(44 * u)
            pair = item.pair
            status = f"{number:03d}/{total:03d}  |  " + text("vehicle_id", language, id=pair.vehicle_id)
            status += "  |  " + text("infrastructure_id", language, id=pair.infrastructure_id)
            if item.split_index is not None:
                status += "  |  " + text("split_index", language, index=item.split_index)
            local = config["point_cloud"]["coordinates"] == "local"
            status += "  |  " + text("local_coordinates" if local else "vehicle_coordinates", language)
            if issues:
                status += "  |  " + text("issues", language, count=len(issues))
            draw.text((margin, footer_y), fit_text(draw, status, self.small, self.width - margin * 2),
                      font=self.small, fill=colors["warning"] if issues else colors["muted"])
        progress_y = self.height - max(3, round(5 * u))
        draw.rectangle((0, progress_y, round(self.width * number / total), self.height), fill=colors["vehicle"])
        return image
