"""
sc131_tools.py - RomWBW SC131 SD Card Tools
Requires: Python 3.x  (no extra packages)
Usage:    python sc131_tools.py
"""

import os
import sys
import subprocess
import glob
import argparse
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────
SCRIPT_DIR   = Path(__file__).parent.resolve()   # …/SC131_SD_Image_Tools/
EXTRACT_ROOT = SCRIPT_DIR / "extracted"   # SD card images extracted from physical cards
BUILD_ROOT   = SCRIPT_DIR / "build"        # images assembled by the ROM upgrade builder
ROMWBW_ROOT  = SCRIPT_DIR / "romwbw"       # files browsed/extracted from RomWBW package images
DISKDEFS     = SCRIPT_DIR / "diskdefs"


def _find_romwbw_package() -> Path:
    """
    Search for a RomWBW package directory.
    Looks in:
      1. Sibling dirs of SC131_SD_Image_Tools that contain Binary/ and Tools/cpmtools/
      2. SC131_SD_Image_Tools itself (if someone drops the package inside)
    Returns the newest-named match (so RomWBW-v3.6 beats v3.5).
    Raises SystemExit with a helpful message if none found.
    """
    candidates = []
    search_roots = [SCRIPT_DIR.parent, SCRIPT_DIR]
    for root in search_roots:
        for d in sorted(root.iterdir(), reverse=True):
            if d.is_dir():
                if (d / "Binary" / "hd1k_combo.img").exists() and \
                   (d / "Tools" / "cpmtools" / "cpmls.exe").exists():
                    candidates.append(d)
    if not candidates:
        print("\n  ERROR: No RomWBW package found.")
        print("  Expected a folder containing Binary/ and Tools/cpmtools/ to be")
        print(f"  located next to:  {SCRIPT_DIR}")
        print("\n  To fix: place the RomWBW-vX.X.X-Package folder alongside")
        print("  SC131_SD_Image_Tools\\  and re-run.")
        input("\n  Press Enter to exit...")
        sys.exit(1)
    return candidates[0]   # highest-sorted name = newest version


PACKAGE_DIR  = _find_romwbw_package()
CPMTOOLS_DIR = PACKAGE_DIR / "Tools" / "cpmtools"
CPMLS        = CPMTOOLS_DIR / "cpmls.exe"
CPMCP        = CPMTOOLS_DIR / "cpmcp.exe"

# ── Disk geometry ──────────────────────────────────────────────────────────────
FORMATS = {
    "hd1k": {
        "seclen": 512, "tracks": 1024, "sectrk": 16,
        "blocksize": 4096, "maxdir": 1024, "boottrk": 2,
        "slice_tracks": 1024, "prefix_tracks": 128,
    },
    "hd512": {
        "seclen": 512, "tracks": 1040, "sectrk": 16,
        "blocksize": 4096, "maxdir": 512,  "boottrk": 16,
        "slice_tracks": 1040, "prefix_tracks": 0,
    },
}

# ═══════════════════════════════════════════════════════════════════════════════
#  CP/M IMAGE BROWSER
# ═══════════════════════════════════════════════════════════════════════════════

def write_diskdef(fmt: str, slice_num: int):
    g = FORMATS[fmt]
    offset = g["prefix_tracks"] + g["slice_tracks"] * slice_num
    DISKDEFS.write_text(
        f"diskdef wbw_browse_slice\n"
        f"  seclen {g['seclen']}\n"
        f"  tracks {g['tracks']}\n"
        f"  sectrk {g['sectrk']}\n"
        f"  blocksize {g['blocksize']}\n"
        f"  maxdir {g['maxdir']}\n"
        f"  skew 0\n"
        f"  boottrk {g['boottrk']}\n"
        f"  offset {offset}T\n"
        f"  os 2.2\n"
        f"end\n"
    )

def cpm_env():
    e = os.environ.copy()
    e["CPMTOOLSFMT"] = str(DISKDEFS.resolve())
    return e

def cpm_cwd():
    """cpmtools finds 'diskdefs' by looking in cwd — so always run it from DISKDEFS.parent."""
    return str(DISKDEFS.parent)

def run_cpmls(img: str, fmt: str, slice_num: int) -> tuple[bool, list[str]]:
    write_diskdef(fmt, slice_num)
    try:
        r = subprocess.run([str(CPMLS), "-f", "wbw_browse_slice", img],
                           capture_output=True, env=cpm_env(), cwd=cpm_cwd())
        if r.returncode != 0:
            return False, []
        lines = [l.strip() for l in r.stdout.decode("cp437", errors="replace").splitlines() if l.strip()]
        return True, lines
    except Exception:
        return False, []

def run_cpmcp(img: str, fmt: str, slice_num: int, pattern: str, dest: str):
    """Extract files into per-user subdirs: dest/user0/, dest/user1/, ..."""
    write_diskdef(fmt, slice_num)
    dest_path = Path(dest)
    for user in range(16):
        user_dir = dest_path / f"user{user}"
        user_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run([str(CPMCP), "-f", "wbw_browse_slice", img, f"{user}:{pattern}", str(user_dir)],
                       capture_output=True, env=cpm_env(), cwd=cpm_cwd())
        # Remove the subdir if nothing was extracted into it
        if not any(user_dir.iterdir()):
            user_dir.rmdir()

def file_lines(lines: list[str]) -> list[str]:
    return [l for l in lines if "." in l and not l.endswith(":")]

def max_slices(img: str, fmt: str) -> int:
    g = FORMATS[fmt]
    slice_bytes  = g["seclen"] * g["sectrk"] * g["slice_tracks"]
    prefix_bytes = g["seclen"] * g["sectrk"] * g["prefix_tracks"]
    usable = max(0, Path(img).stat().st_size - prefix_bytes)
    return min(int(usable / slice_bytes), 31)

def detect_format(img: str) -> str | None:
    for fmt in ("hd1k", "hd512"):
        ok, lines = run_cpmls(img, fmt, 0)
        if ok and any(".com" in l or ".sys" in l for l in lines):
            return fmt
    return None

# Ordered signatures — ALL labels that match are shown (not first-match-wins).
# Each entry: (label, required_all, any_of_one)
# required_all = every stem must be present; any_of = at least one (empty = skip)
# Stems derived from 8.3 filenames: "PIP     .COM" -> stem "pip"
# Aligned with RomWBW Disk Catalog v3.5 and verified against actual binary images.
_SLICE_SIGS = [
    # ── Operating Systems ────────────────────────────────────────────────────
    # CP/M 2.2: CPM.SYS (stem=cpm) is DRI boot image; DDT.COM only in v2.2 set
    ("CP/M 2.2",     {"cpm", "ddt"},                set()),
    # ZSDOS 1.1: ZSYS.SYS replaces CPM.SYS; DATSWEEP.COM is highly distinctive
    ("ZSDOS 1.1",    {"zsys"},                       set()),
    # NZCOM (ZCPR 3.4): loaded over ZSDOS; NZCOM.COM unique
    ("NZCOM",         {"nzcom"},                      set()),
    # CP/M 3 (CP/M Plus): CPMLDR.COM is the DRI boot loader, unique to CP/M 3
    ("CP/M 3",       {"cpmldr"},                     set()),
    # ZPM3: uses ZPMLDR.COM; ZCCP.COM and MAKEDOS.COM also unique to ZPM3
    ("ZPM3",         set(),                          {"zpmldr", "zccp", "makedos"}),
    # Z3PLUS: Z-System for CP/M 3; Z3PLUS.COM unique
    ("Z3PLUS",        {"z3plus"},                     set()),
    # QPM 2.7: QINSTALL.COM unique to QPM
    ("QPM 2.7",      {"qinstall"},                   set()),

    # ── Application Disks ────────────────────────────────────────────────────
    # WordStar 4: WINSTALL.COM, MAINDICT.CMP, WSHELP.OVR
    ("WordStar 4",   set(),                          {"winstall", "maindict", "wshelp"}),
    # Games: Infocom Zork series, Dungeon Master (Rogue-like), Nemesis
    ("Games",        set(),                          {"zork1", "zork2", "dungeon", "nemesis"}),
    # Turbo Pascal 3.0: TINST.COM (installer) unique
    ("Turbo Pascal", {"tinst"},                      set()),
    # SLR Z80ASM suite: Z80ASM.COM + SLR180.COM + SLRMAC.COM + SLRNK.COM
    ("Z80ASM",       set(),                          {"z80asm", "slr180", "slrmac", "slrnk"}),
    # Microsoft Fortran-80: F80.COM compiler unique
    ("Fortran-80",   {"f80"},                        set()),
    # Microsoft BASCOM: BASCOM.COM unique
    ("BASCOM",       {"bascom"},                     set()),
    # HiTech C v3.09: CGEN.COM (code generator) uniquely identifies HiTech
    ("HiTech C",     {"cgen"},                       set()),
    # Aztec C 1.06: CZ.COM (Z80 codegen), LIBASRC.COM, ARCV.COM
    ("Aztec C",      set(),                          {"cz", "libasrc", "arcv"}),
    # Cowgol 2.0: COWFE.COM + COWBE.COM + COWLINK.COM
    ("Cowgol",       set(),                          {"cowfe", "cowbe", "cowlink"}),
    # MSX ROMs: ROMLIST.TXT always present
    ("MSX ROMs",     {"romlist"},                    set()),

    # ── Common Content (most full OS slices include all four) ─────────────────
    # CP/NET 1.2 or 3: LBR archives in user area 4
    ("+ CP/NET",     set(),                          {"cpn12mt", "cpn12ser", "cpn12duo",
                                                      "cpn3mt",  "cpn3ser",  "cpn3duo"}),
    # Sample audio (user area 3): PT3/MYM/VGM tracker files
    ("+ Audio",      set(),                          {"badmice", "sanxion", "attack"}),
    # Hardware testing utilities (user area 2)
    ("+ Testing",    set(),                          {"zexall", "banktest", "ramtest"}),
    # SIMH simulator tools (user area 13)
    ("+ SIMH",       set(),                          {"rsetsimh", "hdir"}),
]


def describe_slice(lines: list[str]) -> str:
    """Return a short label for a slice based on files it contains."""
    stems = set()
    for l in lines:
        # cpmls can output "PIP     .COM" (space-padded 8.3) or compact "pip.com"
        # Strategy: also collapse-join adjacent tokens to catch "PIP" + ".COM"
        tokens = l.split()
        # compact form  e.g. "pip.com"
        for tok in tokens:
            if "." in tok:
                stems.add(tok.split(".")[0].strip().lower())
        # space-padded form: look for a bare word followed by ".EXT"
        for i, tok in enumerate(tokens):
            if i + 1 < len(tokens) and tokens[i+1].startswith("."):
                stems.add(tok.strip().lower())

    labels = []
    seen = set()
    for label, required, any_of in _SLICE_SIGS:
        if label in seen:
            continue
        req_ok  = required.issubset(stems) if required else True
        any_ok  = bool(any_of & stems)     if any_of  else True
        if req_ok and any_ok:
            labels.append(label)
            seen.add(label)
    return ", ".join(labels) if labels else "custom"


def pick_image() -> str:
    """Pick an SD card image from extracted/ backups or D:\ root (never from build/)."""
    # Search extracted/ folder recursively — SD card backups only; skip build/ output
    extracted_imgs = sorted(
        (p for p in EXTRACT_ROOT.rglob("*.img")
         if not p.is_relative_to(BUILD_ROOT)),
        key=lambda p: p.stat().st_mtime, reverse=True
    ) if EXTRACT_ROOT.exists() else []
    drive_imgs = sorted(
        [Path(p) for p in glob.glob("D:\\*.img")],
        key=lambda p: p.stat().st_mtime, reverse=True
    )[:8]

    all_imgs: list[Path] = []
    seen: set[Path] = set()
    for p in extracted_imgs + drive_imgs:
        rp = p.resolve()
        if rp not in seen:
            all_imgs.append(p)
            seen.add(rp)

    if all_imgs:
        print("\n  SD card images:")
        for idx, p in enumerate(all_imgs, 1):
            if p.is_relative_to(EXTRACT_ROOT):
                tag = f"  [SD backup \u25b8 {p.parent.name}]"
            else:
                tag = "  [D:\\ drive]"
            print(f"    [{idx}] {p}  ({p.stat().st_size/1e9:.2f} GB){tag}")

    default = str(all_imgs[0]) if all_imgs else ""
    inp = input(f"\n  Image path or number [Enter = {default or 'none'}]: ").strip()
    if inp.isdigit():
        idx = int(inp) - 1
        if 0 <= idx < len(all_imgs):
            return str(all_imgs[idx])
    return inp if inp else default


def pick_any_image() -> str:
    """Broader picker: SD backups (extracted/), built images (build/), and D:\\ root."""
    def collect(root: Path, tag: str) -> list[tuple[Path, str]]:
        if not root.exists():
            return []
        return [(p, tag) for p in sorted(root.rglob("*.img"),
                key=lambda p: p.stat().st_mtime, reverse=True)]

    groups = (
        collect(EXTRACT_ROOT, "SD backup")
        + collect(BUILD_ROOT,   "built image")
        + collect(ROMWBW_ROOT,  "RomWBW pkg")
        + [(Path(p), "D:\\ drive") for p in sorted(
              glob.glob("D:\\*.img"),
              key=lambda p: Path(p).stat().st_mtime, reverse=True)][:8]
    )

    seen: set[Path] = set()
    all_imgs: list[tuple[Path, str]] = []
    for p, tag in groups:
        rp = p.resolve()
        if rp not in seen:
            all_imgs.append((p, tag))
            seen.add(rp)

    if all_imgs:
        print("\n  Available images:")
        for idx, (p, tag) in enumerate(all_imgs, 1):
            print(f"    [{idx}] {p}  ({p.stat().st_size/1e9:.2f} GB)  [{tag}]")

    default = str(all_imgs[0][0]) if all_imgs else ""
    inp = input(f"\n  Image path or number [Enter = {default or 'none'}]: ").strip()
    if inp.isdigit():
        idx = int(inp) - 1
        if 0 <= idx < len(all_imgs):
            return str(all_imgs[idx][0])
    return inp if inp else default


def pick_package_image() -> str:
    """List .img files from PACKAGE_DIR/Binary/ and let the user pick one."""
    binary_dir = PACKAGE_DIR / "Binary"
    imgs = sorted(binary_dir.glob("*.img"), key=lambda p: p.name)
    if not imgs:
        print(f"  ERROR: no .img files found in {binary_dir}")
        input("  Press Enter..."); return ""
    print(f"\n  RomWBW Package images  ({binary_dir})")
    for idx, p in enumerate(imgs, 1):
        size_mb = p.stat().st_size / 1_048_576
        print(f"    [{idx:2d}] {p.name:<42} {size_mb:6.1f} MB")
    inp = input("\n  Image number or path [Enter=cancel]: ").strip()
    if not inp:
        return ""
    if inp.isdigit():
        i = int(inp) - 1
        if 0 <= i < len(imgs):
            return str(imgs[i])
        print("  Invalid number."); return ""
    return inp


def browse_menu(img: str = "", out_root: Path = None):
    if out_root is None:
        out_root = EXTRACT_ROOT
    if not img:
        img = pick_image()
    if not img or not Path(img).exists():
        print(f"  ERROR: not found: {img}"); input("  Press Enter..."); return

    save_dir = out_root / Path(img).stem
    save_dir.mkdir(parents=True, exist_ok=True)

    print(f"  Detecting format...", end=" ", flush=True)
    fmt = detect_format(img)
    if fmt:
        print(fmt)
    else:
        fmt = input("could not detect. Enter (hd1k/hd512) [hd1k]: ").strip() or "hd1k"

    while True:
        print()
        print(f"  Image  : {img}")
        print(f"  Format : {fmt}    Save to: {save_dir}")
        print()
        print("  [S] Scan all slices    [L] List slice")
        print("  [X] Extract slice      [A] Extract ALL")
        print("  [F] Toggle format      [B] Back to main menu")
        print()
        choice = input("  Command: ").strip().upper()

        if choice == "S":
            n = max_slices(img, fmt)
            print(f"\n  Scanning slices 0-{n} [{fmt}]...\n")
            found = []
            for s in range(n + 1):
                ok, lines = run_cpmls(img, fmt, s)
                if ok:
                    files = file_lines(lines)
                    if files:
                        dest  = save_dir / f"slice{s}"
                        tag   = " [x]" if dest.exists() else ""
                        desc  = describe_slice(lines)
                        print(f"  Slice {s:2d} : {len(files):3d} files  {desc:<28}{tag}")
                        found.append(s)
            print(f"\n  {len(found)} populated slice(s): {', '.join(str(s) for s in found)}")

        elif choice == "L":
            s = input("  Slice number: ").strip()
            if s.isdigit():
                ok, lines = run_cpmls(img, fmt, int(s))
                if not ok or not file_lines(lines):
                    print("  (empty or unreadable)")
                else:
                    print()
                    for line in lines:
                        print(f"    {line}")

        elif choice == "X":
            s = input("  Slice number: ").strip()
            p = input("  Pattern (blank=all, e.g. *.com): ").strip() or "*.*"
            if s.isdigit():
                dest = save_dir / f"slice{int(s)}"
                dest.mkdir(parents=True, exist_ok=True)
                print(f"\n  Saving to {dest} ...")
                run_cpmcp(img, fmt, int(s), p, str(dest))
                user_dirs = sorted(d for d in dest.iterdir() if d.is_dir())
                total = 0
                for udir in user_dirs:
                    files = sorted(udir.iterdir())
                    print(f"    {udir.name}:")
                    for f in files:
                        print(f"      {f.name:<22} {f.stat().st_size/1024:.1f} KB")
                    total += len(files)
                print(f"  Total: {total} file(s) saved across {len(user_dirs)} user(s)")

        elif choice == "A":
            input(f"  Save ALL slices to {save_dir} — press Enter (Ctrl+C=cancel)...")
            n = max_slices(img, fmt)
            for s in range(n + 1):
                ok, lines = run_cpmls(img, fmt, s)
                if ok and file_lines(lines):
                    dest = save_dir / f"slice{s}"
                    dest.mkdir(parents=True, exist_ok=True)
                    run_cpmcp(img, fmt, s, "*.*", str(dest))
                    user_dirs = [d for d in dest.iterdir() if d.is_dir()]
                    count = sum(len(list(d.iterdir())) for d in user_dirs)
                    users = ", ".join(d.name for d in sorted(user_dirs))
                    print(f"  slice{s:<2} : {count:3d} files  ({users})  -> {dest}")
            print(f"\n  Done.")

        elif choice == "F":
            fmt = "hd512" if fmt == "hd1k" else "hd1k"
            print(f"  Switched to: {fmt}")

        elif choice == "B":
            break


def browse_romwbw_menu():
    img = pick_package_image()
    if img:
        browse_menu(img=img, out_root=ROMWBW_ROOT)

# ═══════════════════════════════════════════════════════════════════════════════
#  DISK IMAGER
# ═══════════════════════════════════════════════════════════════════════════════

def image_menu():
    print()
    # Show disks via PowerShell
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-Disk | Select-Object Number,FriendlyName,"
         "@{n='GB';e={[math]::Round($_.Size/1GB,1)}},BusType |"
         " Format-Table -AutoSize"],
        capture_output=True, text=True
    )
    print(result.stdout)

    disk_num = input("  Disk NUMBER to image (e.g. 3): ").strip()
    if not disk_num.isdigit():
        print("  Invalid."); input("  Press Enter..."); return

    disk_num = int(disk_num)

    # Get disk size
    size_result = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         f"(Get-Disk -Number {disk_num}).Size"],
        capture_output=True, text=True
    )
    try:
        total_size = int(size_result.stdout.strip())
    except ValueError:
        print("  Could not get disk size."); input("  Press Enter..."); return

    # Choose output location
    drives = []
    for letter in "DCEFGH":
        p = Path(f"{letter}:\\")
        try:
            free = os.stat(f"{letter}:\\").st_size if p.exists() else 0
            import shutil
            _, _, free = shutil.disk_usage(str(p))
            if free > total_size:
                drives.append((letter, free))
        except Exception:
            pass

    print(f"\n  Image size needed: {total_size/1e9:.2f} GB")
    print("  Drives with enough space:")
    for letter, free in drives:
        print(f"    {letter}:\\  ({free/1e9:.1f} GB free)")

    out_drive = input(f"\n  Save to drive [D]: ").strip().upper() or "D"
    from datetime import datetime
    stamp    = datetime.now().strftime("%Y%m%d_%H%M")
    out_file = Path(f"{out_drive}:\\Disk{disk_num}_backup_{stamp}.img")

    print(f"\n  Source : \\\\.\\PhysicalDrive{disk_num}")
    print(f"  Output : {out_file}")
    input("  Press Enter to start (run this as Administrator if it fails)...")

    BUF = 4 * 1024 * 1024
    written = 0
    try:
        with open(f"\\\\.\\PhysicalDrive{disk_num}", "rb") as src, \
             open(out_file, "wb") as dst:
            while written < total_size:
                chunk = src.read(min(BUF, total_size - written))
                if not chunk:
                    break
                dst.write(chunk)
                written += len(chunk)
                pct = written / total_size * 100
                mb  = written // (1024*1024)
                print(f"\r  {mb:6d} MB  {pct:5.1f}%", end="", flush=True)
        print(f"\n\n  Done! {out_file}  ({written/1e9:.2f} GB)")
    except PermissionError:
        print("\n\n  ERROR: Permission denied.")
        print("  Run SC131_Tools.cmd as Administrator (right-click > Run as administrator)")
    except Exception as e:
        print(f"\n\n  ERROR: {e}")

    input("\n  Press Enter to continue...")

# ═══════════════════════════════════════════════════════════════════════════════
#  IMAGE BUILDER
# ═══════════════════════════════════════════════════════════════════════════════

BIN_DIR    = PACKAGE_DIR / "Binary"
BUILD_TEMP = SCRIPT_DIR / "_build_temp.img"


def slice_size(fmt: str) -> int:
    g = FORMATS[fmt]
    return g["seclen"] * g["sectrk"] * g["slice_tracks"]


def prefix_size(fmt: str) -> int:
    g = FORMATS[fmt]
    return g["seclen"] * g["sectrk"] * g["prefix_tracks"]


def write_diskdef_at(fmt: str, offset_tracks: int):
    """Write diskdefs file with an explicit track offset (used for temp single-slice builds)."""
    g = FORMATS[fmt]
    DISKDEFS.write_text(
        f"diskdef wbw_browse_slice\n"
        f"  seclen {g['seclen']}\n"
        f"  tracks {g['tracks']}\n"
        f"  sectrk {g['sectrk']}\n"
        f"  blocksize {g['blocksize']}\n"
        f"  maxdir {g['maxdir']}\n"
        f"  skew 0\n"
        f"  boottrk {g['boottrk']}\n"
        f"  offset {offset_tracks}T\n"
        f"  os 2.2\n"
        f"end\n"
    )


def read_binary_slice(path: Path, fmt: str) -> bytes:
    """Read a standalone single-slice image (no prefix — offset 0)."""
    ss = slice_size(fmt)
    with open(path, "rb") as f:
        data = f.read(ss)
    return data.ljust(ss, b"\xe5")  # pad with CP/M 0xe5 (erased) if short


def read_combo_slice(combo: Path, fmt: str, slot: int) -> bytes:
    """Read one slice from a combo image (has a prefix block before slice 0)."""
    ss = slice_size(fmt)
    ps = prefix_size(fmt)
    with open(combo, "rb") as f:
        f.seek(ps + slot * ss)
        data = f.read(ss)
    return data.ljust(ss, b"\xe5")


def read_blank_slice(fmt: str) -> bytes:
    """Return a blank (erased) slice — use hd1k_blank.img if present, else zero-fill."""
    blank = BIN_DIR / f"{fmt}_blank.img"
    if blank.exists():
        return read_binary_slice(blank, fmt)
    return bytes([0xe5]) * slice_size(fmt)


def inject_files_into_slice(extracted_dir: Path, fmt: str) -> bytes:
    """
    Given a dir with user0/, user2/, ... subdirs (from run_cpmcp extraction),
    copy all files into a fresh blank slice and return the resulting bytes.
    cpmtools is told the image has no prefix (offset 0T).
    """
    data = read_blank_slice(fmt)
    BUILD_TEMP.write_bytes(data)

    # diskdef with offset 0 — standalone slice file, no prefix
    write_diskdef_at(fmt, 0)

    user_dirs = sorted(extracted_dir.iterdir()) if extracted_dir.exists() else []
    for udir in user_dirs:
        if not udir.is_dir() or not udir.name.startswith("user"):
            continue
        user_num = udir.name[4:]  # "user0" -> "0"
        for f in sorted(udir.iterdir()):
            if f.is_file():
                subprocess.run(
                    [str(CPMCP), "-f", "wbw_browse_slice",
                     str(BUILD_TEMP), str(f), f"{user_num}:{f.name}"],
                    capture_output=True, env=cpm_env(), cwd=cpm_cwd()
                )

    result = BUILD_TEMP.read_bytes()
    ss = slice_size(fmt)
    return result[:ss].ljust(ss, b"\xe5")


def list_binary_slices(fmt: str) -> list[tuple[str, Path]]:
    """Return (short_name, path) for each single-slice binary image (excludes combo/blank)."""
    skip = {f"{fmt}_combo.img", f"{fmt}_blank.img"}
    out = []
    for p in sorted(BIN_DIR.glob(f"{fmt}_*.img")):
        if p.name not in skip:
            out.append((p.stem.replace(f"{fmt}_", ""), p))
    return out


def list_extracted_dirs() -> list[Path]:
    if not EXTRACT_ROOT.exists():
        return []
    return sorted(d for d in EXTRACT_ROOT.iterdir() if d.is_dir())


# ─── Extra-file helpers ───────────────────────────────────────────────────────

def _extract_slice_to_dir(img: Path, fmt: str, slot_num: int, dest_dir: Path,
                          ps: int = -1, filter_files: "set | None" = None):
    """
    Extract files from one slice into dest_dir/userN/ subdirs.
    ps overrides prefix_size(fmt): pass ps=0 for single-slice images.
    filter_files: if set, only extract filenames in this set (any user area).
    """
    extra_tmp = SCRIPT_DIR / "_extra_slice.img"
    ss = slice_size(fmt)
    if ps < 0:
        ps = prefix_size(fmt)
    with open(img, "rb") as f:
        f.seek(ps + slot_num * ss)
        data = f.read(ss)
    extra_tmp.write_bytes(data.ljust(ss, b"\xe5"))
    write_diskdef_at(fmt, 0)
    for user_num in range(16):
        r = subprocess.run(
            [str(CPMLS), "-f", "wbw_browse_slice", str(extra_tmp), f"{user_num}:*.*"],
            capture_output=True, env=cpm_env(), cwd=cpm_cwd()
        )
        lines = [l.strip() for l in r.stdout.decode("cp437", errors="replace").splitlines() if l.strip()]
        files = file_lines(lines)
        if filter_files is not None:
            files = [f for f in files if f.upper() in filter_files]
        if not files:
            continue
        udir = dest_dir / f"user{user_num}"
        udir.mkdir(parents=True, exist_ok=True)
        for fname in files:
            subprocess.run(
                [str(CPMCP), "-f", "wbw_browse_slice",
                 str(extra_tmp), f"{user_num}:{fname}", str(udir / fname)],
                capture_output=True, env=cpm_env(), cwd=cpm_cwd()
            )
    if extra_tmp.exists():
        extra_tmp.unlink()


def _inject_dir_into_temp(src_dir: Path, fmt: str, target_user: "int | None" = None):
    """
    Copy files from a src_dir/userN/ structure into BUILD_TEMP (diskdef offset 0T already set).
    Falls back to treating loose files in src_dir as user 0.
    target_user: if set, all files are placed into that user area regardless of origin.
    """
    import shutil
    has_user_dirs = any(
        d.is_dir() and d.name.startswith("user") for d in src_dir.iterdir()
    ) if src_dir.exists() else False

    write_diskdef_at(fmt, 0)
    if has_user_dirs:
        for udir in sorted(src_dir.iterdir()):
            if not udir.is_dir() or not udir.name.startswith("user"):
                continue
            orig_user = udir.name[4:]
            dest_user = str(target_user) if target_user is not None else orig_user
            for f in sorted(udir.iterdir()):
                if f.is_file():
                    subprocess.run(
                        [str(CPMCP), "-f", "wbw_browse_slice",
                         str(BUILD_TEMP), str(f), f"{dest_user}:{f.name}"],
                        capture_output=True, env=cpm_env(), cwd=cpm_cwd()
                    )
    else:
        # flat folder — put everything in target_user (default 0)
        dest_user = str(target_user) if target_user is not None else "0"
        for f in sorted(src_dir.iterdir()):
            if f.is_file():
                subprocess.run(
                    [str(CPMCP), "-f", "wbw_browse_slice",
                     str(BUILD_TEMP), str(f), f"{dest_user}:{f.name}"],
                    capture_output=True, env=cpm_env(), cwd=cpm_cwd()
                )


def _apply_extras(base_bytes: bytes, extras: list, fmt: str) -> bytes:
    """
    Merge additional files on top of a base slice image.
    extras: list of dicts — each from _pick_extra_source().
    Returns updated slice bytes.
    """
    import shutil

    def _staged_count(stage_dir: Path) -> int:
        """Count host files staged under stage_dir (any depth)."""
        return sum(1 for p in stage_dir.rglob("*") if p.is_file())

    BUILD_TEMP.write_bytes(base_bytes)
    write_diskdef_at(fmt, 0)           # set once; _inject_dir_into_temp also sets it
    tmp_stage = SCRIPT_DIR / "_extra_stage"
    total_merged = 0

    for extra in extras:
        if tmp_stage.exists():
            shutil.rmtree(tmp_stage)
        tmp_stage.mkdir()

        label = extra.get("label", "?")

        if extra["type"] == "combo":
            src_fmt = extra.get("img_fmt", fmt)
            _extract_slice_to_dir(extra["path"], src_fmt, extra["slot"], tmp_stage,
                                  filter_files=extra.get("filter_files"))
        elif extra["type"] == "binary":
            bin_fmt = extra.get("img_fmt", fmt)
            _extract_slice_to_dir(extra["path"], bin_fmt, 0, tmp_stage, ps=0,
                                  filter_files=extra.get("filter_files"))
        elif extra["type"] in ("extracted", "folder"):
            # src_dir is already a staged tree — count directly, then inject
            src = extra["path"]
            src_count = sum(1 for p in src.rglob("*") if p.is_file()) if src.exists() else 0
            if src_count == 0:
                print(f"\n    ⚠ 0 files found in '{label}' — skipping", end="")
                continue
            tu = extra.get("target_user")
            _inject_dir_into_temp(src, fmt, target_user=tu)
            total_merged += src_count
            dest_desc = f"→ user {tu}" if tu is not None else "→ original user areas"
            print(f"\n    + {src_count} file(s) from '{label}' {dest_desc}", end="")
            continue

        n_staged = _staged_count(tmp_stage)
        if n_staged == 0:
            print(f"\n    ⚠ 0 files staged from '{label}' — skipping", end="")
            continue

        tu = extra.get("target_user")
        _inject_dir_into_temp(tmp_stage, fmt, target_user=tu)
        total_merged += n_staged
        dest_desc = f"→ user {tu}" if tu is not None else "→ original user areas"
        print(f"\n    + {n_staged} file(s) from '{label}' {dest_desc}", end="")

    if tmp_stage.exists():
        shutil.rmtree(tmp_stage)

    if total_merged == 0:
        print(f"\n    ⚠ no files were merged", end="  ")
    else:
        print(f"\n    ✓ {total_merged} file(s) merged total", end="  ")

    ss = slice_size(fmt)
    result = BUILD_TEMP.read_bytes()
    return result[:ss].ljust(ss, b"\xe5")


def _pick_extra_source(fmt: str, backup_img: str = "") -> "list[dict]":
    """
    Interactively choose one or more extra-files sources to merge into a slot.
    Returns a list of descriptor dicts (empty list = cancelled / nothing chosen).
    Image-based sources offer a multi-slice loop and per-slice file selection.
    """

    def _ask_file_selection(all_files: list, label: str) -> "set | None":
        """
        Show all_files numbered and ask ALL or SELECT.
        Returns None (all files) or a set of uppercased filenames to include.
        """
        print(f"    {len(all_files)} file(s) in {label}")
        ans = input("    Add [A]ll or [S]elect specific files? [A/S, Enter=All]: ").strip().upper()
        if ans != "S":
            return None
        for i, f in enumerate(all_files):
            print(f"      [{i + 1:3d}] {f}")
        raw = input("    File numbers (e.g. 1 3 5-10 12, or A for all): ").strip().upper()
        if not raw or raw == "A":
            return None
        selected = set()
        for token in raw.split():
            if "-" in token:
                parts = token.split("-", 1)
                if parts[0].isdigit() and parts[1].isdigit():
                    for n in range(int(parts[0]), int(parts[1]) + 1):
                        if 1 <= n <= len(all_files):
                            selected.add(all_files[n - 1].upper())
            elif token.isdigit():
                n = int(token)
                if 1 <= n <= len(all_files):
                    selected.add(all_files[n - 1].upper())
        if not selected:
            print("    No valid selection — adding all files.")
            return None
        print(f"    Selected {len(selected)} file(s).")
        return selected

    def _ask_user_target() -> "int | None":
        """
        Ask which CP/M user area to place the files into.
        Returns an int (0-15) or None (keep original user areas).
        """
        raw = input("    Destination user area [0-15, Enter = keep original]: ").strip()
        if not raw:
            return None
        if raw.isdigit() and 0 <= int(raw) <= 15:
            u = int(raw)
            print(f"    → Files will be placed in user {u}")
            return u
        print("    Invalid — keeping original user areas.")
        return None

    def _scan_all_files_from(img_path: Path, img_fmt: str, slot_num: int, ps: int = -1) -> list:
        """Return flat sorted list of all filenames in a given slice."""
        extra_tmp = SCRIPT_DIR / "_scan_tmp.img"
        ss = slice_size(img_fmt)
        _ps = prefix_size(img_fmt) if ps < 0 else ps
        with open(img_path, "rb") as f:
            f.seek(_ps + slot_num * ss)
            data = f.read(ss)
        extra_tmp.write_bytes(data.ljust(ss, b"\xe5"))
        write_diskdef_at(img_fmt, 0)
        all_files = []
        for user_num in range(16):
            r = subprocess.run(
                [str(CPMLS), "-f", "wbw_browse_slice", str(extra_tmp), f"{user_num}:*.*"],
                capture_output=True, env=cpm_env(), cwd=cpm_cwd()
            )
            lines = [l.strip() for l in r.stdout.decode("cp437", errors="replace").splitlines() if l.strip()]
            all_files.extend(file_lines(lines))
        if extra_tmp.exists():
            extra_tmp.unlink()
        return sorted(all_files)

    opt = 1
    choices = {}
    print("\n    ── Merge extra files from ───────────────────────────────")
    if backup_img:
        print(f"    [{opt}] My SD card backup     ({Path(backup_img).name})")
        choices[str(opt)] = "backup_slice"; opt += 1
    print(f"    [{opt}] RomWBW package image   (combo from Binary/)")
    choices[str(opt)] = "pkg_slice"; opt += 1
    print(f"    [{opt}] Any .img file           (SD backup, built image, or browse)")
    choices[str(opt)] = "any_slice"; opt += 1
    print(f"    [{opt}] Extracted backup slice  (from extracted/ dirs)")
    choices[str(opt)] = "extracted"; opt += 1
    print(f"    [{opt}] Loose folder of files   (files copied to user 0)")
    choices[str(opt)] = "folder"
    raw = input("    Choice [Enter = cancel]: ").strip()
    ch = choices.get(raw, "")
    if not ch:
        return []

    def _pick_slices_from(img_path: Path, img_fmt: str) -> "list[dict]":
        """Scan img_path, show populated slices, let user pick one or more with optional file selection."""
        print(f"    Scanning {img_path.name}...", end=" ", flush=True)
        found = []
        for s in range(max_slices(str(img_path), img_fmt) + 1):
            ok, lines = run_cpmls(str(img_path), img_fmt, s)
            if ok and file_lines(lines):
                desc = describe_slice(lines)
                found.append((s, desc))
        print(f"{len(found)} populated slice(s)")
        if not found:
            print("    No populated slices found."); return []
        for s, desc in found:
            print(f"      Slice {s:2d}: {desc}")
        picked = []
        already = set()
        while True:
            sl = input("    Which slice? [Enter = done]: ").strip()
            if not sl:
                break
            if not sl.isdigit():
                print("    Not a number — try again."); continue
            sl_num = int(sl)
            if sl_num in already:
                print(f"    Slice {sl_num} already added."); continue
            desc = next((d for s, d in found if s == sl_num), None)
            if desc is None:
                print(f"    Slice {sl_num} has no files — choose from the list above."); continue
            # offer file selection
            all_files = _scan_all_files_from(img_path, img_fmt, sl_num)
            ff = _ask_file_selection(all_files, f"slice {sl_num}")
            tu = _ask_user_target()
            n_selected = len(ff) if ff is not None else len(all_files)
            picked.append({"type": "combo", "path": img_path, "slot": sl_num,
                           "label": desc, "filter_files": ff, "img_fmt": img_fmt,
                           "target_user": tu, "files": n_selected})
            already.add(sl_num)
            remaining = [(s, d) for s, d in found if s not in already]
            if not remaining:
                print("    All slices selected."); break
            print(f"    Added slice {sl_num}: {desc}  ({n_selected} file(s))")
            print("    Remaining: " + ", ".join(f"{s}={d[:20]}" for s, d in remaining))
        return picked

    if ch == "backup_slice":
        return _pick_slices_from(Path(backup_img), fmt)

    elif ch == "pkg_slice":
        combos  = sorted(BIN_DIR.glob("*_combo.img"))
        singles = [p for p in sorted(BIN_DIR.glob("*.img"))
                   if p not in combos and not p.stem.endswith("_blank")]
        all_imgs = [(p, "combo") for p in combos] + [(p, "single") for p in singles]
        if not all_imgs:
            print("    No images found in package Binary/."); return []

        def _img_fmt(p: Path) -> str:
            """Derive format from image filename prefix; fall back to current fmt."""
            stem = p.stem.lower()
            for f in FORMATS:
                if stem.startswith(f):
                    return f
            return fmt

        def _show_list():
            print()
            for i, (p, kind) in enumerate(all_imgs):
                tag = "[multi-slice]" if kind == "combo" else "[single-slice]"
                print(f"      [{i + 1:2d}] {p.name:<50} {tag}")

        _show_list()
        results = []
        already_singles = set()
        while True:
            raw = input("    Pick number [Enter = done]: ").strip()
            if not raw:
                break
            if not raw.isdigit() or int(raw) < 1 or int(raw) > len(all_imgs):
                print("    Invalid number."); continue
            img_path, kind = all_imgs[int(raw) - 1]
            img_fmt = _img_fmt(img_path)
            if kind == "single":
                if img_path in already_singles:
                    print(f"    {img_path.name} already added."); continue
                write_diskdef_at(img_fmt, 0)
                r = subprocess.run([str(CPMLS), "-f", "wbw_browse_slice", str(img_path)],
                                   capture_output=True, env=cpm_env(), cwd=cpm_cwd())
                lines = [l.strip() for l in r.stdout.decode("cp437", errors="replace").splitlines() if l.strip()]
                all_files = sorted(file_lines(lines))
                label = img_path.stem
                ff = _ask_file_selection(all_files, img_path.name)
                tu = _ask_user_target()
                n_selected = len(ff) if ff is not None else len(all_files)
                print(f"    + {img_path.name}: {n_selected} file(s) queued  [{img_fmt}]")
                results.append({"type": "binary", "path": img_path,
                                 "label": label, "files": n_selected,
                                 "img_fmt": img_fmt, "filter_files": ff,
                                 "target_user": tu})
                already_singles.add(img_path)
            else:
                # multi-slice combo — open slice picker, add all chosen slices
                slices = _pick_slices_from(img_path, img_fmt)
                if slices:
                    results.extend(slices)
                    print(f"    + {len(slices)} slice(s) from {img_path.name}")
                _show_list()   # re-show list so user can keep adding
        return results

    elif ch == "any_slice":
        img = pick_any_image()
        if not img or not Path(img).exists(): return []
        img_path = Path(img)
        img_fmt = detect_format(img) or (input("    Format (hd1k/hd512) [hd1k]: ").strip() or "hd1k")
        return _pick_slices_from(img_path, img_fmt)

    elif ch == "extracted":
        extracted = list_extracted_dirs()
        if not extracted:
            print("    No extracted dirs found."); return []
        for i, d in enumerate(extracted):
            slices = sorted(s for s in d.iterdir() if s.is_dir() and s.name.startswith("slice"))
            print(f"      [{i}] {d.name}  ({len(slices)} slice(s))")
        src_idx = input("    Pick backup: ").strip()
        if not src_idx.isdigit() or int(src_idx) >= len(extracted): return []
        src_dir = extracted[int(src_idx)]
        slices = sorted(s for s in src_dir.iterdir() if s.is_dir() and s.name.startswith("slice"))
        if not slices:
            print("    No slices extracted yet."); return []
        for i, sl in enumerate(slices):
            udirs = [u for u in sl.iterdir() if u.is_dir()]
            count = sum(len(list(u.iterdir())) for u in udirs)
            print(f"      [{i}] {sl.name}: {count} files")
        sl_idx = input("    Pick slice: ").strip()
        if not sl_idx.isdigit() or int(sl_idx) >= len(slices): return []
        sl_dir = slices[int(sl_idx)]
        udirs = [u for u in sl_dir.iterdir() if u.is_dir()]
        count = sum(len(list(u.iterdir())) for u in udirs)
        tu = _ask_user_target()
        return [{"type": "extracted", "path": sl_dir,
                 "label": f"{src_dir.name}/{sl_dir.name}", "files": count,
                 "target_user": tu}]

    elif ch == "folder":
        folder = input("    Folder path: ").strip().strip('"')
        if not folder or not Path(folder).exists():
            print("    Folder not found."); return []
        folder_path = Path(folder)
        user_subdirs = [d for d in folder_path.iterdir() if d.is_dir() and d.name.startswith("user")]
        loose_files  = [f for f in folder_path.iterdir() if f.is_file()]
        count = (sum(len(list(d.iterdir())) for d in user_subdirs)
                 if user_subdirs else len(loose_files))
        layout = f"user0/ … user{len(user_subdirs)-1}/" if user_subdirs else f"{count} loose files"
        print(f"    {folder_path.name}: {count} files  ({layout})")
        tu = _ask_user_target()
        return [{"type": "folder", "path": folder_path, "label": folder_path.name,
                 "files": count, "target_user": tu}]

    return []


def _set_slot(slots: list, n: int, fmt: str, bin_list: list, backup_img: str = "", backup_fmt: str = ""):
    """Interactively assign a source to slot n."""
    _prev = slots[n]   # track whether this call actually assigns something
    print(f"\n  ── Slot {n}: choose content ─────────────────────────────")
    opt = 1
    choices = {}
    if backup_img:
        print(f"  [{opt}] Restore from my backup  ({Path(backup_img).name})")
        choices[str(opt)] = "backup"; opt += 1
    print(f"  [{opt}] SD card backup slice   (from extracted/ SD card images)")
    choices[str(opt)] = "extracted"; opt += 1
    print(f"  [{opt}] RomWBW package image    (single-OS binary from package)")
    choices[str(opt)] = "binary"; opt += 1
    print(f"  [{opt}] Any .img file           (SD backup, built image, or browse)")
    choices[str(opt)] = "any"; opt += 1
    print(f"  [{opt}] Blank")
    choices[str(opt)] = "blank"
    ch = choices.get(input("  Choice: ").strip(), "")

    if ch == "backup":
        n_slices = max_slices(backup_img, backup_fmt)
        print(f"\n  Slices in {Path(backup_img).name} [{backup_fmt}]:\n")
        found = []
        for s in range(n_slices + 1):
            ok, lines = run_cpmls(backup_img, backup_fmt, s)
            if ok and file_lines(lines):
                desc = describe_slice(lines)
                print(f"    Slice {s:2d} : {len(file_lines(lines)):3d} files  {desc}")
                found.append((s, len(file_lines(lines)), desc))
        if not found:
            print("  No populated slices found."); return
        sl = input(f"  Which slice to put into slot {n}? ").strip()
        if not sl.isdigit(): return
        sl_num = int(sl)
        match = next(((c, d) for s, c, d in found if s == sl_num), (0, ""))
        file_count, desc = match
        slots[n] = {"label": desc or Path(backup_img).stem,
                    "type": "combo", "path": Path(backup_img),
                    "slot": sl_num, "files": file_count,
                    "src_path": backup_img, "src_slice": sl_num}
        print(f"  Slot {n} ← backup slice {sl_num}  ({file_count} files)  [{desc}]")

    elif ch == "extracted":
        extracted = list_extracted_dirs()
        if not extracted:
            print("  No extracted dirs found. Use Browse > Extract first."); return
        print()
        for i, d in enumerate(extracted):
            slices = sorted(s for s in d.iterdir() if s.is_dir() and s.name.startswith("slice"))
            print(f"  [{i}] {d.name}  ({len(slices)} slice(s))")
        src_idx = input("  Pick backup: ").strip()
        if not src_idx.isdigit() or int(src_idx) >= len(extracted): return
        src_dir = extracted[int(src_idx)]
        slices = sorted(s for s in src_dir.iterdir() if s.is_dir() and s.name.startswith("slice"))
        if not slices:
            print("  No slices extracted yet."); return
        print()
        for i, sl in enumerate(slices):
            udirs = [u for u in sl.iterdir() if u.is_dir()]
            count = sum(len(list(u.iterdir())) for u in udirs)
            users = ", ".join(u.name for u in sorted(udirs))
            print(f"  [{i}] {sl.name}: {count} files  ({users})")
        sl_idx = input("  Pick slice: ").strip()
        if not sl_idx.isdigit() or int(sl_idx) >= len(slices): return
        sl_dir = slices[int(sl_idx)]
        udirs = [u for u in sl_dir.iterdir() if u.is_dir()]
        count = sum(len(list(u.iterdir())) for u in udirs)
        slots[n] = {"label": f"{src_dir.name}/{sl_dir.name}",
                    "type": "extracted", "path": sl_dir, "files": count,
                    "src_path": str(sl_dir), "src_slice": sl_dir.name}
        print(f"  Slot {n} ← {src_dir.name}/{sl_dir.name}  ({count} files)")

    elif ch == "binary":
        print()
        for i, (name, path) in enumerate(bin_list):
            print(f"    [{i:2d}] {path.name:<42}  ({path.stat().st_size // 1024 // 1024} MB)")
        idx = input("  Pick number: ").strip()
        if not idx.isdigit() or int(idx) >= len(bin_list): return
        name, path = bin_list[int(idx)]
        print(f"  Scanning {path.name}...", end=" ", flush=True)
        write_diskdef_at(fmt, 0)
        r = subprocess.run([str(CPMLS), "-f", "wbw_browse_slice", str(path)],
                            capture_output=True, env=cpm_env(), cwd=cpm_cwd())
        lines2 = [l.strip() for l in r.stdout.decode("cp437", errors="replace").splitlines() if l.strip()]
        files = len(file_lines(lines2))
        print(f"{files} files")
        slots[n] = {"label": name, "type": "binary", "path": path, "slot": 0, "files": files,
                    "src_path": str(path), "src_slice": 0}

    elif ch == "any":
        img = pick_any_image()
        if not img or not Path(img).exists():
            print("  File not found."); return
        img_path = Path(img)
        img_fmt = detect_format(img) or (input("  Could not detect format (hd1k/hd512) [hd1k]: ").strip() or "hd1k")
        print(f"\n  Slices in {img_path.name} [{img_fmt}]:\n")
        found = []
        for s in range(max_slices(img, img_fmt) + 1):
            ok, lines = run_cpmls(img, img_fmt, s)
            if ok and file_lines(lines):
                desc = describe_slice(lines)
                print(f"    Slice {s:2d} : {len(file_lines(lines)):3d} files  {desc}")
                found.append((s, len(file_lines(lines))))
        if not found:
            print("  No populated slices found."); return
        sl = input("  Pick slice number: ").strip()
        if not sl.isdigit():
            return
        sl_num = int(sl)
        file_count = next((c for s, c in found if s == sl_num), 0)
        slots[n] = {"label": f"{img_path.stem}:slice{sl_num}",
                    "type": "combo", "path": img_path,
                    "slot": sl_num, "files": file_count,
                    "src_path": str(img_path), "src_slice": sl_num}
        print(f"  Slot {n} ← {img_path.name} slice {sl_num}  ({file_count} files)")

    elif ch == "blank":
        slots[n] = {"label": "blank", "type": "blank", "path": None, "files": 0,
                    "src_path": "", "src_slice": ""}
        print(f"  Slot {n} = blank")

    # ── Offer to merge extra files into this slot (non-blank assignments only) ──
    if slots[n] is not _prev and slots[n] is not None and slots[n].get("type") != "blank":
        slots[n].setdefault("extras", [])
        while True:
            ans = input(f"\n  Merge extra files into slot {n}? [Y/N]: ").strip().upper()
            if ans != "Y":
                break
            extras = _pick_extra_source(fmt, backup_img=backup_img)
            if extras:
                slots[n]["extras"].extend(extras)
                total = len(slots[n]["extras"])
                labels = ", ".join(e["label"] for e in extras)
                print(f"  + Added {len(extras)}: {labels}  ({total} extra source(s) queued)")


def _write_image(slots: list, fmt: str, prefix_dat: Path, source_img: str = ""):
    """
    Assemble a new .img file the SAME SIZE as the original SD card image.
      1. Copy the full source image verbatim  (retains partition table + exact size)
      2. Overwrite the prefix block with the new package prefix
      3. Overwrite only the configured slot regions with new/restored slice data
    All other regions are left untouched.
    """
    occupied = [i for i, s in enumerate(slots) if s is not None]
    if not occupied:
        print("  Nothing to write — all slots empty.")
        return

    # ── Confirm source image (for partition table + exact sizing) ─────────────
    if not source_img or not Path(source_img).exists():
        print("\n  Source image for sizing (your original SD card backup):")
        source_img = pick_image()
    if not source_img or not Path(source_img).exists():
        print("  ERROR: No source image — cannot determine output size.")
        input("  Press Enter..."); return

    source_size = Path(source_img).stat().st_size
    last_slot   = max(occupied)
    ss          = slice_size(fmt)
    ps          = prefix_size(fmt)
    needed      = ps + (last_slot + 1) * ss

    print(f"\n  Source image : {Path(source_img).name}  ({source_size / 1e9:.2f} GB)")
    print(f"  CP/M region  : {needed / 1e6:.1f} MB  (prefix + {last_slot + 1} slot(s))")
    if needed > source_size:
        print(f"\n  ERROR: CP/M region ({needed / 1e6:.1f} MB) exceeds "
              f"source image ({source_size / 1e9:.2f} GB)")
        input("  Press Enter..."); return

    # ── Choose output path ────────────────────────────────────────────────────
    from datetime import datetime
    stamp    = datetime.now().strftime("%Y%m%d_%H%M")
    BUILD_ROOT.mkdir(parents=True, exist_ok=True)
    default  = str(BUILD_ROOT / f"upgrade_{fmt}_{stamp}.img")
    out_path = Path(input(f"\n  Output file [{default}]: ").strip() or default)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    BUF = 4 * 1024 * 1024

    # ── Step 1: copy full source image (preserves partition table + size) ─────
    copied = 0
    with open(source_img, "rb") as src, open(out_path, "wb") as dst:
        while True:
            chunk = src.read(BUF)
            if not chunk:
                break
            dst.write(chunk)
            copied += len(chunk)
            pct = copied / source_size * 100
            print(f"\r  [1/3] Copying base image ({source_size / 1e9:.2f} GB)...  {pct:5.1f}%",
                  end="", flush=True)
    print(f"\r  [1/3] Copying base image ({source_size / 1e9:.2f} GB)...  done        ")

    # ── Step 2: overwrite prefix block ───────────────────────────────────────
    prefix_data = prefix_dat.read_bytes()
    print(f"  [2/3] Writing prefix block  ({len(prefix_data) // 1024} KB)...", end=" ", flush=True)
    with open(out_path, "r+b") as out:
        out.seek(0)
        out.write(prefix_data)
    print("done")

    # ── Step 3: overwrite each configured slot region ─────────────────────────
    print(f"  [3/3] Writing {len(occupied)} slot(s):")
    with open(out_path, "r+b") as out:
        for i in range(last_slot + 1):
            s      = slots[i]
            offset = ps + i * ss

            if s is None or s["type"] == "blank":
                out.seek(offset)
                out.write(read_blank_slice(fmt))
                print(f"    Slot {i:2d}  (blank)                       @ {offset / 1e6:7.1f} MB")

            elif s["type"] == "binary":
                data = read_binary_slice(s["path"], fmt)
                if s.get("extras"):
                    print(f"    Slot {i:2d}  [{s['label']:<24}]  merging {len(s['extras'])} extra(s)…",
                          end=" ", flush=True)
                    data = _apply_extras(data, s["extras"], fmt)
                    print("done")
                out.seek(offset)
                out.write(data)
                print(f"    Slot {i:2d}  [{s['label']:<24}]  {len(data) // 1024:5} KB"
                      f"  @ {offset / 1e6:7.1f} MB")

            elif s["type"] == "combo":
                data = read_combo_slice(s["path"], fmt, s["slot"])
                if s.get("extras"):
                    print(f"    Slot {i:2d}  [{s['label']:<24}]  merging {len(s['extras'])} extra(s)…",
                          end=" ", flush=True)
                    data = _apply_extras(data, s["extras"], fmt)
                    print("done")
                out.seek(offset)
                out.write(data)
                kept = "  ◄ MY SLOT" if s.get("kept") else ""
                print(f"    Slot {i:2d}  [{s['label']:<24}]  {len(data) // 1024:5} KB"
                      f"  @ {offset / 1e6:7.1f} MB{kept}")

            elif s["type"] == "extracted":
                print(f"    Slot {i:2d}  [{s['label']:<24}]  injecting...", end=" ", flush=True)
                data = inject_files_into_slice(s["path"], fmt)
                if s.get("extras"):
                    print(f"merging {len(s['extras'])} extra(s)…", end=" ", flush=True)
                    data = _apply_extras(data, s["extras"], fmt)
                out.seek(offset)
                out.write(data)
                kept = "  ◄ MY SLOT" if s.get("kept") else ""
                print(f"done  {len(data) // 1024:5} KB  @ {offset / 1e6:7.1f} MB{kept}")

    size_gb = out_path.stat().st_size / 1e9
    print(f"\n  ✓ Done!  {out_path}")
    print(f"  Output size : {size_gb:.2f} GB  (matches original SD card image)")
    print(f"  Partition table and all non-CP/M regions retained verbatim.")
    print(f"  Ready to flash with Win32DiskImager or dd.")
    if BUILD_TEMP.exists():
        BUILD_TEMP.unlink()
    input("\n  Press Enter to continue...")


def build_menu():
    MAX_SLOT  = 16

    os.system("cls")
    print("=" * 60)
    print("  ROM Upgrade Image Builder")
    print("  Build a new SD image using the updated RomWBW package,")
    print("  restoring your personal slots from your old SD backup.")
    print("=" * 60)

    # Step 1 — pick the new RomWBW base image (default = hd1k_combo.img)
    print(f"\n  Step 1: Choose new RomWBW base image")
    print(f"  Package : {PACKAGE_DIR.name}")
    default_combo = BIN_DIR / "hd1k_combo.img"
    combo_imgs = sorted(BIN_DIR.glob("*_combo.img"), key=lambda p: p.name)
    print()
    for idx, p in enumerate(combo_imgs, 1):
        marker = "  ◄ default" if p == default_combo else ""
        size_mb = p.stat().st_size / 1_048_576
        print(f"    [{idx}] {p.name:<40} {size_mb:6.1f} MB{marker}")
    inp = input(f"\n  Pick number [Enter = {default_combo.name}]: ").strip()
    if inp.isdigit() and 1 <= int(inp) <= len(combo_imgs):
        combo_img = combo_imgs[int(inp) - 1]
    else:
        combo_img = default_combo

    if not combo_img.exists():
        print(f"\n  ERROR: {combo_img} not found"); input("  Press Enter..."); return

    # Derive format from image name (hd1k_combo → hd1k, hd512_combo → hd512)
    stem = combo_img.stem  # e.g. "hd1k_combo"
    fmt = "hd512" if stem.startswith("hd512") else "hd1k"

    prefix_dat = BIN_DIR / f"{fmt}_prefix.dat"
    if not prefix_dat.exists():
        print(f"\n  ERROR: {prefix_dat} not found"); input("  Press Enter..."); return

    slots: list = [None] * MAX_SLOT

    print(f"\n  Base image : {combo_img.name}  [{fmt}]")
    print(f"  Scanning...", end=" ", flush=True)
    pkg_slots: dict[int, dict] = {}
    n = max_slices(str(combo_img), fmt)
    for s in range(n + 1):
        ok, lines = run_cpmls(str(combo_img), fmt, s)
        files = file_lines(lines) if ok else []
        if files:
            desc = describe_slice(lines)
            pkg_slots[s] = {"label": desc or f"combo:slice{s}",
                            "type": "combo", "path": combo_img, "slot": s,
                            "files": len(files), "src_path": str(combo_img),
                            "src_slice": s, "kept": False}
    print(f"{len(pkg_slots)} slots found")
    for s, info in pkg_slots.items():
        slots[s] = dict(info)

    # Step 2 — pick old SD backup so user knows which slots to restore
    print("\n  Step 2: Pick your old SD card backup  (Enter to skip)")
    backup_img = pick_image()
    backup_fmt = ""
    if backup_img and Path(backup_img).exists():
        print(f"  Detecting format...", end=" ", flush=True)
        backup_fmt = detect_format(backup_img)
        if backup_fmt:
            print(backup_fmt)
        else:
            backup_fmt = input("could not detect. Enter (hd1k/hd512) [hd1k]: ").strip() or "hd1k"
        print(f"\n  Your backup slices:\n")
        print(f"  {'Slot':<6} {'Files':>5}  Content                         In new pkg?")
        print(f"  {'-'*6} {'-'*5}  {'-'*30}  {'-'*16}")
        nb = max_slices(backup_img, backup_fmt)
        backup_auto: dict[int, dict] = {}
        for s in range(nb + 1):
            ok, lines = run_cpmls(backup_img, backup_fmt, s)
            if ok and file_lines(lines):
                desc = describe_slice(lines)
                fc   = len(file_lines(lines))
                in_pkg = "in package" if s in pkg_slots else "NOT in package"
                print(f"  Slot {s:<3}   {fc:>4}  {desc:<30}  {in_pkg}")
                backup_auto[s] = {"label": desc or f"backup slice {s}",
                                  "type": "combo", "path": Path(backup_img),
                                  "slot": s, "files": fc,
                                  "src_path": backup_img, "src_slice": s, "kept": True}
        restored = []
        for s, info in backup_auto.items():
            if s not in pkg_slots:
                slots[s] = dict(info)
                restored.append(s)
        if restored:
            print(f"\n  Auto-kept backup-only slots: {restored}")
        print()
        print("  Use  S <n>  to restore a package slot from your backup.")
        print("  Use  C <n>  to pick any source for a slot.")
    else:
        backup_img = ""
        print("  (skipped — use S <n> to set slots manually)")

    bin_list = list_binary_slices(fmt)

    while True:
        print()
        occupied = [i for i, s in enumerate(slots) if s is not None]
        kept_count = sum(1 for s in slots if s and s.get("kept"))
        print(f"  ╔══ ROM Upgrade Image [{fmt}] {'═'*29}╗")
        print(f"  ║  New package : {PACKAGE_DIR.name:<45}║")
        if backup_img:
            bname = Path(backup_img).name[:45]
            print(f"  ║  Old backup  : {bname:<45}║")
        if kept_count:
            print(f"  ║  {kept_count} slot(s) kept from backup  (R to revert to pkg, C to change source){'':>1}║")
        print(f"  ╠{'═'*62}╣")
        last = max(occupied, default=-1)
        for i in range(max(last + 2, 6)):
            s = slots[i]
            if s:
                src    = Path(s.get("src_path", "")).name[-20:] if s.get("src_path") else ""
                sl_num = s.get("src_slice", "")
                desc   = s.get("label", "")[:24]
                nfiles = s.get("files", "?")
                kept   = "  ◄ MY SLOT" if s.get("kept") else ""
                nx     = len(s.get("extras") or [])
                extra_tag = f"  [+{nx} extra]" if nx else ""
                tag    = f"{desc:<24} {nfiles:>4}f  [{src} s{sl_num}]{kept}{extra_tag}"
            else:
                tag = "(empty)"
            print(f"  ║  Slot {i:2d}: {tag}")
        print(f"  ╚{'═'*62}╝")
        print()
        print("  S <n>  Restore slot n from your backup")
        print("  C <n>  Change slot n  (choose any source)")
        print("  E <n>  Add extra files to slot n  (merge from another slot or folder)")
        print("  R <n>  Reset slot n to new package version")
        print("  P <n>  Preview files in slot n")
        print("  W      Write finished image to file")
        print("  F      Toggle format   B  Back")
        print()
        cmd = input("  Command: ").strip().upper()

        parts = cmd.split()

        if parts[0] == "S" and len(parts) == 2 and parts[1].isdigit():
            sn = int(parts[1])
            if not backup_img:
                print("  No backup loaded. Use C <n> to choose a source.")
            elif sn in backup_auto:
                slots[sn] = dict(backup_auto[sn])
                slots[sn]["kept"] = True
                print(f"  Slot {sn} restored from backup  [{backup_auto[sn]['label']}]")
            else:
                print(f"  Slot {sn} is empty in your backup.")

        elif parts[0] == "C" and len(parts) == 2 and parts[1].isdigit():
            sn = int(parts[1])
            _set_slot(slots, sn, fmt, bin_list, backup_img, backup_fmt)
            if slots[sn] and backup_img and str(slots[sn].get("src_path", "")) == backup_img:
                slots[sn]["kept"] = True

        elif parts[0] == "E" and len(parts) == 2 and parts[1].isdigit():
            sn = int(parts[1])
            s  = slots[sn]
            if not s or s.get("type") == "blank":
                print(f"  Slot {sn} has no content — assign it first with C {sn}.")
            else:
                extras = _pick_extra_source(fmt, backup_img=backup_img)
                if extras:
                    s.setdefault("extras", []).extend(extras)
                    labels = ", ".join(e["label"] for e in extras)
                    print(f"  + Added {len(extras)}: {labels}  ({len(s['extras'])} extra source(s) queued for slot {sn})")

        elif parts[0] == "R" and len(parts) == 2 and parts[1].isdigit():
            sn = int(parts[1])
            if sn in pkg_slots:
                slots[sn] = dict(pkg_slots[sn])
                print(f"  Slot {sn} reset to new package  [{pkg_slots[sn]['label']}]")
            else:
                slots[sn] = None
                print(f"  Slot {sn} cleared (not in new package).")

        elif parts[0] == "P" and len(parts) == 2 and parts[1].isdigit():
            n = int(parts[1])
            s = slots[n]
            if not s:
                print(f"  Slot {n} is empty.")
            else:
                print(f"  ── Slot {n} base content ──────────────────────────────────")
                if s["type"] in ("binary",):
                    write_diskdef_at(fmt, 0)
                    r = subprocess.run([str(CPMLS), "-f", "wbw_browse_slice", str(s["path"])],
                                        capture_output=True, env=cpm_env(), cwd=cpm_cwd())
                    for l in r.stdout.decode("cp437", errors="replace").splitlines():
                        if l.strip():
                            print(f"    {l.strip()}")
                elif s["type"] == "combo":
                    ok, lines = run_cpmls(str(s["path"]), fmt, s["slot"])
                    if ok:
                        for l in lines:
                            print(f"    {l}")
                elif s["type"] == "extracted":
                    for udir in sorted(s["path"].iterdir()):
                        if udir.is_dir():
                            files = list(udir.iterdir())
                            if files:
                                print(f"    {udir.name}: {len(files)} files")
                extras = s.get("extras") or []
                if extras:
                    print(f"  ── Queued extras ({len(extras)}) — will be merged on Write ──────────")
                    for xi, ex in enumerate(extras):
                        ff = ex.get("filter_files")
                        if ff:
                            flist = sorted(ff)
                            tu_tag = f"  → user {ex['target_user']}" if ex.get('target_user') is not None else ""
                            print(f"    [{xi + 1}] {ex['label']}  ({len(ff)} selected file(s)){tu_tag}:")
                            for fname in flist:
                                print(f"        {fname}")
                        else:
                            tu_tag = f"  → user {ex['target_user']}" if ex.get('target_user') is not None else ""
                            print(f"    [{xi + 1}] {ex['label']}  ({ex.get('files', '?')} file(s), all){tu_tag}")

        elif cmd == "W":
            _write_image(slots, fmt, prefix_dat, source_img=backup_img)

        elif cmd == "F":
            fmt = "hd512" if fmt == "hd1k" else "hd1k"
            prefix_dat = BIN_DIR / f"{fmt}_prefix.dat"
            combo_img  = BIN_DIR / f"{fmt}_combo.img"
            bin_list   = list_binary_slices(fmt)
            slots      = [None] * MAX_SLOT
            backup_fmt = ""
            print(f"  Switched to: {fmt}  (slots reset — re-select backup if needed)")

        elif cmd == "B":
            break


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN MENU
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    import atexit, shutil

    def _cleanup():
        """Remove temporary working directories created during this session."""
        for path in (ROMWBW_ROOT, BUILD_TEMP,
                     SCRIPT_DIR / "_extra_stage",
                     SCRIPT_DIR / "_extra_slice.img",
                     SCRIPT_DIR / "_scan_tmp.img"):
            try:
                if path.is_dir():
                    shutil.rmtree(path)
                elif path.is_file():
                    path.unlink()
            except Exception:
                pass

    atexit.register(_cleanup)

    if not CPMLS.exists():
        print(f"ERROR: cpmls.exe not found at {CPMTOOLS_DIR}")
        input("Press Enter to exit"); sys.exit(1)

    EXTRACT_ROOT.mkdir(parents=True, exist_ok=True)
    DISKDEFS.parent.mkdir(parents=True, exist_ok=True)

    while True:
        os.system("cls")
        print("=" * 52)
        print("  RomWBW SC131 SD Image Tools")
        print(f"  Package: {PACKAGE_DIR.name}")
        print("=" * 52)
        print("  [1] Browse SD Card CP/M Image (.img file)")
        print("  [2] Browse RomWBW Package Images")
        print("  [3] Build Upgrade Image    (update ROM, keep personal slots)")
        print("  [Q] Quit")
        print("=" * 52)
        choice = input("  Choose: ").strip().upper()

        if choice == "1":
            browse_menu()
        elif choice == "2":
            browse_romwbw_menu()
        elif choice == "3":
            build_menu()
        elif choice == "Q":
            break

if __name__ == "__main__":
    main()
