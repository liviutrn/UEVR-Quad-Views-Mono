import json
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image

import analyze_capture as analyzer


def packed_png(raw: bytes, row_bytes: int, height: int) -> bytes:
    png_width = (row_bytes + 3) // 4
    stride = png_width * 4
    padded = b"".join(raw[y * row_bytes:(y + 1) * row_bytes].ljust(stride, b"\0") for y in range(height))
    rgba = np.frombuffer(padded, dtype=np.uint8).reshape(height, png_width, 4)
    import io
    output = io.BytesIO()
    Image.fromarray(rgba, mode="RGBA").save(output, format="PNG")
    return output.getvalue()


def descriptor(name: str, file_name: str, fmt: int, width: int, height: int, row_bytes: int) -> dict:
    return {
        "name": name,
        "file": file_name,
        "width": width,
        "height": height,
        "row_bytes": row_bytes,
        "format": fmt,
        "footprint_format": None,
        "box": [0, 0, width, height],
        "resource_size": [width, height],
        "encoding": "png-packed-bytes",
        "required": True,
    }


def metadata(jx: float) -> dict:
    return {
        "positions": [[0.0, 0.0, 0.0], [0.064, 0.0, 0.0]],
        "rotations": [[0.0, 0.0, 0.0, 1.0], [0.0, 0.0, 0.0, 1.0]],
        "projection_left": [1.0, 0.0, 0.0, 0.0] * 4,
        "projection_right": [1.0, 0.0, 0.0, 0.0] * 4,
        "crop": {"gaze_rect": [0, 0, 4, 3]},
        "mode": "stereo",
        "strategy": "duoview",
        "quality": "native_fovea",
        "stereo_recorded": True,
        "depth_serials": {"left": 120, "right": 120},
        "depth_viewports": {"left": [0, 0, 4, 3], "right": [0, 0, 4, 3]},
        "guides": [{"input": [4, 3], "jitter": [jx, -jx], "motion_scale": [1.0, 1.0],
                    "flags": 0, "reset": False, "feature": 0, "evaluation": 1}],
    }


def build_frames(frame_count: int = 4, start_index: int = 0) -> tuple[list[dict], dict[str, bytes]]:
    frames = []
    payloads: dict[str, bytes] = {}
    color = np.zeros((3, 4, 4), dtype=np.uint8)
    color[..., 0:3] = 80  # BGRA bytes; stable XR output control
    color[..., 3] = 255
    color_bytes = color.tobytes()
    for i in range(frame_count):
        depth = np.full((3, 4), 0.8, dtype="<f4")
        # A foreground strip moves one texel each rendered frame. The archive
        # stores the exact float byte stream; the analyzer does not infer truth.
        x = i % 4
        depth[1, x] = 0.2
        depth_raw = depth.tobytes()
        cfile = f"planes/f{start_index + i}_xr_left.png"
        rfile = f"planes/f{start_index + i}_xr_right.png"
        dfile = f"planes/f{start_index + i}_depth_left.png"
        right_color = color.copy()
        right_color[..., 2] = (80 + i) % 256
        payloads[cfile] = packed_png(color_bytes, 16, 3)
        payloads[rfile] = packed_png(right_color.tobytes(), 16, 3)
        payloads[dfile] = packed_png(depth_raw, 16, 3)
        frames.append({
            "index": start_index + i,
            "packet": 1000 + start_index + i,
            "time_ms": float((start_index + i) * 11.1),
            "metadata": metadata((0.25, -0.25, 0.25, -0.25)[i % 4]),
            "planes": [
                descriptor("xr_left", cfile, 87, 4, 3, 16),
                descriptor("xr_right", rfile, 87, 4, 3, 16),
                descriptor("depth_left", dfile, 41, 4, 3, 16),
            ],
        })
    return frames, payloads


def write_archive(path: Path, frames: list[dict], payloads: dict[str, bytes], **manifest_fields) -> None:
    manifest = {"schema": analyzer.SCHEMA, "build_commit": "test-commit", "frames": frames}
    manifest.update(manifest_fields)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, separators=(",", ":")))
        for name, data in payloads.items():
            zf.writestr(name, data)


class AnalyzerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_raw_packed_rows_and_float_bits_round_trip(self):
        # Includes two padding bytes per row, which must not leak into pixels.
        words = [0x3F800001, 0x40000002, 0x40400003, 0x40800004]
        row0 = struct.pack("<II", words[0], words[1]) + b"\xab\xcd"
        row1 = struct.pack("<II", words[2], words[3]) + b"\xef\x01"
        raw = row0 + row1
        desc = descriptor("depth", "x.png", 41, 2, 2, 10)
        decoded = analyzer.decode_png_rows(packed_png(raw, 10, 2), desc)
        self.assertEqual(decoded, raw)
        image, kind = analyzer.decode_native(decoded, desc)
        self.assertEqual(kind, "depth_r32_float")
        self.assertEqual(image.view("<u4").reshape(-1).tolist(), words)

    def test_known_dxgi_color_depth_and_motion_decoders(self):
        bgra = descriptor("color", "x.png", 87, 1, 1, 4)
        image, kind = analyzer.decode_native(bytes([10, 20, 30, 255]), bgra)
        self.assertEqual(kind, "color_rgba")
        np.testing.assert_allclose(image[0, 0], [30 / 255, 20 / 255, 10 / 255, 1])

        packed = (1023 | (512 << 10) | (1 << 20) | (3 << 30))
        rgba10 = descriptor("color", "x.png", 24, 1, 1, 4)
        image, _ = analyzer.decode_native(struct.pack("<I", packed), rgba10)
        np.testing.assert_allclose(image[0, 0], [1.0, 512 / 1023, 1 / 1023, 1.0])

        r24 = descriptor("depth", "x.png", 46, 1, 1, 4)
        image, kind = analyzer.decode_native(struct.pack("<I", 0xFFABCDEF), r24)
        self.assertEqual(kind, "depth_r24_unorm")
        self.assertAlmostEqual(float(image[0, 0]), 0xABCDEF / 16777215)

        depth64 = descriptor("depth", "x.png", 20, 1, 1, 8)
        image, kind = analyzer.decode_native(struct.pack("<fI", 2.5, 0xFFFFFFFF), depth64)
        self.assertEqual(kind, "depth_r32_float")
        self.assertEqual(float(image[0, 0]), 2.5)
        depth_footprint = descriptor("depth", "x.png", 20, 1, 1, 4)
        depth_footprint["footprint_format"] = 39
        image, _ = analyzer.decode_native(struct.pack("<f", 3.5), depth_footprint)
        self.assertEqual(float(image[0, 0]), 3.5)

        r16f = descriptor("depth", "x.png", 54, 1, 1, 2)
        image, _ = analyzer.decode_native(struct.pack("<e", 1.25), r16f)
        self.assertEqual(float(image[0, 0]), 1.25)
        rg16 = descriptor("motion", "x.png", 34, 1, 1, 4)
        image, kind = analyzer.decode_native(struct.pack("<ee", 0.5, -0.25), rg16)
        self.assertEqual(kind, "motion_rg16_float")
        np.testing.assert_allclose(image[0, 0], [0.5, -0.25])
        rg32 = descriptor("motion", "x.png", 16, 1, 1, 8)
        image, kind = analyzer.decode_native(struct.pack("<ff", 0.5, -0.25), rg32)
        self.assertEqual(kind, "motion_rg32_float")
        np.testing.assert_allclose(image[0, 0], [0.5, -0.25])

    def test_moving_depth_detected_and_unchanged_color_control(self):
        frames, payloads = build_frames()
        archive = self.root / "sequence.zip"
        write_archive(archive, frames, payloads)
        report = analyzer.analyze_capture(archive, self.root / "out")
        self.assertEqual(report["capture_completeness"]["status"], "unknown")
        xr = report["planes"]["xr_left"]
        depth = report["planes"]["depth_left"]
        self.assertEqual(xr["eligible_stationary_pairs"], 3)
        self.assertAlmostEqual(xr["median_mean_abs_change"], 0.0)
        self.assertGreater(depth["median_mean_abs_change"], 0.0)
        self.assertIsNotNone(depth["raw_depth_edge_activity"]["median_p95_abs_neighbor_delta"])
        self.assertTrue(report["jitter_exploration"]["guide_correlations"])
        self.assertEqual(report["jitter_exploration"]["guide_correlations"][0]["paired_samples"], 3)
        self.assertIn("exploratory", report["jitter_exploration"]["guide_correlations"][0]["interpretation"])
        self.assertTrue((self.root / "out" / "xr_left_contact.png").is_file())
        self.assertTrue((self.root / "out" / "depth_left_temporal_heat.png").is_file())
        self.assertTrue((self.root / "out" / "xr_stereo_sequence.gif").is_file())
        encoded = json.dumps(report).lower()
        self.assertNotIn("lpips", encoded)
        self.assertNotIn("quality_score", encoded)
        self.assertNotIn("accuracy_score", encoded)

    def test_multiple_parts_combined_by_global_frame_index(self):
        all_frames, all_payloads = build_frames(16)
        archives = []
        for part_index, frames_slice in enumerate((all_frames[:8], all_frames[8:])):
            paths = {p["file"] for frame in frames_slice for p in frame["planes"]}
            payloads = {name: all_payloads[name] for name in paths}
            path = self.root / f"part-{part_index}.zip"
            write_archive(path, frames_slice, payloads, capture_id=77, part_index=part_index + 1,
                          part_count=2, total_encoded_frames=16, sufficient_sequence=True,
                          session_start_ms=100.0,
                          capture_span_ms=166.5, requested_window_ms=200.0,
                          termination="time_window", requested_max_frames=96,
                          frames_recorded=16, rejected_frames=0, dropped_frames=0, memory_limited=False,
                          first_frame_index=frames_slice[0]["index"], last_frame_index=frames_slice[-1]["index"],
                          capture_complete=(part_index == 1), truncated_by_size=False)
            archives.append(path)
        index_path = self.root / "capture_index.json"
        index_path.write_text(json.dumps({"schema": "duoview-sequence-parts-1", "capture_id": 77,
                                          "session_start_ms": 100.0, "total_frames": 16,
                                          "parts": [p.name for p in archives]}), encoding="utf-8")
        report = analyzer.analyze_capture(index_path, self.root / "multipart")
        self.assertEqual(report["encoded_frames"], 16)
        self.assertEqual(report["capture_completeness"]["status"], "complete")
        self.assertEqual(report["capture_completeness"]["part_indices"], [1, 2])
        self.assertEqual(report["capture_completeness"]["sufficient_sequence"], True)
        with Image.open(self.root / "multipart" / "xr_stereo_sequence.gif") as gif:
            self.assertEqual(report["artifacts"]["xr_stereo_gif"]["source_frame_count"], 16)
            self.assertEqual(report["artifacts"]["xr_stereo_gif"]["encoded_gif_frame_count"], gif.n_frames)
        self.assertEqual(sum(report["artifacts"]["xr_stereo_gif"]["encoded_gif_durations_ms"]),
                         sum(report["artifacts"]["xr_stereo_gif"]["requested_gif_duration_ms_per_source_frame"]))
        self.assertEqual(report["artifacts"]["xr_stereo_gif"]["resized_or_interpolated"], False)
        self.assertEqual(report["artifacts"]["xr_stereo_gif"]["native_side_by_side_size"], [8, 3])

    def test_frame_limit_capture_can_be_complete_with_shorter_span(self):
        frames, payloads = build_frames(96)
        for i, frame in enumerate(frames):
            frame["time_ms"] = float(i * 8)
        archive = self.root / "frame-limit.zip"
        write_archive(archive, frames, payloads, capture_id=101, session_start_ms=500.0,
                      part_index=1, part_count=1, total_encoded_frames=96,
                      first_frame_index=0, last_frame_index=95,
                      capture_span_ms=760.0, requested_window_ms=2000.0,
                      termination="frame_limit", requested_max_frames=96,
                      sufficient_sequence=True, capture_complete=True,
                      truncated_by_size=False, frames_recorded=96,
                      rejected_frames=0, dropped_frames=0, memory_limited=False)
        report = analyzer.analyze_capture(archive, self.root / "frame-limit-out")
        self.assertEqual(report["capture_completeness"]["status"], "complete")
        self.assertEqual(report["capture_completeness"]["termination"], "frame_limit")
        self.assertEqual(report["capture_completeness"]["actual_frame_span_ms"], 760.0)

    def test_single_split_part_is_marked_partial(self):
        frames, payloads = build_frames(2, start_index=0)
        archive = self.root / "part.zip"
        write_archive(archive, frames, payloads, capture_id="capture-b", part_index=1,
                      part_count=3, total_encoded_frames=6, complete_capture=False,
                      sufficient_sequence=False, truncated_by_size=False)
        report = analyzer.analyze_capture(archive, self.root / "partial")
        self.assertEqual(report["capture_completeness"]["status"], "partial")
        self.assertEqual(report["capture_completeness"]["missing_part_indices"], [2, 3])

    def test_camera_and_roi_change_excludes_stationary_pair(self):
        frames, _ = build_frames(2)
        changed = json.loads(json.dumps(frames[1]))
        changed["metadata"]["positions"][0][0] = 0.02
        changed["metadata"]["crop"]["gaze_rect"] = [1, 0, 5, 3]
        changed["metadata"]["guides"][0]["reset"] = 1
        plane_a = frames[0]["planes"][0]
        plane_b = json.loads(json.dumps(plane_a))
        plane_b["box"] = [1, 0, 5, 3]
        allowed, reasons = analyzer.stationarity_gate(frames[0], changed, plane_a, plane_b)
        self.assertFalse(allowed)
        self.assertIn("camera_position_changed", reasons)
        self.assertIn("crop_changed", reasons)
        self.assertIn("guide_0_temporal_reset", reasons)
        self.assertIn("plane_box_changed", reasons)

    def test_unknown_guides_are_preserved_without_fake_jitter_analysis(self):
        frames, payloads = build_frames(2)
        for frame in frames:
            frame["metadata"]["guides"][0]["input"] = [0, 0]
        archive = self.root / "unknown-guide.zip"
        write_archive(archive, frames, payloads)
        report = analyzer.analyze_capture(archive, self.root / "unknown-guide-out")
        self.assertEqual(report["jitter_exploration"]["guide_count_max"], 0)
        self.assertEqual(report["jitter_exploration"]["guide_correlations"], [])
        self.assertEqual(report["frame_telemetry"][0]["metadata"]["guides"][0]["input"], [0, 0])

    def test_bad_schema_empty_frames_missing_payload_and_zip_budget(self):
        path = self.root / "bad.zip"
        write_archive(path, [], {}, schema="duoview-diagnostic-sequence-1")
        with self.assertRaises(analyzer.CaptureError):
            analyzer._validate_archive(path)

        write_archive(path, [], {}, schema=analyzer.SCHEMA)
        with self.assertRaises(analyzer.CaptureError):
            analyzer._validate_archive(path)

        frames, payloads = build_frames(2)
        missing = dict(payloads)
        missing.pop(frames[0]["planes"][0]["file"])
        write_archive(path, frames, missing)
        with self.assertRaises(analyzer.CaptureError):
            analyzer._validate_archive(path)

        old_limit = analyzer.MAX_ARCHIVE_BYTES
        old_uncompressed_limit = analyzer.MAX_UNCOMPRESSED_BYTES
        try:
            analyzer.MAX_ARCHIVE_BYTES = 1
            with self.assertRaises(analyzer.CaptureError):
                analyzer._validate_archive(path)
            analyzer.MAX_ARCHIVE_BYTES = old_limit
            analyzer.MAX_UNCOMPRESSED_BYTES = 16
            with self.assertRaises(analyzer.CaptureError):
                analyzer._validate_archive(path)
        finally:
            analyzer.MAX_ARCHIVE_BYTES = old_limit
            analyzer.MAX_UNCOMPRESSED_BYTES = old_uncompressed_limit

    def test_crc_corruption_rejected(self):
        frames, payloads = build_frames(2)
        path = self.root / "crc.zip"
        write_archive(path, frames, payloads)
        with zipfile.ZipFile(path, "r") as zf:
            info = zf.getinfo(frames[0]["planes"][0]["file"])
            offset = info.header_offset
        data = bytearray(path.read_bytes())
        name_len, extra_len = struct.unpack_from("<HH", data, offset + 26)
        payload_offset = offset + 30 + name_len + extra_len
        data[payload_offset + 4] ^= 0x01
        path.write_bytes(data)
        with self.assertRaises(analyzer.CaptureError):
            analyzer._validate_archive(path)


if __name__ == "__main__":
    unittest.main()
