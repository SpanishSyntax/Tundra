"""Curated registry of Minecraft server backends, plugins, and client mods."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ServerBackendSpec:
    key: str
    name: str
    category: str
    description: str
    api_type: str  # "papermc" | "purpur" | "fabric_server" | "forge_server" | "none"
    project_slug: str = ""
    loaders: tuple[str, ...] = ("paper", "spigot", "bukkit")


@dataclass(frozen=True)
class PackageSpec:
    key: str
    name: str
    category: str
    side: str  # "plugins" | "client"
    source_type: str  # "modrinth" | "github_release" | "essentialsx"
    project_id: str  # Modrinth project_id/slug or GitHub "owner/repo"
    description: str
    loaders: tuple[str, ...] = ("paper", "spigot", "bukkit")
    asset_filter: str = ""  # Optional filename substring filter (e.g. "EssentialsXChat")
    requires: tuple[str, ...] = field(default_factory=tuple)
    provides: tuple[str, ...] = field(default_factory=tuple)
    incompatible: tuple[str, ...] = field(default_factory=tuple)
    default_selected: bool = True
    fallback_url: str = ""
    fallback_version: str = ""
    fallback_sha256: str = ""
    fallback_filename: str = ""


# ==============================================================================
# 1. Server Backends
# ==============================================================================
SERVER_BACKENDS: dict[str, ServerBackendSpec] = {
    "paper": ServerBackendSpec(
        key="paper",
        name="PaperMC (Recommended)",
        category="Plugin Server",
        description="High-performance async-capable fork of Spigot/Bukkit; required by FAWE",
        api_type="papermc",
        project_slug="paper",
        loaders=("paper", "spigot", "bukkit"),
    ),
    "purpur": ServerBackendSpec(
        key="purpur",
        name="PurpurMC",
        category="Plugin Server",
        description="Drop-in Paper fork with extensive gameplay customization & config toggles",
        api_type="purpur",
        project_slug="purpur",
        loaders=("purpur", "paper", "spigot", "bukkit"),
    ),
    "folia": ServerBackendSpec(
        key="folia",
        name="Folia (Regionized Multithreading)",
        category="Plugin Server",
        description="PaperMC's multithreaded region server for massive player counts",
        api_type="papermc",
        project_slug="folia",
        loaders=("folia", "paper"),
    ),
    "plugins-only": ServerBackendSpec(
        key="plugins-only",
        name="Managed Host / Plugins-Only (Aternos, Apex, Pterodactyl)",
        category="Managed Host",
        description="Skip server runtime .jar download; resolve & bundle plugins/ for panel upload",
        api_type="none",
        project_slug="",
        loaders=("paper", "spigot", "bukkit"),
    ),
    "fabric": ServerBackendSpec(
        key="fabric",
        name="Fabric Server",
        category="Modded Server",
        description="Lightweight, modern modded server runtime",
        api_type="fabric_server",
        project_slug="fabric",
        loaders=("fabric",),
    ),
}


# ==============================================================================
# 2. Server Plugins Registry (Paper / Purpur / Spigot / Bukkit)
# ==============================================================================
SERVER_PLUGINS: dict[str, PackageSpec] = {
    # --- Layer A: Permissions & Service API ---
    "luckperms": PackageSpec(
        key="luckperms",
        name="LuckPerms",
        category="Permissions & API",
        side="plugins",
        source_type="modrinth",
        project_id="Vebnzrzj",
        description="Core permissions & role authority (groups, prefixes, /lp editor); loads before Vault",
        default_selected=True,
    ),
    "vault": PackageSpec(
        key="vault",
        name="Vault",
        category="Permissions & API",
        side="plugins",
        source_type="github_release",
        project_id="MilkBowl/Vault",
        description="Permissions, chat, and economy service API bridging LuckPerms with EssentialsX & Multiverse",
        asset_filter="Vault.jar",
        default_selected=True,
        fallback_url="https://github.com/MilkBowl/Vault/releases/download/1.7.3/Vault.jar",
        fallback_version="1.7.3-b131",
        fallback_sha256="a6b5ed97f43a5cf5bbaf00a7c8cd23c5afc9bd003f849875af8b36e6cf77d01d",
        fallback_filename="Vault.jar",
    ),
    # --- Layer B: Core Gameplay, Chat & Moderation (EssentialsX Suite) ---
    "essentialsx": PackageSpec(
        key="essentialsx",
        name="EssentialsX Core",
        category="EssentialsX Suite",
        side="plugins",
        source_type="essentialsx",
        project_id="hXiIvTyT",
        asset_filter="EssentialsX-",
        description="Foundational server commands (/tpa, /home, /warp, /kit), economy, and moderation",
        default_selected=True,
    ),
    "essentialsx-chat": PackageSpec(
        key="essentialsx-chat",
        name="EssentialsX Chat",
        category="EssentialsX Suite",
        side="plugins",
        source_type="essentialsx",
        project_id="hXiIvTyT",
        asset_filter="EssentialsXChat-",
        requires=("essentialsx",),
        description="Chat formatting addon rendering LuckPerms prefixes/suffixes, colors, and chat radius",
        default_selected=True,
    ),
    "essentialsx-spawn": PackageSpec(
        key="essentialsx-spawn",
        name="EssentialsX Spawn",
        category="EssentialsX Suite",
        side="plugins",
        source_type="essentialsx",
        project_id="hXiIvTyT",
        asset_filter="EssentialsXSpawn-",
        requires=("essentialsx",),
        description="Controls initial join spawn, /setspawn, /spawn, and per-group respawn routing",
        default_selected=True,
    ),
    "essentialsx-protect": PackageSpec(
        key="essentialsx-protect",
        name="EssentialsX Protect",
        category="EssentialsX Suite",
        side="plugins",
        source_type="essentialsx",
        project_id="hXiIvTyT",
        asset_filter="EssentialsXProtect-",
        requires=("essentialsx",),
        description="Global world protection rules (creeper/TNT block damage, fire spread, weather locks)",
        default_selected=True,
    ),
    "essentialsx-antibuild": PackageSpec(
        key="essentialsx-antibuild",
        name="EssentialsX AntiBuild",
        category="EssentialsX Suite",
        side="plugins",
        source_type="essentialsx",
        project_id="hXiIvTyT",
        asset_filter="EssentialsXAntiBuild-",
        requires=("essentialsx",),
        description="Fine-grained rank permission checks for placing, breaking, crafting, or dropping items",
        default_selected=True,
    ),
    # --- Layer C: Multi-World & Portal Routing (Multiverse 5.x Suite) ---
    "multiverse-core": PackageSpec(
        key="multiverse-core",
        name="Multiverse-Core",
        category="Multiverse Suite",
        side="plugins",
        source_type="modrinth",
        project_id="3wmN97b8",
        description="Multi-world engine hosting simultaneous worlds (Lobby, Survival, Creative) with custom rules",
        default_selected=True,
    ),
    "multiverse-inventories": PackageSpec(
        key="multiverse-inventories",
        name="Multiverse-Inventories",
        category="Multiverse Suite",
        side="plugins",
        source_type="modrinth",
        project_id="qvdtDX3s",
        requires=("multiverse-core",),
        description="Isolates player inventories, XP, health, and Ender Chests between Survival & Creative worlds",
        default_selected=True,
    ),
    "multiverse-netherportals": PackageSpec(
        key="multiverse-netherportals",
        name="Multiverse-NetherPortals",
        category="Multiverse Suite",
        side="plugins",
        source_type="modrinth",
        project_id="vtawPsTo",
        requires=("multiverse-core",),
        description="Links vanilla Nether/End portals to world-specific _nether and _the_end dimensions",
        default_selected=True,
    ),
    "multiverse-portals": PackageSpec(
        key="multiverse-portals",
        name="Multiverse-Portals",
        category="Multiverse Suite",
        side="plugins",
        source_type="modrinth",
        project_id="8VMk6P0I",
        requires=("multiverse-core",),
        description="Custom stargates/hub portals selected with the FAWE/WorldEdit wand",
        default_selected=True,
    ),
    "multiverse-signportals": PackageSpec(
        key="multiverse-signportals",
        name="Multiverse-SignPortals",
        category="Multiverse Suite",
        side="plugins",
        source_type="modrinth",
        project_id="WuErDeI1",
        requires=("multiverse-core",),
        description="Clickable [mv] teleportation signs and sign-attached portal destinations",
        default_selected=True,
    ),
    # --- Layer D: Async World Building, Chunk Pre-Generation & Protection ---
    "fastasyncworldedit": PackageSpec(
        key="fastasyncworldedit",
        name="FastAsyncWorldEdit (FAWE)",
        category="World & Protection",
        side="plugins",
        source_type="modrinth",
        project_id="z4HZZnLr",
        provides=("worldedit", "1u6JkXh5"),
        description="Blazingly fast async WorldEdit replacement (provides: [WorldEdit]) for WorldGuard & Portals",
        default_selected=True,
    ),
    "worldguard": PackageSpec(
        key="worldguard",
        name="WorldGuard",
        category="World & Protection",
        side="plugins",
        source_type="modrinth",
        project_id="DKY9btbd",
        requires=("fastasyncworldedit",),
        description="3D region protection & flags (Spawn Hub, PvP arenas, build permissions, mob-spawning)",
        default_selected=True,
    ),
    "chunky": PackageSpec(
        key="chunky",
        name="Chunky",
        category="World & Protection",
        side="plugins",
        source_type="modrinth",
        project_id="fALzjamp",
        description="Asynchronous world chunk pre-generator (/chunky) eliminating exploration lag spikes",
        default_selected=True,
    ),
    # --- Layer E: Optional Cross-Version & Voice Addons ---
    "simple-voice-chat": PackageSpec(
        key="simple-voice-chat",
        name="Simple Voice Chat (Server)",
        category="Voice & Cross-Version",
        side="plugins",
        source_type="modrinth",
        project_id="9eGKb6K1",
        description="Proximity voice chat server plugin for players using the Simple Voice Chat client mod",
        default_selected=False,
    ),
    "viaversion": PackageSpec(
        key="viaversion",
        name="ViaVersion",
        category="Voice & Cross-Version",
        side="plugins",
        source_type="modrinth",
        project_id="P1OZGk5p",
        description="Allows newer Minecraft client versions to connect to your server",
        default_selected=False,
    ),
    "viabackwards": PackageSpec(
        key="viabackwards",
        name="ViaBackwards",
        category="Voice & Cross-Version",
        side="plugins",
        source_type="modrinth",
        project_id="NpvuJQoq",
        requires=("viaversion",),
        description="Allows older Minecraft client versions to connect to a newer server",
        default_selected=False,
    ),
}


# ==============================================================================
# 3. Client Mods Registry — Fabric (Recommended) & Forge / NeoForge
# ==============================================================================
CLIENT_MODS_FABRIC: dict[str, PackageSpec] = {
    "fabric-api": PackageSpec(
        key="fabric-api",
        name="Fabric API",
        category="Core API",
        side="client",
        source_type="modrinth",
        project_id="P7dR8mSH",
        loaders=("fabric",),
        description="Essential standard library required by almost all Fabric client mods",
        default_selected=True,
    ),
    "sodium": PackageSpec(
        key="sodium",
        name="Sodium",
        category="Performance & Shaders",
        side="client",
        source_type="modrinth",
        project_id="AANobbMI",
        loaders=("fabric",),
        requires=("fabric-api",),
        description="Modern open-source rendering engine that dramatically boosts FPS and fixes frame stutter",
        default_selected=True,
    ),
    "iris": PackageSpec(
        key="iris",
        name="Iris Shaders",
        category="Performance & Shaders",
        side="client",
        source_type="modrinth",
        project_id="YL57xq9U",
        loaders=("fabric",),
        requires=("sodium",),
        description="Modern shader pack loader paired with Sodium (replaces OptiFine shaders)",
        default_selected=True,
    ),
    "journeymap": PackageSpec(
        key="journeymap",
        name="JourneyMap",
        category="HUD & Navigation",
        side="client",
        source_type="modrinth",
        project_id="lfHFW1mp",
        loaders=("fabric",),
        requires=("fabric-api",),
        description="Real-time HUD minimap, fullscreen world map, cave mapping, and death/waypoint markers",
        default_selected=True,
    ),
    "ferrite-core": PackageSpec(
        key="ferrite-core",
        name="FerriteCore",
        category="Performance & Shaders",
        side="client",
        source_type="modrinth",
        project_id="uXXizFIs",
        loaders=("fabric",),
        description="Reduces Minecraft client memory (RAM) usage by ~45% via blockstate deduplication",
        default_selected=True,
    ),
    "entityculling": PackageSpec(
        key="entityculling",
        name="EntityCulling",
        category="Performance & Shaders",
        side="client",
        source_type="modrinth",
        project_id="NNAgCjsB",
        loaders=("fabric",),
        description="Skips rendering block entities and mobs hidden behind walls using async raytracing",
        default_selected=True,
    ),
    "modmenu": PackageSpec(
        key="modmenu",
        name="Mod Menu",
        category="Quality of Life",
        side="client",
        source_type="modrinth",
        project_id="mOgUt4GM",
        loaders=("fabric",),
        requires=("fabric-api",),
        description="In-game screen for viewing installed Fabric mods and configuring mod settings",
        default_selected=True,
    ),
    "zoomify": PackageSpec(
        key="zoomify",
        name="Zoomify",
        category="Quality of Life",
        side="client",
        source_type="modrinth",
        project_id="w7ThoJFB",
        loaders=("fabric",),
        requires=("fabric-api",),
        description="Smooth, infinitely customizable spyglass/OptiFine-style C-key zoom",
        default_selected=False,
    ),
    "simple-voice-chat": PackageSpec(
        key="simple-voice-chat",
        name="Simple Voice Chat (Client)",
        category="Quality of Life",
        side="client",
        source_type="modrinth",
        project_id="9eGKb6K1",
        loaders=("fabric",),
        description="In-game proximity voice chat client mod",
        default_selected=False,
    ),
}

CLIENT_MODS_FORGE: dict[str, PackageSpec] = {
    "embeddium": PackageSpec(
        key="embeddium",
        name="Embeddium (Forge)",
        category="Performance & Shaders",
        side="client",
        source_type="modrinth",
        project_id="sk9rgfiA",
        loaders=("forge", "neoforge"),
        description="Modern Sodium-based client rendering engine for Forge replacing OptiFine; required by Oculus",
        default_selected=True,
    ),
    "oculus": PackageSpec(
        key="oculus",
        name="Oculus (Forge)",
        category="Performance & Shaders",
        side="client",
        source_type="modrinth",
        project_id="GchcoXML",
        loaders=("forge", "neoforge"),
        requires=("embeddium",),
        provides=("iris",),
        description="Modern Iris-based shader pack loader for Forge; requires Embeddium",
        default_selected=True,
    ),
    "journeymap": PackageSpec(
        key="journeymap",
        name="JourneyMap (Forge)",
        category="HUD & Navigation",
        side="client",
        source_type="modrinth",
        project_id="lfHFW1mp",
        loaders=("forge", "neoforge"),
        description="Real-time in-game minimap, fullscreen world map, and death/waypoint markers for players",
        default_selected=True,
    ),
    "ferrite-core": PackageSpec(
        key="ferrite-core",
        name="FerriteCore (Forge)",
        category="Performance & Shaders",
        side="client",
        source_type="modrinth",
        project_id="uXXizFIs",
        loaders=("forge", "neoforge"),
        description="Reduces client memory (RAM) usage via blockstate deduplication",
        default_selected=False,
    ),
    "entityculling": PackageSpec(
        key="entityculling",
        name="EntityCulling (Forge)",
        category="Performance & Shaders",
        side="client",
        source_type="modrinth",
        project_id="NNAgCjsB",
        loaders=("forge", "neoforge"),
        description="Async raytracing to skip rendering entities & block-entities behind walls",
        default_selected=False,
    ),
    "simple-voice-chat": PackageSpec(
        key="simple-voice-chat",
        name="Simple Voice Chat (Forge)",
        category="Quality of Life",
        side="client",
        source_type="modrinth",
        project_id="9eGKb6K1",
        loaders=("forge", "neoforge"),
        description="In-game proximity voice chat client mod",
        default_selected=False,
    ),
}


def get_client_registry(loader: str) -> dict[str, PackageSpec]:
    """Returns the appropriate client mod catalog for the chosen mod loader."""
    if loader.lower() in ("forge", "neoforge"):
        return CLIENT_MODS_FORGE
    return CLIENT_MODS_FABRIC


def expand_required_dependencies(
    selected_keys: list[str], registry: dict[str, PackageSpec]
) -> list[str]:
    """Automatically includes hard dependencies (e.g., iris -> sodium -> fabric-api)."""
    resolved: list[str] = []
    seen: set[str] = set()

    def visit(key: str):
        if key in seen or key not in registry:
            return
        seen.add(key)
        spec = registry[key]
        for req in spec.requires:
            visit(req)
        resolved.append(key)

    for k in selected_keys:
        visit(k)
    return resolved
