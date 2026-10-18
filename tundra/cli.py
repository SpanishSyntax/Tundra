"""CLI entrypoints and interactive configurator wizards for `tundra`, `tundra-server`, and `tundra-client`."""

import sys
from pathlib import Path

from tundra import __version__
from tundra.config import (
    TundraConfig,
    find_manifest_path,
    load_config,
    save_config,
)
from tundra.core import (
    build_mrpack,
    create_release_bundle,
    export_plugins_zip,
    fetch_available_mc_versions,
    resolve_full_config,
    run_offline_jar_inspector,
    run_upstream_audit,
    sync_packages,
)
from tundra.registry import (
    SERVER_BACKENDS,
    SERVER_PLUGINS,
    expand_required_dependencies,
    get_client_registry,
)
from tundra.ui import ui


def handle_color_args():
    for i, arg in enumerate(sys.argv[1:]):
        if arg == "--no-color":
            ui.set_color_mode("never")
        elif arg.startswith("--color="):
            ui.set_color_mode(arg.split("=", 1)[1])
        elif arg == "--color" and i + 1 < len(sys.argv[1:]):
            ui.set_color_mode(sys.argv[1:][i + 1])


def print_server_help():
    app = ui.app_name
    print(f"""{ui.badge()} {ui.bold("Declarative Minecraft Server Backend & Plugin Configurator")}

{ui.blue("Usage:")}
  {app}                        Launch interactive server configurator & dashboard
  {app} <command> [options]

{ui.blue("Commands:")}
  configure                    Interactive wizard to pick MC version, backend (Paper/Purpur/Folia), & plugins
  sync, download               Download & SHA256-verify server runtime + plugins from tundra.toml
  resolve [--mc VER]           Query PaperMC, Purpur, & Modrinth APIs to verify compatibility & dependencies
  inspect-deps                 Stream plugin.yml out of downloaded .jar files to verify hard/soft dependencies
  verify                       Verify SHA256 checksums of local server/ and plugins/ binaries
  list                         List declared server runtime and plugin packages with install status
  export-zip                   Bundle plugins/*.jar into a .zip ready for managed panels (Aternos, Pterodactyl)

{ui.blue("Options:")}
  -c, --config PATH            Path to tundra.toml manifest (default: ./tundra.toml)
  --mc VERSION                 Target Minecraft version override (e.g. 1.21.4, 1.20.1)
  -f, --force                  Re-download files even if SHA256 checksum already matches
  --from-release               Prefer fetching packages from the Tundra GitHub Release mirror first
  --color MODE                 Color output mode: auto, always, never (default: auto)
  --no-color                   Disable colored terminal output
  -h, --help                   Show this help message and exit
  -V, -v, --version            Show version information and exit

{ui.blue("Examples:")}
  {app}                        # Launch interactive server configurator menu
  {app} configure              # Pick Paper/Purpur/Aternos mode, toggle plugins, and update tundra.toml
  {app} sync                   # Download and verify server/*.jar and plugins/*.jar
  {app} resolve --mc 1.21.4    # Preview upgrading the server stack to Minecraft 1.21.4
  {app} export-zip             # Create a clean plugins .zip for drag-and-drop server hosting panels
""")


def print_client_help():
    app = ui.app_name
    print(f"""{ui.badge()} {ui.bold("Minecraft Player Modpack Installer & Client Configurator")}

{ui.blue("Usage:")}
  {app}                        Launch interactive player installer & mod selector menu
  {app} <command> [options]

{ui.blue("Commands:")}
  install, configure           Interactive menu to pick Fabric/Forge, toggle recommended mods, & install
  mrpack                       Generate Prism Launcher one-click modpack (client/Tundra-Client-<mc>.mrpack)
  sync, download               Download & SHA256-verify client mods and loader installer to ./client/
  resolve [--mc VER]           Verify client mod compatibility & dependency graph via Modrinth API
  inspect-deps                 Inspect embedded fabric.mod.json / mods.toml inside downloaded client .jars
  verify                       Verify SHA256 checksums of local client/ binaries
  list                         List declared client mods and tools with verification status

{ui.blue("Options:")}
  -c, --config PATH            Path to tundra.toml manifest (default: ./tundra.toml)
  --loader LOADER              Override client mod loader: fabric (recommended) or forge
  --mods-dir DIR               Install client mod .jar files directly into a custom .minecraft/mods folder
  -f, --force                  Re-download files even if SHA256 checksum already matches
  --from-release               Prefer fetching packages from the Tundra GitHub Release mirror first
  --color MODE                 Color output mode: auto, always, never (default: auto)
  --no-color                   Disable colored terminal output
  -h, --help                   Show this help message and exit
  -V, -v, --version            Show version information and exit

{ui.blue("Examples:")}
  {app}                        # Launch interactive player mod installer (Fabric/Forge + .mrpack)
  {app} mrpack                 # Build client/Tundra-Client-<mc>.mrpack for Prism Launcher
  {app} sync                   # Download all verified client mods into ./client/
  {app} sync --mods-dir ~/.minecraft/mods  # Install selected mods directly into vanilla launcher folder
""")


def print_unified_help():
    app = ui.app_name
    print(f"""{ui.badge()} {ui.bold("Declarative Minecraft Server Configurator, Client Installer & Dependency Resolver")}

{ui.blue("Usage:")}
  tundra                       Launch interactive Tundra dashboard (Server & Client)
  tundra server [cmd] [opts]   Run the Server Configurator (`tundra-server`)
  tundra client [cmd] [opts]   Run the Player / Client Installer (`tundra-client`)
  tundra <command> [options]

{ui.blue("Dedicated Entrypoints:")}
  tundra-server                Dedicated server backend (Paper/Purpur/Folia/Aternos) & plugin configurator
  tundra-client                Dedicated player modpack (.mrpack / Fabric / Forge) configurator & installer

{ui.blue("Commands:")}
  server                       Launch server configurator wizard or run server subcommands
  client                       Launch player client installer or run client subcommands
  sync, download               Download & SHA256-verify all packages and build Prism Launcher .mrpack
  resolve [--mc VER]           Query Modrinth, PaperMC, Purpur & Fabric/Forge APIs ("uv for Minecraft")
  inspect-deps                 Stream plugin.yml, fabric.mod.json & mods.toml from local .jars offline
  verify                       Verify SHA256 checksums of all local files without downloading
  list                         List all declared packages, versions, install status, and purpose
  mrpack                       Build client/Tundra-Client-<mc>.mrpack from tundra.toml
  bundle                       Create tundra-mc<ver>-binaries.tar.gz + SHA256SUMS for GitHub Releases

{ui.blue("Options:")}
  -c, --config PATH            Path to tundra.toml manifest (default: ./tundra.toml)
  --mc VERSION                 Target Minecraft version for 'resolve' (e.g. --mc 1.21.4)
  --server / --plugins         Filter operation to server runtime or server plugins only
  --client                     Filter operation to client mods/tools only
  -f, --force                  Re-download files even if SHA256 checksum matches
  --from-release               Prefer fetching packages from the Tundra GitHub Release mirror
  --color MODE                 Color output mode: auto, always, never (default: auto)
  --no-color                   Disable colored terminal output
  -h, --help                   Show this help message and exit
  -V, -v, --version            Show version information and exit
""")


def print_status_banner(cfg: TundraConfig, root_dir: Path, scope: str = "all"):
    """Displays a Borealis-style status summary panel."""
    srv_pkgs = [p for p in cfg.packages if p.category == "server"]
    plg_pkgs = [p for p in cfg.packages if p.category == "plugins"]
    cli_pkgs = [p for p in cfg.packages if p.category == "client"]

    srv_ok = sum(1 for p in srv_pkgs if (root_dir / p.file_path).is_file())
    plg_ok = sum(1 for p in plg_pkgs if (root_dir / p.file_path).is_file())
    cli_ok = sum(1 for p in cli_pkgs if (root_dir / p.file_path).is_file())

    backend_spec = SERVER_BACKENDS.get(cfg.server_backend)
    backend_label = backend_spec.name if backend_spec else cfg.server_backend

    lines: list[str] = [
        f"Manifest         : {ui.bold(str(root_dir / 'tundra.toml'))}",
        f"Minecraft Target : {ui.bold_cyan(cfg.mc_version)}",
    ]
    if scope in ("all", "server"):
        lines.extend(
            [
                f"Server Backend   : {ui.bold(backend_label)} ({srv_ok}/{len(srv_pkgs)} runtime jar)",
                f"Server Plugins   : {ui.bold_green(str(len(cfg.server_plugins)))} enabled ({plg_ok}/{len(plg_pkgs)} local jars verified)",
            ]
        )
    if scope in ("all", "client"):
        loader_disp = f"{cfg.client_loader.capitalize()} {cfg.client_loader_version}".strip()
        mrpack_path = root_dir / "client" / f"Tundra-Client-{cfg.mc_version}.mrpack"
        mrpack_status = (
            ui.bold_green("Ready") if mrpack_path.is_file() else ui.dim("Not built yet")
        )
        lines.extend(
            [
                f"Client Loader    : {ui.bold(loader_disp)}",
                f"Client Mods      : {ui.bold_green(str(len(cfg.client_mods)))} enabled ({cli_ok}/{len(cli_pkgs)} local files, .mrpack: {mrpack_status})",
            ]
        )

    title = (
        "Tundra Server Stack"
        if scope == "server"
        else ("Tundra Player Client Stack" if scope == "client" else "Tundra Stack Overview")
    )
    ui.panel(title, lines)


# ==============================================================================
# Interactive Server Configurator Wizard (`tundra-server`)
# ==============================================================================
def run_server_wizard(cfg: TundraConfig, manifest_path: Path) -> int:
    root_dir = manifest_path.parent
    print_status_banner(cfg, root_dir, scope="server")

    action = ui.select(
        "Server Configurator — What would you like to do?",
        [
            (
                "configure",
                "Configure Server Stack (Wizard)",
                "Pick Minecraft version, server backend (Paper/Purpur/Aternos), and plugins",
            ),
            (
                "sync",
                "Download & Verify Server + Plugins",
                f"Fetch pinned {cfg.server_backend} & {len(cfg.server_plugins)} plugins into ./server/ and ./plugins/",
            ),
            (
                "resolve",
                f"Audit Upstream Compatibility (MC {cfg.mc_version})",
                "Verify Paper/Purpur builds, Modrinth versions, and plugin dependency edges",
            ),
            (
                "upgrade-preview",
                "Preview Upgrading to Another MC Version",
                "Simulate resolving your server plugins against a newer Minecraft release",
            ),
            (
                "inspect-deps",
                "Inspect Local Plugin .jar Manifests",
                "Stream embedded plugin.yml / paper-plugin.yml from ./plugins/*.jar",
            ),
            (
                "export-zip",
                "Export Plugins .zip for Managed Hosting Panels",
                "Bundle ./plugins/*.jar for drag-and-drop upload (Aternos / Exaroton / Pterodactyl)",
            ),
            ("list", "List Declared Server Packages", "View versions, hashes, and install status"),
            ("exit", "Exit", "Quit without changes"),
        ],
    )

    if action == "exit":
        return 0
    if action == "sync":
        return sync_packages(cfg, root_dir, mode="download", filter_cat="server-all")
    if action == "resolve":
        return run_upstream_audit(cfg, target_mc=cfg.mc_version, filter_cat="server") or run_upstream_audit(cfg, target_mc=cfg.mc_version, filter_cat="plugins")
    if action == "inspect-deps":
        return run_offline_jar_inspector(cfg, root_dir, filter_cat="plugins")
    if action == "export-zip":
        rc = sync_packages(cfg, root_dir, mode="download", filter_cat="plugins")
        if rc == 0:
            export_plugins_zip(cfg, root_dir)
        return rc
    if action == "list":
        return sync_packages(cfg, root_dir, mode="list", filter_cat="server-all")
    if action == "upgrade-preview":
        with ui.spinner("Fetching available Minecraft versions from PaperMC API..."):
            vers = fetch_available_mc_versions("paper")
        ver_opts = [(v, v, "Current pinned version" if v == cfg.mc_version else "Upstream release") for v in vers]
        chosen_mc = ui.select("Select target Minecraft version to preview:", ver_opts)
        return run_upstream_audit(cfg, target_mc=chosen_mc, filter_cat="all")

    # --- Full Interactive Server Configuration Flow ---
    # 1. Choose Backend
    backend_options = [
        (b.key, f"{b.name:<42} [{b.category}]", b.description)
        for b in SERVER_BACKENDS.values()
    ]
    default_b_idx = next(
        (i for i, b in enumerate(SERVER_BACKENDS.keys()) if b == cfg.server_backend), 0
    )
    chosen_backend = ui.select(
        "Step 1/3 — Select Server Backend:",
        backend_options,
        default_index=default_b_idx,
    )
    cfg.server_backend = chosen_backend

    # 2. Choose Minecraft Version
    with ui.spinner(f"Fetching supported Minecraft versions for {chosen_backend}..."):
        avail_versions = fetch_available_mc_versions(chosen_backend)
    if cfg.mc_version not in avail_versions:
        avail_versions.insert(0, cfg.mc_version)

    mc_options = []
    for idx, v in enumerate(avail_versions):
        note = "Current in tundra.toml" if v == cfg.mc_version else ("Latest upstream release" if idx == 0 else "Stable release")
        mc_options.append((v, v, note))

    default_mc_idx = next(
        (i for i, (v, _, _) in enumerate(mc_options) if v == cfg.mc_version), 0
    )
    chosen_mc = ui.select(
        "Step 2/3 — Select Target Minecraft Version:",
        mc_options,
        default_index=default_mc_idx,
    )
    mc_changed = chosen_mc != cfg.mc_version
    cfg.mc_version = chosen_mc

    # 3. Choose Server Plugins
    plugin_options = [
        (
            p.key,
            f"{p.name:<28} [{p.category}]",
            p.description,
        )
        for p in SERVER_PLUGINS.values()
    ]
    preselected_plugins = (
        cfg.server_plugins
        if cfg.server_plugins
        else [p.key for p in SERVER_PLUGINS.values() if p.default_selected]
    )
    chosen_plugins = ui.multiselect(
        "Step 3/3 — Select Server Plugins (dependencies auto-resolved):",
        plugin_options,
        preselected=preselected_plugins,
    )
    cfg.server_plugins = expand_required_dependencies(chosen_plugins, SERVER_PLUGINS)

    # Resolve upstream URLs & hashes and save tundra.toml
    resolve_scope = "all" if mc_changed else "server"
    resolve_full_config(cfg, scope=resolve_scope)
    saved_path = save_config(cfg, manifest_path)
    ui.success(
        f"Updated {ui.bold(saved_path.name)} (MC {cfg.mc_version}, backend: {cfg.server_backend}, {len(cfg.server_plugins)} plugins)"
    )

    next_step = ui.select(
        "Download & verify the resolved server stack now?",
        [
            ("download", "Download & verify server/ and plugins/ binaries now"),
            ("zip", "Download plugins & export a .zip for managed server panel (Aternos/Pterodactyl)"),
            ("skip", "Save tundra.toml only (download later with `tundra-server sync`)"),
        ],
    )
    if next_step == "download":
        return sync_packages(cfg, root_dir, mode="download", filter_cat="server-all")
    if next_step == "zip":
        rc = sync_packages(cfg, root_dir, mode="download", filter_cat="plugins")
        if rc == 0:
            export_plugins_zip(cfg, root_dir)
        return rc
    return 0


# ==============================================================================
# Interactive Player / Client Installer Wizard (`tundra-client`)
# ==============================================================================
def run_client_wizard(cfg: TundraConfig, manifest_path: Path) -> int:
    root_dir = manifest_path.parent
    print_status_banner(cfg, root_dir, scope="client")

    action = ui.select(
        f"Player Client Installer (Server MC {cfg.mc_version}) — What would you like to do?",
        [
            (
                "quick-mrpack",
                f"(Recommended) Build Prism Launcher Modpack (.mrpack) & Sync Client",
                f"One-click import for Prism/Modrinth App ({cfg.client_loader.capitalize()} {cfg.mc_version})",
            ),
            (
                "configure",
                "Customize Client Loader & Recommended Mods",
                "Choose Fabric (Sodium + Iris) or Forge (Embeddium + Oculus) and toggle mods",
            ),
            (
                "direct-mods",
                "Install Mod .jars Directly into a Folder (.minecraft/mods)",
                "For players using the standard Minecraft Launcher instead of Prism",
            ),
            (
                "resolve",
                f"Verify Client Mod Compatibility (MC {cfg.mc_version})",
                "Audit Modrinth versions and required dependencies",
            ),
            (
                "inspect-deps",
                "Inspect Local Client Mod .jar Manifests",
                "Check embedded fabric.mod.json / META-INF/mods.toml offline",
            ),
            ("list", "List Declared Client Packages", "View versions, hashes, and status"),
            ("exit", "Exit", "Quit without changes"),
        ],
    )

    if action == "exit":
        return 0
    if action == "quick-mrpack":
        return sync_packages(cfg, root_dir, mode="download", filter_cat="client")
    if action == "resolve":
        return run_upstream_audit(cfg, target_mc=cfg.mc_version, filter_cat="client")
    if action == "inspect-deps":
        return run_offline_jar_inspector(cfg, root_dir, filter_cat="client")
    if action == "list":
        return sync_packages(cfg, root_dir, mode="list", filter_cat="client")
    if action == "direct-mods":
        default_mc_mods = Path.home() / ".minecraft" / "mods"
        dest_choice = ui.select(
            "Where should the client mod .jar files be installed?",
            [
                ("local", f"Repository ./client/ folder ({root_dir / 'client'})", "Includes loader installer & .mrpack"),
                ("mc", f"Standard Minecraft mods folder ({default_mc_mods})", "Copies mod .jars directly into ~/.minecraft/mods"),
            ],
        )
        if dest_choice == "mc":
            return sync_packages(
                cfg,
                root_dir,
                mode="download",
                filter_cat="client",
                target_dir_override=default_mc_mods,
            )
        return sync_packages(cfg, root_dir, mode="download", filter_cat="client")

    # --- Customize Client Stack (Loader + Recommended Mods) ---
    loader_options = [
        (
            "fabric",
            "(Recommended) Fabric Loader — Sodium + Iris Shaders + FerriteCore",
            "Fastest updates, highest FPS, and lowest RAM usage for modern Minecraft",
        ),
        (
            "forge",
            "Minecraft Forge — Embeddium + Oculus + JourneyMap",
            "Classic Forge mod loader stack for Forge-specific client setups",
        ),
    ]
    default_l_idx = 0 if cfg.client_loader == "fabric" else 1
    chosen_loader = ui.select(
        f"Step 1/3 — Select Client Mod Loader (for MC {cfg.mc_version}):",
        loader_options,
        default_index=default_l_idx,
    )
    loader_changed = chosen_loader != cfg.client_loader
    cfg.client_loader = chosen_loader

    client_reg = get_client_registry(chosen_loader)
    mod_options = [
        (
            m.key,
            f"{m.name:<28} [{m.category}]",
            m.description,
        )
        for m in client_reg.values()
    ]
    if loader_changed or not cfg.client_mods:
        preselected_mods = [m.key for m in client_reg.values() if m.default_selected]
    else:
        preselected_mods = [
            k for k in cfg.client_mods if k in client_reg
        ] or [m.key for m in client_reg.values() if m.default_selected]

    chosen_mods = ui.multiselect(
        f"Step 2/3 — Select Recommended Client Mods ({chosen_loader.capitalize()}):",
        mod_options,
        preselected=preselected_mods,
    )
    cfg.client_mods = expand_required_dependencies(chosen_mods, client_reg)

    prism_choice = ui.select(
        "Step 3/3 — Include standalone Prism Launcher desktop installer in ./client/?",
        [
            ("yes", "Yes — Include Prism Launcher installer + .mrpack", "Great for new players setting up from scratch"),
            ("no", "No — Only download mods, loader installer, and .mrpack", "Skip the ~24MB Windows .exe installer"),
        ],
        default_index=0 if cfg.include_prism_installer else 1,
    )
    cfg.include_prism_installer = prism_choice == "yes"

    resolve_full_config(cfg, scope="client")
    saved_path = save_config(cfg, manifest_path)
    ui.success(
        f"Updated {ui.bold(saved_path.name)} ({cfg.client_loader.capitalize()} {cfg.client_loader_version}, {len(cfg.client_mods)} client mods)"
    )

    install_now = ui.select(
        "Download client mods and generate Prism Launcher .mrpack now?",
        [
            ("yes", "Download verified client mods & build Tundra-Client.mrpack now"),
            ("skip", "Save tundra.toml only (run `tundra-client sync` later)"),
        ],
    )
    if install_now == "yes":
        return sync_packages(cfg, root_dir, mode="download", filter_cat="client")
    return 0


# ==============================================================================
# Entrypoints (`tundra-server`, `tundra-client`, `tundra`)
# ==============================================================================
def _parse_common_flags(args: list[str]) -> tuple[list[str], dict[str, Any]]:
    opts: dict[str, Any] = {
        "config": None,
        "mc": None,
        "loader": None,
        "mods_dir": None,
        "force": False,
        "from_release": False,
        "filter": "all",
    }
    positional: list[str] = []
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-c", "--config") and i + 1 < len(args):
            opts["config"] = args[i + 1]
            i += 2
        elif a.startswith("--config="):
            opts["config"] = a.split("=", 1)[1]
            i += 1
        elif a == "--mc" and i + 1 < len(args):
            opts["mc"] = args[i + 1]
            i += 2
        elif a.startswith("--mc="):
            opts["mc"] = a.split("=", 1)[1]
            i += 1
        elif a == "--loader" and i + 1 < len(args):
            opts["loader"] = args[i + 1]
            i += 2
        elif a.startswith("--loader="):
            opts["loader"] = a.split("=", 1)[1]
            i += 1
        elif a == "--mods-dir" and i + 1 < len(args):
            opts["mods_dir"] = args[i + 1]
            i += 2
        elif a.startswith("--mods-dir="):
            opts["mods_dir"] = a.split("=", 1)[1]
            i += 1
        elif a in ("-f", "--force"):
            opts["force"] = True
            i += 1
        elif a == "--from-release":
            opts["from_release"] = True
            i += 1
        elif a == "--server":
            opts["filter"] = "server"
            i += 1
        elif a == "--plugins":
            opts["filter"] = "plugins"
            i += 1
        elif a == "--client":
            opts["filter"] = "client"
            i += 1
        elif a in ("--color", "--no-color") or a.startswith("--color="):
            if a == "--color" and i + 1 < len(args):
                i += 2
            else:
                i += 1
        # Legacy download.sh flag compatibility (--resolve, --verify, --list, --inspect-deps, --mrpack, --bundle)
        elif a in (
            "--resolve",
            "--verify",
            "--list",
            "--inspect-deps",
            "--mrpack",
            "--bundle",
        ):
            positional.insert(0, a.lstrip("-"))
            i += 1
        else:
            positional.append(a)
            i += 1
    return positional, opts


def main_server(argv: list[str] | None = None) -> int:
    """Dedicated entrypoint for `tundra-server`."""
    handle_color_args()
    ui.set_identity("tundra-server", icon="🏔️", badge_color="1;34")
    raw_args = argv if argv is not None else sys.argv[1:]

    if any(a in ("-h", "--help", "help") for a in raw_args):
        print_server_help()
        return 0
    if any(a in ("-V", "-v", "--version", "version") for a in raw_args):
        print(f"{ui.badge()} {ui.bold(f'v{__version__}')}")
        return 0

    positional, opts = _parse_common_flags(raw_args)
    manifest_path = find_manifest_path(opts["config"])
    root_dir = manifest_path.parent
    cfg = load_config(manifest_path)

    if not positional:
        if sys.stdin.isatty():
            return run_server_wizard(cfg, manifest_path)
        print_server_help()
        return 0

    cmd = positional[0].lower()
    if cmd in ("configure", "config", "init", "wizard"):
        return run_server_wizard(cfg, manifest_path)
    if cmd in ("sync", "download", "install"):
        fcat = opts["filter"] if opts["filter"] != "all" else "server-all"
        return sync_packages(
            cfg,
            root_dir,
            mode="download",
            filter_cat=fcat,
            force=opts["force"],
            prefer_release=opts["from_release"],
        )
    if cmd == "verify":
        fcat = opts["filter"] if opts["filter"] != "all" else "server-all"
        return sync_packages(cfg, root_dir, mode="verify", filter_cat=fcat)
    if cmd in ("list", "ls"):
        fcat = opts["filter"] if opts["filter"] != "all" else "server-all"
        return sync_packages(cfg, root_dir, mode="list", filter_cat=fcat)
    if cmd == "resolve":
        return run_upstream_audit(
            cfg, target_mc=opts["mc"] or cfg.mc_version, filter_cat="plugins"
        )
    if cmd == "inspect-deps":
        return run_offline_jar_inspector(cfg, root_dir, filter_cat="plugins")
    if cmd == "export-zip":
        rc = sync_packages(cfg, root_dir, mode="download", filter_cat="plugins")
        if rc == 0:
            export_plugins_zip(cfg, root_dir)
        return rc

    ui.error(f"Unknown server command '{cmd}'. Run `tundra-server --help` for usage.")
    return 1


def main_client(argv: list[str] | None = None) -> int:
    """Dedicated entrypoint for `tundra-client`."""
    handle_color_args()
    ui.set_identity("tundra-client", icon="🧊", badge_color="1;36")
    raw_args = argv if argv is not None else sys.argv[1:]

    if any(a in ("-h", "--help", "help") for a in raw_args):
        print_client_help()
        return 0
    if any(a in ("-V", "-v", "--version", "version") for a in raw_args):
        print(f"{ui.badge()} {ui.bold(f'v{__version__}')}")
        return 0

    positional, opts = _parse_common_flags(raw_args)
    manifest_path = find_manifest_path(opts["config"])
    root_dir = manifest_path.parent
    cfg = load_config(manifest_path)

    if opts["loader"]:
        new_loader = opts["loader"].lower()
        if new_loader != cfg.client_loader:
            cfg.client_loader = new_loader
            reg = get_client_registry(new_loader)
            cfg.client_mods = [m.key for m in reg.values() if m.default_selected]
            resolve_full_config(cfg, scope="client")
            save_config(cfg, manifest_path)

    if not positional:
        if sys.stdin.isatty():
            return run_client_wizard(cfg, manifest_path)
        print_client_help()
        return 0

    cmd = positional[0].lower()
    if cmd in ("configure", "config", "init", "wizard"):
        return run_client_wizard(cfg, manifest_path)
    if cmd in ("sync", "download", "install"):
        mods_dir = Path(opts["mods_dir"]).expanduser().resolve() if opts["mods_dir"] else None
        return sync_packages(
            cfg,
            root_dir,
            mode="download",
            filter_cat="client",
            force=opts["force"],
            prefer_release=opts["from_release"],
            target_dir_override=mods_dir,
        )
    if cmd == "mrpack":
        build_mrpack(cfg, root_dir)
        return 0
    if cmd == "verify":
        return sync_packages(cfg, root_dir, mode="verify", filter_cat="client")
    if cmd in ("list", "ls"):
        return sync_packages(cfg, root_dir, mode="list", filter_cat="client")
    if cmd == "resolve":
        return run_upstream_audit(
            cfg, target_mc=opts["mc"] or cfg.mc_version, filter_cat="client"
        )
    if cmd == "inspect-deps":
        return run_offline_jar_inspector(cfg, root_dir, filter_cat="client")

    ui.error(f"Unknown client command '{cmd}'. Run `tundra-client --help` for usage.")
    return 1


def main() -> int:
    """Unified entrypoint for `tundra`."""
    handle_color_args()
    ui.set_identity("tundra", icon="🏔️", badge_color="1;36")
    raw_args = sys.argv[1:]

    if raw_args and raw_args[0] == "server":
        return main_server(raw_args[1:])
    if raw_args and raw_args[0] == "client":
        return main_client(raw_args[1:])

    if any(a in ("-h", "--help", "help") for a in raw_args):
        print_unified_help()
        return 0
    if any(a in ("-V", "-v", "--version", "version") for a in raw_args):
        print(f"{ui.badge()} {ui.bold(f'v{__version__}')}")
        return 0

    positional, opts = _parse_common_flags(raw_args)
    manifest_path = find_manifest_path(opts["config"])
    root_dir = manifest_path.parent
    cfg = load_config(manifest_path)

    if not positional:
        if sys.stdin.isatty():
            print_status_banner(cfg, root_dir, scope="all")
            choice = ui.select(
                "Welcome to Tundra — Select a tool or action:",
                [
                    (
                        "server",
                        "Server Configurator (tundra-server)",
                        "Pick Paper/Purpur/Folia/Aternos backend, toggle plugins, & sync ./plugins/",
                    ),
                    (
                        "client",
                        "Player Client Installer (tundra-client)",
                        "Pick Fabric (Sodium/Iris) or Forge (Embeddium/Oculus) & build .mrpack",
                    ),
                    (
                        "sync",
                        "Sync & Verify All Packages",
                        "Download & SHA256-verify server, plugins, client mods, and build .mrpack",
                    ),
                    (
                        "resolve",
                        f"Resolve Upstream Compatibility & Dependency Graph (MC {cfg.mc_version})",
                        "Query Modrinth, PaperMC, and Fabric/Forge APIs",
                    ),
                    (
                        "inspect-deps",
                        "Inspect Embedded .jar Manifests Offline",
                        "Verify plugin.yml, fabric.mod.json, and META-INF/mods.toml dependencies",
                    ),
                    (
                        "list",
                        "List All Declared Packages",
                        "Display version, status, and purpose of every package in tundra.toml",
                    ),
                    ("exit", "Exit", "Quit"),
                ],
            )
            if choice == "exit":
                return 0
            if choice == "server":
                return main_server(["configure"])
            if choice == "client":
                return main_client(["configure"])
            positional = [choice]
        else:
            positional = ["sync"]

    cmd = positional[0].lower()
    if cmd in ("sync", "download", "install"):
        return sync_packages(
            cfg,
            root_dir,
            mode="download",
            filter_cat=opts["filter"],
            force=opts["force"],
            prefer_release=opts["from_release"],
        )
    if cmd == "verify":
        return sync_packages(
            cfg, root_dir, mode="verify", filter_cat=opts["filter"]
        )
    if cmd in ("list", "ls"):
        return sync_packages(
            cfg, root_dir, mode="list", filter_cat=opts["filter"]
        )
    if cmd == "resolve":
        return run_upstream_audit(
            cfg,
            target_mc=opts["mc"] or cfg.mc_version,
            filter_cat=opts["filter"],
        )
    if cmd == "inspect-deps":
        return run_offline_jar_inspector(cfg, root_dir, filter_cat=opts["filter"])
    if cmd == "mrpack":
        build_mrpack(cfg, root_dir)
        return 0
    if cmd == "bundle":
        return create_release_bundle(cfg, root_dir)

    ui.error(f"Unknown command '{cmd}'. Run `tundra --help` for usage.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
