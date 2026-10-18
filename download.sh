#!/usr/bin/env bash
# ==============================================================================
# Tundra Package Manager & Downloader (Minecraft 1.20.1)
# Reads declarative package metadata from packages.tsv, downloads missing files,
# verifies SHA256 checksums, and optionally creates a GitHub Release bundle.
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANIFEST="${SCRIPT_DIR}/packages.tsv"
DEFAULT_RELEASE_URL="https://github.com/SpanishSyntax/Tundra/releases/download/v1.0.0"

MODE="download"         # download | verify | list | bundle
FILTER="all"            # all | client | plugins
FORCE=0                 # 1 = re-download even if checksum matches
ALLOW_FALLBACK=0        # 1 = allow Modrinth 5.4.145 fallback for purged LuckPerms CI build
RELEASE_BASE_URL="${TUNDRA_RELEASE_URL:-}" # Optional GitHub release asset base URL

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
RESET='\033[0m'

usage() {
  cat <<EOF
${BOLD}Tundra Package Manager (MC 1.20.1)${RESET}

Usage: ./download.sh [OPTIONS]

Modes:
  (default)              Download missing packages and verify SHA256 checksums
  --verify               Verify SHA256 checksums of existing local files without downloading
  --list                 List all declared packages, versions, install status, and purpose
  --bundle               Create 'tundra-mc1.20.1-binaries.tar.gz' + 'SHA256SUMS' for GitHub Releases

Filters & Options:
  --client               Only process client packages (client/)
  --plugins              Only process server plugins (plugins/)
  --force                Re-download files even if they already exist and pass SHA256 check
  --from-release         Prefer fetching all packages directly from the Tundra v1.0.0 GitHub Release
  --release-url <URL>    Fetch files from a custom GitHub Release base URL first
                         (default mirror: ${DEFAULT_RELEASE_URL})
  --allow-fallback       If a purged CI build (e.g. LuckPerms 5.4.120) is unavailable,
                         download the closest archived Modrinth 5.4.x release (5.4.145)
  -h, --help             Show this help message
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --verify)         MODE="verify"; shift ;;
    --list)           MODE="list"; shift ;;
    --bundle)         MODE="bundle"; shift ;;
    --client)         FILTER="client"; shift ;;
    --plugins)        FILTER="plugins"; shift ;;
    --force)          FORCE=1; shift ;;
    --from-release)   RELEASE_BASE_URL="$DEFAULT_RELEASE_URL"; shift ;;
    --release-url)    RELEASE_BASE_URL="${2%/}"; shift 2 ;;
    --allow-fallback) ALLOW_FALLBACK=1; shift ;;
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
    curl -fL --retry 3 --connect-timeout 15 -sS -o "$dest" "$url"
  elif [[ "$HTTP_CLIENT" == "wget" ]]; then
    wget -q --tries=3 --timeout=15 -O "$dest" "$url"
  else
    echo -e "${RED}Error: Neither 'curl' nor 'wget' is installed.${RESET}" >&2
    return 1
  fi
}

fetch_optifine() {
  local filename="$1"
  local dest="$2"
  local cookie_file="${dest}.cookies.tmp"
  local adload_url="https://optifine.net/adloadx?f=${filename}"

  if [[ "$HTTP_CLIENT" != "curl" ]]; then
    echo -e "${RED}Error: Automated OptiFine token scraping requires 'curl'.${RESET}" >&2
    return 1
  fi

  local token_path
  token_path="$(curl -sS -L -c "$cookie_file" "$adload_url" \
    | grep -oE "downloadx\?f=${filename//./\\.}&x=[a-f0-9]+" \
    | head -n 1 || true)"

  if [[ -z "$token_path" ]]; then
    rm -f "$cookie_file"
    echo -e "${RED}Error: Could not extract session token from ${adload_url}${RESET}" >&2
    return 1
  fi

  curl -fL --retry 3 -sS -b "$cookie_file" -H "Referer: ${adload_url}" \
    -o "$dest" "https://optifine.net/${token_path}"
  rm -f "$cookie_file"
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

if [[ "$MODE" == "bundle" ]]; then
  BUNDLE_NAME="tundra-mc1.20.1-binaries.tar.gz"
  SUMS_FILE="SHA256SUMS"
  echo -e "${BLUE}${BOLD}==> Auditing files before creating release bundle...${RESET}"
  "$0" --verify
  echo -e "\n${BLUE}${BOLD}==> Generating ${SUMS_FILE} and ${BUNDLE_NAME}...${RESET}"
  (
    cd "$SCRIPT_DIR"
    files=()
    while IFS=$'\t' read -r category filepath name version sha256 url purpose; do
      [[ -z "$category" || "$category" =~ ^# ]] && continue
      files+=("$filepath")
    done < "$MANIFEST"
    sha256sum "${files[@]}" > "$SUMS_FILE"
    tar -czf "$BUNDLE_NAME" "$SUMS_FILE" "${files[@]}"
  )
  echo -e "${GREEN}✔ Created ${BUNDLE_NAME} and ${SUMS_FILE}${RESET}"
  echo -e "  Upload to GitHub Releases with: ${BOLD}gh release create v1.0.0 ${BUNDLE_NAME} ${SUMS_FILE} client/* plugins/*${RESET}"
  exit 0
fi

pass_count=0
fail_count=0
download_count=0

if [[ "$MODE" == "list" ]]; then
  printf "${BOLD}%-8s  %-30s  %-16s  %-10s  %s${RESET}\n" "CAT" "PACKAGE" "VERSION" "STATUS" "PURPOSE"
  printf "%s\n" "------------------------------------------------------------------------------------------------------------------------"
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
    printf "%-8s  %-30s  %-16s  %b  %s\n" "$category" "$name" "$version" "$status" "$purpose"
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
    if [[ "$url" == optifine://* ]]; then
      of_file="${url#optifine://}"
      echo -e "${BLUE}[FETCH]${RESET}    ${filepath} <- optifine.net (${of_file})"
      if fetch_optifine "$of_file" "$tmp_path"; then
        downloaded=1
      elif fetch_url "${DEFAULT_RELEASE_URL}/${filename}" "$tmp_path"; then
        downloaded=1
      fi
    elif [[ "$url" == luckperms-ci://* ]]; then
      # Format: luckperms-ci://<ver>|<fallback_url>|<fallback_sha256>
      IFS='|' read -r lp_primary fallback_url fallback_sha <<< "$url"
      echo -e "${BLUE}[FETCH]${RESET}    ${filepath} <- ${DEFAULT_RELEASE_URL}/${filename} (Tundra release mirror)"
      if fetch_url "${DEFAULT_RELEASE_URL}/${filename}" "$tmp_path" 2>/dev/null; then
        downloaded=1
      elif [[ "$ALLOW_FALLBACK" -eq 1 && -n "$fallback_url" ]]; then
        echo -e "${YELLOW}[FALLBACK]${RESET} Fetching archived Modrinth 5.4.145 build..."
        target_path="${SCRIPT_DIR}/plugins/$(basename "$fallback_url")"
        tmp_path="${target_path}.part"
        expected_sha="$fallback_sha"
        if fetch_url "$fallback_url" "$tmp_path"; then
          downloaded=1
        fi
      else
        echo -e "${YELLOW}[WARN]${RESET}     ${filepath}: Jenkins CI build 5.4.120 was purged upstream by LuckPerms."
        echo -e "           Pass '--allow-fallback' for Modrinth 5.4.145 or check ${DEFAULT_RELEASE_URL}"
        fail_count=$((fail_count + 1))
        continue
      fi
    else
      echo -e "${BLUE}[FETCH]${RESET}    ${filepath} <- ${url}"
      if fetch_url "$url" "$tmp_path"; then
        downloaded=1
      fi
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

if [[ "$MODE" != "list" ]]; then
  echo -e "\n${BOLD}Summary:${RESET} ${GREEN}${pass_count} verified${RESET} (${download_count} newly downloaded), ${RED}${fail_count} failed/missing${RESET}."
  [[ "$fail_count" -eq 0 ]] || exit 1
fi
