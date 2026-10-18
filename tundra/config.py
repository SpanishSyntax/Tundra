"""Declarative TOML configuration parser and serializer for Tundra (`tundra.toml`)."""

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class LockedPackage:
    key: str
    category: str  # "server" | "plugins" | "client"
    file_path: str
    name: str
    version: str
    sha256: str
    source_url: str
    purpose: str
    sha1: str = ""
    sha512: str = ""
    file_size: int = 0


@dataclass
class TundraConfig:
    name: str = "Tundra"
    mc_version: str = "1.20.1"
    release_url: str = "https://github.com/SpanishSyntax/Tundra/releases/download/v2.0.0"

    # [server]
    server_backend: str = "paper"  # "paper" | "purpur" | "folia" | "plugins-only" | "fabric"
    server_plugins: list[str] = field(
        default_factory=lambda: [
            "luckperms",
            "vault",
            "essentialsx",
            "essentialsx-chat",
            "essentialsx-spawn",
            "essentialsx-protect",
            "essentialsx-antibuild",
            "multiverse-core",
            "multiverse-inventories",
            "multiverse-netherportals",
            "multiverse-portals",
            "multiverse-signportals",
            "fastasyncworldedit",
            "worldguard",
            "chunky",
        ]
    )

    # [client]
    client_loader: str = "fabric"  # "fabric" (recommended) or "forge" / "neoforge"
    client_loader_version: str = ""  # e.g. "0.16.10" (fabric) or "47.4.10" (forge)
    include_prism_installer: bool = True
    prism_version: str = "11.1.1"
    client_mods: list[str] = field(
        default_factory=lambda: [
            "fabric-api",
            "sodium",
            "iris",
            "journeymap",
            "ferrite-core",
            "entityculling",
            "modmenu",
        ]
    )

    # [[packages]] lock entries
    packages: list[LockedPackage] = field(default_factory=list)


def find_manifest_path(explicit_path: str | Path | None = None) -> Path:
    """Locates tundra.toml in current directory or parent directories."""
    if explicit_path:
        return Path(explicit_path).expanduser().resolve()
    cwd = Path.cwd()
    for p in [cwd, *cwd.parents]:
        candidate = p / "tundra.toml"
        if candidate.is_file():
            return candidate
    return cwd / "tundra.toml"


def load_config(path: str | Path | None = None) -> TundraConfig:
    """Loads `tundra.toml` into a structured `TundraConfig` object."""
    cfg_path = find_manifest_path(path)
    if not cfg_path.is_file():
        return TundraConfig()

    raw: dict[str, Any] = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
    general = raw.get("general", {})
    server = raw.get("server", {})
    client = raw.get("client", {})
    raw_pkgs = raw.get("packages", [])

    locked: list[LockedPackage] = []
    for item in raw_pkgs:
        if not isinstance(item, dict):
            continue
        locked.append(
            LockedPackage(
                key=str(item.get("key", "")),
                category=str(item.get("category", "")),
                file_path=str(item.get("file_path", "")),
                name=str(item.get("name", "")),
                version=str(item.get("version", "")),
                sha256=str(item.get("sha256", "")),
                source_url=str(item.get("source_url", "")),
                purpose=str(item.get("purpose", "")),
                sha1=str(item.get("sha1", "")),
                sha512=str(item.get("sha512", "")),
                file_size=int(item.get("file_size", 0) or 0),
            )
        )

    cfg = TundraConfig()
    if "name" in general:
        cfg.name = str(general["name"])
    if "mc_version" in general:
        cfg.mc_version = str(general["mc_version"])
    if "release_url" in general:
        cfg.release_url = str(general["release_url"])

    if "backend" in server:
        cfg.server_backend = str(server["backend"])
    if "plugins" in server and isinstance(server["plugins"], list):
        cfg.server_plugins = [str(x) for x in server["plugins"]]

    if "loader" in client:
        cfg.client_loader = str(client["loader"])
    if "loader_version" in client:
        cfg.client_loader_version = str(client["loader_version"])
    if "include_prism_installer" in client:
        cfg.include_prism_installer = bool(client["include_prism_installer"])
    if "prism_version" in client:
        cfg.prism_version = str(client["prism_version"])
    if "mods" in client and isinstance(client["mods"], list):
        cfg.client_mods = [str(x) for x in client["mods"]]

    cfg.packages = locked
    return cfg


def _toml_str(val: str) -> str:
    escaped = val.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _toml_list(items: list[str]) -> str:
    if not items:
        return "[]"
    lines = ["["]
    for item in items:
        lines.append(f"  {_toml_str(item)},")
    lines.append("]")
    return "\n".join(lines)


def save_config(cfg: TundraConfig, path: str | Path | None = None) -> Path:
    """Serializes `TundraConfig` cleanly into `tundra.toml` with comments."""
    target = Path(path).resolve() if path else find_manifest_path(None)
    lines: list[str] = [
        "# ==============================================================================",
        "# TUNDRA - Declarative Minecraft Server & Client Stack Manifest",
        "# Managed via `tundra` (`tundra server` / `tundra client`)",
        "# ==============================================================================",
        "",
        "[general]",
        f"name = {_toml_str(cfg.name)}",
        f"mc_version = {_toml_str(cfg.mc_version)}",
        f"release_url = {_toml_str(cfg.release_url)}",
        "",
        "# ==============================================================================",
        "# SERVER STACK CONFIGURATION (`tundra server`)",
        '# Supported backends: "paper" (recommended), "purpur", "folia", "plugins-only", "fabric"',
        '# Note: Use "plugins-only" for managed hosts like Aternos where the panel provides the jar.',
        "# ==============================================================================",
        "",
        "[server]",
        f"backend = {_toml_str(cfg.server_backend)}",
        f"plugins = {_toml_list(cfg.server_plugins)}",
        "",
        "# ==============================================================================",
        "# CLIENT STACK CONFIGURATION (`tundra client`)",
        '# Supported loaders: "fabric" (recommended: Sodium + Iris) or "forge" (Embeddium + Oculus)',
        "# ==============================================================================",
        "",
        "[client]",
        f"loader = {_toml_str(cfg.client_loader)}",
        f"loader_version = {_toml_str(cfg.client_loader_version)}",
        f"include_prism_installer = {'true' if cfg.include_prism_installer else 'false'}",
        f"prism_version = {_toml_str(cfg.prism_version)}",
        f"mods = {_toml_list(cfg.client_mods)}",
        "",
        "# ==============================================================================",
        "# LOCKED PACKAGE MANIFEST (`[[packages]]`)",
        "# Pinning exact versions, SHA256 checksums, and upstream CDN URLs.",
        "# ==============================================================================",
    ]

    for pkg in cfg.packages:
        lines.extend(
            [
                "",
                "[[packages]]",
                f"key = {_toml_str(pkg.key)}",
                f"category = {_toml_str(pkg.category)}",
                f"file_path = {_toml_str(pkg.file_path)}",
                f"name = {_toml_str(pkg.name)}",
                f"version = {_toml_str(pkg.version)}",
                f"sha256 = {_toml_str(pkg.sha256)}",
                f"source_url = {_toml_str(pkg.source_url)}",
                f"purpose = {_toml_str(pkg.purpose)}",
            ]
        )
        if pkg.sha1:
            lines.append(f"sha1 = {_toml_str(pkg.sha1)}")
        if pkg.sha512:
            lines.append(f"sha512 = {_toml_str(pkg.sha512)}")
        if pkg.file_size:
            lines.append(f"file_size = {pkg.file_size}")

    lines.append("")
    target.write_text("\n".join(lines), encoding="utf-8")
    return target
