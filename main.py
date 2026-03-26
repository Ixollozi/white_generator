from __future__ import annotations

import argparse
import sys
from pathlib import Path

from core.config_loader import resolve_config
from core.runner import generate_all


def _cmd_generate(args: argparse.Namespace) -> int:
    project_root = Path(__file__).resolve().parent
    config_arg = args.config or args.config_file
    if args.config and args.config_file:
        print("Use either positional config path or --config, not both.", file=sys.stderr)
        return 2
    config_path = Path(config_arg).resolve() if config_arg else None
    cli_overrides: dict = {}
    if args.count is not None:
        cli_overrides["count"] = args.count
    if args.output_dir:
        cli_overrides["output_dir"] = args.output_dir
    if args.base_url:
        cli_overrides["base_url"] = args.base_url
    if args.seed is not None:
        cli_overrides["seed"] = args.seed
    if args.templates:
        cli_overrides["templates"] = [t.strip() for t in args.templates.split(",") if t.strip()]
    if args.zip:
        cli_overrides["zip_each_site"] = True

    cfg = resolve_config(config_path, cli_overrides, project_root)
    sites = generate_all(cfg)
    for s in sites:
        print(s)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="White-site generator")
    sub = parser.add_subparsers(dest="command", required=True)

    g = sub.add_parser("generate", help="Generate one or more sites")
    g.add_argument(
        "config_file",
        nargs="?",
        default=None,
        help="Path to config YAML (optional if using flags only)",
    )
    g.add_argument("--config", type=str, default=None, help="Path to config YAML")
    g.add_argument("--count", type=int, default=None, help="Number of sites")
    g.add_argument("--output-dir", type=str, default=None, help="Output directory (under project root)")
    g.add_argument("--base-url", type=str, default=None, help="Canonical base URL for sitemap")
    g.add_argument("--seed", type=int, default=None, help="Global seed (per-site seeds are derived)")
    g.add_argument("--templates", type=str, default=None, help="Comma-separated template ids")
    g.add_argument("--zip", action="store_true", help="Write a zip next to each site folder")
    g.set_defaults(func=_cmd_generate)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
