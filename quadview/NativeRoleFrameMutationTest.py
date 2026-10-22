#!/usr/bin/env python3
"""Prove the role-frame regression test catches the old canonical-frame filter."""

from pathlib import Path
import shutil
import subprocess
import tempfile


HERE = Path(__file__).resolve().parent
OLD_FILTER = "slot.source.scene == scene) {\n            for (size_t i = 0; i < 4; ++i) if (slot.targets[i] == target &&"
MUTATED_FILTER = "slot.source.scene == scene && slot.source.engine_frame == frame) {\n            for (size_t i = 0; i < 4; ++i) if (slot.targets[i] == target &&"


def main() -> int:
    if not shutil.which("g++"):
        raise SystemExit("g++ is required for the role-frame mutation check")

    with tempfile.TemporaryDirectory(prefix="quadview-role-frame-mutation-") as temp_name:
        temp = Path(temp_name)
        header = (HERE / "QuadViewNativeDelivery.hpp").read_text()
        if header.count(OLD_FILTER) != 1:
            raise SystemExit("could not uniquely locate the render filter to mutate")
        (temp / "QuadViewNativeDelivery.hpp").write_text(
            header.replace(OLD_FILTER, MUTATED_FILTER, 1)
        )
        shutil.copy2(HERE / "QuadViewDelivery.hpp", temp / "QuadViewDelivery.hpp")
        shutil.copy2(HERE / "NativeRoleFrameTests.cpp", temp / "NativeRoleFrameTests.cpp")

        executable = temp / "role-frame-mutant-test"
        compile_result = subprocess.run(
            ["g++", "-std=c++20", "-Wall", "-Wextra", "-Werror", "-UNDEBUG",
             "-pthread", str(temp / "NativeRoleFrameTests.cpp"), "-o", str(executable)],
            text=True, capture_output=True,
        )
        if compile_result.returncode:
            raise SystemExit("mutant compile failed:\n" + compile_result.stderr)

        run_result = subprocess.run([str(executable)], text=True, capture_output=True)
        if (run_result.returncode == 0 or "Assertion" not in run_result.stderr or
                "command && command->view == view" not in run_result.stderr):
            raise SystemExit(
                "mutated old-frame filter did not trigger an assertion failure\n"
                + run_result.stderr
            )

    print("role-frame mutation check passed: old canonical-frame filter triggers an assertion")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
