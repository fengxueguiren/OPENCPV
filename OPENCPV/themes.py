"""Coordinated video palettes for light and dark backgrounds."""

THEMES = {
    "light": {
        "background": "#ffffff",
        "panel": "#f5f7fa",
        "text": "#182536",
        "muted": "#5b6b7e",
        "border": "#d8e0e9",
        "grid": "#dde4ec",
        "placeholder": "#8996a6",
        "vehicle": "#087884",
        "infrastructure": "#a95c16",
        "result": "#6b4db3",
        "warning": "#9a4c0d",
        "axes": ("#a91b69", "#7041b5", "#263445"),
        "height_colors": ((39, 91, 150), (17, 132, 132), (183, 133, 27), (194, 70, 57)),
        "intensity_range": (190, 35),
    },
    "dark": {
        "background": "#101722",
        "panel": "#172332",
        "text": "#edf2f7",
        "muted": "#9aafc4",
        "border": "#2a3b4e",
        "grid": "#24374a",
        "placeholder": "#4b6175",
        "vehicle": "#58d9ec",
        "infrastructure": "#ffbd72",
        "result": "#b8a1ff",
        "warning": "#ffbd72",
        "axes": ("#ff8cc6", "#c7a3ff", "#f2f5f9"),
        "height_colors": ((45, 90, 155), (64, 211, 204), (244, 205, 95), (255, 113, 89)),
        "intensity_range": (65, 255),
    },
}


def get_theme(name="light"):
    return THEMES[name]
