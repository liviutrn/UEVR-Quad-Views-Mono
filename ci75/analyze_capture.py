#!/usr/bin/env python3
"""Decode and summarize DuoView diagnostic-sequence-2 captures.

The report describes measured, unregistered temporal changes and telemetry.
It does not estimate stereo quality, depth accuracy, or ground-truth error.
"""
from __future__ import annotations

import argparse
import io
import json
import math
import statistics
import struct
import sys
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

SCHEMA = "duoview-diagnostic-sequence-2"
ANALYSIS_SCHEMA = "duoview-diagnostic-analysis-1"
MAX_ARCHIVE_BYTES = 20 * 1024 * 1024
MAX_TOTAL_ARCHIVE_BYTES = 128 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 512 * 1024 * 1024
MAX_MEMBER_BYTES = 128 * 1024 * 1024
MAX_PREVIEW_BYTES = 128 * 1024 * 1024
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_ENTRIES = 4096
MAX_FRAMES = 512
MAX_DIMENSION = 16384

# DXGI_FORMAT numeric values. Aliases are deliberately limited to formats
# whose byte interpretation is known to this analyzer.
FORMAT_NAMES = {
    "R10G10B10A2_UNORM": 24,
    "R16G16_FLOAT": 34,
    "R32G32_FLOAT": 16,
    "R16_FLOAT": 54,
    "R16_UNORM": 55,
    "R32_FLOAT": 41,
    "R32_TYPELESS": 39,
    "D32_FLOAT": 40,
    "R24G8_TYPELESS": 44,
    "D24_UNORM_S8_UINT": 45,
    "R24_UNORM_X8_TYPELESS": 46,
    "R32G8X24_TYPELESS": 19,
    "D32_FLOAT_S8X24_UINT": 20,
    "R32_FLOAT_X8X24_TYPELESS": 21,
    "B8G8R8A8_UNORM": 87,
    "B8G8R8A8_UNORM_SRGB": 91,
    "B8G8R8A8_TYPELESS": 90,
    "R8G8B8A8_TYPELESS": 27,
    "R8G8B8A8_UNORM": 28,
    "R8G8B8A8_UNORM_SRGB": 29,
}


class CaptureError(ValueError):
    """The archive is malformed, unsafe, or does not match the declared schema."""


class UnsupportedFormat(Exception):
    pass


def _finite_tree(value: Any, where: str) -> None:
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return
    if isinstance(value, int):
        if abs(value) > 2**63 - 1:
            raise CaptureError(f"{where} contains an integer outside signed 64-bit range")
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CaptureError(f"{where} contains a non-finite number")
        return
    if isinstance(value, list):
        for i, item in enumerate(value):
            _finite_tree(item, f"{where}[{i}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise CaptureError(f"{where} has a non-string object key")
            _finite_tree(item, f"{where}.{key}")
        return
    raise CaptureError(f"{where} contains unsupported JSON value {type(value).__name__}")


def _integer(value: Any, where: str, minimum: int = 0, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CaptureError(f"{where} must be an integer")
    if value < minimum or (maximum is not None and value > maximum):
        raise CaptureError(f"{where} is outside the allowed range")
    return value


def _safe_member_name(name: Any, where: str) -> str:
    if not isinstance(name, str) or not name or "\\" in name or "\x00" in name:
        raise CaptureError(f"{where} must be a safe relative ZIP path")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in ("", ".", "..") for part in name.split("/")):
        raise CaptureError(f"{where} must not contain absolute or traversal components")
    if ":" in path.parts[0]:
        raise CaptureError(f"{where} must not contain a drive prefix")
    return name


def _validate_archive(path: str | Path) -> tuple[zipfile.ZipFile, dict[str, Any]]:
    path = Path(path)
    if not path.is_file():
        raise CaptureError(f"Capture ZIP does not exist: {path}")
    if path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise CaptureError(f"Capture ZIP exceeds {MAX_ARCHIVE_BYTES // (1024 * 1024)} MiB")
    try:
        zf = zipfile.ZipFile(path, "r")
    except (OSError, zipfile.BadZipFile) as exc:
        raise CaptureError(f"Invalid ZIP archive: {exc}") from exc
    try:
        infos = zf.infolist()
        if len(infos) > MAX_ENTRIES:
            raise CaptureError("ZIP contains too many entries")
        names: set[str] = set()
        total_size = 0
        for info in infos:
            validated_name = info.filename[:-1] if info.is_dir() and info.filename.endswith("/") else info.filename
            _safe_member_name(validated_name, "ZIP member name")
            name = info.filename
            if name in names:
                raise CaptureError(f"ZIP has duplicate member {name!r}")
            names.add(name)
            if info.flag_bits & 0x1:
                raise CaptureError(f"Encrypted ZIP member is not supported: {name}")
            # Reject symlinks so a later consumer cannot reinterpret the archive
            # as a filesystem extraction instruction.
            mode = (info.external_attr >> 16) & 0xFFFF
            if (mode & 0o170000) == 0o120000:
                raise CaptureError(f"ZIP symlink is not permitted: {name}")
            if info.file_size > MAX_MEMBER_BYTES and name != "manifest.json":
                raise CaptureError(f"ZIP member exceeds the {MAX_MEMBER_BYTES}-byte limit: {name}")
            if info.file_size < 0 or info.compress_size < 0:
                raise CaptureError(f"Invalid ZIP member size: {name}")
            total_size += info.file_size
            if total_size > MAX_UNCOMPRESSED_BYTES:
                raise CaptureError("ZIP uncompressed content exceeds the safety budget")
            if info.file_size > max(1024 * 1024, info.compress_size * 2000):
                raise CaptureError(f"Suspicious compression ratio in ZIP member {name!r}")
        if "manifest.json" not in names:
            raise CaptureError("ZIP is missing manifest.json")
        if zf.getinfo("manifest.json").file_size > MAX_MANIFEST_BYTES:
            raise CaptureError("manifest.json exceeds the size limit")
        # Stream every member through zipfile's CRC verifier while enforcing
        # actual output limits. `testzip()` has no caller-provided expansion
        # cap, so a forged central-directory size could otherwise overrun the
        # stated budget before analysis begins.
        actual_total = 0
        for info in infos:
            actual_member = 0
            try:
                with zf.open(info, "r") as member:
                    while True:
                        chunk = member.read(64 * 1024)
                        if not chunk:
                            break
                        actual_member += len(chunk)
                        actual_total += len(chunk)
                        if actual_member > min(MAX_MEMBER_BYTES, MAX_MANIFEST_BYTES if info.filename == "manifest.json" else MAX_MEMBER_BYTES):
                            raise CaptureError(f"ZIP member expands beyond its actual size budget: {info.filename}")
                        if actual_total > MAX_UNCOMPRESSED_BYTES:
                            raise CaptureError("ZIP expands beyond the uncompressed safety budget")
            except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
                raise CaptureError(f"ZIP CRC/decompression check failed for {info.filename!r}: {exc}") from exc
            if actual_member != info.file_size:
                raise CaptureError(f"ZIP member size does not match its directory entry: {info.filename!r}")
        try:
            manifest = json.loads(zf.read("manifest.json"))
        except (UnicodeDecodeError, json.JSONDecodeError, OSError, RuntimeError) as exc:
            raise CaptureError(f"Could not decode manifest.json: {exc}") from exc
        _validate_manifest(manifest, names)
        return zf, manifest
    except Exception:
        zf.close()
        raise


def _validate_manifest(manifest: Any, zip_names: set[str]) -> None:
    if not isinstance(manifest, dict):
        raise CaptureError("manifest.json root must be an object")
    if manifest.get("schema") != SCHEMA:
        raise CaptureError(f"Unsupported schema; expected {SCHEMA}")
    if (not isinstance(manifest.get("build_commit"), str) or not manifest["build_commit"] or
            len(manifest["build_commit"]) > 256):
        raise CaptureError("manifest.build_commit must be a non-empty string")
    if "capture_id" in manifest and (not isinstance(manifest["capture_id"], str) or len(manifest["capture_id"]) > 256):
        raise CaptureError("manifest.capture_id must be a string")
    if "part_index" in manifest and manifest["part_index"] is not None:
        _integer(manifest["part_index"], "manifest.part_index", 1, 100000)
    if "part_count" in manifest and manifest["part_count"] is not None:
        _integer(manifest["part_count"], "manifest.part_count", 1, 100000)
    for key in ("total_encoded_frames", "total_recorded_frames"):
        if key in manifest and manifest[key] is not None:
            _integer(manifest[key], f"manifest.{key}", 0, 2**31 - 1)
    if (manifest.get("total_encoded_frames") is not None and manifest.get("total_recorded_frames") is not None and
            manifest["total_encoded_frames"] != manifest["total_recorded_frames"]):
        raise CaptureError("manifest total frame count fields disagree")
    for key in ("capture_complete", "complete_capture", "sufficient_sequence", "truncated_by_size"):
        if key in manifest and not isinstance(manifest[key], bool):
            raise CaptureError(f"manifest.{key} must be boolean")
    if ("capture_complete" in manifest and "complete_capture" in manifest and
            manifest["capture_complete"] != manifest["complete_capture"]):
        raise CaptureError("manifest capture-complete flags disagree")
    if "session_start_ms" in manifest:
        start = manifest["session_start_ms"]
        if isinstance(start, bool) or not isinstance(start, (int, float)):
            raise CaptureError("manifest.session_start_ms must be finite")
        try:
            start = float(start)
        except OverflowError as exc:
            raise CaptureError("manifest.session_start_ms is outside the supported range") from exc
        if not math.isfinite(start) or abs(start) > 1e15:
            raise CaptureError("manifest.session_start_ms is outside the supported range")
    frames = manifest.get("frames")
    if not isinstance(frames, list) or not frames:
        raise CaptureError("manifest.frames must contain at least one frame")
    if len(frames) > MAX_FRAMES:
        raise CaptureError(f"manifest.frames exceeds {MAX_FRAMES} frames")
    frame_indices_declared = []
    indices: set[int] = set()
    declared_members: set[str] = {"manifest.json"}
    for fi, frame in enumerate(frames):
        where = f"frames[{fi}]"
        if not isinstance(frame, dict):
            raise CaptureError(f"{where} must be an object")
        index = _integer(frame.get("index"), f"{where}.index", 0, 2**31 - 1)
        if index in indices:
            raise CaptureError(f"Duplicate frame index {index}")
        indices.add(index)
        frame_indices_declared.append(index)
        if "packet" not in frame or isinstance(frame["packet"], bool) or not isinstance(frame["packet"], (int, str)):
            raise CaptureError(f"{where}.packet must be an integer or string")
        if isinstance(frame["packet"], int):
            _integer(frame["packet"], f"{where}.packet", -(2**63), 2**63 - 1)
        elif len(frame["packet"]) > 256:
            raise CaptureError(f"{where}.packet string is too long")
        timestamp = frame.get("time_ms")
        if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
            raise CaptureError(f"{where}.time_ms must be finite")
        try:
            timestamp_value = float(timestamp)
        except OverflowError as exc:
            raise CaptureError(f"{where}.time_ms is outside the supported range") from exc
        if not math.isfinite(timestamp_value) or abs(timestamp_value) > 1e15:
            raise CaptureError(f"{where}.time_ms must be finite and within the supported range")
        metadata = frame.get("metadata")
        if not isinstance(metadata, dict):
            raise CaptureError(f"{where}.metadata must be an object")
        _finite_tree(metadata, f"{where}.metadata")
        _validate_typed_metadata(metadata, where)
        planes = frame.get("planes")
        if not isinstance(planes, list) or not planes:
            raise CaptureError(f"{where}.planes must be a non-empty array")
        plane_names: set[str] = set()
        for pi, plane in enumerate(planes):
            pw = f"{where}.planes[{pi}]"
            if not isinstance(plane, dict):
                raise CaptureError(f"{pw} must be an object")
            name = plane.get("name")
            if (not isinstance(name, str) or not name or len(name) > 64 or
                    any(not (ch.isalnum() or ch in "_.-") for ch in name) or name in (".", "..") or
                    name in plane_names):
                raise CaptureError(f"{pw}.name must be unique and non-empty within the frame")
            plane_names.add(name)
            required = plane.get("required")
            if not isinstance(required, bool):
                raise CaptureError(f"{pw}.required must be boolean")
            width = _integer(plane.get("width"), f"{pw}.width", 1, MAX_DIMENSION)
            height = _integer(plane.get("height"), f"{pw}.height", 1, MAX_DIMENSION)
            row_bytes = _integer(plane.get("row_bytes"), f"{pw}.row_bytes", 1, MAX_MEMBER_BYTES)
            if row_bytes * height > MAX_MEMBER_BYTES:
                raise CaptureError(f"{pw} decoded byte plane exceeds the per-plane safety budget")
            _format_id(plane.get("format"), f"{pw}.format", allow_unknown=True)
            if "footprint_format" in plane and plane["footprint_format"] is not None:
                _format_id(plane["footprint_format"], f"{pw}.footprint_format", allow_unknown=True)
            if plane.get("encoding") != "png-packed-bytes":
                raise CaptureError(f"{pw}.encoding must be 'png-packed-bytes'")
            box = plane.get("box")
            resource = plane.get("resource_size")
            if not isinstance(box, list) or len(box) != 4:
                raise CaptureError(f"{pw}.box must be [x0,y0,x1,y1]")
            if not isinstance(resource, list) or len(resource) != 2:
                raise CaptureError(f"{pw}.resource_size must be [width,height]")
            x0, y0, x1, y1 = [_integer(v, f"{pw}.box", 0, MAX_DIMENSION) for v in box]
            rw, rh = [_integer(v, f"{pw}.resource_size", 1, MAX_DIMENSION) for v in resource]
            if x1 <= x0 or y1 <= y0 or x1 - x0 != width or y1 - y0 != height:
                raise CaptureError(f"{pw}.box extent must equal its plane width and height")
            if x1 > rw or y1 > rh:
                raise CaptureError(f"{pw}.box extends beyond resource_size")
            file_name = plane.get("file")
            if file_name is None and not required:
                continue
            file_name = _safe_member_name(file_name, f"{pw}.file")
            if file_name in declared_members:
                # A shared image would make descriptor-specific decode claims
                # ambiguous; require every plane payload to have one owner.
                raise CaptureError(f"ZIP payload {file_name!r} is referenced more than once")
            declared_members.add(file_name)
            if required and file_name not in zip_names:
                raise CaptureError(f"Required plane payload is missing: {file_name}")
            if file_name in zip_names and file_name == "manifest.json":
                raise CaptureError("A plane cannot refer to manifest.json")
    if "first_frame_index" in manifest and manifest["first_frame_index"] is not None:
        _integer(manifest["first_frame_index"], "manifest.first_frame_index", 0, 2**31 - 1)
        if manifest["first_frame_index"] != min(frame_indices_declared):
            raise CaptureError("manifest.first_frame_index does not match its frames")
    if "last_frame_index" in manifest and manifest["last_frame_index"] is not None:
        _integer(manifest["last_frame_index"], "manifest.last_frame_index", 0, 2**31 - 1)
        if manifest["last_frame_index"] != max(frame_indices_declared):
            raise CaptureError("manifest.last_frame_index does not match its frames")
    # Missing optional references are accepted and explicitly reported later.


def _validate_typed_metadata(metadata: dict[str, Any], where: str) -> None:
    for key in ("positions", "rotations", "projection_left", "projection_right", "crop"):
        if key in metadata and not isinstance(metadata[key], (dict, list)):
            raise CaptureError(f"{where}.metadata.{key} must be an object or array")
    for key in ("projection_left", "projection_right"):
        if key in metadata:
            values = _numeric_vector(metadata[key])
            if values is None or len(values) != 16:
                raise CaptureError(f"{where}.metadata.{key} must contain 16 finite column-major values")
    guides = metadata.get("guides", [])
    if not isinstance(guides, list):
        raise CaptureError(f"{where}.metadata.guides must be an array")
    if len(guides) > 32:
        raise CaptureError(f"{where}.metadata.guides exceeds 32 entries")
    for gi, guide in enumerate(guides):
        gw = f"{where}.metadata.guides[{gi}]"
        if not isinstance(guide, dict):
            raise CaptureError(f"{gw} must be an object")
        size = guide.get("input")
        jitter = guide.get("jitter")
        if not isinstance(size, list) or len(size) != 2:
            raise CaptureError(f"{gw}.input must be [width,height]")
        for dim in size:
            _integer(dim, f"{gw}.input", 1, MAX_DIMENSION)
        if _numeric_vector(jitter) is None or len(_numeric_vector(jitter) or []) != 2:
            raise CaptureError(f"{gw}.jitter must contain two finite values")


def _numeric_vector(value: Any) -> list[float] | None:
    if isinstance(value, list) and all(not isinstance(x, bool) and isinstance(x, (int, float)) for x in value):
        try:
            converted = [float(x) for x in value]
        except OverflowError:
            return None
        if all(math.isfinite(x) for x in converted):
            return converted
    return None


def _format_id(value: Any, where: str, allow_unknown: bool = False) -> int | None:
    if isinstance(value, bool):
        raise CaptureError(f"{where} must be a DXGI format number or name")
    if isinstance(value, int):
        if value < 0 or value > 65535:
            raise CaptureError(f"{where} is outside the DXGI format range")
        return value
    if isinstance(value, str):
        key = value.upper().removeprefix("DXGI_FORMAT_")
        if key in FORMAT_NAMES:
            return FORMAT_NAMES[key]
        try:
            return int(key, 0)
        except ValueError:
            if allow_unknown:
                return None
    if allow_unknown:
        return None
    raise CaptureError(f"{where} must be a DXGI format number or supported name")


def _stored_format(descriptor: dict[str, Any]) -> int | None:
    fp = descriptor.get("footprint_format")
    if fp is not None:
        stored = _format_id(fp, "footprint_format", allow_unknown=True)
        if stored is None:
            raise UnsupportedFormat(f"unsupported footprint format {fp!r}")
        return stored
    return _format_id(descriptor.get("format"), "format", allow_unknown=True)


def _format_layout(descriptor: dict[str, Any]) -> tuple[str, int]:
    fmt = _format_id(descriptor.get("format"), "format", allow_unknown=True)
    storage = _stored_format(descriptor)
    if fmt in (87, 90, 91):
        return "bgra8", 4
    if fmt in (27, 28, 29):
        return "rgba8", 4
    if fmt == 24:
        return "r10g10b10a2", 4
    if fmt in (39, 40, 41):
        return "r32f", 4
    if fmt == 54:
        return "r16f", 2
    if fmt in (53, 55, 56):
        return "r16unorm", 2
    if fmt in (44, 45, 46):
        return "r24", 4
    if fmt in (19, 20, 21):
        # D32_FLOAT_S8X24 may be copied to an R32 depth footprint; otherwise
        # each source element is eight bytes and depth occupies the first four.
        return "r32g8x24", 4 if storage in (39, 41, 40) else 8
    if fmt == 34:
        return "rg16f", 4
    if fmt == 16:
        return "rg32f", 8
    raise UnsupportedFormat(f"unsupported DXGI format {descriptor.get('format')!r}")


def decode_png_rows(encoded_png: bytes, descriptor: dict[str, Any]) -> bytes:
    """Decode the PNG's RGBA channel bytes back to the packed row stream."""
    row_bytes = descriptor["row_bytes"]
    height = descriptor["height"]
    expected_png_size = ((row_bytes + 3) // 4, height)
    if row_bytes * height > MAX_MEMBER_BYTES or expected_png_size[0] * height * 4 > MAX_MEMBER_BYTES + 3 * height:
        raise CaptureError("Decoded plane exceeds the per-plane safety budget")
    try:
        with Image.open(io.BytesIO(encoded_png)) as img:
            if img.format != "PNG" or img.mode != "RGBA":
                raise CaptureError("Packed payload must be a lossless RGBA PNG")
            if img.size != expected_png_size:
                raise CaptureError(f"Packed PNG dimensions {img.size} do not match {expected_png_size}")
            arr = np.asarray(img, dtype=np.uint8)
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        if isinstance(exc, CaptureError):
            raise
        raise CaptureError(f"Invalid packed PNG: {exc}") from exc
    packed = np.ascontiguousarray(arr).reshape(height, expected_png_size[0] * 4)
    return packed[:, :row_bytes].tobytes(order="C")


def decode_native(raw: bytes, descriptor: dict[str, Any]) -> tuple[np.ndarray, str]:
    """Decode known DXGI byte layouts into numeric planes; unknown stays explicit."""
    kind, bpp = _format_layout(descriptor)
    width, height, row_bytes = descriptor["width"], descriptor["height"], descriptor["row_bytes"]
    if row_bytes < width * bpp:
        raise CaptureError(f"row_bytes={row_bytes} is too small for width={width} and format={descriptor['format']!r}")
    if len(raw) != row_bytes * height:
        raise CaptureError("Decoded packed byte count does not match row_bytes × height")
    rows = np.frombuffer(raw, dtype=np.uint8).reshape(height, row_bytes)
    pixel_bytes = rows[:, :width * bpp].copy()
    if kind in ("bgra8", "rgba8"):
        v = pixel_bytes.reshape(height, width, 4).astype(np.float32) / 255.0
        if kind == "bgra8":
            v = v[..., [2, 1, 0, 3]]
        return v, "color_rgba"
    if kind == "r10g10b10a2":
        word = pixel_bytes.reshape(height, width, 4).copy().view("<u4").reshape(height, width)
        v = np.empty((height, width, 4), dtype=np.float32)
        v[..., 0] = (word & 0x3FF) / 1023.0
        v[..., 1] = ((word >> 10) & 0x3FF) / 1023.0
        v[..., 2] = ((word >> 20) & 0x3FF) / 1023.0
        v[..., 3] = ((word >> 30) & 0x3) / 3.0
        return v, "color_rgba"
    if kind in ("r32f", "r32g8x24"):
        if bpp == 4:
            v = pixel_bytes.reshape(height, width, 4).copy().view("<f4").reshape(height, width)
        else:
            v = pixel_bytes.reshape(height, width, 8)[..., :4].copy().view("<f4").reshape(height, width)
        return v, "depth_r32_float"
    if kind == "r16f":
        v = pixel_bytes.reshape(height, width, 2).copy().view("<f2").reshape(height, width)
        return v, "depth_r16_float"
    if kind == "r16unorm":
        v = pixel_bytes.reshape(height, width, 2).copy().view("<u2").reshape(height, width)
        return v.astype(np.float32) / 65535.0, "depth_r16_unorm"
    if kind == "r24":
        word = pixel_bytes.reshape(height, width, 4).copy().view("<u4").reshape(height, width)
        return (word & 0xFFFFFF).astype(np.float32) / 16777215.0, "depth_r24_unorm"
    if kind == "rg16f":
        v = pixel_bytes.reshape(height, width, 4).copy().view("<f2").reshape(height, width, 2)
        return v, "motion_rg16_float"
    if kind == "rg32f":
        v = pixel_bytes.reshape(height, width, 8).copy().view("<f4").reshape(height, width, 2)
        return v, "motion_rg32_float"
    raise UnsupportedFormat(f"no decoder for {kind}")


def _load_plane(zf: zipfile.ZipFile, plane: dict[str, Any]) -> tuple[np.ndarray | None, str, str | None]:
    file_name = plane.get("file")
    if not file_name or file_name not in zf.NameToInfo:
        if not plane["required"]:
            return None, "missing_optional", None
        raise CaptureError(f"Missing required plane payload {file_name!r}")
    raw_rows = decode_png_rows(zf.read(file_name), plane)
    try:
        decoded, kind = decode_native(raw_rows, plane)
        return decoded, kind, None
    except UnsupportedFormat as exc:
        return None, "unsupported", str(exc)


def _plane_lookup(frame: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {p["name"]: p for p in frame["planes"]}


def _flatten_numbers(value: Any) -> list[float] | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            result = float(value)
        except OverflowError:
            return None
        if math.isfinite(result):
            return [result]
        return None
    if isinstance(value, list):
        out: list[float] = []
        for item in value:
            sub = _flatten_numbers(item)
            if sub is None:
                return None
            out.extend(sub)
        return out
    if isinstance(value, dict):
        out = []
        for key in sorted(value):
            sub = _flatten_numbers(value[key])
            if sub is None:
                return None
            out.extend(sub)
        return out
    return None


def _find_meta(meta: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in meta:
            return meta[key]
    return None


def _pose_vector(meta: dict[str, Any], kind: str) -> list[float] | None:
    if kind == "positions":
        value = _find_meta(meta, "positions", "eye_positions", "position_left", "left_position")
        if value is None and "position_right" in meta:
            value = {"left": meta.get("position_left", meta.get("left_position")), "right": meta["position_right"]}
    else:
        value = _find_meta(meta, "rotations", "eye_rotations", "rotation_left", "left_rotation")
        if value is None and "rotation_right" in meta:
            value = {"left": meta.get("rotation_left", meta.get("left_rotation")), "right": meta["rotation_right"]}
    return _flatten_numbers(value) if value is not None else None


def _pose_delta(a: list[float], b: list[float], rotations: bool) -> float:
    if len(a) != len(b):
        return math.inf
    if rotations and len(a) in (4, 8):
        # Each quaternion q and -q encode the same orientation.
        chunks = len(a) // 4
        worst = 0.0
        for i in range(chunks):
            av = np.asarray(a[i * 4:(i + 1) * 4])
            bv = np.asarray(b[i * 4:(i + 1) * 4])
            worst = max(worst, float(min(np.linalg.norm(av - bv), np.linalg.norm(av + bv))))
        return worst
    return max((abs(x - y) for x, y in zip(a, b)), default=math.inf)


def _json_stable(a: Any, b: Any, tol: float = 1e-6) -> bool:
    va, vb = _flatten_numbers(a), _flatten_numbers(b)
    if va is not None and vb is not None:
        return len(va) == len(vb) and all(abs(x - y) <= tol for x, y in zip(va, vb))
    return a == b


def stationarity_gate(a: dict[str, Any], b: dict[str, Any], plane_a: dict[str, Any], plane_b: dict[str, Any]) -> tuple[bool, list[str]]:
    """Require stable camera/crop telemetry and the plane's resource ROI."""
    reasons: list[str] = []
    ma, mb = a["metadata"], b["metadata"]
    pos_a, pos_b = _pose_vector(ma, "positions"), _pose_vector(mb, "positions")
    rot_a, rot_b = _pose_vector(ma, "rotations"), _pose_vector(mb, "rotations")
    if pos_a is None or pos_b is None:
        reasons.append("camera_position_missing")
    elif _pose_delta(pos_a, pos_b, False) > 1e-4:
        reasons.append("camera_position_changed")
    if rot_a is None or rot_b is None:
        reasons.append("camera_rotation_missing")
    elif _pose_delta(rot_a, rot_b, True) > 1e-5:
        reasons.append("camera_rotation_changed")
    for key in ("projection_left", "projection_right"):
        if key not in ma or key not in mb:
            reasons.append(key + "_missing")
        elif not _json_stable(ma[key], mb[key], 1e-6):
            reasons.append(key + "_changed")
    for key in ("crop", "gaze", "gaze_position", "mode", "strategy", "quality", "stereo_recorded"):
        if key in ma or key in mb:
            if key not in ma or key not in mb:
                reasons.append(key + "_missing")
            elif not _json_stable(ma[key], mb[key]):
                reasons.append(key + "_changed")
    guides_a, guides_b = ma.get("guides", []), mb.get("guides", [])
    if len(guides_a) != len(guides_b):
        reasons.append("guide_count_changed")
    else:
        for gi, (ga, gb) in enumerate(zip(guides_a, guides_b)):
            for key in ("input", "motion_scale", "flags", "feature", "evaluation"):
                if ga.get(key) != gb.get(key):
                    reasons.append(f"guide_{gi}_{key}_changed")
            if ga.get("reset") is True or gb.get("reset") is True:
                reasons.append(f"guide_{gi}_temporal_reset")
    for key in ("width", "height", "box", "resource_size", "format", "footprint_format"):
        if plane_a.get(key) != plane_b.get(key):
            reasons.append("plane_" + key + "_changed")
    return not reasons, reasons


def _gray_color(image: np.ndarray) -> np.ndarray:
    # Values are the decoded UNORM code values; no transfer-function or display
    # calibration is inferred from the descriptor.
    return image[..., :3] @ np.asarray([0.2126, 0.7152, 0.0722], dtype=np.float32)


def _diff_metrics(a: np.ndarray, b: np.ndarray, kind: str) -> tuple[dict[str, Any], np.ndarray]:
    if a.shape != b.shape:
        raise CaptureError("Plane dimensions changed between frames")
    if kind == "color_rgba":
        av, bv = _gray_color(a), _gray_color(b)
        valid = np.isfinite(av) & np.isfinite(bv)
        delta = np.abs(av - bv)
        threshold = 1.0 / 255.0
    elif kind.startswith("motion_"):
        delta_channels = np.abs(a.astype(np.float64) - b.astype(np.float64))
        delta = np.sqrt(np.mean(delta_channels * delta_channels, axis=2))
        av, bv = a, b
        valid = np.all(np.isfinite(av), axis=2) & np.all(np.isfinite(bv), axis=2)
        threshold = 0.0
    else:
        av, bv = a.astype(np.float64), b.astype(np.float64)
        valid = np.isfinite(av) & np.isfinite(bv)
        delta = np.abs(av - bv)
        threshold = 0.0
    values = delta[valid]
    if values.size == 0:
        stats = {"mean_abs_change": None, "p95_abs_change": None, "changed_fraction": None, "valid_fraction": 0.0}
    else:
        stats = {
            "mean_abs_change": float(np.mean(values, dtype=np.float64)),
            "p95_abs_change": float(np.percentile(values, 95)),
            "changed_fraction": float(np.mean(values > threshold)),
            "valid_fraction": float(valid.mean()),
        }
    safe_delta = np.where(valid, delta, 0.0).astype(np.float64)
    return stats, safe_delta


def _depth_edges(image: np.ndarray) -> dict[str, Any]:
    values = image.astype(np.float64)
    valid = np.isfinite(values)
    pieces: list[np.ndarray] = []
    if values.shape[1] > 1:
        m = valid[:, 1:] & valid[:, :-1]
        if np.any(m):
            pieces.append(np.abs(values[:, 1:] - values[:, :-1])[m])
    if values.shape[0] > 1:
        m = valid[1:, :] & valid[:-1, :]
        if np.any(m):
            pieces.append(np.abs(values[1:, :] - values[:-1, :])[m])
    if not pieces:
        return {"valid_neighbor_pairs": 0, "median_abs_neighbor_delta": None, "p95_abs_neighbor_delta": None}
    d = np.concatenate(pieces)
    return {"valid_neighbor_pairs": int(d.size), "median_abs_neighbor_delta": float(np.median(d)),
            "p95_abs_neighbor_delta": float(np.percentile(d, 95))}


def _metric_summary(values: list[float]) -> float | None:
    return float(statistics.median(values)) if values else None


def _guide_series(frames: list[dict[str, Any]]) -> dict[int, list[tuple[int, float, float, tuple[int, int], tuple[Any, ...]]]]:
    series: dict[int, list[tuple[int, float, float, tuple[int, int], tuple[Any, ...]]]] = {}
    for pos, frame in enumerate(frames):
        guides = frame["metadata"].get("guides", [])
        for gi, guide in enumerate(guides):
            if isinstance(guide, dict) and _numeric_vector(guide.get("jitter")) is not None:
                jx, jy = _numeric_vector(guide["jitter"])
                settings = tuple(guide.get(k) for k in ("input", "motion_scale", "flags", "feature", "evaluation", "reset"))
                size = tuple(guide["input"])
                series.setdefault(gi, []).append((pos, jx, jy, size, settings))
    return series


def _corr(x: list[float], y: list[float]) -> float | None:
    if len(x) < 3 or len(x) != len(y):
        return None
    xa, ya = np.asarray(x), np.asarray(y)
    if float(np.std(xa)) == 0.0 or float(np.std(ya)) == 0.0:
        return None
    return float(np.corrcoef(xa, ya)[0, 1])


def _make_contact_sheet(zfs: list[zipfile.ZipFile], frames: list[dict[str, Any]], plane_name: str, out: Path) -> str | None:
    choices = sorted(set((0, len(frames) // 2, len(frames) - 1)))
    samples: list[tuple[int, np.ndarray]] = []
    for index in choices:
        frame = frames[index]
        frame_zip = zfs[frame["__zip_index"]]
        desc = _plane_lookup(frame).get(plane_name)
        if not desc or not desc.get("file") or desc["file"] not in frame_zip.NameToInfo:
            continue
        data, kind, _ = _load_plane(frame_zip, desc)
        if data is None or kind != "color_rgba":
            continue
        rgb = np.clip(data[..., :3] * 255.0, 0, 255).astype(np.uint8)
        samples.append((frames[index]["index"], rgb))
    if not samples:
        return None
    cell_w, cell_h = 384, 384
    label_h = 24
    sheet = Image.new("RGB", (cell_w * len(samples), cell_h + label_h), (24, 24, 24))
    draw = ImageDraw.Draw(sheet)
    for col, (frame_index, rgb) in enumerate(samples):
        img = Image.fromarray(rgb, mode="RGB")
        img.thumbnail((cell_w, cell_h), Image.Resampling.BILINEAR)
        ox = col * cell_w + (cell_w - img.width) // 2
        oy = label_h + (cell_h - img.height) // 2
        sheet.paste(img, (ox, oy))
        draw.text((col * cell_w + 8, 5), f"frame {frame_index}", fill=(255, 255, 255))
    sheet.save(out, format="PNG", optimize=True)
    return out.name


def _save_xr_sequence_gif(zfs: list[zipfile.ZipFile], frames: list[dict[str, Any]], out: Path) -> dict[str, Any]:
    """Make a native-pixel side-by-side XR preview; never resize/interpolate."""
    rgb_frames: list[Image.Image] = []
    native_size: tuple[int, int] | None = None
    memory = 0
    for frame in frames:
        lookup = _plane_lookup(frame)
        images = []
        for name in ("xr_left", "xr_right"):
            desc = lookup.get(name)
            if not desc or not desc.get("file"):
                return {"skipped": True, "reason": f"{name} is missing in frame {frame['index']}"}
            data, kind, reason = _load_plane(zfs[frame["__zip_index"]], desc)
            if data is None or kind != "color_rgba":
                return {"skipped": True, "reason": reason or f"{name} is not a supported color plane"}
            images.append(np.clip(np.rint(data[..., :3] * 255.0), 0, 255).astype(np.uint8))
        size = (images[0].shape[1] + images[1].shape[1], max(images[0].shape[0], images[1].shape[0]))
        if native_size is None:
            native_size = size
        elif size != native_size:
            return {"skipped": True, "reason": "XR plane dimensions changed during the capture"}
        memory += size[0] * size[1] * 3
        if memory > MAX_PREVIEW_BYTES:
            return {"skipped": True, "reason": "native-resolution preview exceeds its memory budget"}
        canvas = np.zeros((size[1], size[0], 3), dtype=np.uint8)
        canvas[:images[0].shape[0], :images[0].shape[1]] = images[0]
        x = images[0].shape[1]
        canvas[:images[1].shape[0], x:x + images[1].shape[1]] = images[1]
        rgb_frames.append(Image.fromarray(canvas, mode="RGB"))
    if len(rgb_frames) < 2:
        return {"skipped": True, "reason": "at least two XR frame pairs are required"}
    times = [float(frame["time_ms"]) for frame in frames]
    diffs = [b - a for a, b in zip(times, times[1:])]
    positive = [d for d in diffs if d > 0]
    fallback = float(statistics.median(positive)) if positive else 100.0
    source_durations = [(d if d > 0 else fallback) for d in diffs] + [fallback]
    gif_durations = [max(10, min(655350, int(round(d / 10.0) * 10))) for d in source_durations]
    palette = rgb_frames[0].convert("P", palette=Image.Palette.ADAPTIVE, colors=256)
    paletted = [palette]
    paletted.extend(im.quantize(palette=palette, dither=Image.Dither.NONE) for im in rgb_frames[1:])
    paletted[0].save(out, format="GIF", save_all=True, append_images=paletted[1:],
                     duration=gif_durations, loop=0, disposal=2, optimize=False)
    return {
        "file": out.name,
        "frame_count": len(frames),
        "native_side_by_side_size": list(native_size),
        "resized_or_interpolated": False,
        "palette_quantization": "GIF 256-color preview; inspect raw packed PNG planes for exact values",
        "source_frame_duration_ms": source_durations,
        "encoded_gif_duration_ms": gif_durations,
    }


def _save_heatmap(values: np.ndarray, out: Path) -> str:
    # This visualization is separately normalized per plane at its p95 change;
    # its colors cannot be compared as scores across planes.
    scale = max(float(np.percentile(values, 95)), 1e-12)
    gray = np.clip(values / scale, 0.0, 1.0)
    rgb = np.stack((gray, gray * 0.45, 0.0 * gray), axis=2)
    Image.fromarray((rgb * 255.0).astype(np.uint8), mode="RGB").save(out, format="PNG", optimize=True)
    return out.name


def _capture_completeness(parts: list[dict[str, Any]], frames: list[dict[str, Any]]) -> dict[str, Any]:
    ids = {p.get("capture_id") for p in parts if p.get("capture_id") is not None}
    if len(ids) > 1:
        raise CaptureError("ZIP parts have different capture_id values")
    part_ids_complete = len(parts) == 1 or (len(ids) == 1 and all(p.get("capture_id") is not None for p in parts))
    session_starts = [float(p["session_start_ms"]) for p in parts if p.get("session_start_ms") is not None]
    if session_starts and max(session_starts) - min(session_starts) > 1e-3:
        raise CaptureError("ZIP parts disagree about session_start_ms")
    part_indices: list[int] = []
    declared_counts: list[int] = []
    total_counts: list[int] = []
    for p in parts:
        idx, count = p.get("part_index"), p.get("part_count")
        if idx is not None:
            part_indices.append(_integer(idx, "manifest.part_index", 1, 100000))
        if count is not None:
            declared_counts.append(_integer(count, "manifest.part_count", 1, 100000))
        total = p.get("total_encoded_frames", p.get("total_recorded_frames"))
        if total is not None:
            total_counts.append(_integer(total, "manifest.total_encoded_frames", 0, 2**31 - 1))
        flag = p.get("capture_complete", p.get("complete_capture"))
        if flag is not None and not isinstance(flag, bool):
            raise CaptureError("manifest capture-complete flag must be boolean when present")
    if part_indices and len(set(part_indices)) != len(part_indices):
        raise CaptureError("Duplicate part_index across supplied ZIPs")
    if len(set(declared_counts)) > 1:
        raise CaptureError("ZIP parts disagree about part_count")
    if len(set(total_counts)) > 1:
        raise CaptureError("ZIP parts disagree about total_encoded_frames")
    expected_parts = declared_counts[0] if declared_counts else None
    supplied = sorted(part_indices)
    if expected_parts is not None and any(i > expected_parts for i in supplied):
        raise CaptureError("part_index exceeds the declared 1-based part_count")
    missing = list(range(1, expected_parts + 1)) if expected_parts is not None else None
    if missing is not None:
        missing = [x for x in missing if x not in set(supplied)]
    frame_indices = sorted(f["index"] for f in frames)
    gaps: list[int] = []
    gap_count = 0
    for left, right in zip(frame_indices, frame_indices[1:]):
        if right > left + 1:
            gap_count += right - left - 1
            if len(gaps) < 256:
                gaps.extend(range(left + 1, min(right, left + 1 + (256 - len(gaps)))))
    declared_total = total_counts[0] if total_counts else None
    terminal_complete = any(p.get("capture_complete", p.get("complete_capture")) is True and
                            (expected_parts is None or p.get("part_index") == expected_parts)
                            for p in parts)
    explicit_partial = any(p.get("capture_complete", p.get("complete_capture")) is False for p in parts)
    truncated = any(p.get("truncated_by_size") is True for p in parts)
    suff_flags = [p["sufficient_sequence"] for p in parts if "sufficient_sequence" in p]
    sufficient = (all(suff_flags) if suff_flags else (declared_total >= 16 if declared_total is not None else None))
    if declared_total is not None and declared_total < 16:
        sufficient = False
    packet_keys = [(type(f["packet"]).__name__, str(f["packet"])) for f in frames]
    packet_counts: dict[tuple[str, str], int] = {}
    for key in packet_keys:
        packet_counts[key] = packet_counts.get(key, 0) + 1
    duplicate_packets = sorted(key for key, count in packet_counts.items() if count > 1)
    if not part_ids_complete:
        status = "unverified"
        reason = "capture_id_missing_from_one_or_more_parts"
    elif expected_parts is not None and missing:
        status = "partial"
        reason = "one_or_more_declared_parts_not_supplied"
    elif truncated:
        status = "partial"
        reason = "manifest_reports_size_truncation"
    elif duplicate_packets:
        status = "partial"
        reason = "duplicate_packet_serials"
    elif explicit_partial and not terminal_complete:
        status = "partial"
        reason = "manifest_marks_capture_incomplete"
    elif sufficient is False:
        status = "partial"
        reason = "sequence_below_or_failed_the_16_frame_sufficiency_gate"
    elif expected_parts is not None and declared_total is not None and len(frames) != declared_total:
        status = "partial"
        reason = "supplied_frame_count_differs_from_declared_total"
    elif expected_parts is not None and len(supplied) != expected_parts:
        status = "partial"
        reason = "part_count_does_not_match_supplied_archives"
    elif gap_count:
        status = "partial"
        reason = "global_frame_index_gaps"
    elif expected_parts is not None and declared_total is not None and len(frames) == declared_total and terminal_complete and sufficient is True:
        status = "complete"
        reason = "all_declared_parts_and_frames_present; terminal_manifest_marks_complete"
    elif expected_parts is None and len(parts) == 1 and (parts[0].get("part_index") is None):
        status = "unknown"
        reason = "single_archive_has_no_part_completeness_metadata"
    elif expected_parts is None and terminal_complete and len(parts) == 1:
        status = "completion_flag_set_part_count_unknown"
        reason = "manifest_marks_complete_but_expected_part_count_is_unknown"
    else:
        status = "unverified"
        reason = "part_or_total_frame_metadata_is_incomplete"
    return {
        "status": status,
        "reason": reason,
        "capture_id": next(iter(ids)) if ids else None,
        "session_start_ms": session_starts[0] if session_starts else None,
        "supplied_archives": len(parts),
        "part_indices": supplied,
        "expected_part_count": expected_parts,
        "missing_part_indices": missing,
        "declared_total_encoded_frames": declared_total,
        "sufficient_sequence": sufficient,
        "minimum_sufficient_frames": 16,
        "truncated_by_size": truncated,
        "duplicate_packet_serials": [value for _, value in duplicate_packets],
        "supplied_unique_frames": len(frames),
        "global_frame_indices": frame_indices,
        "global_frame_index_gaps": gaps[:256],
        "global_frame_index_gap_count": gap_count,
        "frame_index_gaps_truncated": gap_count > 256,
        "terminal_complete_flag_seen": terminal_complete,
        "capture_complete_declared": any(p.get("capture_complete", p.get("complete_capture")) is True for p in parts),
    }


def analyze_capture(archives: str | Path | list[str | Path] | tuple[str | Path, ...], out_dir: str | Path) -> dict[str, Any]:
    """Decode one or more sequence parts and write report plus PNG sidecars."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if isinstance(archives, (str, Path)):
        archives = [archives]
    archives = list(archives)
    if not archives or len(archives) > 128:
        raise CaptureError("Supply between 1 and 128 ZIP archives")
    zfs: list[zipfile.ZipFile] = []
    manifests: list[dict[str, Any]] = []
    aggregate_size = 0
    aggregate_archive_size = 0
    try:
        for archive in archives:
            aggregate_archive_size += Path(archive).stat().st_size
            if aggregate_archive_size > MAX_TOTAL_ARCHIVE_BYTES:
                raise CaptureError("Combined ZIP parts exceed the 128 MiB archive budget")
            zf, manifest = _validate_archive(archive)
            zfs.append(zf)
            manifests.append(manifest)
            aggregate_size += sum(info.file_size for info in zf.infolist())
            if aggregate_size > MAX_UNCOMPRESSED_BYTES:
                raise CaptureError("Combined ZIP parts exceed the uncompressed safety budget")
        build_commits = {m["build_commit"] for m in manifests}
        if len(build_commits) != 1:
            raise CaptureError("ZIP parts have different build_commit values")
        frames = []
        for zi, manifest in enumerate(manifests):
            for frame in manifest["frames"]:
                copied = dict(frame)
                copied["__zip_index"] = zi
                frames.append(copied)
        if len(frames) < 2:
            raise CaptureError("At least two combined frames are required for temporal analysis")
        if len({f["index"] for f in frames}) != len(frames):
            raise CaptureError("Duplicate global frame index across ZIP parts")
        frames = sorted(frames, key=lambda f: f["index"])
        completeness = _capture_completeness(manifests, frames)
        manifest = manifests[0]
        plane_names = sorted({p["name"] for f in frames for p in f["planes"]})
        times = [float(f["time_ms"]) for f in frames]
        intervals = [b - a for a, b in zip(times, times[1:])]
        report: dict[str, Any] = {
            "schema": ANALYSIS_SCHEMA,
            "input": [Path(x).name for x in archives],
            "capture_schema": manifest["schema"],
            "build_commit": manifest["build_commit"],
            "encoded_frames": len(frames),
            "frame_indices": [f["index"] for f in frames],
            "capture_completeness": completeness,
            "frame_telemetry": [{"index": f["index"], "packet": f["packet"], "time_ms": f["time_ms"],
                                 "metadata": f["metadata"]} for f in frames],
            "stationarity_gate_policy": {
                "requires": ["stable positions", "stable rotations", "stable left/right projection matrices",
                             "stable crop/gaze/mode when present", "stable per-plane box/resource ROI",
                             "stable guide dimensions/settings and no temporal reset"],
                "position_tolerance_native_units": 1e-4,
                "rotation_component_or_quaternion_norm_tolerance": 1e-5,
                "projection_tolerance": 1e-6,
                "scene_motion_is_not_detected_by_metadata_gate": True,
            },
            "timing": {
                "duration_ms": max(times) - min(times),
                "median_frame_interval_ms": _metric_summary(intervals),
                "max_frame_interval_ms": max(intervals) if intervals else None,
                "nonmonotonic_intervals": sum(x <= 0 for x in intervals),
            },
            "claim": "Unregistered temporal image/depth activity and telemetry only; no stereo ground truth or quality score is computed.",
            "limits": [
                "Camera telemetry does not prove the scene was static; moving objects can change temporal metrics.",
                "Temporal jitter correlations are exploratory and do not establish causation or physical accuracy.",
                "Source-depth bytes are decoded as stored; depth provenance and eye/frame binding are not independently authenticated here.",
                "Color comparisons use unregistered code values and do not model display transfer functions or headset reprojection.",
            ],
            "planes": {},
            "artifacts": {},
        }
        all_depth_pairs: dict[str, list[dict[str, Any]]] = {}
        all_color_pairs: dict[str, list[dict[str, Any]]] = {}
        for plane_name in plane_names:
            per_pair: list[dict[str, Any]] = []
            edge_activity: list[dict[str, Any]] = []
            heat_sum: np.ndarray | None = None
            heat_count = 0
            supported = 0
            first_descriptor: dict[str, Any] | None = None
            plane_kinds: set[str] = set()
            unsupported_formats: list[str] = []
            declared_frames: list[int] = []
            # Process frames in global render order. Retain only the prior plane
            # plus one accumulated heat map, so long captures stay bounded.
            previous_frame = None
            previous_data = None
            previous_kind = None
            for fi, frame in enumerate(frames):
                desc = _plane_lookup(frame).get(plane_name)
                frame_zip = zfs[frame["__zip_index"]]
                if not desc or not desc.get("file") or desc["file"] not in frame_zip.NameToInfo:
                    if previous_frame is not None:
                        per_pair.append({"from_frame": previous_frame["index"], "to_frame": frame["index"],
                                         "eligible": False, "reason": ["plane_missing"]})
                    previous_frame, previous_data, previous_kind = None, None, None
                    continue
                declared_frames.append(frame["index"])
                current, kind, unsupported_reason = _load_plane(frame_zip, desc)
                if current is None:
                    if unsupported_reason:
                        plane_kinds.add("unsupported")
                        unsupported_formats.append(unsupported_reason)
                    if previous_frame is not None:
                        per_pair.append({"from_frame": previous_frame["index"], "to_frame": frame["index"],
                                         "eligible": False, "reason": [unsupported_reason or "unsupported_format"]})
                    previous_frame, previous_data, previous_kind = None, None, None
                    continue
                if first_descriptor is None:
                    first_descriptor = desc
                if previous_frame is not None:
                    eligible, reasons = stationarity_gate(previous_frame, frame,
                        _plane_lookup(previous_frame)[plane_name], desc)
                    if previous_kind != kind or previous_data.shape != current.shape:
                        eligible, reasons = False, reasons + ["plane_shape_or_format_changed"]
                    pair: dict[str, Any] = {"from_frame": previous_frame["index"], "to_frame": frame["index"],
                                            "eligible": bool(eligible), "reason": reasons}
                    if eligible:
                        metric, delta = _diff_metrics(previous_data, current, kind)
                        pair["metrics"] = metric
                        if heat_sum is None:
                            heat_sum = np.zeros_like(delta, dtype=np.float64)
                        if heat_sum.shape == delta.shape:
                            heat_sum += delta
                            heat_count += 1
                        if kind.startswith("depth_"):
                            all_depth_pairs.setdefault(plane_name, []).append(pair)
                        elif kind == "color_rgba":
                            all_color_pairs.setdefault(plane_name, []).append(pair)
                    per_pair.append(pair)
                previous_frame, previous_data, previous_kind = frame, current, kind
                plane_kinds.add(kind)
                supported += 1
                if kind.startswith("depth_"):
                    edge_activity.append({"frame_index": frame["index"], **_depth_edges(current)})
            plane_descriptors = [p for f in frames for p in f["planes"] if p["name"] == plane_name]
            descriptor_formats = sorted({p["format"] for p in plane_descriptors}, key=str)
            footprint_formats = sorted({p.get("footprint_format") for p in plane_descriptors}, key=str)
            payload_frame_set = set(declared_frames)
            valid_stats = [p["metrics"] for p in per_pair if p.get("eligible") and p.get("metrics")]
            entry: dict[str, Any] = {
                "present_frames": supported,
                "available_payload_frames": len(payload_frame_set),
                "missing_frame_indices": [f["index"] for f in frames if f["index"] not in payload_frame_set],
                "format_ids": descriptor_formats,
                "footprint_formats": footprint_formats,
                "decoded_kinds": sorted(plane_kinds),
                "unsupported_formats": sorted(set(unsupported_formats)),
                "shape": [first_descriptor["height"], first_descriptor["width"]] if first_descriptor else None,
                "box": first_descriptor.get("box") if first_descriptor else None,
                "resource_size": first_descriptor.get("resource_size") if first_descriptor else None,
                "per_frame_regions": [{"frame_index": f["index"], "width": p["width"], "height": p["height"],
                                       "row_bytes": p["row_bytes"],
                                       "box": p["box"], "resource_size": p["resource_size"],
                                       "format": p["format"], "footprint_format": p.get("footprint_format")}
                                      for f in frames for p in f["planes"] if p["name"] == plane_name],
                "eligible_stationary_pairs": sum(1 for p in per_pair if p.get("eligible")),
                "excluded_pairs": sum(1 for p in per_pair if not p.get("eligible")),
                "median_mean_abs_change": _metric_summary([s["mean_abs_change"] for s in valid_stats if s["mean_abs_change"] is not None]),
                "median_p95_abs_change": _metric_summary([s["p95_abs_change"] for s in valid_stats if s["p95_abs_change"] is not None]),
                "per_pair": per_pair,
            }
            if plane_kinds and all(k.startswith("depth_") for k in plane_kinds):
                edge_stats = [x for x in edge_activity if x.get("valid_neighbor_pairs")]
                entry["raw_depth_edge_activity"] = {
                    "unit": "stored numeric depth units; not calibrated",
                    "median_abs_neighbor_delta_median": _metric_summary([x["median_abs_neighbor_delta"] for x in edge_stats]),
                    "median_p95_abs_neighbor_delta": _metric_summary([x["p95_abs_neighbor_delta"] for x in edge_stats]),
                    "per_frame": edge_activity,
                }
            report["planes"][plane_name] = entry
            if heat_sum is not None and heat_count:
                heat_file = f"{plane_name}_temporal_heat.png"
                _save_heatmap(heat_sum / heat_count, out / heat_file)
                report["artifacts"][plane_name + "_heatmap"] = heat_file
            if "color_rgba" in plane_kinds:
                contact = _make_contact_sheet(zfs, frames, plane_name, out / f"{plane_name}_contact.png")
                if contact:
                    report["artifacts"][plane_name + "_contact_sheet"] = contact
        # Keep jitter analysis descriptive: pairwise jitter displacement and
        # color/depth temporal activity are correlated only as an exploration.
        guide_correlations: list[dict[str, Any]] = []
        guide_series = _guide_series(frames)
        for guide_index, series in sorted(guide_series.items()):
            by_pos = {pos: (jx, jy, size, settings) for pos, jx, jy, size, settings in series}
            for plane_name, pairs in {**all_color_pairs, **all_depth_pairs}.items():
                xs: list[float] = []
                ys: list[float] = []
                frame_to_pos = {f["index"]: i for i, f in enumerate(frames)}
                for pair in pairs:
                    p0 = frame_to_pos[pair["from_frame"]]
                    p1 = frame_to_pos[pair["to_frame"]]
                    if p0 not in by_pos or p1 not in by_pos:
                        continue
                    if pair["metrics"].get("mean_abs_change") is None:
                        continue
                    j0, j1 = by_pos[p0], by_pos[p1]
                    if j0[2:] != j1[2:]:
                        continue
                    xs.append(math.hypot(j1[0] - j0[0], j1[1] - j0[1]))
                    ys.append(pair["metrics"]["mean_abs_change"])
                if xs:
                    guide_correlations.append({"guide_index": guide_index, "plane": plane_name,
                        "paired_samples": len(xs), "pearson_delta_jitter_vs_temporal_change": _corr(xs, ys),
                        "interpretation": "exploratory association only; not causal or a quality metric"})
        report["jitter_exploration"] = {
            "guide_count_max": max(guide_series.keys(), default=-1) + 1,
            "guide_correlations": guide_correlations,
        }
        report["artifacts"]["xr_stereo_gif"] = _save_xr_sequence_gif(zfs, frames, out / "xr_stereo_sequence.gif")
        report["parts"] = [{"capture_id": m.get("capture_id"), "session_start_ms": m.get("session_start_ms"),
                            "part_index": m.get("part_index"), "part_count": m.get("part_count"),
                            "total_encoded_frames": m.get("total_encoded_frames", m.get("total_recorded_frames")),
                            "first_frame_index": m.get("first_frame_index"), "last_frame_index": m.get("last_frame_index"),
                            "capture_complete": m.get("capture_complete", m.get("complete_capture")),
                            "sufficient_sequence": m.get("sufficient_sequence"),
                            "truncated_by_size": m.get("truncated_by_size")} for m in manifests]
        (out / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
        return report
    finally:
        for zf in zfs:
            zf.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archives", nargs="+", help="one or more duoview-diagnostic-sequence-2 ZIP parts")
    parser.add_argument("--out", required=True, help="directory for report.json and PNG sidecars")
    args = parser.parse_args(argv)
    try:
        report = analyze_capture(args.archives, args.out)
    except (CaptureError, OSError, zipfile.BadZipFile) as exc:
        print(f"capture analysis failed: {exc}", file=sys.stderr)
        return 2
    print(f"Decoded {report['encoded_frames']} frames across {len(report['planes'])} named planes; capture status: {report['capture_completeness']['status']}")
    print(f"Wrote {Path(args.out) / 'report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
