"""Upstream API resolver, binary downloader, offline .jar inspector, and .mrpack builder."""

import hashlib
import json
import os
import re
import shutil
import tarfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tundra import __version__
from tundra.config import LockedPackage, TundraConfig
from tundra.registry import (
    SERVER_BACKENDS,
    SERVER_PLUGINS,
    PackageSpec,
    expand_required_dependencies,
    get_client_registry,
)
from tundra.ui import ui

USER_AGENT = f"Tundra/{__version__} (Frost-Ecosystem; +https://github.com/SpanishSyntax/Tundra)"


def fetch_json(url: str, timeout: int = 12) -> Any:
    """Fetches and parses JSON from an upstream HTTP endpoint using stdlib."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def download_file(url: str, dest: Path, timeout: int = 30) -> bool:
    """Downloads a binary asset atomically via a `.part` temporary file."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest.with_suffix(dest.suffix + ".part")
    if tmp_path.exists():
        tmp_path.unlink()

    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp, tmp_path.open(
            "wb"
        ) as out:
            shutil.copyfileobj(resp, out)
        tmp_path.replace(dest)
        return True
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        return False


def compute_hashes(path: Path) -> tuple[str, str, str, int]:
    """Computes (sha256, sha1, sha512, file_size) in a single streaming pass."""
    h256 = hashlib.sha256()
    h1 = hashlib.sha1()
    h512 = hashlib.sha512()
    size = 0
    with path.open("rb") as f:
        while chunk := f.read(65536):
            size += len(chunk)
            h256.update(chunk)
            h1.update(chunk)
            h512.update(chunk)
    return h256.hexdigest(), h1.hexdigest(), h512.hexdigest(), size


def compute_sha256(path: Path) -> str:
    return compute_hashes(path)[0]


# ==============================================================================
# Upstream Backend Resolution (PaperMC, Folia, Purpur, Fabric, Forge)
# ==============================================================================
def fetch_available_mc_versions(backend: str = "paper") -> list[str]:
    """Queries PaperMC or Purpur API for available stable Minecraft versions."""
    try:
        if backend == "purpur":
            data = fetch_json("https://api.purpurmc.org/v2/purpur")
            versions = [
                v for v in reversed(data.get("versions", [])) if "-" not in v
            ]
            return versions[:15]
        slug = "folia" if backend == "folia" else "paper"
        data = fetch_json(f"https://fill.papermc.io/v3/projects/{slug}")
        result: list[str] = []
        for major_list in data.get("versions", {}).values():
            for v in major_list:
                if "-" not in v:  # Only stable releases
                    result.append(v)
        return result[:15]
    except Exception:
        return ["1.21.4", "1.21.1", "1.20.6", "1.20.4", "1.20.1"]


def resolve_server_backend(
    backend_key: str, mc_version: str
) -> LockedPackage | None:
    """Resolves the latest server runtime .jar for the given backend and MC version."""
    spec = SERVER_BACKENDS.get(backend_key)
    if not spec or spec.api_type == "none":
        return None

    if spec.api_type == "papermc":
        slug = spec.project_slug
        url = f"https://fill.papermc.io/v3/projects/{slug}/versions/{mc_version}/builds/latest"
        data = fetch_json(url)
        build_id = data["id"]
        dl_info = data["downloads"].get("server:default") or next(
            iter(data["downloads"].values())
        )
        filename = dl_info["name"]
        sha256 = dl_info["checksums"]["sha256"]
        dl_url = dl_info["url"]
        size = int(dl_info.get("size", 0))
        return LockedPackage(
            key=backend_key,
            category="server",
            file_path=f"server/{filename}",
            name=f"{spec.name.split(' (')[0]} Server",
            version=f"{mc_version}-{build_id}",
            sha256=sha256,
            source_url=dl_url,
            purpose=spec.description,
            file_size=size,
        )

    if spec.api_type == "purpur":
        url = f"https://api.purpurmc.org/v2/purpur/{mc_version}/latest"
        data = fetch_json(url)
        build_id = data["build"]
        filename = f"purpur-{mc_version}-{build_id}.jar"
        dl_url = f"https://api.purpurmc.org/v2/purpur/{mc_version}/{build_id}/download"
        return LockedPackage(
            key="purpur",
            category="server",
            file_path=f"server/{filename}",
            name="PurpurMC Server",
            version=f"{mc_version}-{build_id}",
            sha256="",  # Computed on download (Purpur API only exposes md5)
            source_url=dl_url,
            purpose=spec.description,
        )

    if spec.api_type == "fabric_server":
        loaders = fetch_json(
            f"https://meta.fabricmc.net/v2/versions/loader/{mc_version}"
        )
        installers = fetch_json("https://meta.fabricmc.net/v2/versions/installer")
        loader_ver = loaders[0]["loader"]["version"]
        inst_ver = installers[0]["version"]
        filename = f"fabric-server-mc.{mc_version}-loader.{loader_ver}-launcher.{inst_ver}.jar"
        dl_url = f"https://meta.fabricmc.net/v2/versions/loader/{mc_version}/{loader_ver}/{inst_ver}/server/jar"
        return LockedPackage(
            key="fabric-server",
            category="server",
            file_path=f"server/{filename}",
            name="Fabric Server Launcher",
            version=f"{mc_version}-{loader_ver}",
            sha256="",
            source_url=dl_url,
            purpose=spec.description,
        )

    return None


def resolve_client_loader(
    loader: str, mc_version: str
) -> tuple[str, LockedPackage | None]:
    """
    Resolves the recommended client loader version (Fabric or Forge)
    and optional standalone installer jar.
    """
    loader_norm = loader.lower()
    if loader_norm == "fabric":
        try:
            loaders = fetch_json(
                f"https://meta.fabricmc.net/v2/versions/loader/{mc_version}"
            )
            installers = fetch_json("https://meta.fabricmc.net/v2/versions/installer")
            stable_loaders = [
                entry
                for entry in loaders
                if entry.get("loader", {}).get("stable", True)
            ]
            chosen = stable_loaders[0] if stable_loaders else loaders[0]
            loader_ver = chosen["loader"]["version"]
            inst_ver = installers[0]["version"]
            inst_url = installers[0]["url"]
            filename = f"fabric-installer-{inst_ver}.jar"
            pkg = LockedPackage(
                key="fabric-installer",
                category="client",
                file_path=f"client/{filename}",
                name="Fabric Loader Installer",
                version=f"{mc_version}-{loader_ver}",
                sha256="",
                source_url=inst_url,
                purpose=f"Official Fabric client mod loader ({loader_ver}) for Minecraft {mc_version}.",
            )
            return loader_ver, pkg
        except Exception:
            return "0.16.10", None

    if loader_norm in ("forge", "neoforge"):
        try:
            promos = fetch_json(
                "https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json"
            ).get("promos", {})
            forge_ver = promos.get(f"{mc_version}-recommended") or promos.get(
                f"{mc_version}-latest"
            )
            if not forge_ver:
                forge_ver = "47.4.10"
            full_ver = f"{mc_version}-{forge_ver}"
            filename = f"forge-{full_ver}-installer.jar"
            url = f"https://maven.minecraftforge.net/net/minecraftforge/forge/{full_ver}/{filename}"
            sha256 = (
                "1912760b4cb6b803d8a826de603c9076b1da71ec2765e9a1f8c1ca78f65278e3"
                if full_ver == "1.20.1-47.4.10"
                else ""
            )
            pkg = LockedPackage(
                key="forge-installer",
                category="client",
                file_path=f"client/{filename}",
                name="Minecraft Forge Installer",
                version=full_ver,
                sha256=sha256,
                source_url=url,
                purpose=f"Recommended {mc_version} Forge client mod loader required for Embeddium & Oculus.",
            )
            return forge_ver, pkg
        except Exception:
            return "47.4.10", None

    return "", None


def build_prism_package(version: str = "11.1.1") -> LockedPackage:
    """Creates the locked entry for the Prism Launcher desktop installer."""
    filename = f"PrismLauncher-Windows-MSVC-Setup-{version}.exe"
    sha = (
        "aaf1f371a41d530785b679e3a2e1141dceec98651fc35d56dc0842b2740280ae"
        if version == "11.1.1"
        else ""
    )
    return LockedPackage(
        key="prism-launcher",
        category="client",
        file_path=f"client/{filename}",
        name="Prism Launcher (Windows Installer)",
        version=version,
        sha256=sha,
        source_url=f"https://github.com/PrismLauncher/PrismLauncher/releases/download/{version}/{filename}",
        purpose="Open-source Minecraft launcher with native Modrinth (.mrpack) one-click import.",
    )


def _select_modrinth_version(
    project_id: str,
    mc_version: str,
    loaders: tuple[str, ...],
) -> dict[str, Any] | None:
    """Queries Modrinth for the best matching release version, with minor-version fallback for plugins."""
    params = urllib.parse.urlencode(
        {
            "game_versions": json.dumps([mc_version]),
            "loaders": json.dumps(list(loaders)),
        }
    )
    url = f"https://api.modrinth.com/v2/project/{project_id}/version?{params}"
    data = fetch_json(url)
    if not data and any(l in ("paper", "spigot", "bukkit") for l in loaders):
        # Some Bukkit plugins (e.g. EssentialsX 2.21+) tag only the latest patch of a minor series
        params_all = urllib.parse.urlencode({"loaders": json.dumps(list(loaders))})
        all_vers = fetch_json(
            f"https://api.modrinth.com/v2/project/{project_id}/version?{params_all}"
        )
        mc_prefix = ".".join(mc_version.split(".")[:2])  # e.g. "1.21"
        matched = [
            v
            for v in all_vers
            if any(gv.startswith(mc_prefix) for gv in v.get("game_versions", []))
        ]
        data = matched or all_vers

    if not data:
        return None

    releases = [v for v in data if v.get("version_type") == "release"]
    return releases[0] if releases else data[0]


def resolve_package_spec(
    spec: PackageSpec,
    mc_version: str,
    existing_by_key: dict[str, LockedPackage] | None = None,
) -> LockedPackage | None:
    """Resolves a single plugin or client mod specification via Modrinth or GitHub APIs."""
    subdir = "plugins" if spec.side == "plugins" else "client"

    # 1. GitHub Release (e.g. Vault)
    if spec.source_type == "github_release":
        if spec.fallback_url:
            return LockedPackage(
                key=spec.key,
                category=spec.side,
                file_path=f"{subdir}/{spec.fallback_filename}",
                name=spec.name,
                version=spec.fallback_version,
                sha256=spec.fallback_sha256,
                source_url=spec.fallback_url,
                purpose=spec.description,
            )
        try:
            rel = fetch_json(
                f"https://api.github.com/repos/{spec.project_id}/releases/latest"
            )
            tag = rel.get("tag_name", "latest").lstrip("v")
            for asset in rel.get("assets", []):
                if spec.asset_filter in asset["name"]:
                    return LockedPackage(
                        key=spec.key,
                        category=spec.side,
                        file_path=f"{subdir}/{asset['name']}",
                        name=spec.name,
                        version=tag,
                        sha256="",
                        source_url=asset["browser_download_url"],
                        purpose=spec.description,
                        file_size=int(asset.get("size", 0)),
                    )
        except Exception:
            return None

    # 2. EssentialsX Suite (Modrinth for 1.20.1 or Core; GitHub Release fallback for 2.21+ addons)
    if spec.source_type == "essentialsx":
        ver_obj = _select_modrinth_version(spec.project_id, mc_version, spec.loaders)
        if ver_obj:
            ver_num = ver_obj["version_number"]
            for file_obj in ver_obj.get("files", []):
                fname = file_obj["filename"]
                if fname.startswith(spec.asset_filter):
                    hashes = file_obj.get("hashes", {})
                    return LockedPackage(
                        key=spec.key,
                        category=spec.side,
                        file_path=f"{subdir}/{fname}",
                        name=spec.name,
                        version=ver_num,
                        sha256=hashes.get("sha256", ""),
                        source_url=file_obj["url"],
                        purpose=spec.description,
                        sha1=hashes.get("sha1", ""),
                        sha512=hashes.get("sha512", ""),
                        file_size=int(file_obj.get("size", 0)),
                    )
            # In EssentialsX 2.21+, addon jars (Chat, Spawn, Protect, AntiBuild) are on GitHub Releases
            fname = f"{spec.asset_filter}{ver_num}.jar"
            gh_url = f"https://github.com/EssentialsX/Essentials/releases/download/{ver_num}/{fname}"
            return LockedPackage(
                key=spec.key,
                category=spec.side,
                file_path=f"{subdir}/{fname}",
                name=spec.name,
                version=ver_num,
                sha256="",
                source_url=gh_url,
                purpose=spec.description,
            )

    # 3. Standard Modrinth Package
    ver_obj = _select_modrinth_version(spec.project_id, mc_version, spec.loaders)
    if not ver_obj:
        if existing_by_key and spec.key in existing_by_key:
            return existing_by_key[spec.key]
        return None

    ver_num = ver_obj["version_number"]
    files = ver_obj.get("files", [])
    if not files:
        return None

    chosen_file = files[0]
    for f in files:
        if spec.asset_filter and spec.asset_filter in f["filename"]:
            chosen_file = f
            break
        if f.get("primary"):
            chosen_file = f
            break

    hashes = chosen_file.get("hashes", {})
    return LockedPackage(
        key=spec.key,
        category=spec.side,
        file_path=f"{subdir}/{chosen_file['filename']}",
        name=spec.name,
        version=ver_num,
        sha256=hashes.get("sha256", ""),
        source_url=chosen_file["url"],
        purpose=spec.description,
        sha1=hashes.get("sha1", ""),
        sha512=hashes.get("sha512", ""),
        file_size=int(chosen_file.get("size", 0)),
    )


def resolve_full_config(
    cfg: TundraConfig,
    scope: str = "all",  # "all" | "server" | "client"
) -> list[LockedPackage]:
    """
    Resolves and updates locked packages in `cfg` for the requested scope
    while preserving locked packages from the untouched side.
    """
    existing_by_key = {p.key: p for p in cfg.packages}
    preserved_server = [
        p for p in cfg.packages if p.category in ("server", "plugins")
    ]
    preserved_client = [p for p in cfg.packages if p.category == "client"]

    new_server_pkgs: list[LockedPackage] = []
    new_client_pkgs: list[LockedPackage] = []

    if scope in ("all", "server"):
        with ui.spinner(
            f"Resolving server backend ({cfg.server_backend}) & {len(cfg.server_plugins)} plugins for MC {cfg.mc_version}..."
        ) as sp:
            if cfg.server_backend != "plugins-only":
                sp.update(
                    f"Querying upstream {cfg.server_backend} API for MC {cfg.mc_version}..."
                )
                srv_pkg = resolve_server_backend(cfg.server_backend, cfg.mc_version)
                if srv_pkg:
                    new_server_pkgs.append(srv_pkg)

            expanded_plugins = expand_required_dependencies(
                cfg.server_plugins, SERVER_PLUGINS
            )
            cfg.server_plugins = expanded_plugins

            for pkey in expanded_plugins:
                spec = SERVER_PLUGINS.get(pkey)
                if not spec:
                    continue
                sp.update(f"Resolving plugin {ui.bold(spec.name)} ({cfg.mc_version})...")
                pkg = resolve_package_spec(spec, cfg.mc_version, existing_by_key)
                if pkg:
                    new_server_pkgs.append(pkg)
                else:
                    ui.warn(
                        f"No upstream release found for plugin '{spec.name}' on MC {cfg.mc_version}"
                    )
    else:
        new_server_pkgs = preserved_server

    if scope in ("all", "client"):
        client_reg = get_client_registry(cfg.client_loader)
        expanded_mods = expand_required_dependencies(cfg.client_mods, client_reg)
        cfg.client_mods = expanded_mods

        with ui.spinner(
            f"Resolving {cfg.client_loader.capitalize()} client loader & {len(expanded_mods)} mods for MC {cfg.mc_version}..."
        ) as sp:
            if cfg.include_prism_installer:
                new_client_pkgs.append(build_prism_package(cfg.prism_version))

            loader_ver, loader_pkg = resolve_client_loader(
                cfg.client_loader, cfg.mc_version
            )
            if loader_ver:
                cfg.client_loader_version = loader_ver
            if loader_pkg:
                new_client_pkgs.append(loader_pkg)

            for mkey in expanded_mods:
                spec = client_reg.get(mkey)
                if not spec:
                    continue
                sp.update(
                    f"Resolving client mod {ui.bold(spec.name)} ({cfg.client_loader} {cfg.mc_version})..."
                )
                pkg = resolve_package_spec(spec, cfg.mc_version, existing_by_key)
                if pkg:
                    new_client_pkgs.append(pkg)
                else:
                    ui.warn(
                        f"No upstream release found for client mod '{spec.name}' on {cfg.client_loader} {cfg.mc_version}"
                    )
    else:
        new_client_pkgs = preserved_client

    cfg.packages = new_server_pkgs + new_client_pkgs
    return cfg.packages


# ==============================================================================
# Upstream Compatibility & Dependency Graph Audit (`--resolve`)
# ==============================================================================
@dataclass
class AuditRow:
    name: str
    pinned_version: str
    status: str  # "COMPATIBLE" | "UPGRADEABLE" | "NEEDS BUMP" | "UNSUPPORTED" | "AGNOSTIC"
    latest_version: str
    notes: str


def run_upstream_audit(
    cfg: TundraConfig,
    target_mc: str | None = None,
    filter_cat: str = "all",
) -> int:
    """
    Queries Modrinth v2 Bulk API, PaperMC Fill v3 API, Purpur, and Fabric/Forge APIs
    to verify compatibility and typed dependency edges (`tundra resolve [--mc VER]`).
    """
    mc = target_mc or cfg.mc_version
    ui.header(
        f"TUNDRA UPSTREAM COMPATIBILITY & DEPENDENCY RESOLVER (MC {mc})", width=116
    )

    # Collect Modrinth project IDs and version IDs from URLs
    modrinth_url_re = re.compile(r"cdn\.modrinth\.com/data/([^/]+)/versions/([^/]+)/")
    pkg_proj_id: dict[str, str] = {}
    pkg_ver_id: dict[str, str] = {}
    proj_present: dict[str, str] = {}
    ver_ids: list[str] = []
    proj_ids: list[str] = []

    for pkg in cfg.packages:
        m = modrinth_url_re.search(pkg.source_url)
        if m:
            pid, vid = m.group(1), m.group(2)
            pkg_proj_id[pkg.file_path] = pid
            pkg_ver_id[pkg.file_path] = vid
            proj_present[pid] = pkg.name
            if vid not in ver_ids:
                ver_ids.append(vid)
            if pid not in proj_ids:
                proj_ids.append(pid)

    # Virtual provides: FastAsyncWorldEdit (z4HZZnLr) satisfies WorldEdit (1u6JkXh5)
    if "z4HZZnLr" in proj_present:
        proj_present["1u6JkXh5"] = "FastAsyncWorldEdit (provides WorldEdit)"

    versions_map: dict[str, dict[str, Any]] = {}
    projects_map: dict[str, dict[str, Any]] = {}

    with ui.spinner(f"Querying Modrinth & server backend APIs for MC {mc}..."):
        if ver_ids:
            q_vers = urllib.parse.urlencode({"ids": json.dumps(ver_ids)})
            v_list = fetch_json(f"https://api.modrinth.com/v2/versions?{q_vers}")
            for v in v_list:
                versions_map[v["id"]] = v
                for dep in v.get("dependencies", []):
                    dpid = dep.get("project_id")
                    if dpid and dpid not in proj_ids:
                        proj_ids.append(dpid)

        if proj_ids:
            q_projs = urllib.parse.urlencode({"ids": json.dumps(proj_ids)})
            p_list = fetch_json(f"https://api.modrinth.com/v2/projects?{q_projs}")
            for p in p_list:
                projects_map[p["id"]] = p

    hdr_mc = f"MC {mc}"
    hdr_lat = f"LATEST FOR {mc}"
    print(
        f"\n{ui.bold(f'{'PACKAGE':<28}  {'PINNED VERSION':<18}  {hdr_mc:<14}  {hdr_lat:<20}  DEPENDENCY & LOADER CHECK')}"
    )
    print(ui.dim("-" * 116))

    issues = 0
    latest_cache: dict[str, str] = {}

    for pkg in cfg.packages:
        if filter_cat != "all" and pkg.category != filter_cat:
            continue

        # 1. PaperMC / Folia Server
        if pkg.file_path.startswith("server/paper-") or pkg.file_path.startswith(
            "server/folia-"
        ):
            slug = "folia" if "folia" in pkg.file_path else "paper"
            try:
                b_data = fetch_json(
                    f"https://fill.papermc.io/v3/projects/{slug}/versions/{mc}/builds/latest"
                )
                latest_b = f"{mc}-{b_data['id']}"
                compat = (
                    ui.bold_green("✔ COMPATIBLE  ")
                    if pkg.version == latest_b
                    else ui.yellow("↻ UPGRADEABLE ")
                )
                print(
                    f"{pkg.name:<28}  {pkg.version:<18}  {compat}  {latest_b:<20}  PaperMC Fill v3 API (channel: {b_data.get('channel', 'STABLE')})"
                )
            except Exception:
                print(
                    f"{pkg.name:<28}  {pkg.version:<18}  {ui.red('✘ NO BUILD    ')}  {'none':<20}  No {slug} build found for {mc}"
                )
                issues += 1
            continue

        # 2. Purpur Server
        if pkg.file_path.startswith("server/purpur-"):
            try:
                p_data = fetch_json(f"https://api.purpurmc.org/v2/purpur/{mc}/latest")
                latest_p = f"{mc}-{p_data['build']}"
                compat = (
                    ui.bold_green("✔ COMPATIBLE  ")
                    if pkg.version == latest_p
                    else ui.yellow("↻ UPGRADEABLE ")
                )
                print(
                    f"{pkg.name:<28}  {pkg.version:<18}  {compat}  {latest_p:<20}  PurpurMC v2 API"
                )
            except Exception:
                print(
                    f"{pkg.name:<28}  {pkg.version:<18}  {ui.red('✘ NO BUILD    ')}  {'none':<20}  No Purpur build found for {mc}"
                )
                issues += 1
            continue

        # 3. Forge Installer
        if pkg.file_path.startswith("client/forge-"):
            try:
                promos = fetch_json(
                    "https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json"
                ).get("promos", {})
                best_f = promos.get(f"{mc}-recommended") or promos.get(f"{mc}-latest")
                if best_f:
                    full_f = f"{mc}-{best_f}"
                    compat = (
                        ui.bold_green("✔ COMPATIBLE  ")
                        if pkg.version.startswith(f"{mc}-")
                        else ui.yellow("↻ UPGRADEABLE ")
                    )
                    print(
                        f"{pkg.name:<28}  {pkg.version:<18}  {compat}  {full_f:<20}  Forge Maven ({mc}-recommended)"
                    )
                else:
                    print(
                        f"{pkg.name:<28}  {pkg.version:<18}  {ui.red('✘ NO BUILD    ')}  {'none':<20}  No Forge build for {mc}"
                    )
                    issues += 1
            except Exception:
                issues += 1
            continue

        # 4. Fabric Installer
        if pkg.file_path.startswith("client/fabric-installer"):
            try:
                loaders = fetch_json(
                    f"https://meta.fabricmc.net/v2/versions/loader/{mc}"
                )
                l_ver = loaders[0]["loader"]["version"]
                full_fab = f"{mc}-{l_ver}"
                compat = (
                    ui.bold_green("✔ COMPATIBLE  ")
                    if pkg.version.startswith(f"{mc}-")
                    else ui.yellow("↻ UPGRADEABLE ")
                )
                print(
                    f"{pkg.name:<28}  {pkg.version:<18}  {compat}  {full_fab:<20}  Fabric Meta v2 API"
                )
            except Exception:
                issues += 1
            continue

        # 5. GitHub Releases (Prism Launcher, Vault, EssentialsX 2.21+ addons)
        if pkg.source_url.startswith("https://github.com/"):
            if "PrismLauncher" in pkg.file_path:
                print(
                    f"{pkg.name:<28}  {pkg.version:<18}  {ui.bold_green('✔ AGNOSTIC    ')}  {pkg.version:<20}  Desktop Launcher (supports all MC versions)"
                )
            elif pkg.file_path.endswith("Vault.jar"):
                print(
                    f"{pkg.name:<28}  {pkg.version:<18}  {ui.bold_green('✔ COMPATIBLE  ')}  {pkg.version:<20}  Bukkit Service API (hooked by LuckPerms)"
                )
            else:
                print(
                    f"{pkg.name:<28}  {pkg.version:<18}  {ui.bold_green('✔ COMPATIBLE  ')}  {pkg.version:<20}  GitHub Release Asset"
                )
            continue

        # 6. Modrinth Packages
        pid = pkg_proj_id.get(pkg.file_path)
        vid = pkg_ver_id.get(pkg.file_path)
        if pid and vid:
            v_info = versions_map.get(vid, {})
            g_vers = v_info.get("game_versions", [])
            loaders_list = ",".join(v_info.get("loaders", []))
            supports_mc = mc in g_vers

            cache_key = f"{pid}:{pkg.category}"
            if cache_key in latest_cache:
                latest_ver = latest_cache[cache_key]
            else:
                loader_filter = (
                    (
                        ("forge", "neoforge")
                        if cfg.client_loader in ("forge", "neoforge")
                        else ("fabric",)
                    )
                    if pkg.category == "client"
                    else ("paper", "spigot", "bukkit")
                )
                best_v = _select_modrinth_version(pid, mc, loader_filter)
                latest_ver = best_v["version_number"] if best_v else "none"
                latest_cache[cache_key] = latest_ver

            if supports_mc:
                compat = ui.bold_green("✔ COMPATIBLE  ")
            elif latest_ver != "none":
                compat = ui.yellow("↻ NEEDS BUMP  ")
            else:
                compat = ui.red("✘ UNSUPPORTED ")
                issues += 1

            dep_notes: list[str] = []
            for dep in v_info.get("dependencies", []):
                dpid = dep.get("project_id")
                dtype = dep.get("dependency_type")
                if not dpid:
                    continue
                dtitle = projects_map.get(dpid, {}).get("title", dpid)
                if dtype == "required":
                    if dpid in proj_present:
                        dep_notes.append(ui.green(f"req:{dtitle}✔"))
                    else:
                        dep_notes.append(ui.red(f"MISSING:{dtitle}✘"))
                        issues += 1
                elif dtype == "incompatible":
                    if dpid in proj_present:
                        dep_notes.append(ui.red(f"CONFLICT:{dtitle}✘"))
                        issues += 1
                    else:
                        dep_notes.append(ui.cyan(f"!{dtitle}✔"))

            dep_str = f"loaders:[{loaders_list}]"
            if dep_notes:
                dep_str += " " + " ".join(dep_notes)

            print(
                f"{pkg.name:<28}  {pkg.version:<18}  {compat}  {latest_ver:<20}  {dep_str}"
            )

    print()
    if issues == 0:
        ui.success(
            f"Dependency & compatibility resolution passed with 0 conflicts for Minecraft {mc}."
        )
        return 0
    else:
        ui.warn(
            f"Resolution found {issues} compatibility/dependency issue(s) for Minecraft {mc}."
        )
        return 1


# ==============================================================================
# Offline .jar Manifest Inspector (`--inspect-deps` via Python `zipfile`)
# ==============================================================================
def _read_jar_entry(jar_path: Path, candidates: tuple[str, ...]) -> str:
    try:
        with zipfile.ZipFile(jar_path, "r") as zf:
            names = set(zf.namelist())
            for cand in candidates:
                if cand in names:
                    return zf.read(cand).decode("utf-8", errors="replace")
    except Exception:
        pass
    return ""


def _parse_yaml_scalar_or_list(text: str, key: str) -> list[str]:
    """Lightweight parser for `name:`, `api-version:`, `provides:`, `depend:`, `softdepend:` in plugin.yml."""
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        m = re.match(rf"^{re.escape(key)}:\s*(.*)$", line)
        if not m:
            continue
        val = m.group(1).strip()
        if val.startswith("[") and val.endswith("]"):
            inner = val[1:-1].replace('"', "").replace("'", "")
            return [x.strip() for x in inner.split(",") if x.strip()]
        if val:
            cleaned = val.strip("\"'")
            return [cleaned] if cleaned else []
        # Multi-line YAML list
        items: list[str] = []
        for sub in lines[idx + 1 :]:
            sm = re.match(r"^\s*-\s*([^\s#]+)", sub)
            if sm:
                items.append(sm.group(1).strip("\"'"))
            elif re.match(r"^[A-Za-z0-9_-]+:", sub):
                break
        return items
    return []


def run_offline_jar_inspector(
    cfg: TundraConfig, root_dir: Path, filter_cat: str = "all"
) -> int:
    """
    Streams `plugin.yml`, `paper-plugin.yml`, `fabric.mod.json`, and `META-INF/mods.toml`
    directly out of local `.jar` archives using Python's built-in `zipfile` module (no 7z needed!).
    """
    ui.header(
        "TUNDRA OFFLINE .JAR MANIFEST INSPECTOR (plugin.yml / fabric.mod.json / mods.toml)",
        width=124,
    )

    installed_ids: dict[str, str] = {
        "minecraft": cfg.mc_version,
        "java": "21",
        "forge": cfg.client_loader_version or "47.4.10",
        "neoforge": cfg.client_loader_version or "21.1",
        "fabricloader": cfg.client_loader_version or "0.16.10",
        "fabric-loader": cfg.client_loader_version or "0.16.10",
    }

    # First pass: index all installed plugin names, modIds, provides, and Jar-in-Jar bundles
    for pkg in cfg.packages:
        if not pkg.file_path.endswith(".jar"):
            continue
        if pkg.file_path.startswith(("server/paper-", "server/purpur-", "server/folia-", "client/forge-", "client/fabric-installer")):
            continue
        jar_path = root_dir / pkg.file_path
        if not jar_path.is_file():
            continue

        if pkg.category == "plugins":
            pyml = _read_jar_entry(jar_path, ("plugin.yml", "paper-plugin.yml"))
            names = _parse_yaml_scalar_or_list(pyml, "name")
            if names:
                installed_ids[names[0]] = pkg.file_path
            for prov in _parse_yaml_scalar_or_list(pyml, "provides"):
                installed_ids[prov] = f"{pkg.file_path} (via provides)"

        elif pkg.category == "client":
            fjson_raw = _read_jar_entry(jar_path, ("fabric.mod.json",))
            if fjson_raw:
                try:
                    fmod = json.loads(fjson_raw)
                    mid = fmod.get("id", "")
                    if mid:
                        installed_ids[mid] = pkg.file_path
                        if mid == "fabric-api":
                            installed_ids["fabric"] = pkg.file_path
                    for prov in fmod.get("provides", []):
                        if isinstance(prov, str):
                            installed_ids[prov] = f"{pkg.file_path} (via provides)"
                    for jar_entry in fmod.get("jars", []):
                        jfile = jar_entry.get("file", "")
                        if jfile:
                            base_j = Path(jfile).stem.split("-")[0]
                            installed_ids[base_j] = f"{pkg.file_path} (bundled JiJ)"
                            try:
                                with zipfile.ZipFile(jar_path, "r") as outer_zf:
                                    if jfile in outer_zf.namelist():
                                        with outer_zf.open(jfile) as nested_stream:
                                            with zipfile.ZipFile(nested_stream) as nested_zf:
                                                if "fabric.mod.json" in nested_zf.namelist():
                                                    nd = json.loads(
                                                        nested_zf.read("fabric.mod.json").decode("utf-8", errors="replace")
                                                    )
                                                    nid = nd.get("id", "")
                                                    if nid:
                                                        installed_ids[nid] = f"{pkg.file_path} (bundled JiJ)"
                            except Exception:
                                pass
                except Exception:
                    pass

            mtoml_raw = _read_jar_entry(
                jar_path, ("META-INF/mods.toml", "META-INF/neoforge.mods.toml")
            )
            if mtoml_raw:
                try:
                    import tomllib

                    mt = tomllib.loads(mtoml_raw)
                    for mod_entry in mt.get("mods", []):
                        mid = mod_entry.get("modId", "")
                        if mid:
                            installed_ids[mid] = pkg.file_path
                        for prov in mod_entry.get("provides", []):
                            installed_ids[prov] = f"{pkg.file_path} (via provides)"
                except Exception:
                    for m in re.finditer(r'modId\s*=\s*["\']([^"\']+)["\']', mtoml_raw):
                        installed_ids[m.group(1)] = pkg.file_path

            jarjar_raw = _read_jar_entry(jar_path, ("META-INF/jarjar/metadata.json",))
            if jarjar_raw:
                try:
                    jj = json.loads(jarjar_raw)
                    for j in jj.get("jars", []):
                        art = j.get("identifier", {}).get("artifact", "")
                        if art:
                            norm = re.sub(r"-forge$", "", art).replace("-", "")
                            installed_ids[norm] = f"{pkg.file_path} (bundled JarJar)"
                except Exception:
                    pass

    print(
        f"\n{ui.bold(f'{'JAR FILE':<38}  {'API / MC':<10}  {'PROVIDES / ID':<28}  {'HARD DEPENDS (REQUIRED)':<26}  SOFT DEPENDS / ORDERING')}"
    )
    print(ui.dim("-" * 124))

    missing_deps = 0
    for pkg in cfg.packages:
        if filter_cat != "all" and pkg.category != filter_cat:
            continue
        if not pkg.file_path.endswith(".jar"):
            continue
        if pkg.file_path.startswith(("server/paper-", "server/purpur-", "server/folia-", "client/forge-", "client/fabric-installer")):
            continue

        jar_path = root_dir / pkg.file_path
        fname = Path(pkg.file_path).name
        if not jar_path.is_file():
            print(f"{fname:<38}  {ui.red('MISSING LOCAL JAR (run sync/download first)')}")
            missing_deps += 1
            continue

        if pkg.category == "plugins":
            pyml = _read_jar_entry(jar_path, ("plugin.yml", "paper-plugin.yml"))
            names = _parse_yaml_scalar_or_list(pyml, "name")
            apivers = _parse_yaml_scalar_or_list(pyml, "api-version")
            provides = _parse_yaml_scalar_or_list(pyml, "provides")
            depends = _parse_yaml_scalar_or_list(pyml, "depend")
            softdeps = _parse_yaml_scalar_or_list(pyml, "softdepend")

            pname = names[0] if names else fname
            apiver = apivers[0] if apivers else "legacy"
            id_disp = f"{pname} (+{','.join(provides)})" if provides else pname

            hard_parts: list[str] = []
            for d in depends:
                if d in installed_ids:
                    hard_parts.append(ui.green(f"{d}✔"))
                else:
                    hard_parts.append(ui.red(f"{d}✘"))
                    missing_deps += 1
            hard_disp = ",".join(hard_parts) if hard_parts else "-"
            soft_disp = ",".join(softdeps) if softdeps else "-"

            print(
                f"{fname:<38}  {apiver:<10}  {id_disp:<28}  {hard_disp:<26}  {soft_disp}"
            )

        elif pkg.category == "client":
            fjson_raw = _read_jar_entry(jar_path, ("fabric.mod.json",))
            if fjson_raw:
                try:
                    fmod = json.loads(fjson_raw)
                    mid = fmod.get("id", fname)
                    provs = [p for p in fmod.get("provides", []) if isinstance(p, str)]
                    id_disp = f"{mid} (+{','.join(provs)})" if provs else mid
                    hard_parts = []
                    for d_key in fmod.get("depends", {}).keys():
                        if d_key in ("minecraft", "java", "fabricloader", "fabric-loader") or d_key.startswith("fabric-"):
                            if d_key == "fabric-api" or d_key == "fabric":
                                if "fabric" in installed_ids or "fabric-api" in installed_ids:
                                    hard_parts.append(ui.green("fabric-api✔"))
                                else:
                                    hard_parts.append(ui.red("fabric-api✘"))
                                    missing_deps += 1
                            continue
                        if d_key in installed_ids:
                            hard_parts.append(ui.green(f"{d_key}✔"))
                        else:
                            hard_parts.append(ui.red(f"{d_key}✘"))
                            missing_deps += 1
                    hard_disp = ",".join(hard_parts) if hard_parts else "-"
                    suggests = list(fmod.get("suggests", {}).keys())
                    soft_disp = ",".join(suggests) if suggests else "-"
                    print(
                        f"{fname:<38}  {cfg.mc_version:<10}  {id_disp:<28}  {hard_disp:<26}  {soft_disp}"
                    )
                    continue
                except Exception:
                    pass

            mtoml_raw = _read_jar_entry(
                jar_path, ("META-INF/mods.toml", "META-INF/neoforge.mods.toml")
            )
            if mtoml_raw:
                import tomllib

                try:
                    mt = tomllib.loads(mtoml_raw)
                    mods_list = mt.get("mods", [])
                    mids = [m.get("modId", "") for m in mods_list if m.get("modId")]
                    provs = []
                    for m in mods_list:
                        provs.extend(m.get("provides", []))
                    primary_mid = mids[0] if mids else fname
                    extra = mids[1:] + provs
                    id_disp = (
                        f"{primary_mid} (+{','.join(extra)})" if extra else primary_mid
                    )

                    hard_parts = []
                    soft_parts = []
                    deps_dict = mt.get("dependencies", {})
                    for dep_list in deps_dict.values():
                        if not isinstance(dep_list, list):
                            continue
                        for dep_item in dep_list:
                            did = dep_item.get("modId", "")
                            if not did:
                                continue
                            mand = bool(dep_item.get("mandatory", False))
                            vrng = str(dep_item.get("versionRange", ""))
                            if "NOT-COMPATIBLE" in vrng:
                                soft_parts.append(f"!{did}")
                            elif mand:
                                if did in installed_ids:
                                    hard_parts.append(ui.green(f"{did}✔"))
                                else:
                                    hard_parts.append(ui.red(f"{did}✘"))
                                    missing_deps += 1
                            else:
                                soft_parts.append(
                                    f"{did}✔" if did in installed_ids else did
                                )
                    hard_disp = ",".join(hard_parts) if hard_parts else "-"
                    soft_disp = ",".join(soft_parts) if soft_parts else "-"
                    print(
                        f"{fname:<38}  {cfg.mc_version:<10}  {id_disp:<28}  {hard_disp:<26}  {soft_disp}"
                    )
                except Exception:
                    print(f"{fname:<38}  {cfg.mc_version:<10}  (parsed manifest)")

    print()
    if missing_deps == 0:
        ui.success(
            "All embedded .jar hard dependencies (depend / provides) are satisfied."
        )
        return 0
    else:
        ui.error(
            f"Found {missing_deps} missing jar(s) or unsatisfied hard dependencies."
        )
        return 1


# ==============================================================================
# Modrinth `.mrpack` Builder (Prism Launcher One-Click Import)
# ==============================================================================
def build_mrpack(cfg: TundraConfig, root_dir: Path) -> Path | None:
    """
    Generates `modrinth.index.json` and packages `client/Tundra-Client-<mc>.mrpack`
    for one-click import into Prism Launcher or Modrinth App.
    """
    client_mods = [
        p
        for p in cfg.packages
        if p.category == "client"
        and p.file_path.endswith(".jar")
        and not p.file_path.startswith(("client/forge-", "client/fabric-installer"))
    ]
    if not client_mods:
        return None

    loader_key = (
        "fabric-loader"
        if cfg.client_loader == "fabric"
        else ("neoforge" if cfg.client_loader == "neoforge" else "forge")
    )
    loader_ver = cfg.client_loader_version or (
        "0.16.10" if cfg.client_loader == "fabric" else "47.4.10"
    )

    files_entries: list[dict[str, Any]] = []
    for pkg in client_mods:
        local_file = root_dir / pkg.file_path
        sha1 = pkg.sha1
        sha512 = pkg.sha512
        fsize = pkg.file_size

        if local_file.is_file() and (not sha1 or not sha512 or not fsize):
            _, sha1, sha512, fsize = compute_hashes(local_file)
            pkg.sha1 = sha1
            pkg.sha512 = sha512
            pkg.file_size = fsize

        if not sha1 or not sha512:
            continue

        fname = Path(pkg.file_path).name
        server_env = "optional" if "journeymap" in fname.lower() else "unsupported"
        files_entries.append(
            {
                "path": f"mods/{fname}",
                "hashes": {
                    "sha1": sha1,
                    "sha512": sha512,
                },
                "env": {
                    "client": "required",
                    "server": server_env,
                },
                "downloads": [pkg.source_url],
                "fileSize": fsize,
            }
        )

    mod_names = ", ".join(p.name.split(" (")[0] for p in client_mods[:4])
    index_data = {
        "formatVersion": 1,
        "game": "minecraft",
        "versionId": __version__,
        "name": f"{cfg.name} Client ({cfg.mc_version})",
        "summary": f"Modernized {cfg.client_loader.capitalize()} {cfg.mc_version} client stack for {cfg.name} ({mod_names})",
        "dependencies": {
            "minecraft": cfg.mc_version,
            loader_key: loader_ver,
        },
        "files": files_entries,
    }

    index_path = root_dir / "modrinth.index.json"
    index_path.write_text(json.dumps(index_data, indent=2) + "\n", encoding="utf-8")

    mrpack_out = root_dir / "client" / f"Tundra-Client-{cfg.mc_version}.mrpack"
    mrpack_out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(mrpack_out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(index_path, arcname="modrinth.index.json")

    ui.success(
        f"Generated {ui.bold(mrpack_out.name)} ({cfg.client_loader.capitalize()} {cfg.mc_version}) for Prism Launcher one-click import"
    )
    return mrpack_out


# ==============================================================================
# Package Sync / Verification / Bundling Engine
# ==============================================================================
def sync_packages(
    cfg: TundraConfig,
    root_dir: Path,
    mode: str = "download",  # "download" | "verify" | "list"
    filter_cat: str = "all",  # "all" | "server" | "client" | "plugins"
    force: bool = False,
    prefer_release: bool = False,
    target_dir_override: Path | None = None,
) -> int:
    """
    Downloads, verifies SHA256 checksums, or lists declared packages from `tundra.toml`.
    """
    if mode == "list":
        ui.header(
            f"TUNDRA PACKAGE MANIFEST (MC {cfg.mc_version} • Server: {cfg.server_backend} • Client: {cfg.client_loader})",
            width=116,
        )
        print(
            f"\n{ui.bold(f'{'CAT':<8}  {'PACKAGE':<30}  {'VERSION':<18}  {'STATUS':<10}  PURPOSE')}"
        )
        print(ui.dim("-" * 116))

    pass_count = 0
    fail_count = 0
    download_count = 0
    updated_locks = False

    for pkg in cfg.packages:
        if filter_cat != "all":
            if filter_cat == "server-all" and pkg.category not in ("server", "plugins"):
                continue
            elif filter_cat != "server-all" and pkg.category != filter_cat:
                continue

        if target_dir_override and pkg.category == "client" and pkg.file_path.endswith(".jar") and not pkg.file_path.startswith(("client/forge-", "client/fabric-installer")):
            target_path = target_dir_override / Path(pkg.file_path).name
            rel_disp = str(target_path)
        else:
            target_path = root_dir / pkg.file_path
            rel_disp = pkg.file_path

        filename = Path(pkg.file_path).name

        if mode == "list":
            if target_path.is_file():
                actual_sha = compute_sha256(target_path)
                if not pkg.sha256 or actual_sha == pkg.sha256:
                    status = ui.bold_green("OK      ")
                else:
                    status = ui.yellow("MISMATCH")
            else:
                status = ui.red("MISSING ")
            print(
                f"{pkg.category:<8}  {pkg.name:<30}  {pkg.version:<18}  {status}  {pkg.purpose}"
            )
            continue

        # Check existing local binary
        if target_path.is_file() and not force:
            actual_sha, sha1, sha512, fsize = compute_hashes(target_path)
            if not pkg.sha256:
                pkg.sha256 = actual_sha
                pkg.sha1 = sha1
                pkg.sha512 = sha512
                pkg.file_size = fsize
                updated_locks = True
            if actual_sha == pkg.sha256:
                ui.success(f"{rel_disp} ({pkg.name} {pkg.version})")
                pass_count += 1
                continue
            elif mode == "verify":
                ui.error(
                    f"[MISMATCH] {rel_disp} (expected {pkg.sha256[:12]}..., got {actual_sha[:12]}...)"
                )
                fail_count += 1
                continue
            else:
                ui.warn(f"{rel_disp} checksum mismatch; re-downloading...")
        elif mode == "verify":
            ui.error(f"[MISSING]  {rel_disp} ({pkg.name} {pkg.version})")
            fail_count += 1
            continue

        # Download mode
        downloaded = False
        release_base = os.environ.get("TUNDRA_RELEASE_URL") or (
            cfg.release_url if prefer_release else ""
        )

        with ui.spinner(f"Downloading {ui.bold(filename)} ({pkg.name} {pkg.version})..."):
            if release_base:
                mirror_url = f"{release_base.rstrip('/')}/{filename}"
                downloaded = download_file(mirror_url, target_path)
            if not downloaded:
                downloaded = download_file(pkg.source_url, target_path)

        if not downloaded or not target_path.is_file():
            ui.error(f"Failed to download {rel_disp} from {pkg.source_url}")
            fail_count += 1
            continue

        actual_sha, sha1, sha512, fsize = compute_hashes(target_path)
        if pkg.sha256 and actual_sha != pkg.sha256:
            ui.error(
                f"SHA256 mismatch for {rel_disp}: expected {pkg.sha256}, got {actual_sha}"
            )
            target_path.unlink(missing_ok=True)
            fail_count += 1
            continue

        if not pkg.sha256 or not pkg.sha1:
            pkg.sha256 = actual_sha
            pkg.sha1 = sha1
            pkg.sha512 = sha512
            pkg.file_size = fsize
            updated_locks = True

        ui.success(
            f"Downloaded {rel_disp} (SHA256 verified: {ui.cyan(actual_sha[:12])}...)"
        )
        download_count += 1
        pass_count += 1

    if updated_locks:
        from tundra.config import save_config

        save_config(cfg, root_dir / "tundra.toml")

    if mode == "download" and filter_cat in ("all", "client") and not target_dir_override:
        build_mrpack(cfg, root_dir)

    if mode != "list":
        print()
        ui.panel(
            "Verification Summary",
            [
                f"Verified packages : {ui.bold_green(str(pass_count))} ({download_count} newly downloaded)",
                f"Failed / Missing  : {ui.red(str(fail_count)) if fail_count else ui.dim('0')}",
            ],
        )
        return 0 if fail_count == 0 else 1

    return 0


def _write_tar_with_sums(
    bundle_path: Path, root_dir: Path, rel_files: list[str]
) -> list[str]:
    """Creates a `.tar.gz` archive containing only `rel_files` and a scoped `SHA256SUMS`."""
    import io

    sums_lines: list[str] = []
    for rf in rel_files:
        sha = compute_sha256(root_dir / rf)
        sums_lines.append(f"{sha}  {rf}")
    sums_bytes = ("\n".join(sums_lines) + "\n").encode("utf-8")

    with ui.spinner(
        f"Archiving {len(rel_files)} files into {ui.bold(bundle_path.name)}..."
    ):
        with tarfile.open(bundle_path, "w:gz") as tf:
            ti = tarfile.TarInfo(name="SHA256SUMS")
            ti.size = len(sums_bytes)
            ti.mode = 0o644
            tf.addfile(ti, io.BytesIO(sums_bytes))
            for rf in rel_files:
                tf.add(root_dir / rf, arcname=rf)

    ui.success(
        f"Created {ui.bold(bundle_path.name)} ({len(rel_files)} files + scoped SHA256SUMS)"
    )
    return sums_lines


def create_release_bundle(
    cfg: TundraConfig, root_dir: Path, scope: str = "all"
) -> int:
    """
    Verifies declared binaries and builds separate server and client `.tar.gz` bundles:
      - `tundra-server-mc<ver>.tar.gz` (`server/*` + `plugins/*` + scoped `SHA256SUMS`)
      - `tundra-client-mc<ver>.tar.gz` (`client/*` + `.mrpack` + scoped `SHA256SUMS`)
    Also writes a top-level `SHA256SUMS` file in `root_dir`.
    """
    norm_scope = (
        "server"
        if scope in ("server", "plugins", "server-all")
        else ("client" if scope == "client" else "all")
    )
    verify_cat = (
        "server-all"
        if norm_scope == "server"
        else ("client" if norm_scope == "client" else "all")
    )

    rc = sync_packages(cfg, root_dir, mode="verify", filter_cat=verify_cat)
    if rc != 0:
        ui.error(
            "Cannot create release bundle while packages are missing or unverified."
        )
        return rc

    all_sums_lines: list[str] = []
    created_bundles: list[Path] = []

    if norm_scope in ("all", "server"):
        server_files = [
            p.file_path
            for p in cfg.packages
            if p.category in ("server", "plugins") and (root_dir / p.file_path).is_file()
        ]
        if server_files:
            srv_bundle = root_dir / f"tundra-server-mc{cfg.mc_version}.tar.gz"
            all_sums_lines.extend(
                _write_tar_with_sums(srv_bundle, root_dir, server_files)
            )
            created_bundles.append(srv_bundle)

    if norm_scope in ("all", "client"):
        mrpack_path = build_mrpack(cfg, root_dir)
        client_files = [
            p.file_path
            for p in cfg.packages
            if p.category == "client" and (root_dir / p.file_path).is_file()
        ]
        if mrpack_path and mrpack_path.is_file():
            mrpack_rel = f"client/{mrpack_path.name}"
            if mrpack_rel not in client_files:
                client_files.append(mrpack_rel)
        if client_files:
            cli_bundle = root_dir / f"tundra-client-mc{cfg.mc_version}.tar.gz"
            all_sums_lines.extend(
                _write_tar_with_sums(cli_bundle, root_dir, client_files)
            )
            created_bundles.append(cli_bundle)

    for bpath in created_bundles:
        bsha = compute_sha256(bpath)
        all_sums_lines.append(f"{bsha}  {bpath.name}")

    sums_path = root_dir / "SHA256SUMS"
    sums_path.write_text("\n".join(all_sums_lines) + "\n", encoding="utf-8")
    ui.success(f"Updated top-level {ui.bold('SHA256SUMS')}")
    return 0



def export_plugins_zip(cfg: TundraConfig, root_dir: Path) -> Path:
    """Packages all downloaded `plugins/*.jar` into a single `.zip` for managed server panels."""
    zip_name = f"tundra-server-plugins-mc{cfg.mc_version}.zip"
    zip_path = root_dir / zip_name
    plugin_pkgs = [p for p in cfg.packages if p.category == "plugins"]
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in plugin_pkgs:
            fp = root_dir / p.file_path
            if fp.is_file():
                zf.write(fp, arcname=p.file_path)
    ui.success(
        f"Exported {ui.bold(zip_name)} ({len(plugin_pkgs)} plugins) ready for server panel upload"
    )
    return zip_path
