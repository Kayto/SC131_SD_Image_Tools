# SC131 SD Image Tools

Python tools for browsing, extracting, building, and imaging RomWBW SD cards
for the SC131 Z180 SBC (and any other RomWBW `hd1k`/`hd512` format board).

---
## Credits & Acknowledgements

- **[RomWBW](https://github.com/wwarthen/RomWBW)** by Wayne Warthen —
  the ROM firmware and disk image package that this tool is built around.
  RomWBW provides the CP/M system images, `cpmtools` binaries, and disk
  format definitions used throughout.

- **[SC131 Z180 Pocket Computer](https://smallcomputercentral.com/sc131-z180-pocket-computer/)**
  by Small Computer Central / Stephen Cousins — the Z180-based single-board
  computer this toolset was originally created for.
## Folder structure

This folder (`SC131_SD_Image_Tools\`) must sit **alongside** an unpacked
RomWBW release package.  Only two sub-folders from that package are needed:

```
<any location>\
├── SC131_SD_Image_Tools\       ← this folder (relocate wherever you like)
│   ├── sc131_tools.py          ← main script – all tools in one file
│   ├── SC131_Tools.cmd         ← launcher shortcut
│   ├── diskdefs                ← temp file, auto-managed, safe to delete
│   ├── extracted\              ← CP/M files extracted from SD card images (auto-created)
│   ├── romwbw\                 ← CP/M files browsed from RomWBW package images (temp, auto-cleaned)
│   ├── build\                  ← assembled output images
│   ├── _build_temp.img         ← temp scratch during build, auto-cleaned on exit
│   ├── _extra_slice.img        ← temp scratch during extras merge, auto-cleaned on exit
│   └── _extra_stage\           ← temp staging dir during extras merge, auto-cleaned on exit
│
└── RomWBW-vX.X.X-Package\     ← sibling folder from the RomWBW distribution
    ├── Binary\                 ← REQUIRED: hd1k_*.img, hd512_*.img, *_prefix.dat
    └── Tools\
        └── cpmtools\           ← REQUIRED: cpmls.exe, cpmcp.exe
```

`sc131_tools.py` **auto-detects** the RomWBW package at startup — it scans
sibling directories for the presence of `Binary\hd1k_combo.img` and
`Tools\cpmtools\cpmls.exe`.  If multiple packages are present the
highest-sorted name wins (i.e. `v3.6` beats `v3.5`).

All temporary files (`_build_temp.img`, `_extra_slice.img`, `_extra_stage\`,
`_scan_tmp.img`, `romwbw\`) are automatically cleaned up on exit.

### Updating to a new RomWBW release

1. Download the new RomWBW release package and unzip it alongside this folder.
2. Run `SC131_Tools.cmd` — the new package is picked up automatically.
3. The old package folder can be deleted when you're satisfied.

---

## Requirements

- **Python 3.10+** — standard library only, no pip installs needed.
  `python.exe` must be on your PATH, or edit `SC131_Tools.cmd` to point at it.
- **cpmtools** — `cpmls.exe` / `cpmcp.exe` from the RomWBW package
  (`Tools\cpmtools\`).  These are Windows binaries; no installation needed.

---

## Running

Double-click **`SC131_Tools.cmd`**, or:

```cmd
python SC131_SD_Image_Tools\sc131_tools.py
```

The main menu shows the detected RomWBW package name so you always know
which version's binary images are active.

---

## Menu options

### [1] Browse SD Card CP/M Image

Inspect any `.img` file (your SD card backup or any hd1k/hd512 image).

| Key | Action |
|-----|--------|
| S   | Scan all slices — shows file count + auto-detected OS/content label |
| L   | List files in a specific slice |
| X   | Extract a single slice → `extracted\<image>\slice<n>\user<n>\` |
| A   | Extract ALL populated slices |
| F   | Toggle between hd1k and hd512 format |
| B   | Back to main menu |

Extraction preserves CP/M user areas as subdirectories:
`slice0\user0\`, `slice0\user2\`, etc.

### [2] Browse RomWBW Package Images

Browse the images included in the RomWBW package (`Binary\` folder).
Pick any combo or single-slice image, then scan/list/extract with the
same controls as option [1].  Extracted files go to `romwbw\` (cleaned up on
exit).

### [3] Build Upgrade Image

Build a new full-size SD card image that upgrades the RomWBW system slices
from a new package while keeping your personal/custom slots intact.

#### Workflow

1. **Choose the new RomWBW base** — defaults to `hd1k_combo.img` from the
   package.  All combo images (`hd512_combo.img` etc.) are listed.
2. **Pick your old SD card backup** — the builder scans it and auto-restores
   any slots that aren't in the new package (your custom or personal slots).
3. **Customise the slot table** — use the commands below to finesse which
   slots come from the new package, which come from your backup, and which
   get extra files merged in.
4. **Write** — produces a full-size `.img` file (matching your original SD
   card size) ready to flash.

#### Slot table commands

| Command | Action |
|---------|--------|
| `S <n>` | Restore slot *n* from your backup |
| `C <n>` | Change slot *n* — choose any source (combo slice, binary image, extracted folder, blank) |
| `E <n>` | Add extra files to slot *n* — merge files from another image or folder on top of the existing content |
| `R <n>` | Reset slot *n* to the new package version |
| `P <n>` | Preview files in slot *n* (base content + queued extras) |
| `W`     | Write the finished image to a file |
| `F`     | Toggle format (hd1k ↔ hd512) — resets all slots |
| `B`     | Back to main menu |

Slots marked **◄ MY SLOT** were auto-restored from your backup (not present
in the new package).  Slots with **[+N extra]** have additional files queued
for merging at write time.

#### Extra files merging (`E <n>`)

Merge CP/M files from other sources on top of an existing slot.  Sources:

| Source | Description |
|--------|-------------|
| My SD card backup | Pick one or more slices from your backup image |
| RomWBW package image | Pick from any combo (multi-slice) or single-slice image in `Binary\` — format is auto-detected from the filename (`hd1k_*`, `hd512_*`) |
| Any .img file | Browse for any `.img` file and pick slices from it |
| Extracted backup slice | Use a previously extracted slice from `extracted\` |
| Loose folder of files | Point at a folder of files on disk |

For image-based sources:

- **Multi-slice images** open a slice picker — select one or more slices in
  a loop (Enter = done).
- **Single-slice images** are added directly.
- After selecting the source, choose **[A]ll files** or **[S]elect specific
  files** — the select option shows a numbered list and accepts ranges like
  `1 3 5-10`.
- Optionally set a **destination user area** (0–15) — all merged files go
  into that user area.  Enter = keep original user areas from the source.

The merge is applied during `W` (write).  `P <n>` shows exactly what extras
are queued, including selected files and target user area.

#### Output image structure

```
Prefix block              1 MB   boot tracks (hd1k_prefix.dat)
Slot 0                    8 MB   e.g. CP/M 2.2
Slot 1                    8 MB   e.g. ZSDOS 1.1
Slot 2                    8 MB   e.g. NZ-COM
...
(remaining SD card)              partition table and all non-CP/M regions retained verbatim
```

The output image is copied from your original SD card backup first (preserving
the exact size, partition table, and all non-CP/M data), then the prefix and
slot regions are overwritten in place.

---

## SD card image files

| File | Default location | Created by |
|------|-----------------|-----------|
| Built upgrade image | `build\upgrade_<fmt>_YYYYMMDD_HHMM.img` | Build Upgrade Image menu |
| Extracted files | `extracted\<image stem>\slice<n>\user<n>\` | Browse menus |

---

## Slice content signatures

The scan attempts to auto-identify slice content against known RomWBW disk images as of rev 3.5.1. This is subject to update so refer to the RomWBW disk catalog for actual content.

Unrecognised slices show as `custom`.

---

## Disk formats

| Format | Slice size | Prefix | Sec/trk | Block size | Max dir entries | Boot tracks |
|--------|-----------|--------|---------|------------|----------------|-------------|
| `hd1k` | 8192 KB (1024 tracks) | 1024 KB (128 tracks) | 16 × 512 | 4096 | 1024 | 2 |
| `hd512` | 8320 KB (1040 tracks) | 0 KB (no prefix) | 16 × 512 | 4096 | 512 | 16 |

The format is auto-detected when scanning unknown images by trying both
formats and checking for recognisable CP/M files.

---

## Notes

- All disk I/O uses the `cpmtools` binaries from the RomWBW package.
  `cpmls.exe` / `cpmcp.exe` require their `diskdefs` config file to be in
  their **working directory**; `sc131_tools.py` handles this automatically.
- CP/M filenames are decoded as **CP437** (DOS codepage).
- The `extracted\` folder is safe to delete at any time; nothing is stored
  there that cannot be re-extracted from the `.img` file.
- All temporary working files are cleaned up on exit via `atexit`.

---

## Author

[Kayto](https://github.com/Kayto)

## Licence

MIT