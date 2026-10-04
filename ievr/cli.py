from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import zipfile

from .convert import (
    identity_fingerprint,
    pc_autosave_to_switch,
    switch_autosave_to_pc,
    top_objects,
    transplant_pc_identity,
)
from .pc import SYSTEMLIVE, USERDATALIVE, parse_pc_file, rebuild_from_template
from .switch import _member_bytes, pack_switch_blob_experimental, read_switch_save
from .steam import (
    detect_active_steam_account_id,
    detect_active_steam_id64,
    resolve_steam_id,
    steam_id64_from_account_id,
    validate_steam_id64,
)


def steam_id_arg(value: str) -> str:
    if value.lower() == "auto":
        return "auto"
    try:
        return validate_steam_id64(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _write_manifest(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def cmd_switch_to_pc(args: argparse.Namespace) -> int:
    source = Path(args.switch_save).expanduser().resolve()
    template_path = Path(args.pc_template).expanduser().resolve()
    out_dir = Path(args.output).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_user = out_dir / USERDATALIVE
    if out_user.exists() and not args.force:
        raise ValueError(f"refusing to overwrite {out_user}; use --force")

    target = parse_pc_file(template_path, USERDATALIVE)
    switch = read_switch_save(source)
    switch_auto_pc = switch_autosave_to_pc(switch["AUTOSAVE"].unpacked)
    target_auto = target.blob("AUTOSAVE_data.bin").data
    converted_auto = transplant_pc_identity(switch_auto_pc, target_auto, args.identity_mode)
    result = rebuild_from_template(target, {"AUTOSAVE_data.bin": converted_auto})
    out_user.write_bytes(result)

    copied_system = None
    if args.system_template:
        system_path = Path(args.system_template).expanduser().resolve()
        parse_pc_file(system_path, SYSTEMLIVE)  # strict validation before copying
        copied_system = out_dir / SYSTEMLIVE
        shutil.copyfile(system_path, copied_system)

    resolved_steam_id = resolve_steam_id(args.steam_id)
    fp = identity_fingerprint(target)
    manifest = {
        "direction": "switch-to-pc",
        "tested_game_version": "7.1.2",
        "steam_id64": resolved_steam_id,
        "steam_id_note": (
            "The SteamID labels the intended target account. Account binding is currently "
            "derived from --pc-template, not calculated from SteamID64 alone."
        ),
        "identity_mode": args.identity_mode,
        "target_identity_fingerprint": {
            "guid_0x18C6F574": fp.guid_hex,
            "identity_object_0x100BFFEE_sha256": fp.identity_object_sha256,
            "pc_header_0x08": fp.pc_header_0x08_hex,
        },
        "output": {
            "USERDATALIVE_sha256": hashlib.sha256(result).hexdigest(),
            "USERDATALIVE_size": len(result),
            "SYSTEMLIVE_copied": copied_system is not None,
        },
    }
    _write_manifest(out_dir / "ievr-conversion.json", manifest)
    print(f"Wrote {out_user}")
    if copied_system:
        print(f"Copied {copied_system}")
    print(f"Identity mode: {args.identity_mode}")
    if resolved_steam_id:
        print(f"Target SteamID64: {resolved_steam_id}")
    print("Validation: OK")
    return 0


def cmd_steam_id(args: argparse.Namespace) -> int:
    if args.account_id is not None:
        account_id = args.account_id
        value = steam_id64_from_account_id(account_id)
        print(f"AccountID: {account_id}")
        print(f"SteamID64: {value}")
        return 0

    account_id = detect_active_steam_account_id()
    value = detect_active_steam_id64()
    if account_id is None or value is None:
        raise ValueError(
            "could not detect the active Steam account. "
            "This command reads HKCU\\Software\\Valve\\Steam\\ActiveProcess\\ActiveUser "
            "and therefore requires Windows with Steam running and logged in."
        )
    print(f"AccountID: {account_id}")
    print(f"SteamID64: {value}")
    return 0


def cmd_inspect_pc(args: argparse.Namespace) -> int:
    save = parse_pc_file(Path(args.path).expanduser().resolve(), args.name)
    print(f"Canonical name: {save.canonical_name}")
    print(f"Size: {len(save.raw):,} bytes")
    print(f"Header 0x08: {save.plain[8:12].hex()}")
    for blob in save.blobs:
        print(f"Blob: {blob.name:<20} {blob.size:>12,} bytes @0x{blob.offset:X}")
    if args.name == USERDATALIVE:
        fp = identity_fingerprint(save)
        print(f"Identity GUID 0x18C6F574: {fp.guid_hex}")
        print(f"Identity object SHA-256: {fp.identity_object_sha256}")
    return 0


def cmd_inspect_switch(args: argparse.Namespace) -> int:
    save = read_switch_save(Path(args.path).expanduser().resolve())
    for name, blob in save.items():
        print(
            f"{name:<10} encrypted={len(blob.encrypted):>9,}  "
            f"unpacked={len(blob.unpacked):>12,}  sha256={hashlib.sha256(blob.unpacked).hexdigest()}"
        )
    return 0


def cmd_pc_to_switch(args: argparse.Namespace) -> int:
    if not args.experimental:
        raise ValueError(
            "PC->Switch wrapper reconstruction is not yet game-validated. "
            "Re-run with --experimental only if you accept that limitation."
        )
    pc = parse_pc_file(Path(args.pc_save).expanduser().resolve(), USERDATALIVE)
    template_source = Path(args.switch_template).expanduser().resolve()
    out_dir = Path(args.output).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    pc_auto = pc.blob("AUTOSAVE_data.bin").data
    # Mirror the proven PC-target workflow: preserve progression from the source,
    # but transplant opaque account/platform material from the target Switch template
    # before expanding the four PC u32 fields back to the Switch u64 layout.
    switch_template = read_switch_save(template_source)
    template_auto_pc_layout = switch_autosave_to_pc(switch_template["AUTOSAVE"].unpacked)
    pc_auto_with_switch_identity = transplant_pc_identity(pc_auto, template_auto_pc_layout, "full")
    switch_auto = pc_autosave_to_switch(pc_auto_with_switch_identity)
    # HEADERSAVE cross-platform semantics are not fully proven in the reverse
    # direction, so preserve the supplied Switch template HEADERSAVE by default.
    template_auto_enc = _member_bytes(template_source, "AUTOSAVE")
    template_head_enc = _member_bytes(template_source, "HEADERSAVE")
    auto_enc = pack_switch_blob_experimental(switch_auto, "AUTOSAVE", template_auto_enc)

    auto_path = out_dir / "AUTOSAVE" / "data.bin"
    head_path = out_dir / "HEADERSAVE" / "data.bin"
    auto_path.parent.mkdir(parents=True, exist_ok=True)
    head_path.parent.mkdir(parents=True, exist_ok=True)
    auto_path.write_bytes(auto_enc)
    head_path.write_bytes(template_head_enc)
    print(f"Wrote experimental {auto_path}")
    print(f"Preserved template {head_path}")
    print("WARNING: PC->Switch outer-wrapper integrity is structurally tested but not yet confirmed in game.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ievr-convert",
        description="Inazuma Eleven: Victory Road 7.1.2 Switch/PC save conversion tools",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("switch-to-pc", help="convert a Switch save to a PC USERDATALIVE")
    p.add_argument("switch_save", help="Switch save ZIP or extracted folder")
    p.add_argument("--pc-template", required=True, help="native USERDATALIVE created by the target account")
    p.add_argument("--system-template", help="optional native SYSTEMLIVE from the same target account")
    p.add_argument(
        "--steam-id",
        type=steam_id_arg,
        help="17-digit SteamID64 of the intended target account, or 'auto' on Windows",
    )
    p.add_argument(
        "--identity-mode",
        choices=("full", "object", "guid"),
        default="full",
        help="account-identity transplant; full is recommended and game-confirmed",
    )
    p.add_argument("--output", default="converted", help="output folder (default: converted)")
    p.add_argument("--force", action="store_true", help="overwrite an existing output USERDATALIVE")
    p.set_defaults(func=cmd_switch_to_pc)

    p = sub.add_parser("steam-id", help="show the active SteamID64 or convert a userdata AccountID")
    p.add_argument(
        "--account-id",
        type=int,
        help="32-bit AccountID, e.g. the numeric folder name under Steam\\userdata",
    )
    p.set_defaults(func=cmd_steam_id)

    p = sub.add_parser("inspect-pc", help="validate and inspect a PC save")
    p.add_argument("path")
    p.add_argument("--name", choices=(USERDATALIVE, SYSTEMLIVE), default=USERDATALIVE)
    p.set_defaults(func=cmd_inspect_pc)

    p = sub.add_parser("inspect-switch", help="validate and inspect a Switch save")
    p.add_argument("path")
    p.set_defaults(func=cmd_inspect_switch)

    p = sub.add_parser("pc-to-switch", help="EXPERIMENTAL reverse conversion")
    p.add_argument("pc_save", help="PC USERDATALIVE")
    p.add_argument("--switch-template", required=True, help="real Switch save ZIP/folder used as wrapper template")
    p.add_argument("--output", default="converted-switch")
    p.add_argument("--experimental", action="store_true", help="acknowledge that game acceptance is not proven")
    p.set_defaults(func=cmd_pc_to_switch)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
