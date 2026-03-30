"""Font builder engine for Crimson Desert modding.

Supports:
1. Extract game font from PAZ (LZ4 decompress, NO decryption)
2. Replace entire TTF with custom font
3. Add script glyphs from a donor font
4. Merge GSUB/GDEF/GPOS tables when a script needs shaping
5. Patch font back to PAZ with full checksum chain

CRITICAL from ReadMetoSeeCorrectWay.md:
- Fonts are LZ4 ONLY, NOT encrypted (no ChaCha20)
- sefont/ directory must NOT contain modified fonts
- Always update PAMT comp/orig sizes after font size change
"""

import io
import os
import copy
import struct
from dataclasses import dataclass, field
from typing import Optional, Callable

from fontTools.ttLib import TTFont
from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.pens.ttGlyphPen import TTGlyphPen

from core.pamt_parser import parse_pamt, PamtData, PamtFileEntry, update_pamt_paz_entry, update_pamt_file_entry, update_pamt_self_crc
from core.papgt_manager import parse_papgt, get_pamt_crc_offset, update_papgt_pamt_crc, update_papgt_self_crc
from core.paz_write_utils import build_space_map, write_entry_payload
from core.checksum_engine import pa_checksum, checksum_file
from core.compression_engine import decompress, compress
from core.backup_manager import BackupManager
from utils.platform_utils import get_file_timestamps, set_file_timestamps, atomic_write
from utils.logger import get_logger

logger = get_logger("core.font_builder")


@dataclass
class FontBuildResult:
    """Result of a font build + patch operation."""
    success: bool
    message: str
    original_size: int = 0
    new_size: int = 0
    glyphs_added: int = 0
    pua_glyphs_added: int = 0
    paz_crc: int = 0
    pamt_crc: int = 0
    papgt_crc: int = 0
    backup_dir: str = ""
    errors: list[str] = field(default_factory=list)


@dataclass
class FontInfo:
    """Information about a font file in the game archives."""
    filename: str
    path: str
    paz_file: str
    offset: int
    comp_size: int
    orig_size: int
    paz_index: int
    compression_type: int
    encrypted: bool
    group: str
    entry: PamtFileEntry


def find_game_fonts(packages_path: str) -> list[FontInfo]:
    """Scan all package groups for font files (.ttf, .otf)."""
    fonts = []
    for grp in sorted(os.listdir(packages_path)):
        pamt_path = os.path.join(packages_path, grp, "0.pamt")
        if not os.path.isfile(pamt_path):
            continue
        try:
            pamt = parse_pamt(pamt_path, paz_dir=os.path.join(packages_path, grp))
            for entry in pamt.file_entries:
                ext = os.path.splitext(entry.path.lower())[1]
                if ext in (".ttf", ".otf", ".woff", ".woff2"):
                    fonts.append(FontInfo(
                        filename=os.path.basename(entry.path),
                        path=entry.path,
                        paz_file=entry.paz_file,
                        offset=entry.offset,
                        comp_size=entry.comp_size,
                        orig_size=entry.orig_size,
                        paz_index=entry.paz_index,
                        compression_type=entry.compression_type,
                        encrypted=entry.encrypted,
                        group=grp,
                        entry=entry,
                    ))
        except Exception as e:
            logger.warning("Error scanning %s for fonts: %s", grp, e)
    return fonts


def extract_font(font_info: FontInfo) -> bytes:
    """Extract a font file from PAZ (decompress, NO decrypt for fonts)."""
    with open(font_info.paz_file, "rb") as f:
        f.seek(font_info.offset)
        data = f.read(font_info.comp_size)

    if font_info.compression_type == 2:
        data = decompress(data, font_info.orig_size, 2)

    return data


def load_ttfont(data: bytes) -> TTFont:
    """Load a TTFont from raw bytes."""
    return TTFont(io.BytesIO(data))


def save_ttfont(font: TTFont) -> bytes:
    """Save a TTFont to raw bytes.

    If compilation fails due to GSUB/GPOS referencing missing glyphs,
    strips the offending tables and retries — the font will still render
    correctly, it just loses some ligature/positioning rules.
    """
    buf = io.BytesIO()
    try:
        font.save(buf)
        return buf.getvalue()
    except (KeyError, struct.error, OverflowError) as e:
        logger.warning("Font save failed: %s — applying fixes and retrying", e)

        # Fix 1: Force recalcBBoxes to clamp glyph coordinates to valid range
        # CJK/Korean fonts can have coordinates > 65535 which overflow 'H' format
        if "glyf" in font:
            for glyph_name in font.getGlyphOrder():
                try:
                    g = font["glyf"][glyph_name]
                    if hasattr(g, "xMin"):
                        g.xMin = max(-32768, min(32767, g.xMin))
                        g.yMin = max(-32768, min(32767, g.yMin))
                        g.xMax = max(-32768, min(32767, g.xMax))
                        g.yMax = max(-32768, min(32767, g.yMax))
                except Exception:
                    pass

        # Fix 2: Strip broken GSUB/GPOS/GDEF tables
        for table_tag in ("GSUB", "GPOS", "GDEF"):
            if table_tag in font:
                try:
                    font[table_tag].compile(font)
                except Exception:
                    logger.warning("Removing broken %s table from font", table_tag)
                    del font[table_tag]

        buf = io.BytesIO()
        font.save(buf)
        return buf.getvalue()


def get_font_stats(font: TTFont) -> dict:
    """Get statistics about a font including per-script coverage."""
    from core.script_ranges import detect_font_scripts, SCRIPT_REGISTRY
    cmap = font.getBestCmap()
    glyph_order = font.getGlyphOrder()
    pua = [cp for cp in cmap if 0xE000 <= cp <= 0xF8FF]
    scripts = detect_font_scripts(cmap)
    gsub_scripts = []
    if "GSUB" in font:
        for sr in font["GSUB"].table.ScriptList.ScriptRecord:
            gsub_scripts.append(sr.ScriptTag)
    return {
        "total_glyphs": len(glyph_order),
        "cmap_entries": len(cmap),
        "scripts": scripts,
        "pua_glyphs": len(pua),
        "gsub_scripts": gsub_scripts,
        "units_per_em": font["head"].unitsPerEm,
    }


def add_script_glyphs(
    target_font: TTFont,
    donor_font: TTFont,
    script_name: str,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> dict:
    """Add glyphs for a specific script from a donor font.

    Copies glyphs at their original codepoints and merges GSUB/GDEF/GPOS
    when the script needs shaping.

    Args:
        target_font: The game font to modify.
        donor_font: Font to copy glyphs from (e.g. NotoSans for the target script).
        script_name: Script name from SCRIPT_REGISTRY (e.g. "Cyrillic").
        progress_callback: callback(done, total, message).

    Returns dict with stats.
    """
    from core.script_ranges import SCRIPT_REGISTRY
    script_info = SCRIPT_REGISTRY.get(script_name)
    if not script_info:
        raise ValueError(f"Unknown script: {script_name}. Available: {list(SCRIPT_REGISTRY.keys())}")

    return _add_glyphs_direct(target_font, donor_font, script_info, progress_callback)


def _add_glyphs_direct(
    target_font: TTFont,
    donor_font: TTFont,
    script_info,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> dict:
    """Copy glyphs from donor font at their original codepoints."""
    target_cmap = target_font.getBestCmap()
    donor_cmap = donor_font.getBestCmap()
    target_go = list(target_font.getGlyphOrder())
    target_glyf = target_font["glyf"]
    target_hmtx = target_font["hmtx"]
    donor_glyf = donor_font["glyf"]
    donor_hmtx = donor_font["hmtx"]

    target_upm = target_font["head"].unitsPerEm
    donor_upm = donor_font["head"].unitsPerEm
    scale = target_upm / donor_upm if target_upm != donor_upm else 1.0

    codepoints_to_add = []
    for start, end in script_info.ranges:
        for cp in range(start, end + 1):
            if cp in donor_cmap and cp not in target_cmap:
                codepoints_to_add.append(cp)

    stats = {"glyphs_added": 0, "codepoints_mapped": 0, "errors": []}
    total = len(codepoints_to_add)

    for idx, cp in enumerate(codepoints_to_add):
        donor_name = donor_cmap[cp]
        new_name = f"uni{cp:04X}"
        if new_name in target_go:
            new_name = f"u{cp:05X}"

        try:
            if donor_name not in donor_glyf:
                continue
            src = donor_glyf[donor_name]
            if src.numberOfContours == 0 and not src.isComposite():
                pen = TTGlyphPen(None)
                target_glyf[new_name] = pen.glyph()
            else:
                rec_pen = DecomposingRecordingPen(donor_font.getGlyphSet())
                donor_font.getGlyphSet()[donor_name].draw(rec_pen)
                pen = TTGlyphPen(None)
                if scale != 1.0:
                    for op, args in rec_pen.value:
                        if op == "moveTo":
                            pen.moveTo(*[(int(x * scale), int(y * scale)) for x, y in args])
                        elif op == "lineTo":
                            pen.lineTo(*[(int(x * scale), int(y * scale)) for x, y in args])
                        elif op == "qCurveTo":
                            pen.qCurveTo(*[(int(x * scale), int(y * scale)) for x, y in args])
                        elif op == "closePath":
                            pen.closePath()
                        elif op == "endPath":
                            pen.endPath()
                else:
                    rec_pen.replay(pen)
                target_glyf[new_name] = pen.glyph()

            if donor_name in donor_hmtx.metrics:
                w, lsb = donor_hmtx.metrics[donor_name]
                target_hmtx.metrics[new_name] = (int(w * scale), int(lsb * scale))
            else:
                target_hmtx.metrics[new_name] = (600, 0)

            target_go.append(new_name)
            for table in target_font["cmap"].tables:
                if not hasattr(table, "cmap"):
                    continue
                if table.format == 0 and cp > 255:
                    continue
                table.cmap[cp] = new_name
            stats["glyphs_added"] += 1
            stats["codepoints_mapped"] += 1
        except Exception as e:
            stats["errors"].append(f"U+{cp:04X}: {e}")

        if progress_callback and (idx + 1) % 50 == 0:
            progress_callback(idx + 1, total, f"Copying glyphs: {idx + 1}/{total}")

    target_font.setGlyphOrder(target_go)
    target_font["maxp"].numGlyphs = len(target_go)

    if script_info.needs_gsub:
        if "GSUB" in target_font and "GSUB" in donor_font:
            try:
                _merge_gsub(target_font, donor_font)
            except Exception as e:
                stats["errors"].append(f"GSUB merge: {e}")
        if "GDEF" in target_font and "GDEF" in donor_font:
            try:
                _merge_gdef(target_font, donor_font)
            except Exception as e:
                stats["errors"].append(f"GDEF merge: {e}")
        if "GPOS" in target_font and "GPOS" in donor_font:
            try:
                _merge_gpos(target_font, donor_font)
            except Exception as e:
                stats["errors"].append(f"GPOS merge: {e}")

    if progress_callback:
        progress_callback(total, total, f"Added {stats['glyphs_added']} glyphs")

    return stats


def _lookup_references_missing_glyphs(lookup, glyph_order_set):
    """Check if a GSUB lookup references glyphs not in the target font."""
    try:
        for subtable in lookup.SubTable:
            # Check Coverage tables for missing glyphs
            if hasattr(subtable, "Coverage") and subtable.Coverage:
                for glyph in subtable.Coverage.glyphs:
                    if glyph not in glyph_order_set:
                        return True
            # Check substitution mappings
            if hasattr(subtable, "mapping"):
                for g in list(subtable.mapping.keys()) + list(subtable.mapping.values()):
                    if g not in glyph_order_set:
                        return True
    except Exception:
        return True
    return False


def _merge_gsub(target_font, donor_font):
    """Merge GSUB features from a donor font.

    Only copies lookups whose glyphs all exist in the target font,
    preventing KeyError crashes during font compilation.
    """
    target_gsub = target_font["GSUB"].table
    donor_gsub = donor_font["GSUB"].table
    target_go_set = set(target_font.getGlyphOrder())
    existing_count = len(target_gsub.LookupList.Lookup)
    lookup_map = {}

    for i, lookup in enumerate(donor_gsub.LookupList.Lookup):
        # Skip lookups that reference glyphs missing from target
        if _lookup_references_missing_glyphs(lookup, target_go_set):
            continue
        new_lookup = copy.deepcopy(lookup)
        new_idx = existing_count + len(lookup_map)
        target_gsub.LookupList.Lookup.append(new_lookup)
        lookup_map[i] = new_idx

    feature_map = {}
    for i, fr in enumerate(donor_gsub.FeatureList.FeatureRecord):
        new_fr = copy.deepcopy(fr)
        new_fr.Feature.LookupListIndex = [lookup_map[li] for li in fr.Feature.LookupListIndex if li in lookup_map]
        if new_fr.Feature.LookupListIndex:
            new_idx = len(target_gsub.FeatureList.FeatureRecord)
            target_gsub.FeatureList.FeatureRecord.append(new_fr)
            feature_map[i] = new_idx

    for sr in donor_gsub.ScriptList.ScriptRecord:
        new_script = copy.deepcopy(sr)
        if new_script.Script.DefaultLangSys:
            new_script.Script.DefaultLangSys.FeatureIndex = [
                feature_map[fi] for fi in new_script.Script.DefaultLangSys.FeatureIndex if fi in feature_map
            ]
        for lang_sys_record in getattr(new_script.Script, "LangSysRecord", []):
            lang_sys_record.LangSys.FeatureIndex = [
                feature_map[fi] for fi in lang_sys_record.LangSys.FeatureIndex if fi in feature_map
            ]
        target_gsub.ScriptList.ScriptRecord.append(new_script)

    target_gsub.LookupList.LookupCount = len(target_gsub.LookupList.Lookup)
    target_gsub.FeatureList.FeatureCount = len(target_gsub.FeatureList.FeatureRecord)
    target_gsub.ScriptList.ScriptCount = len(target_gsub.ScriptList.ScriptRecord)


def _merge_gdef(target_font, donor_font):
    """Merge glyph class definitions from a donor font."""
    target_gdef = target_font["GDEF"].table
    donor_gdef = donor_font["GDEF"].table
    target_go = target_font.getGlyphOrder()
    if donor_gdef.GlyphClassDef and target_gdef.GlyphClassDef:
        for glyph, cls in donor_gdef.GlyphClassDef.classDefs.items():
            if glyph in target_go and glyph not in target_gdef.GlyphClassDef.classDefs:
                target_gdef.GlyphClassDef.classDefs[glyph] = cls


def _merge_gpos(target_font, donor_font):
    """Merge GPOS features from a donor font.

    Skips lookups that reference glyphs missing from the target font.
    """
    target_gpos = target_font["GPOS"].table
    donor_gpos = donor_font["GPOS"].table
    target_go_set = set(target_font.getGlyphOrder())
    existing_count = len(target_gpos.LookupList.Lookup)
    lookup_map = {}
    for i, lookup in enumerate(donor_gpos.LookupList.Lookup):
        if _lookup_references_missing_glyphs(lookup, target_go_set):
            continue
        target_gpos.LookupList.Lookup.append(copy.deepcopy(lookup))
        lookup_map[i] = existing_count + len(lookup_map)

    feature_map = {}
    for i, fr in enumerate(donor_gpos.FeatureList.FeatureRecord):
        new_fr = copy.deepcopy(fr)
        new_fr.Feature.LookupListIndex = [lookup_map[li] for li in fr.Feature.LookupListIndex if li in lookup_map]
        if new_fr.Feature.LookupListIndex:
            new_idx = len(target_gpos.FeatureList.FeatureRecord)
            target_gpos.FeatureList.FeatureRecord.append(new_fr)
            feature_map[i] = new_idx

    for sr in donor_gpos.ScriptList.ScriptRecord:
        new_script = copy.deepcopy(sr)
        if new_script.Script.DefaultLangSys:
            new_script.Script.DefaultLangSys.FeatureIndex = [
                feature_map[fi] for fi in new_script.Script.DefaultLangSys.FeatureIndex if fi in feature_map
            ]
        for lang_sys_record in getattr(new_script.Script, "LangSysRecord", []):
            lang_sys_record.LangSys.FeatureIndex = [
                feature_map[fi] for fi in lang_sys_record.LangSys.FeatureIndex if fi in feature_map
            ]
        target_gpos.ScriptList.ScriptRecord.append(new_script)

    target_gpos.LookupList.LookupCount = len(target_gpos.LookupList.Lookup)
    target_gpos.FeatureList.FeatureCount = len(target_gpos.FeatureList.FeatureRecord)
    target_gpos.ScriptList.ScriptCount = len(target_gpos.ScriptList.ScriptRecord)


def patch_font_to_game(
    font_data: bytes,
    font_info: FontInfo,
    packages_path: str,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> FontBuildResult:
    """Patch a modified font back into the game with full checksum chain.

    CRITICAL: Fonts are LZ4 only, NOT encrypted.

    Args:
        font_data: Raw TTF bytes of the modified font.
        font_info: Original font metadata from PAMT.
        packages_path: Path to the game packages/ directory.
        progress_callback: callback(step, total, message).
    """
    TOTAL = 8
    result = FontBuildResult(success=False, message="", original_size=font_info.orig_size, new_size=len(font_data))

    def step(n, msg):
        if progress_callback:
            progress_callback(n, TOTAL, msg)

    try:
        group = font_info.group
        group_dir = os.path.join(packages_path, group)
        pamt_path = os.path.join(group_dir, "0.pamt")
        papgt_path = os.path.join(packages_path, "meta", "0.papgt")

        fresh_pamt = parse_pamt(pamt_path, paz_dir=group_dir)
        entry = None
        for fe in fresh_pamt.file_entries:
            if fe.path == font_info.path and fe.paz_index == font_info.paz_index:
                entry = fe
                break
        if not entry:
            result.message = f"Font entry not found in PAMT: {font_info.path}"
            return result

        step(1, "Compressing font with LZ4 (no encryption)...")
        compressed = compress(font_data, 2)
        new_comp_size = len(compressed)
        new_orig_size = len(font_data)

        step(2, "Creating backup...")
        paz_path = entry.paz_file
        backup_dir = os.path.join(packages_path, "..", "crimsonforge_backups")
        bm = BackupManager(backup_dir)
        backup = bm.create_backup(
            [paz_path, pamt_path, papgt_path],
            description=f"Font patch: {font_info.filename}",
        )
        result.backup_dir = backup.backup_dir

        step(3, "Writing to PAZ archive...")
        space_map = build_space_map(fresh_pamt.file_entries)
        new_offset, _ = write_entry_payload(entry, compressed, space_map)

        step(4, "Computing PAZ checksum...")
        new_paz_crc = checksum_file(paz_path)
        new_paz_size = os.path.getsize(paz_path)
        result.paz_crc = new_paz_crc

        step(5, "Updating PAMT index...")
        pamt_raw = bytearray(fresh_pamt.raw_data)
        for te in fresh_pamt.paz_table:
            if te.index == entry.paz_index:
                update_pamt_paz_entry(pamt_raw, te, new_paz_crc, new_paz_size)
                break
        for fe in fresh_pamt.file_entries:
            if fe.offset == entry.offset and fe.paz_index == entry.paz_index:
                update_pamt_file_entry(
                    pamt_raw,
                    fe,
                    new_comp_size,
                    new_orig_size,
                    new_offset=new_offset,
                )
                break
        new_pamt_crc = update_pamt_self_crc(pamt_raw)
        result.pamt_crc = new_pamt_crc

        ts_pamt = get_file_timestamps(pamt_path)
        atomic_write(pamt_path, bytes(pamt_raw))
        set_file_timestamps(pamt_path, ts_pamt["modified"], ts_pamt["accessed"])

        step(6, "Updating PAPGT root index...")
        papgt_data = parse_papgt(papgt_path)
        papgt_raw = bytearray(papgt_data.raw_data)
        folder_number = int(group)
        pamt_crc_offset = get_pamt_crc_offset(papgt_data, folder_number)
        update_papgt_pamt_crc(papgt_raw, pamt_crc_offset, new_pamt_crc)
        new_papgt_crc = update_papgt_self_crc(papgt_raw)
        result.papgt_crc = new_papgt_crc

        ts_papgt = get_file_timestamps(papgt_path)
        atomic_write(papgt_path, bytes(papgt_raw))
        set_file_timestamps(papgt_path, ts_papgt["modified"], ts_papgt["accessed"])

        step(7, "Verifying checksums...")
        from core.checksum_engine import verify_papgt_checksum, verify_pamt_checksum
        ok_papgt, _, _ = verify_papgt_checksum(papgt_path)
        ok_pamt, _, _ = verify_pamt_checksum(pamt_path)
        if not ok_papgt or not ok_pamt:
            result.message = "Checksum verification failed after font patch."
            return result

        step(8, "Font patched successfully!")
        result.success = True
        result.message = (
            f"Font patched: {font_info.filename}\n"
            f"Size: {font_info.orig_size:,} -> {new_orig_size:,} bytes\n"
            f"Compressed: {font_info.comp_size:,} -> {new_comp_size:,} bytes"
        )
        return result

    except Exception as e:
        result.message = str(e)
        result.errors.append(str(e))
        return result
