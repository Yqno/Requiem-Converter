#!/usr/bin/env python3
"""
RE9 Save Manager — unified tool combining:
  - MandarinJuice (brute force, re-sign, decrypt/encrypt)
  - REE Save Editor (field inspection)
  - Garlic Save Manager (PS5 package building & HTTP push)

Run:  python3 server.py
Then: open http://localhost:8765
"""

import json, os, re, shutil, subprocess, sys, tempfile, time, zipfile
import http.server, socketserver, urllib.parse, urllib.request
from pathlib import Path

PORT      = 8765
BASE_DIR  = Path(__file__).parent.resolve()
STATIC    = BASE_DIR / "static"
UPLOADS   = BASE_DIR / "uploads"
UPLOADS.mkdir(parents=True, exist_ok=True)

CONV_BIN  = BASE_DIR / "convert_re9_ps5"
SCE_TPL   = BASE_DIR / "sce_sys_template"
PROFILES_DIR = BASE_DIR / "_profiles"

# MandarinJuice — binary placed next to server.py as "MandarinJuice"
MJ_BIN = Path(os.environ.get("MJ_BIN", str(BASE_DIR / "MandarinJuice")))

# ── defaults ──────────────────────────────────────────────────────────────────
DEFAULT_STEAM_ID    = "76561197960265728"   # Steam32=0 (mod saves)
DEFAULT_PS5_ID      = ""     # your PS5 account ID in Decimal
DEFAULT_TITLE_ID    = "PPSA31246"           # RE9 EU
DEFAULT_REGION_HASH = "481759118"           # RE9 EU/AS PS5 (from confirmed guide)
DEFAULT_APP_VERSION = "16785408"            # v1.0.2.0

# Known _MainRegionHash values
REGION_PRESETS = {
    "pc":           (1874947740,  "PC / Steam"),
    "ps5_eu_as":    (481759118,   "PS5 EU/AS (PPSA31246)"),
    "ps5_eu_us_v2": (3208943443,  "PS5 EU/US (PPSA30803)"),
}

# Known _ApplicationVersion values
VERSION_PRESETS = {
    "pc_1012":  (16781314,  "v1.0.1.2 PC"),
    "ps5_102":  (16785408,  "v1.0.2.0 PS5"),
}

# ── save file inspection ───────────────────────────────────────────────────────
def inspect_file(path: Path) -> dict:
    try:
        stat = path.stat()
        with open(path, "rb") as f:
            hdr = f.read(16)
        name = path.name.lower()
        size = stat.st_size
        mtime = stat.st_mtime

        is_re = (hdr[:4] in (b"SSSD", b"DSSS") or
                 name.endswith(".bin") and ("data0" in name or "slot" in name))

        if is_re:
            if "00-1" in path.name or "-1" in path.name:
                stype = "system"
                label = "System / Settings"
            elif "000" in path.name:
                stype = "autosave"
                label = "Autosave (Continue)"
            else:
                stype = "slot"
                m = re.search(r'data(\d+)', path.name, re.I)
                slot = int(m.group(1)) if m else 0
                label = f"Slot {slot}"

            return {
                "name": path.name, "path": str(path), "size": size, "mtime": mtime,
                "size_str": f"{size/1024:.1f} KB",
                "mtime_str": time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime)),
                "engine": "re_engine", "type": stype, "label": label,
                "is_valid": True,
            }

        # Unreal Engine (Split Fiction)
        if hdr[:4] == b"GVAS":
            return {
                "name": path.name, "path": str(path), "size": size, "mtime": mtime,
                "size_str": f"{size/1024:.1f} KB",
                "mtime_str": time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime)),
                "engine": "unreal_engine", "type": "slot", "label": "UE GVAS Save",
                "is_valid": True,
            }
        try:
            txt = hdr.decode("utf-8", errors="ignore").strip()
            if txt.startswith("{"):
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    data = json.load(f)
                if "FurthestUnlockedChapter" in data or "EULA_Accepted" in data:
                    chapter = data.get("LastSaveChapter", "").split("/")[-1].replace("##", " - ")
                    return {
                        "name": path.name, "path": str(path), "size": size, "mtime": mtime,
                        "size_str": f"{size/1024:.1f} KB",
                        "mtime_str": time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime)),
                        "engine": "unreal_engine", "type": "slot",
                        "label": f"Split Fiction — {chapter or 'PC Save'}",
                        "is_valid": True, "meta": {"chapter": chapter, "uid": data.get("UID", "")}
                    }
                if "Profile" in data:
                    prof = data["Profile"]
                    chapter = prof.get("LastSaveChapter", "").split("/")[-1].replace("##", " - ")
                    return {
                        "name": path.name, "path": str(path), "size": size, "mtime": mtime,
                        "size_str": f"{size/1024:.1f} KB",
                        "mtime_str": time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime)),
                        "engine": "unreal_engine", "type": "slot",
                        "label": f"Split Fiction PS5 — {chapter or 'PS5 Save'}",
                        "is_valid": True, "meta": {"chapter": chapter, "uid": prof.get("UID", "")}
                    }
        except Exception:
            pass

        return {
            "name": path.name, "path": str(path), "size": size, "mtime": mtime,
            "size_str": f"{size/1024:.1f} KB",
            "mtime_str": time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime)),
            "engine": "unknown", "type": "unknown", "label": "Unknown file", "is_valid": False,
        }
    except Exception as e:
        return {"name": path.name, "path": str(path), "size": 0, "mtime": 0,
                "size_str": "0 KB", "mtime_str": "-", "engine": "unknown",
                "type": "unknown", "label": f"Error: {e}", "is_valid": False}


def scan_dir(target: Path) -> list:
    saves = []
    if not target.exists():
        return saves
    for root, _, files in os.walk(target):
        for f in files:
            fl = f.lower()
            if fl.endswith((".bin", ".split", ".sav", ".json")):
                info = inspect_file(Path(root) / f)
                if info["is_valid"]:
                    saves.append(info)
    saves.sort(key=lambda s: s["mtime"], reverse=True)
    return saves


# ── RE Engine conversion ───────────────────────────────────────────────────────
def convert_re(src: Path, dst: Path, source_id: str, target_id: str,
               mode: str, region_hash: str, app_version: str) -> dict:
    if not CONV_BIN.exists():
        return {"success": False, "error": f"convert_re9_ps5 binary not found at {CONV_BIN}"}
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [str(CONV_BIN), str(src), str(dst),
           source_id, target_id, mode, region_hash, app_version]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=True)
        return {"success": True, "log": p.stdout + p.stderr, "output": str(dst)}
    except subprocess.CalledProcessError as e:
        return {"success": False, "error": f"Converter exited {e.returncode}",
                "log": e.stdout + e.stderr}
    except Exception as e:
        return {"success": False, "error": str(e)}


def batch_convert_re(src_dir: Path, dst_dir: Path, source_id: str, target_id: str,
                     mode: str, region_hash: str, app_version: str) -> dict:
    if not CONV_BIN.exists():
        return {"success": False, "error": f"convert_re9_ps5 not found at {CONV_BIN}"}
    dst_dir.mkdir(parents=True, exist_ok=True)
    cmd = [str(CONV_BIN), str(src_dir), str(dst_dir),
           source_id, target_id, mode, region_hash, app_version]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=True)
        return {"success": True, "log": p.stdout + p.stderr, "output_dir": str(dst_dir)}
    except subprocess.CalledProcessError as e:
        return {"success": False, "error": f"Batch converter exited {e.returncode}",
                "log": e.stdout + e.stderr}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── MandarinJuice integration ──────────────────────────────────────────────────
def mj_brute_force(save_dir: Path, game_profile: Path, mj_bin: Path) -> dict:
    if not mj_bin.exists():
        return {"success": False, "error": f"MandarinJuice CLI not found: {mj_bin}\nSet MJ_BIN env var or place mandarin-juice-cli next to server.py"}
    if not game_profile.exists():
        return {"success": False, "error": f"Game profile not found: {game_profile}"}
    if not save_dir.is_dir():
        # treat as file, use its parent
        save_dir = save_dir.parent

    cmd = [str(mj_bin), "-m", "b", "-g", str(game_profile), "-p", str(save_dir), "-q"]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=300, cwd=str(BASE_DIR))
        output = (p.stdout or "") + (p.stderr or "")
        for pat in [r'Found user id[:\s]+(\d+)', r'Found ID[:\s]+(\d+)',
                    r'SteamID[:\s]+(\d{15,20})', r'User ID[:\s]+(\d{15,20})']:
            m = re.search(pat, output, re.I)
            if m:
                return {"success": True, "steam_id": m.group(1), "log": output}
        return {"success": False, "log": output,
                "error": "Steam ID not found — check the log for hints"}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Brute force timed out (> 5 min)"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def mj_resign(save_dir: Path, game_profile: Path, mj_bin: Path,
              old_id: str, new_id: str) -> dict:
    if not mj_bin.exists():
        return {"success": False, "error": f"MandarinJuice CLI not found: {mj_bin}"}
    cmd = [str(mj_bin), "-m", "r", "-g", str(game_profile),
           "-p", str(save_dir), "-uI", old_id, "-uO", new_id, "-q"]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=True, cwd=str(BASE_DIR))
        return {"success": True, "log": p.stdout + p.stderr}
    except subprocess.CalledProcessError as e:
        return {"success": False, "error": f"MandarinJuice exited {e.returncode}",
                "log": e.stdout + e.stderr}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Field inspection ───────────────────────────────────────────────────────────
def _run_converter_probe(src_id: str, tgt_id: str, mode: str,
                         file_path: Path, region: int, version: int) -> tuple[int, str]:
    """Run converter and return (returncode, combined_output). Never raises."""
    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tf:
        tmp = Path(tf.name)
    try:
        cmd = [str(CONV_BIN), str(file_path), str(tmp),
               src_id, tgt_id, mode, str(region), str(version)]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as e:
        return -1, str(e)
    finally:
        tmp.unlink(missing_ok=True)


def _parse_patches(out: str) -> tuple[int, int, int, int]:
    """
    Parse (region_count, region_val, ver_count, ver_val) from converter output.
    'Region=N:0xVALUE' — N = number of fields patched, VALUE = new (target) value.
    N=1 → field existed and was different → original had a DIFFERENT value.
    N=0 → field was either already equal to target, not found, or mode doesn't patch.
    """
    rm = re.search(r'Region=(\d+):0x([0-9a-fA-F]+)', out)
    vm = re.search(r'Ver=(\d+):0x([0-9a-fA-F]+)', out)
    rc = int(rm.group(1)) if rm else -1
    rv = int(rm.group(2), 16) if rm else 0
    vc = int(vm.group(1)) if vm else -1
    vv = int(vm.group(2), 16) if vm else 0
    return rc, rv, vc, vv


def autodetect_save(file_path: Path, steam_id: str, ps5_id: str) -> dict:
    """
    Auto-detect platform (PC/PS5) and actual current field values.

    Strategy:
      - pc2pc succeeds → it's a PC save (steam_id decrypts it)
      - ps52pc succeeds → it's a PS5 save (ps5_id decrypts it)
      - For actual region hash: run pc2ps5 / ps52pc with known target:
          Region=1 → field WAS different from target → original had the other known value
          Region=0 → field was already the target value (or not found in this mode)
    """
    if not CONV_BIN.exists():
        return {"success": False, "error": "Converter binary not found"}

    PC_REGION  = REGION_PRESETS["pc"][0]           # 1874947740 = 0x6fc16e9c
    PS5_REGION = REGION_PRESETS["ps5_eu_as"][0]    # 481759118  = 0x1cb70f8e
    PS5_REGION2= REGION_PRESETS["ps5_eu_us_v2"][0] # 3208943443 = 0xbf3a9d4b
    PS5_VER    = VERSION_PRESETS["ps5_102"][0]     # 16785408   = 0x1002000
    PC_VER     = VERSION_PRESETS["pc_1012"][0]     # 16781314   = 0x1001002

    res = {
        "success": False,
        "platform": None,
        "source_id": None,
        "region_hash": None,
        "region_hash_hex": None,
        "region_hash_label": None,
        "app_version": None,
        "app_version_hex": None,
        "app_version_label": None,
        "needs_region_patch": False,
        "needs_version_patch": False,
        "suggested_mode": None,
        "suggested_region": None,
        "suggested_version": None,
        "suggested_target_id": None,
        "flags": None,
        "decrypted_size": None,
        "log": []
    }

    def parse_meta(out):
        sm = re.search(r'Size:\s*(\d+)', out)
        fm = re.search(r'Flags:\s*(SaveFlags\([^)]+\))', out)
        return (int(sm.group(1)) if sm else None,
                fm.group(1) if fm else None)

    # ── Step 1: test PC (steam_id) decryption ─────────────────────────────────
    rc, out = _run_converter_probe(steam_id, steam_id, "pc2pc",
                                   file_path, PC_REGION, PS5_VER)
    res["log"].append(f"pc2pc probe rc={rc}")

    if rc == 0 and "key mismatch" not in out.lower():
        res["platform"] = "PC"
        res["source_id"] = steam_id
        sz, fl = parse_meta(out)
        res["decrypted_size"] = sz
        res["flags"] = fl

        # Detect actual region hash via pc2ps5 (this mode DOES patch the field)
        rc2, out2 = _run_converter_probe(steam_id, ps5_id, "pc2ps5",
                                         file_path, PS5_REGION, PS5_VER)
        res["log"].append(f"pc2ps5 probe (PS5-EU/AS target) rc={rc2}")

        if rc2 == 0:
            rcnt, rval, vcnt, vval = _parse_patches(out2)
            res["log"].append(f"  Patches: Region={rcnt}:0x{rval:08x}  Ver={vcnt}:0x{vval:08x}")

            if rcnt == 1:
                # Was changed → had something DIFFERENT from PS5_REGION
                # 99% of unmodified PC saves: original = PC_REGION
                res["region_hash"] = PC_REGION
                res["region_hash_hex"] = f"0x{PC_REGION:08x}"
                res["region_hash_label"] = "PC/Steam"
                res["needs_region_patch"] = True
            elif rcnt == 0:
                # Already had PS5 region (or profile save with no region field)
                res["region_hash"] = PS5_REGION
                res["region_hash_hex"] = f"0x{PS5_REGION:08x}"
                res["region_hash_label"] = "PS5 EU/AS (already set)"
                res["needs_region_patch"] = False

            # Version: Ver=0 in pc2ps5 means PC save already has PS5 version 0x1002000
            if vcnt == 0 and vval:
                res["app_version"] = vval
                res["app_version_hex"] = f"0x{vval:08x}"
                lbl = next((l for _, (v, l) in VERSION_PRESETS.items() if v == vval), f"0x{vval:08x}")
                res["app_version_label"] = lbl
                res["needs_version_patch"] = False
            elif vcnt == 1 and vval:
                # Version was different → original was something else
                res["app_version"] = vval  # target value that was set
                res["app_version_hex"] = f"0x{vval:08x}"
                lbl = next((l for _, (v, l) in VERSION_PRESETS.items() if v == vval), f"0x{vval:08x}")
                res["app_version_label"] = f"{lbl} (patched)"
                res["needs_version_patch"] = True

        res["suggested_mode"] = "pc2ps5"
        res["suggested_region"] = PS5_REGION
        res["suggested_version"] = PS5_VER
        res["suggested_target_id"] = ps5_id
        res["success"] = True
        return res

    # ── Step 2: test PS5 (ps5_id) decryption ──────────────────────────────────
    rc, out = _run_converter_probe(ps5_id, steam_id, "ps52pc",
                                   file_path, PC_REGION, PC_VER)
    res["log"].append(f"ps52pc probe rc={rc}")

    if rc == 0 and "key mismatch" not in out.lower():
        res["platform"] = "PS5"
        res["source_id"] = ps5_id
        sz, fl = parse_meta(out)
        res["decrypted_size"] = sz
        res["flags"] = fl

        rcnt, rval, vcnt, vval = _parse_patches(out)
        res["log"].append(f"  Patches: Region={rcnt}:0x{rval:08x}  Ver={vcnt}:0x{vval:08x}")

        if rcnt == 1:
            # Was changed to PC_REGION → original was something PS5-specific
            # Try to narrow down which PS5 region
            rc3, out3 = _run_converter_probe(ps5_id, steam_id, "ps52pc",
                                              file_path, PS5_REGION2, PC_VER)
            if rc3 == 0:
                rcnt3, _, _, _ = _parse_patches(out3)
                if rcnt3 == 0:
                    res["region_hash"] = PS5_REGION2
                    res["region_hash_hex"] = f"0x{PS5_REGION2:08x}"
                    res["region_hash_label"] = REGION_PRESETS["ps5_eu_us_v2"][1]
                else:
                    res["region_hash"] = PS5_REGION
                    res["region_hash_hex"] = f"0x{PS5_REGION:08x}"
                    res["region_hash_label"] = REGION_PRESETS["ps5_eu_as"][1]
            else:
                res["region_hash"] = PS5_REGION
                res["region_hash_hex"] = f"0x{PS5_REGION:08x}"
                res["region_hash_label"] = REGION_PRESETS["ps5_eu_as"][1]
            res["needs_region_patch"] = True
        elif rcnt == 0:
            res["region_hash"] = PC_REGION
            res["region_hash_hex"] = f"0x{PC_REGION:08x}"
            res["region_hash_label"] = "PC/Steam (unusual in PS5 save)"
            res["needs_region_patch"] = False

        if vcnt >= 0 and vval:
            res["app_version"] = vval
            res["app_version_hex"] = f"0x{vval:08x}"
            lbl = next((l for _, (v, l) in VERSION_PRESETS.items() if v == vval), f"0x{vval:08x}")
            res["app_version_label"] = lbl
            res["needs_version_patch"] = vcnt == 1

        res["suggested_mode"] = "ps52pc"
        res["suggested_region"] = PC_REGION
        res["suggested_version"] = PC_VER
        res["suggested_target_id"] = steam_id
        res["success"] = True
        return res

    res["error"] = "Cannot decrypt — try different Steam/PS5 Account ID"
    return res


def inspect_re_fields(file_path: Path, source_id: str) -> dict:
    """Try both pc2ps5 and ps52pc to extract field values from save."""
    if not CONV_BIN.exists():
        return {"success": False, "error": "convert_re9_ps5 binary not found"}

    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tf:
        tmp = Path(tf.name)

    result = {"fields": {}, "log": "", "success": False}
    for mode in ["pc2ps5", "ps52pc"]:
        tid = source_id  # use same ID for target so we can decrypt result
        cmd = [str(CONV_BIN), str(file_path), str(tmp),
               source_id, tid, mode, DEFAULT_REGION_HASH, DEFAULT_APP_VERSION]
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
            out = (p.stdout or "") + (p.stderr or "")
            result["log"] += f"\n── mode={mode} ──\n{out}"

            if p.returncode == 0:
                f = {}
                rcnt, rval, vcnt, vval = _parse_patches(out)

                if rval:
                    # For pc2ps5/ps52pc: Region=1 → original had different value
                    # We report the ORIGINAL value (not the target)
                    if rcnt == 1:
                        if mode == "pc2ps5":
                            orig_region = REGION_PRESETS["pc"][0]
                        else:
                            orig_region = REGION_PRESETS["ps5_eu_as"][0]
                    else:
                        orig_region = rval  # already matched target

                    f["_MainRegionHash"] = orig_region
                    f["_MainRegionHash_hex"] = f"0x{orig_region:08x}"
                    f["_MainRegionHash_target"] = rval
                    f["_MainRegionHash_target_hex"] = f"0x{rval:08x}"
                    f["region_patched"] = rcnt == 1
                    for key, (val, lbl) in REGION_PRESETS.items():
                        if val == orig_region:
                            f["platform_hint"] = lbl
                            break
                    else:
                        f["platform_hint"] = f"Unknown (0x{orig_region:08x})"

                if vval:
                    f["_ApplicationVersion"] = vval
                    f["_ApplicationVersion_hex"] = f"0x{vval:08x}"
                    f["version_patched"] = vcnt == 1
                    for key, (val, lbl) in VERSION_PRESETS.items():
                        if val == vval:
                            f["version_label"] = lbl
                            break
                    else:
                        f["version_label"] = f"Unknown (0x{vval:08x})"

                sm = re.search(r'Size:\s*(\d+)\s*bytes', out)
                if sm:
                    f["decrypted_size"] = int(sm.group(1))
                    f["decrypted_size_str"] = f"{int(sm.group(1))/1024:.1f} KB"

                fm = re.search(r'Flags:\s*(SaveFlags\([^)]+\))', out)
                if fm:
                    f["flags"] = fm.group(1)

                if f:
                    result["fields"] = f
                    result["success"] = True
                    result["detected_mode"] = mode
                    break
        except Exception as e:
            result["log"] += f"\nException in mode={mode}: {e}"
        finally:
            tmp.unlink(missing_ok=True)

    return result


# ── Garlic package builder ─────────────────────────────────────────────────────
def build_garlic_package(bin_files: list, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    keystone = bytes(96)
    icon0 = None
    icon0_p = SCE_TPL / "icon0.png"
    if icon0_p.exists():
        icon0 = icon0_p.read_bytes()

    built = []
    errors = []
    for bp in bin_files:
        p = Path(bp)
        if not p.exists():
            errors.append(f"Not found: {p}")
            continue
        m = re.match(r'^data(\d+)(?:Slot)?\.bin$', p.name, re.I)
        if not m:
            errors.append(f"Unrecognized name: {p.name}")
            continue

        slot = int(m.group(1))
        if slot == 0:
            folder = "sdimg_SAVESERVICE-LINE-0-0"
            fname  = "data000.bin"
        else:
            folder = f"sdimg_SAVESERVICE-LINE-0-{slot}Slot"
            fname  = f"data{slot:03d}Slot.bin"

        sd = out_dir / folder
        sc = sd / "sce_sys"
        sd.mkdir(parents=True, exist_ok=True)
        sc.mkdir(parents=True, exist_ok=True)

        shutil.copy2(str(p), str(sd / fname))
        (sc / "keystone").write_bytes(keystone)
        if icon0:
            (sc / "icon0.png").write_bytes(icon0)

        built.append({"slot": slot, "folder": folder, "file": fname, "path": str(sd)})

    return {"success": bool(built), "built": built, "errors": errors, "output_dir": str(out_dir)}


def build_garlic_zip(bin_files: list, zip_path: Path) -> dict:
    with tempfile.TemporaryDirectory() as td:
        res = build_garlic_package(bin_files, Path(td))
        if not res["success"]:
            return res
        with zipfile.ZipFile(str(zip_path), "w", zipfile.ZIP_DEFLATED) as z:
            for root, _, files in os.walk(td):
                for f in files:
                    fp = Path(root) / f
                    z.write(str(fp), fp.relative_to(td).as_posix())
        return {"success": True, "zip": str(zip_path), "built": res["built"]}


# ── Garlic HTTP API ────────────────────────────────────────────────────────────
def garlic_list_saves(ip: str, port: str) -> dict:
    url = f"http://{ip}:{port}/api/saves"
    try:
        with urllib.request.urlopen(url, timeout=3) as r:
            return {"success": True, "saves": json.loads(r.read())}
    except Exception as e:
        return {"success": False, "error": str(e)}


def garlic_push_file(ip: str, port: str, title_id: str, slot_folder: str,
                     local_bin: Path, bin_name: str) -> dict:
    base = f"http://{ip}:{port}"
    try:
        # list saves to find the right index
        with urllib.request.urlopen(f"{base}/api/saves", timeout=3) as r:
            saves = json.loads(r.read())
        idx = None
        for i, s in enumerate(saves.get("saves", [])):
            if s.get("title_id") == title_id:
                idx = i
                break
        if idx is None:
            return {"success": False, "error": f"No save slot found for {title_id}"}

        # mount
        with urllib.request.urlopen(f"{base}/api/mount?idx={idx}", timeout=5) as r:
            mount_info = json.loads(r.read())

        # upload bin
        with open(local_bin, "rb") as f:
            data = f.read()
        req = urllib.request.Request(
            f"{base}/api/upload_file?name={urllib.parse.quote(bin_name)}",
            data=data, headers={"Content-Type": "application/octet-stream"})
        with urllib.request.urlopen(req, timeout=10) as r:
            up_info = json.loads(r.read())

        # unmount
        with urllib.request.urlopen(f"{base}/api/unmount", timeout=5) as r:
            unm_info = json.loads(r.read())

        return {"success": True, "mount": mount_info, "upload": up_info, "unmount": unm_info}
    except Exception as e:
        try:
            urllib.request.urlopen(f"{base}/api/unmount", timeout=2)
        except Exception:
            pass
        return {"success": False, "error": str(e)}


# ── Garlic ZIP import ─────────────────────────────────────────────────────────
def import_garlic_zip(zip_path: Path, out_dir: Path) -> dict:
    """Extract .bin saves from a Garlic-format ZIP into out_dir, return list of saves."""
    out_dir.mkdir(parents=True, exist_ok=True)
    saves = []
    errors = []
    try:
        with zipfile.ZipFile(zip_path) as z:
            for entry in z.namelist():
                parts = entry.replace("\\", "/").split("/")
                # Garlic structure: TITLE_ID/FOLDER/file.bin  or  TITLE_ID/FOLDER/sce_sys/...
                # We only want the .bin files directly in a slot folder
                if len(parts) >= 3 and parts[-1].lower().endswith(".bin") and "sce_sys" not in entry:
                    folder    = parts[-2]  # e.g. sdimg_SAVESERVICE-LINE-0-10
                    orig_name = parts[-1]   # e.g. data010.bin
                    # Normalize filename to our canonical naming scheme
                    m = re.match(r'^data(\d+)(?:Slot)?\.bin$', orig_name, re.I)
                    if not m:
                        # Try alternate: save.bin → unnamed, skip
                        if orig_name.lower() == "save.bin":
                            # Infer slot from folder
                            fm = re.search(r'-(\d+)(?:Slot)?$', folder)
                            slot = int(fm.group(1)) if fm else 0
                        else:
                            errors.append(f"Unrecognized name: {entry}")
                            continue
                    else:
                        slot = int(m.group(1))

                    # Extract
                    dest_name = f"data{slot:03d}Slot.bin" if slot > 0 else "data000.bin"
                    dest = out_dir / dest_name
                    dest.write_bytes(z.read(entry))
                    info = inspect_file(dest)
                    info["garlic_folder"] = folder
                    info["slot"] = slot
                    saves.append(info)
    except Exception as e:
        return {"success": False, "error": str(e)}

    saves.sort(key=lambda s: s.get("slot", 999))
    return {"success": True, "saves": saves, "output_dir": str(out_dir), "errors": errors}


# ── Hex patch (save editor) via binary chain ───────────────────────────────────
PC_REGION_VAL = 1874947740  # hardcoded in binary's pc2ps5/ps52pc modes

def hex_patch_save(file_path: Path, source_id: str, target_id: str, mode: str,
                   patches: list, region_hash: str, app_version: str) -> dict:
    """
    Apply arbitrary 4-byte find→replace patches to a save file.

    Strategy (bypasses binary's hardcoded search values):
    For each patch (find_val → replace_val):
      1. If find_val == PC_REGION_VAL (1874947740):
           Use pc2ps5/ps52pc normally (binary searches for PC_REGION hardcoded)
      2. Otherwise, chain:
           Step A: ps52pc with region=find_val → replaces find_val with PC_REGION_VAL
           Step B: pc2ps5 with region=replace_val → replaces PC_REGION_VAL with replace_val
      Note: this is safe as long as find_val/replace_val ≠ PC_REGION_VAL and
            PC_REGION_VAL doesn't appear elsewhere with meaning in the save.

    patches: list of {"find": int, "replace": int, "label": str}
    """
    if not CONV_BIN.exists():
        return {"success": False, "error": "Converter binary not found"}

    logs = []
    current = file_path

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        step = 0

        for patch in patches:
            find_val    = int(patch["find"])
            replace_val = int(patch["replace"])
            label       = patch.get("label", f"{find_val}→{replace_val}")

            if find_val == replace_val:
                logs.append(f"Skip {label}: same value")
                continue

            if find_val == PC_REGION_VAL:
                # Direct: binary in pc2ps5 mode will find PC_REGION and replace with replace_val
                out = td / f"step{step}.bin"
                cmd = [str(CONV_BIN), str(current), str(out),
                       source_id, target_id, mode, str(replace_val), app_version]
                try:
                    p = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                    out_txt = p.stdout + p.stderr
                    rcnt = re.search(r'Region=(\d+)', out_txt)
                    logs.append(f"[{label}] direct patch: Region={rcnt.group(1) if rcnt else '?'} rc={p.returncode}")
                    if p.returncode != 0:
                        return {"success": False, "error": f"Patch failed at step {step}", "log": "\n".join(logs)}
                    current = out
                    step += 1
                except Exception as e:
                    return {"success": False, "error": str(e), "log": "\n".join(logs)}
            else:
                # Chain: A) find_val → PC_REGION_VAL, B) PC_REGION_VAL → replace_val
                # Step A: Use ps52pc with same source/target ID, region=find_val (binary replaces find_val→PC_REGION)
                # Step B: Use pc2ps5 with same source/target ID, region=replace_val (binary replaces PC_REGION→replace_val)
                mid = td / f"step{step}_mid.bin"
                out = td / f"step{step}.bin"

                # Step A
                # In ps52pc mode: searches for target_region param → replaces with PC_REGION (hardcoded)
                # We pass source_id as BOTH source and target to keep encryption key same
                # Mode is always "ps52pc" for step A regardless of original mode
                probe_mode_a = "ps52pc" if mode in ("ps52pc", "pc2pc") else "ps52pc"
                cmd_a = [str(CONV_BIN), str(current), str(mid),
                         source_id, source_id, probe_mode_a, str(find_val), app_version]
                try:
                    pa = subprocess.run(cmd_a, capture_output=True, text=True, timeout=60)
                    out_a = pa.stdout + pa.stderr
                    rcnt_a = re.search(r'Region=(\d+)', out_a)
                    n_found = int(rcnt_a.group(1)) if rcnt_a else 0
                    logs.append(f"[{label}] step A (find {find_val}→PC_REGION): Region={n_found} rc={pa.returncode}")
                    if pa.returncode != 0:
                        return {"success": False, "error": f"Chain step A failed at patch '{label}'", "log": "\n".join(logs)}
                    if n_found == 0:
                        logs.append(f"  → value {find_val} (0x{find_val:08x}) not found in save, skipping")
                        continue  # skip step B, nothing to do
                except Exception as e:
                    return {"success": False, "error": str(e), "log": "\n".join(logs)}

                # Step B: replace PC_REGION_VAL → replace_val
                probe_mode_b = "pc2ps5" if mode in ("pc2ps5", "pc2pc") else "pc2ps5"
                cmd_b = [str(CONV_BIN), str(mid), str(out),
                         source_id, target_id, probe_mode_b, str(replace_val), app_version]
                try:
                    pb = subprocess.run(cmd_b, capture_output=True, text=True, timeout=60)
                    out_b = pb.stdout + pb.stderr
                    rcnt_b = re.search(r'Region=(\d+)', out_b)
                    logs.append(f"[{label}] step B (PC_REGION→{replace_val}): Region={rcnt_b.group(1) if rcnt_b else '?'} rc={pb.returncode}")
                    if pb.returncode != 0:
                        return {"success": False, "error": f"Chain step B failed at patch '{label}'", "log": "\n".join(logs)}
                    current = out
                    step += 1
                except Exception as e:
                    return {"success": False, "error": str(e), "log": "\n".join(logs)}

        # Copy final result to uploads
        if step == 0:
            return {"success": True, "log": "\n".join(logs), "output": str(file_path),
                    "note": "No patches applied (all values already matched or not found)"}

        out_name = f"patched_{file_path.name}"
        final = UPLOADS / out_name
        shutil.copy2(str(current), str(final))
        return {"success": True, "log": "\n".join(logs), "output": str(final),
                "output_name": out_name, "patches_applied": step}


# ── Python brute-force Steam ID ────────────────────────────────────────────────
def bruteforce_steam_id_py(file_path: Path, start: int = 0, end: int = 100000,
                            ps5_id: str = DEFAULT_PS5_ID) -> dict:
    """
    Brute-force Steam32 ID by probing with convert_re9_ps5 binary.
    Returns found steam64 or failure.
    """
    if not CONV_BIN.exists():
        return {"success": False, "error": "Converter binary not found"}
    if not file_path.exists():
        return {"success": False, "error": f"File not found: {file_path}"}

    STEAM_BASE = 76561197960265728

    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tf:
        tmp = Path(tf.name)

    try:
        for s32 in range(start, end + 1):
            s64 = STEAM_BASE + s32
            cmd = [str(CONV_BIN), str(file_path), str(tmp),
                   str(s64), str(s64), "pc2pc", "1874947740", "16781314"]
            try:
                p = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                out = p.stdout + p.stderr
                if p.returncode == 0 and "key mismatch" not in out.lower() and "checksum" not in out.lower():
                    return {
                        "success": True,
                        "steam32": s32,
                        "steam64": s64,
                        "log": f"Found at steam32={s32} (steam64={s64})"
                    }
            except subprocess.TimeoutExpired:
                continue
            except Exception:
                continue
    finally:
        tmp.unlink(missing_ok=True)

    return {"success": False, "error": f"Steam ID not found in range {start}–{end}"}


# ── Split Fiction (Unreal Engine) conversion ───────────────────────────────────
def convert_split_fiction(src: Path, dst: Path, mode: str,
                           src_id: str, tgt_id: str) -> dict:
    try:
        with open(src, "r", encoding="utf-8") as f:
            data = json.load(f)
        dst.parent.mkdir(parents=True, exist_ok=True)

        if mode == "pc2ps5":
            if "UID" in data:
                data["UID"] = tgt_id
            out = {"Profile": data}
        else:  # ps52pc
            prof = data.get("Profile", data)
            if "UID" in prof:
                prof["UID"] = tgt_id
            out = prof

        with open(dst, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        return {"success": True, "output": str(dst)}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── HTTP handler ───────────────────────────────────────────────────────────────
class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def log_message(self, fmt, *args):
        pass  # silence access log

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path   = parsed.path
        query  = urllib.parse.parse_qs(parsed.query)

        # ── config ──
        if path == "/api/config":
            profiles = []
            if PROFILES_DIR.exists():
                for f in sorted(PROFILES_DIR.glob("*.bin")):
                    profiles.append({"name": f.stem, "path": str(f)})
            self.send_json({
                "defaults": {
                    "steam_id":    DEFAULT_STEAM_ID,
                    "ps5_id":      DEFAULT_PS5_ID,
                    "title_id":    DEFAULT_TITLE_ID,
                    "region_hash": DEFAULT_REGION_HASH,
                    "app_version": DEFAULT_APP_VERSION,
                },
                "region_presets": {k: {"value": v, "label": l}
                                   for k, (v, l) in REGION_PRESETS.items()},
                "version_presets": {k: {"value": v, "label": l}
                                    for k, (v, l) in VERSION_PRESETS.items()},
                "mj_available": MJ_BIN.exists(),
                "conv_available": CONV_BIN.exists(),
                "profiles": profiles,
            })
            return

        # ── scan directory ──
        if path == "/api/scan":
            d = query.get("dir", [None])[0]
            if not d:
                self.send_json({"success": False, "error": "dir param missing"})
                return
            saves = scan_dir(Path(d))
            self.send_json({"success": True, "dir": d, "saves": saves})
            return

        # ── list game profiles ──
        if path == "/api/list_profiles":
            profiles = []
            if PROFILES_DIR.exists():
                for f in sorted(PROFILES_DIR.glob("*.bin")):
                    profiles.append({"name": f.stem, "path": str(f)})
            self.send_json({"success": True, "profiles": profiles})
            return

        # ── PS5 Garlic status ──
        if path == "/api/ps5_status":
            ip   = query.get("ip",   ["192.168.1.173"])[0]
            port = query.get("port", ["8082"])[0]
            res = garlic_list_saves(ip, port)
            self.send_json(res)
            return

        # ── download converted output as ZIP ──
        if path == "/api/download":
            fp = query.get("file", [None])[0]
            if not fp or not Path(fp).exists():
                self.send_error(404, "File not found")
                return
            p = Path(fp)
            data = p.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Disposition", f'attachment; filename="{p.name}"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path   = parsed.path
        length = int(self.headers.get("Content-Length", 0))

        # ── file upload ──
        if path == "/api/upload":
            q = urllib.parse.parse_qs(parsed.query)
            fname = os.path.basename(q.get("name", ["upload.bin"])[0])
            stem  = Path(fname).stem  # filename without extension
            payload = self.rfile.read(length)

            if fname.lower().endswith(".zip"):
                # ZIP: save next to its own named folder
                zip_dest = UPLOADS / fname
                zip_dest.write_bytes(payload)
                udir = UPLOADS / f"unzip_{int(time.time())}"
                udir.mkdir()
                with zipfile.ZipFile(zip_dest) as z:
                    z.extractall(udir)
                saves = scan_dir(udir)
                self.send_json({"success": True, "is_archive": True,
                                "zip_path": str(zip_dest),
                                "dir": str(udir), "saves": saves})
            else:
                # Single file: put into its own folder named after the file stem
                slot_dir = UPLOADS / stem
                slot_dir.mkdir(exist_ok=True)
                dest = slot_dir / fname
                dest.write_bytes(payload)
                info = inspect_file(dest)
                self.send_json({"success": True, "is_archive": False,
                                "dir": str(slot_dir), "saves": [info]})
            return

        body = self.rfile.read(length).decode("utf-8") if length else "{}"
        try:
            req = json.loads(body)
        except Exception:
            req = {}

        # ── single file convert ──
        if path == "/api/convert":
            src    = Path(req.get("source_file", ""))
            dst    = Path(req.get("output_file", str(UPLOADS / "output.bin")))
            mode   = req.get("mode", "pc2ps5")
            engine = req.get("engine", "re_engine")
            sid    = req.get("source_id", DEFAULT_STEAM_ID)
            tid    = req.get("target_id", DEFAULT_PS5_ID)
            rhash  = req.get("region_hash", DEFAULT_REGION_HASH)
            aver   = req.get("app_version", DEFAULT_APP_VERSION)

            if not src.exists():
                self.send_json({"success": False, "error": f"File not found: {src}"})
                return

            if engine == "unreal_engine":
                res = convert_split_fiction(src, dst, mode, sid, tid)
            else:
                res = convert_re(src, dst, sid, tid, mode, rhash, aver)

            self.send_json(res)
            return

        # ── batch convert directory ──
        if path == "/api/convert_batch":
            src_dir = Path(req.get("source_dir", ""))
            out_dir = Path(req.get("output_dir", str(UPLOADS / "batch_out")))
            mode    = req.get("mode", "pc2ps5")
            sid     = req.get("source_id", DEFAULT_STEAM_ID)
            tid     = req.get("target_id", DEFAULT_PS5_ID)
            rhash   = req.get("region_hash", DEFAULT_REGION_HASH)
            aver    = req.get("app_version", DEFAULT_APP_VERSION)

            res = batch_convert_re(src_dir, out_dir, sid, tid, mode, rhash, aver)
            self.send_json(res)
            return

        # ── auto-detect platform + field values ──
        if path == "/api/autodetect":
            fp      = Path(req.get("file_path", ""))
            steam   = req.get("steam_id", DEFAULT_STEAM_ID)
            ps5     = req.get("ps5_id",   DEFAULT_PS5_ID)
            if not fp.exists():
                self.send_json({"success": False, "error": f"File not found: {fp}"})
                return
            res = autodetect_save(fp, steam, ps5)
            self.send_json(res)
            return

        # ── field inspector ──
        if path == "/api/inspect_fields":
            fp  = Path(req.get("file_path", ""))
            sid = req.get("source_id", DEFAULT_STEAM_ID)
            if not fp.exists():
                self.send_json({"success": False, "error": f"File not found: {fp}"})
                return
            res = inspect_re_fields(fp, sid)
            self.send_json(res)
            return

        # ── List game profiles ──
        if path == "/api/list_profiles":
            profiles = []
            if PROFILES_DIR.exists():
                for f in sorted(PROFILES_DIR.glob("*.bin")):
                    profiles.append({"name": f.stem, "path": str(f)})
            self.send_json({"success": True, "profiles": profiles})
            return

        # ── MandarinJuice brute force ──
        if path == "/api/bruteforce":
            save_path    = Path(req.get("save_path", ""))
            profile_path = Path(req.get("game_profile", ""))
            res = mj_brute_force(save_path, profile_path, MJ_BIN)
            self.send_json(res)
            return

        # ── MandarinJuice re-sign ──
        if path == "/api/mj_resign":
            save_dir = Path(req.get("save_dir", ""))
            profile  = Path(req.get("game_profile", ""))
            old_id   = req.get("old_id", DEFAULT_STEAM_ID)
            new_id   = req.get("new_id", DEFAULT_PS5_ID)
            res = mj_resign(save_dir, profile, MJ_BIN, old_id, new_id)
            self.send_json(res)
            return

        # ── Build Garlic BROWSE package ──
        if path == "/api/garlic_package":
            files   = req.get("files", [])
            out_dir = Path(req.get("output_dir", str(UPLOADS / "garlic_out")))
            as_zip  = req.get("as_zip", False)

            if as_zip:
                zip_path = Path(req.get("zip_path", str(UPLOADS / "garlic_package.zip")))
                res = build_garlic_zip(files, zip_path)
                if res.get("success"):
                    res["download_url"] = f"/api/download?file={urllib.parse.quote(str(zip_path))}"
            else:
                res = build_garlic_package(files, out_dir)

            self.send_json(res)
            return

        # ── Direct PS5 push via Garlic HTTP ──
        if path == "/api/garlic_push":
            ip        = req.get("ip", "192.168.1.173")
            port      = req.get("port", "8082")
            title_id  = req.get("title_id", DEFAULT_TITLE_ID)
            slot_folder = req.get("slot_folder", "")
            bin_path  = Path(req.get("bin_path", ""))
            bin_name  = req.get("bin_name", bin_path.name)
            if not bin_path.exists():
                self.send_json({"success": False, "error": f"File not found: {bin_path}"})
                return
            res = garlic_push_file(ip, port, title_id, slot_folder, bin_path, bin_name)
            self.send_json(res)
            return

        # ── open folder in file manager ──
        if path == "/api/open_folder":
            folder = req.get("folder", "")
            try:
                subprocess.Popen(["xdg-open", folder])
                self.send_json({"success": True})
            except Exception as e:
                self.send_json({"success": False, "error": str(e)})
            return

        # ── Garlic ZIP import ──
        if path == "/api/garlic_import":
            zip_fp = Path(req.get("zip_path", ""))
            # Default output folder: named after the ZIP file stem (e.g. "RE9-Slots10-21-Garlic")
            default_out = UPLOADS / zip_fp.stem if zip_fp.name else UPLOADS / f"garlic_import_{int(time.time())}"
            out_dir = Path(req.get("output_dir", str(default_out)))
            if not zip_fp.exists():
                self.send_json({"success": False, "error": f"ZIP not found: {zip_fp}"})
                return
            res = import_garlic_zip(zip_fp, out_dir)
            self.send_json(res)
            return

        # ── Hex patch (save editor) ──
        if path == "/api/hex_patch":
            fp       = Path(req.get("file_path", ""))
            sid      = req.get("source_id", DEFAULT_STEAM_ID)
            tid      = req.get("target_id", req.get("source_id", DEFAULT_STEAM_ID))
            mode     = req.get("mode", "ps52pc")
            patches  = req.get("patches", [])
            rhash    = req.get("region_hash", DEFAULT_REGION_HASH)
            aver     = req.get("app_version", DEFAULT_APP_VERSION)
            if not fp.exists():
                self.send_json({"success": False, "error": f"File not found: {fp}"})
                return
            if not patches:
                self.send_json({"success": False, "error": "No patches specified"})
                return
            res = hex_patch_save(fp, sid, tid, mode, patches, rhash, aver)
            if res.get("success") and res.get("output"):
                outp = Path(res["output"])
                res["download_url"] = f"/api/download?file={urllib.parse.quote(str(outp))}"
            self.send_json(res)
            return

        # ── Python brute-force Steam ID ──
        if path == "/api/bruteforce_py":
            fp      = Path(req.get("file_path", ""))
            start   = int(req.get("start", 0))
            end     = int(req.get("end", 100000))
            ps5_id  = req.get("ps5_id", DEFAULT_PS5_ID)
            if not fp.exists():
                self.send_json({"success": False, "error": f"File not found: {fp}"})
                return
            if end - start > 500000:
                self.send_json({"success": False, "error": "Range too large (max 500000)"})
                return
            res = bruteforce_steam_id_py(fp, start, end, ps5_id)
            self.send_json(res)
            return

        self.send_error(404, f"Unknown endpoint: {path}")


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    print(f"RE9 Save Manager")
    print(f"  convert_re9_ps5 : {'✓ ' + str(CONV_BIN) if CONV_BIN.exists() else '✗ NOT FOUND — place binary next to server.py'}")
    print(f"  MandarinJuice   : {'✓ ' + str(MJ_BIN) if MJ_BIN.exists() else '✗ NOT FOUND — set MJ_BIN env var'}")
    print(f"  sce_sys template: {'✓' if SCE_TPL.exists() else '✗ NOT FOUND'}")
    print(f"\nOpen http://localhost:{PORT}\n")
    with Server(("", PORT), Handler) as s:
        s.serve_forever()


if __name__ == "__main__":
    main()
