"""Command-line interface for input inspection, frame previews and video export."""

import argparse
import sys
from pathlib import Path

def main(argv=None):
    parser = argparse.ArgumentParser(description="Open Collaborative Perception Visualization (OPENCPV): "
                                    "DAIR-V2X camera, point-cloud and BEV video export")
    commands = parser.add_subparsers(dest="command", required=True)
    descriptions = {
        "inspect": "Check frame mapping and input files",
        "preview": "Export composed frames as PNG images",
        "render": "Export an MP4 video",
    }
    for name, description in descriptions.items():
        sub = commands.add_parser(name, help=description, description=description)
        sub.add_argument("--config", type=Path, required=True, help="Path to configuration JSON")
        sub.add_argument("--limit", type=int, help="Process at most N result images")
        if name != "inspect":
            sub.add_argument("--overwrite", action="store_true", help="Replace existing output")
        if name == "preview":
            sub.add_argument("--count", type=int, default=5, help="Number of preview frames (default: 5)")
    args = parser.parse_args(argv)
    from .pipeline import load_config, run

    try:
        config = load_config(args.config)
        if args.limit is not None:
            if args.limit < 1:
                raise ValueError("--limit must be positive")
            config["limit"] = args.limit
        count = getattr(args, "count", 5)
        if count < 1:
            raise ValueError("--count must be positive")
        run(config, args.command, count, getattr(args, "overwrite", False))
        return 0
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Cancelled.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
