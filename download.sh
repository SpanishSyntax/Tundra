#!/usr/bin/env bash
# ==============================================================================
# Tundra Package Manager, Resolver & Downloader (Minecraft 1.20.1)
# - Declares & verifies server, client, and plugin binaries from packages.tsv
# - Resolves version/loader compatibility & dependency graphs via Modrinth/Paper
#   APIs (--resolve [--mc <VER>]), acting like 'uv' for Minecraft packages
# - Inspects embedded .jar manifests (plugin.yml & META-INF/mods.toml) offline
#   to verify hard/soft dependencies (--inspect-deps)
# - Packages modrinth.index.json into client/Tundra-Client-1.20.1.mrpack
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANIFEST="${SCRIPT_DIR}/packages.tsv"
MRPACK_INDEX="${SCRIPT_DIR}/modrinth.index.json"
MRPACK_OUT="${SCRIPT_DIR}/client/Tundra-Client-1.20.1.mrpack"
DEFAULT_RELEASE_URL="https://github.com/SpanishSyntax/Tundra/releases/download/v2.0.0"

MODE="download"         # download | verify | list | resolve | inspect-deps | mrpack | bundle
FILTER="all"            # all | server | client | plugins
FORCE=0                 # 1 = re-download even if checksum matches
TARGET_MC="1.20.1"      # Target Minecraft version for --resolve compatibility checks
RELEASE_BASE_URL="${TUNDRA_RELEASE_URL:-}" # Optional GitHub release asset base URL

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

usage() {
  cat <<EOF
${BOLD}Tundra Package Manager & Dependency Resolver (MC 1.20.1)${RESET}

Usage: ./download.sh [OPTIONS]

Modes:
  (default)              Download missing packages, verify SHA256, and build .mrpack
  --verify               Verify SHA256 checksums of existing local files without downloading
  --list                 List all declared packages, versions, install status, and purpose
  --resolve              Query Modrinth, PaperMC, and Forge APIs to verify MC/loader
                         compatibility, upstream dependency graphs, and latest releases
  --inspect-deps         Extract internal plugin.yml & META-INF/mods.toml from local .jar
                         files to verify hard/soft dependencies without reading READMEs
  --mrpack               Build 'client/Tundra-Client-1.20.1.mrpack' from modrinth.index.json
  --bundle               Create 'tundra-mc1.20.1-binaries.tar.gz' + 'SHA256SUMS' for Releases

Filters & Options:
  --mc <VERSION>         Target Minecraft version for '--resolve' (default: 1.20.1;
                         try '--resolve --mc 1.21.1' to preview upgrading the server)
  --server               Only process server runtime packages (server/)
  --client               Only process client packages (client/)
  --plugins              Only process server plugins (plugins/)
  --force                Re-download files even if they already exist and pass SHA256 check
  --from-release         Prefer fetching all packages directly from the Tundra GitHub Release
  --release-url <URL>    Fetch files from a custom GitHub Release base URL first
                         (default mirror: ${DEFAULT_RELEASE_URL})
  -h, --help             Show this help message
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --verify)         MODE="verify"; shift ;;
    --list)           MODE="list"; shift ;;
    --resolve)        MODE="resolve"; shift ;;
    --inspect-deps)   MODE="inspect-deps"; shift ;;
    --mrpack)         MODE="mrpack"; shift ;;
    --bundle)         MODE="bundle"; shift ;;
    --mc)             TARGET_MC="$2"; shift 2 ;;
    --server)         FILTER="server"; shift ;;
    --client)         FILTER="client"; shift ;;
    --plugins)        FILTER="plugins"; shift ;;
    --force)          FORCE=1; shift ;;
    --from-release)   RELEASE_BASE_URL="$DEFAULT_RELEASE_URL"; shift ;;
    --release-url)    RELEASE_BASE_URL="${2%/}"; shift 2 ;;
    -h|--help)        usage; exit 0 ;;
    *)                echo -e "${RED}Unknown argument: $1${RESET}" >&2; usage; exit 1 ;;
  esac
done

if [[ ! -f "$MANIFEST" ]]; then
  echo -e "${RED}Error: Manifest file not found at ${MANIFEST}${RESET}" >&2
  exit 1
fi

# Detect HTTP client
HTTP_CLIENT=""
if command -v curl >/dev/null 2>&1; then
  HTTP_CLIENT="curl"
elif command -v wget >/dev/null 2>&1; then
  HTTP_CLIENT="wget"
fi

fetch_url() {
  local url="$1"
  local dest="$2"
  if [[ "$HTTP_CLIENT" == "curl" ]]; then
    curl -fL --retry 3 --connect-timeout 15 -sS -H "User-Agent: Tundra/2.0" -o "$dest" "$url"
  elif [[ "$HTTP_CLIENT" == "wget" ]]; then
    wget -q --tries=3 --timeout=15 --header="User-Agent: Tundra/2.0" -O "$dest" "$url"
  else
    echo -e "${RED}Error: Neither 'curl' nor 'wget' is installed.${RESET}" >&2
    return 1
  fi
}

compute_sha256() {
  local file="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$file" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$file" | awk '{print $1}'
  else
    echo "missing-sha256-tool"
  fi
}

build_mrpack() {
  if [[ ! -f "$MRPACK_INDEX" ]]; then
    return 0
  fi
  mkdir -p "$(dirname "$MRPACK_OUT")"
  rm -f "$MRPACK_OUT"
  if command -v 7z >/dev/null 2>&1; then
    (cd "$SCRIPT_DIR" && 7z a -tzip -bso0 -bsp0 "$MRPACK_OUT" "modrinth.index.json")
    echo -e "${GREEN}[MRPACK]${RESET}   Generated $(basename "$MRPACK_OUT") for Prism Launcher one-click import"
  elif command -v zip >/dev/null 2>&1; then
    (cd "$SCRIPT_DIR" && zip -q "$MRPACK_OUT" "modrinth.index.json")
    echo -e "${GREEN}[MRPACK]${RESET}   Generated $(basename "$MRPACK_OUT") for Prism Launcher one-click import"
  else
    echo -e "${YELLOW}[WARN]${RESET}     Neither '7z' nor 'zip' found; skipping .mrpack archive creation."
  fi
}

# ==============================================================================
# MODE: --mrpack
# ==============================================================================
if [[ "$MODE" == "mrpack" ]]; then
  build_mrpack
  exit 0
fi

# ==============================================================================
# MODE: --resolve (Upstream API Compatibility & Dependency Graph Resolver)
# ==============================================================================
if [[ "$MODE" == "resolve" ]]; then
  if ! command -v curl >/dev/null 2>&1 || ! command -v jq >/dev/null 2>&1; then
    echo -e "${RED}Error: '--resolve' requires both 'curl' and 'jq' installed.${RESET}" >&2
    exit 1
  fi

  echo -e "${BLUE}${BOLD}==> Resolving Compatibility & Dependency Graph via Upstream APIs (Target MC: ${TARGET_MC})${RESET}"

  # Collect Modrinth project_ids and version_ids from packages.tsv
  declare -A pkg_proj_id=()
  declare -A pkg_ver_id=()
  declare -A proj_present=()
  modrinth_ver_ids=()
  modrinth_proj_ids=()

  while IFS=$'\t' read -r category filepath name version sha256 url purpose; do
    [[ -z "$category" || "$category" =~ ^# ]] && continue
    if [[ "$url" =~ cdn\.modrinth\.com/data/([^/]+)/versions/([^/]+)/ ]]; then
      pid="${BASH_REMATCH[1]}"
      vid="${BASH_REMATCH[2]}"
      pkg_proj_id["$filepath"]="$pid"
      pkg_ver_id["$filepath"]="$vid"
      proj_present["$pid"]="$name"
      # Dedup version IDs (EssentialsX shares one Modrinth release across 5 jars)
      if [[ ! " ${modrinth_ver_ids[*]} " =~ " \"${vid}\" " ]]; then
        modrinth_ver_ids+=("\"${vid}\"")
      fi
      if [[ ! " ${modrinth_proj_ids[*]} " =~ " \"${pid}\" " ]]; then
        modrinth_proj_ids+=("\"${pid}\"")
      fi
    fi
  done < "$MANIFEST"

  # Virtual 'provides': FastAsyncWorldEdit (z4HZZnLr) satisfies WorldEdit (1u6JkXh5)
  if [[ -n "${proj_present[z4HZZnLr]:-}" ]]; then
    proj_present["1u6JkXh5"]="FastAsyncWorldEdit (provides WorldEdit)"
  fi

  ver_json_array="[$(IFS=,; echo "${modrinth_ver_ids[*]}")]"
  versions_data="$(curl -sG -H "User-Agent: Tundra/2.0" "https://api.modrinth.com/v2/versions" \
    --data-urlencode "ids=${ver_json_array}")"

  # Also gather any referenced dependency project_ids so we can resolve their human-readable names
  dep_proj_ids="$(echo "$versions_data" | jq -r '.[].dependencies[].project_id // empty' | sort -u)"
  for dpid in $dep_proj_ids; do
    if [[ ! " ${modrinth_proj_ids[*]} " =~ " \"${dpid}\" " ]]; then
      modrinth_proj_ids+=("\"${dpid}\"")
    fi
  done
  proj_json_array="[$(IFS=,; echo "${modrinth_proj_ids[*]}")]"
  projects_data="$(curl -sG -H "User-Agent: Tundra/2.0" "https://api.modrinth.com/v2/projects" \
    --data-urlencode "ids=${proj_json_array}")"

  printf "\n${BOLD}%-28s  %-18s  %-14s  %-20s  %s${RESET}\n" \
    "PACKAGE" "PINNED VERSION" "MC ${TARGET_MC}" "LATEST FOR ${TARGET_MC}" "DEPENDENCY & LOADER CHECK"
  printf "%s\n" "----------------------------------------------------------------------------------------------------------------------------------"

  issues=0
  declare -A latest_ver_cache=()

  while IFS=$'\t' read -r category filepath name version sha256 url purpose; do
    [[ -z "$category" || "$category" =~ ^# ]] && continue
    if [[ "$FILTER" != "all" && "$category" != "$FILTER" ]]; then
      continue
    fi

    # 1. PaperMC Server check via Fill v3 API
    if [[ "$filepath" == server/paper-* ]]; then
      paper_resp="$(curl -s -H "User-Agent: Tundra/2.0" "https://fill.papermc.io/v3/projects/paper/versions/${TARGET_MC}/builds/latest" || true)"
      paper_build="$(echo "$paper_resp" | jq -r '.id // empty' 2>/dev/null || true)"
      if [[ -n "$paper_build" ]]; then
        latest_paper="${TARGET_MC}-${paper_build}"
        if [[ "$version" == "$latest_paper" ]]; then
          compat="${GREEN}✔ COMPATIBLE${RESET}  "
        else
          compat="${YELLOW}↻ UPGRADEABLE${RESET} "
        fi
        printf "%-28s  %-18s  %b  %-20s  %s\n" "$name" "$version" "$compat" "$latest_paper" "PaperMC Fill v3 API (channel: STABLE)"
      else
        printf "%-28s  %-18s  ${RED}✘ NO BUILD${RESET}    %-20s  %s\n" "$name" "$version" "none" "No PaperMC build found for ${TARGET_MC}"
        issues=$((issues + 1))
      fi
      continue
    fi

    # 2. Forge Installer check via Forge Promotions API
    if [[ "$filepath" == client/forge-* ]]; then
      forge_promos="$(curl -s -H "User-Agent: Tundra/2.0" "https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json" || true)"
      rec_forge="$(echo "$forge_promos" | jq -r --arg k "${TARGET_MC}-recommended" '.promos[$k] // empty')"
      lat_forge="$(echo "$forge_promos" | jq -r --arg k "${TARGET_MC}-latest" '.promos[$k] // empty')"
      best_forge="${rec_forge:-$lat_forge}"
      if [[ -n "$best_forge" ]]; then
        full_forge="${TARGET_MC}-${best_forge}"
        if [[ "$version" == "${TARGET_MC}-"* ]]; then
          compat="${GREEN}✔ COMPATIBLE${RESET}  "
        else
          compat="${YELLOW}↻ UPGRADEABLE${RESET} "
        fi
        printf "%-28s  %-18s  %b  %-20s  %s\n" "$name" "$version" "$compat" "$full_forge" "Forge Maven (${TARGET_MC}-recommended)"
      else
        printf "%-28s  %-18s  ${RED}✘ NO BUILD${RESET}    %-20s  %s\n" "$name" "$version" "none" "No Forge build for ${TARGET_MC}"
        issues=$((issues + 1))
      fi
      continue
    fi

    # 3. GitHub Release packages (Prism Launcher & Vault)
    if [[ "$url" == https://github.com/* ]]; then
      if [[ "$filepath" == *PrismLauncher* ]]; then
        printf "%-28s  %-18s  ${GREEN}✔ AGNOSTIC${RESET}    %-20s  %s\n" "$name" "$version" "$version" "Desktop Launcher (supports all MC versions)"
      elif [[ "$filepath" == *Vault.jar ]]; then
        printf "%-28s  %-18s  ${GREEN}✔ COMPATIBLE${RESET}  %-20s  %s\n" "$name" "$version" "$version" "Bukkit Service API (hooked by LuckPerms)"
      fi
      continue
    fi

    # 4. Modrinth packages
    pid="${pkg_proj_id[$filepath]:-}"
    vid="${pkg_ver_id[$filepath]:-}"
    if [[ -n "$pid" && -n "$vid" ]]; then
      # Query pinned version metadata from bulk response
      v_info="$(echo "$versions_data" | jq -c --arg vid "$vid" '.[] | select(.id == $vid)')"
      supports_mc="$(echo "$v_info" | jq -r --arg mc "$TARGET_MC" 'if (.game_versions | index($mc)) then "yes" else "no" end')"
      loaders_list="$(echo "$v_info" | jq -r '.loaders | join(",")')"

      # Query latest release for TARGET_MC (cache per project_id so EssentialsX 5 jars only query once)
      if [[ -n "${latest_ver_cache[$pid]:-}" ]]; then
        latest_ver="${latest_ver_cache[$pid]}"
      else
        if [[ "$category" == "client" ]]; then
          loader_filter='["forge","neoforge"]'
        else
          loader_filter='["paper","spigot","bukkit"]'
        fi
        latest_ver="$(curl -sG -H "User-Agent: Tundra/2.0" "https://api.modrinth.com/v2/project/${pid}/version" \
          --data-urlencode "game_versions=[\"${TARGET_MC}\"]" \
          --data-urlencode "loaders=${loader_filter}" \
          | jq -r '[.[] | select(.version_type == "release")][0].version_number // .[0].version_number // "none"')"
        latest_ver_cache["$pid"]="$latest_ver"
      fi

      if [[ "$supports_mc" == "yes" ]]; then
        compat="${GREEN}✔ COMPATIBLE${RESET}  "
      elif [[ "$latest_ver" != "none" ]]; then
        compat="${YELLOW}↻ NEEDS BUMP${RESET}  "
      else
        compat="${RED}✘ UNSUPPORTED${RESET} "
        issues=$((issues + 1))
      fi

      # Check required and incompatible dependencies
      dep_notes=()
      while IFS=$'\t' read -r dep_pid dep_type; do
        [[ -z "$dep_pid" ]] && continue
        dep_title="$(echo "$projects_data" | jq -r --arg id "$dep_pid" '.[] | select(.id == $id) | .title // $id')"
        if [[ "$dep_type" == "required" ]]; then
          if [[ -n "${proj_present[$dep_pid]:-}" ]]; then
            dep_notes+=("${GREEN}req:${dep_title}✔${RESET}")
          else
            dep_notes+=("${RED}MISSING:${dep_title}✘${RESET}")
            issues=$((issues + 1))
          fi
        elif [[ "$dep_type" == "incompatible" ]]; then
          if [[ -n "${proj_present[$dep_pid]:-}" ]]; then
            dep_notes+=("${RED}CONFLICT:${dep_title}✘${RESET}")
            issues=$((issues + 1))
          else
            dep_notes+=("${CYAN}!${dep_title}✔${RESET}")
          fi
        fi
      done < <(echo "$v_info" | jq -r '.dependencies[]? | "\(.project_id)\t\(.dependency_type)"')

      dep_str="loaders:[${loaders_list}]"
      if [[ "${#dep_notes[@]}" -gt 0 ]]; then
        dep_str="${dep_str} $(IFS=' '; echo "${dep_notes[*]}")"
      fi

      printf "%-28s  %-18s  %b  %-20s  %b\n" "$name" "$version" "$compat" "$latest_ver" "$dep_str"
    fi
  done < "$MANIFEST"

  echo ""
  if [[ "$issues" -eq 0 ]]; then
    echo -e "${GREEN}${BOLD}✔ Dependency & compatibility resolution passed with 0 conflicts for Minecraft ${TARGET_MC}.${RESET}"
  else
    echo -e "${YELLOW}${BOLD}⚠ Resolution found ${issues} compatibility/dependency issue(s) for Minecraft ${TARGET_MC}.${RESET}"
    exit 1
  fi
  exit 0
fi

# ==============================================================================
# MODE: --inspect-deps (Offline Binary .jar Manifest Inspector via 7z)
# ==============================================================================
if [[ "$MODE" == "inspect-deps" ]]; then
  if ! command -v 7z >/dev/null 2>&1; then
    echo -e "${RED}Error: '--inspect-deps' requires '7z' to read embedded plugin.yml and mods.toml files.${RESET}" >&2
    exit 1
  fi

  echo -e "${BLUE}${BOLD}==> Inspecting Embedded .jar Dependency Manifests (plugin.yml & META-INF/mods.toml)${RESET}\n"

  declare -A installed_identifiers=()
  declare -A hard_deps_map=()

  # First pass: collect all installed plugin names, modIds, and 'provides' aliases
  while IFS=$'\t' read -r category filepath name version sha256 url purpose; do
    [[ -z "$category" || "$category" =~ ^# ]] && continue
    [[ "$filepath" != *.jar || "$filepath" == client/forge-* || "$filepath" == server/paper-* ]] && continue
    target_path="${SCRIPT_DIR}/${filepath}"
    [[ ! -f "$target_path" ]] && continue

    if [[ "$category" == "plugins" ]]; then
      pyml="$(7z x -so "$target_path" plugin.yml paper-plugin.yml 2>/dev/null || true)"
      pname="$(echo "$pyml" | awk -F': *' '/^name:/ {gsub(/["\047\r]/, "", $2); print $2; exit}')"
      [[ -n "$pname" ]] && installed_identifiers["$pname"]="$filepath"
      # Extract provides: [ WorldEdit ]
      provides_raw="$(echo "$pyml" | awk -F': *' '/^provides:/ {gsub(/[\[\]"\047\r]/, "", $2); print $2; exit}')"
      for prov in ${provides_raw//,/ }; do
        [[ -n "$prov" ]] && installed_identifiers["$prov"]="$filepath (via provides)"
      done
    elif [[ "$category" == "client" ]]; then
      mtoml="$(7z x -so "$target_path" META-INF/mods.toml 2>/dev/null || true)"
      for mid in $(echo "$mtoml" | awk -F'=' '/^[[:space:]]*modId[[:space:]]*=/ {gsub(/[ "\047\r]/, "", $2); print $2}'); do
        [[ -n "$mid" ]] && installed_identifiers["$mid"]="$filepath"
      done
      provides_mod="$(echo "$mtoml" | awk -F'=' '/^[[:space:]]*provides[[:space:]]*=/ {gsub(/[\[\] "\047\r]/, "", $2); print $2; exit}')"
      for prov in ${provides_mod//,/ }; do
        [[ -n "$prov" ]] && installed_identifiers["$prov"]="$filepath (via provides)"
      done
      # Also register bundled Jar-in-Jar artifacts from META-INF/jarjar/metadata.json
      jarjar="$(7z x -so "$target_path" META-INF/jarjar/metadata.json 2>/dev/null || true)"
      if [[ -n "$jarjar" ]] && command -v jq >/dev/null 2>&1; then
        for art in $(echo "$jarjar" | jq -r '.jars[]?.identifier.artifact // empty' 2>/dev/null); do
          norm_art="$(echo "$art" | sed 's/-forge$//; s/-//g')"
          [[ -n "$norm_art" ]] && installed_identifiers["$norm_art"]="$filepath (bundled JarJar)"
        done
      fi
    fi
  done < "$MANIFEST"
  installed_identifiers["minecraft"]="1.20.1"
  installed_identifiers["forge"]="47.4.10"

  printf "${BOLD}%-38s  %-10s  %-28s  %-26s  %s${RESET}\n" \
    "JAR FILE" "API / MC" "PROVIDES / ID" "HARD DEPENDS (REQUIRED)" "SOFT DEPENDS / ORDERING"
  printf "%s\n" "--------------------------------------------------------------------------------------------------------------------------------------------"

  missing_deps=0
  while IFS=$'\t' read -r category filepath name version sha256 url purpose; do
    [[ -z "$category" || "$category" =~ ^# ]] && continue
    [[ "$filepath" != *.jar || "$filepath" == client/forge-* || "$filepath" == server/paper-* ]] && continue
    target_path="${SCRIPT_DIR}/${filepath}"
    if [[ ! -f "$target_path" ]]; then
      printf "%-38s  ${RED}MISSING LOCAL JAR (run ./download.sh first)${RESET}\n" "$filepath"
      missing_deps=$((missing_deps + 1))
      continue
    fi

    if [[ "$category" == "plugins" ]]; then
      pyml="$(7z x -so "$target_path" plugin.yml paper-plugin.yml 2>/dev/null || true)"
      pname="$(echo "$pyml" | awk -F': *' '/^name:/ {gsub(/["\047\r]/, "", $2); print $2; exit}')"
      apiver="$(echo "$pyml" | awk -F': *' '/^api-version:/ {gsub(/["\047\r]/, "", $2); print $2; exit}')"
      provides_raw="$(echo "$pyml" | awk -F': *' '/^provides:/ {gsub(/[\[\]"\047\r ]/, "", $2); print $2; exit}')"
      depend_raw="$(echo "$pyml" | awk -F': *' '/^depend:/ {gsub(/[\[\]"\047\r ]/, "", $2); print $2; exit}')"
      soft_raw="$(echo "$pyml" | awk -F': *' '/^softdepend:/ {gsub(/[\[\]"\047\r ]/, "", $2); print $2; exit}')"

      id_disp="$pname"
      [[ -n "$provides_raw" ]] && id_disp="${pname} (+${provides_raw})"

      hard_disp="-"
      if [[ -n "$depend_raw" ]]; then
        hard_parts=()
        for d in ${depend_raw//,/ }; do
          if [[ -n "${installed_identifiers[$d]:-}" ]]; then
            hard_parts+=("${GREEN}${d}✔${RESET}")
          else
            hard_parts+=("${RED}${d}✘${RESET}")
            missing_deps=$((missing_deps + 1))
          fi
        done
        hard_disp="$(IFS=,; echo "${hard_parts[*]}")"
      fi

      printf "%-38s  %-10s  %-28s  %-35b  %s\n" \
        "$(basename "$filepath")" "${apiver:-legacy}" "$id_disp" "$hard_disp" "${soft_raw:--}"

    elif [[ "$category" == "client" ]]; then
      mtoml="$(7z x -so "$target_path" META-INF/mods.toml 2>/dev/null || true)"
      all_mids="$(echo "$mtoml" | awk '/^\[\[mods\]\]/{in_m=1;next} /^\[\[dependencies/{in_m=0} in_m && /^[[:space:]]*modId[[:space:]]*=/{gsub(/.*=[[:space:]]*|["\047\r ]/, ""); print}' | paste -sd, -)"
      mid="${all_mids%%,*}"
      extra_mids=""
      [[ "$all_mids" == *,* ]] && extra_mids="${all_mids#*,}"
      provides_mod="$(echo "$mtoml" | awk -F'=' '/^[[:space:]]*provides[[:space:]]*=/ {gsub(/[\[\] "\047\r]/, "", $2); print $2; exit}')"

      id_disp="$mid"
      [[ -n "$extra_mids" ]] && id_disp="${id_disp} (+${extra_mids})"
      [[ -n "$provides_mod" ]] && id_disp="${id_disp} (+${provides_mod})"

      # Parse [[dependencies]] blocks into mandatory vs optional
      hard_parts=()
      soft_parts=()
      while IFS='|' read -r d_id d_mand d_range; do
        [[ -z "$d_id" ]] && continue
        if [[ "$d_range" == *NOT-COMPATIBLE* ]]; then
          soft_parts+=("!${d_id}")
        elif [[ "$d_mand" == "true" ]]; then
          if [[ -n "${installed_identifiers[$d_id]:-}" ]]; then
            hard_parts+=("${GREEN}${d_id}✔${RESET}")
          else
            hard_parts+=("${RED}${d_id}✘${RESET}")
            missing_deps=$((missing_deps + 1))
          fi
        else
          if [[ -n "${installed_identifiers[$d_id]:-}" ]]; then
            soft_parts+=("${d_id}✔")
          else
            soft_parts+=("${d_id}")
          fi
        fi
      done < <(echo "$mtoml" | awk '
        /^\[\[dependencies/ { if (id != "") print id "|" mand "|" rng; id=""; mand="false"; rng=""; in_d=1; next }
        /^\[/ && !/^\[\[dependencies/ { if (id != "") print id "|" mand "|" rng; id=""; in_d=0 }
        in_d && /^[[:space:]]*modId[[:space:]]*=/ { s=$0; sub(/.*=[[:space:]]*/, "", s); gsub(/["\047\r ]/, "", s); id=s }
        in_d && /^[[:space:]]*mandatory[[:space:]]*=/ { s=$0; sub(/.*=[[:space:]]*/, "", s); gsub(/["\047\r #].*/, "", s); mand=s }
        in_d && /^[[:space:]]*versionRange[[:space:]]*=/ { s=$0; sub(/.*=[[:space:]]*/, "", s); gsub(/["\047\r ]/, "", s); rng=s }
        END { if (id != "") print id "|" mand "|" rng }
      ')

      hard_disp="-"
      [[ "${#hard_parts[@]}" -gt 0 ]] && hard_disp="$(IFS=,; echo "${hard_parts[*]}")"
      soft_disp="-"
      [[ "${#soft_parts[@]}" -gt 0 ]] && soft_disp="$(IFS=,; echo "${soft_parts[*]}")"

      printf "%-38s  %-10s  %-28s  %-35b  %s\n" \
        "$(basename "$filepath")" "1.20.1" "$id_disp" "$hard_disp" "$soft_disp"
    fi
  done < "$MANIFEST"

  echo ""
  if [[ "$missing_deps" -eq 0 ]]; then
    echo -e "${GREEN}${BOLD}✔ All embedded .jar hard dependencies (depend / provides) are satisfied.${RESET}"
  else
    echo -e "${RED}${BOLD}✘ Found ${missing_deps} missing jar(s) or unsatisfied hard dependencies.${RESET}"
    exit 1
  fi
  exit 0
fi

# ==============================================================================
# MODE: --bundle
# ==============================================================================
if [[ "$MODE" == "bundle" ]]; then
  BUNDLE_NAME="tundra-mc1.20.1-binaries.tar.gz"
  SUMS_FILE="SHA256SUMS"
  echo -e "${BLUE}${BOLD}==> Auditing files before creating release bundle...${RESET}"
  "$0" --verify
  build_mrpack
  echo -e "\n${BLUE}${BOLD}==> Generating ${SUMS_FILE} and ${BUNDLE_NAME}...${RESET}"
  (
    cd "$SCRIPT_DIR"
    files=()
    while IFS=$'\t' read -r category filepath name version sha256 url purpose; do
      [[ -z "$category" || "$category" =~ ^# ]] && continue
      files+=("$filepath")
    done < "$MANIFEST"
    [[ -f "client/Tundra-Client-1.20.1.mrpack" ]] && files+=("client/Tundra-Client-1.20.1.mrpack")
    sha256sum "${files[@]}" > "$SUMS_FILE"
    tar -czf "$BUNDLE_NAME" "$SUMS_FILE" "${files[@]}"
  )
  echo -e "${GREEN}✔ Created ${BUNDLE_NAME} and ${SUMS_FILE}${RESET}"
  echo -e "  Upload to GitHub Releases with: ${BOLD}gh release create v2.0.0 ${BUNDLE_NAME} ${SUMS_FILE} server/* client/* plugins/*${RESET}"
  exit 0
fi

# ==============================================================================
# MODE: --list | --verify | download (default)
# ==============================================================================
pass_count=0
fail_count=0
download_count=0

if [[ "$MODE" == "list" ]]; then
  printf "${BOLD}%-8s  %-30s  %-18s  %-10s  %s${RESET}\n" "CAT" "PACKAGE" "VERSION" "STATUS" "PURPOSE"
  printf "%s\n" "--------------------------------------------------------------------------------------------------------------------------"
fi

while IFS=$'\t' read -r category filepath name version sha256 url purpose; do
  [[ -z "$category" || "$category" =~ ^# ]] && continue
  if [[ "$FILTER" != "all" && "$category" != "$FILTER" ]]; then
    continue
  fi

  target_path="${SCRIPT_DIR}/${filepath}"
  filename="$(basename "$filepath")"

  if [[ "$MODE" == "list" ]]; then
    status="${RED}MISSING${RESET}"
    if [[ -f "$target_path" ]]; then
      actual_sha="$(compute_sha256 "$target_path")"
      if [[ "$actual_sha" == "$sha256" ]]; then
        status="${GREEN}OK${RESET}     "
      else
        status="${YELLOW}MISMATCH${RESET}"
      fi
    fi
    printf "%-8s  %-30s  %-18s  %b  %s\n" "$category" "$name" "$version" "$status" "$purpose"
    continue
  fi

  # Check existing file
  if [[ -f "$target_path" && "$FORCE" -eq 0 ]]; then
    actual_sha="$(compute_sha256 "$target_path")"
    if [[ "$actual_sha" == "$sha256" ]]; then
      echo -e "${GREEN}[OK]${RESET}       ${filepath} (${name} ${version})"
      pass_count=$((pass_count + 1))
      continue
    elif [[ "$MODE" == "verify" ]]; then
      echo -e "${RED}[MISMATCH]${RESET} ${filepath} (expected ${sha256:0:12}..., got ${actual_sha:0:12}...)"
      fail_count=$((fail_count + 1))
      continue
    else
      echo -e "${YELLOW}[UPDATE]${RESET}   ${filepath} checksum mismatch; re-downloading..."
    fi
  elif [[ "$MODE" == "verify" ]]; then
    echo -e "${RED}[MISSING]${RESET}  ${filepath} (${name} ${version})"
    fail_count=$((fail_count + 1))
    continue
  fi

  # Download mode
  mkdir -p "$(dirname "$target_path")"
  tmp_path="${target_path}.part"
  rm -f "$tmp_path"
  expected_sha="$sha256"
  downloaded=0

  # 1. Try explicit GitHub Release mirror first if configured
  if [[ -n "$RELEASE_BASE_URL" ]]; then
    echo -e "${BLUE}[FETCH]${RESET}    ${filepath} <- ${RELEASE_BASE_URL}/${filename}"
    if fetch_url "${RELEASE_BASE_URL}/${filename}" "$tmp_path"; then
      downloaded=1
    fi
  fi

  # 2. Otherwise use upstream source URL from manifest
  if [[ "$downloaded" -eq 0 ]]; then
    echo -e "${BLUE}[FETCH]${RESET}    ${filepath} <- ${url}"
    if fetch_url "$url" "$tmp_path"; then
      downloaded=1
    fi
  fi

  if [[ "$downloaded" -eq 0 || ! -f "$tmp_path" ]]; then
    echo -e "${RED}[FAIL]${RESET}     Failed to download ${filepath}"
    rm -f "$tmp_path"
    fail_count=$((fail_count + 1))
    continue
  fi

  actual_sha="$(compute_sha256 "$tmp_path")"
  if [[ "$actual_sha" != "$expected_sha" ]]; then
    echo -e "${RED}[HASH ERR]${RESET} ${filepath}: expected ${expected_sha}, got ${actual_sha}"
    rm -f "$tmp_path"
    fail_count=$((fail_count + 1))
    continue
  fi

  mv "$tmp_path" "$target_path"
  echo -e "${GREEN}[DOWNLOADED]${RESET} ${filepath} (SHA256 verified: ${actual_sha:0:12}...)"
  download_count=$((download_count + 1))
  pass_count=$((pass_count + 1))

done < "$MANIFEST"

if [[ "$MODE" == "download" && ( "$FILTER" == "all" || "$FILTER" == "client" ) ]]; then
  build_mrpack
fi

if [[ "$MODE" != "list" ]]; then
  echo -e "\n${BOLD}Summary:${RESET} ${GREEN}${pass_count} verified${RESET} (${download_count} newly downloaded), ${RED}${fail_count} failed/missing${RESET}."
  [[ "$fail_count" -eq 0 ]] || exit 1
fi
