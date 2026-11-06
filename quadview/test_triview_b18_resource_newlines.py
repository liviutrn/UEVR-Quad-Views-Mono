#!/usr/bin/env python3
"""Source parity accepts checkout line endings and rejects source changes."""
import tempfile
from pathlib import Path
import unittest
from test_triview_b18_resources import same_source_text

class SourceParityTests(unittest.TestCase):
    def test_windows_checkout_matches_lf_overlay(self):
        with tempfile.TemporaryDirectory() as directory:
            checkout=Path(directory)/'checkout.hpp'
            generated=Path(directory)/'generated.hpp'
            source=b'#pragma once\ninline bool valid() { return true; }\n'
            checkout.write_bytes(source.replace(b'\n',b'\r\n'))
            generated.write_bytes(source)
            self.assertNotEqual(checkout.read_bytes(),generated.read_bytes())
            self.assertTrue(same_source_text(checkout,generated))
            # A meaningful change still fails the same production comparison.
            generated.write_bytes(source.replace(b'true',b'false'))
            self.assertFalse(same_source_text(checkout,generated))
    def test_only_line_endings_are_normalized(self):
        with tempfile.TemporaryDirectory() as directory:
            a=Path(directory)/'a.hpp';b=Path(directory)/'b.hpp'
            a.write_bytes(b'int x=1;\r\n');b.write_bytes(b'int x=2;\n')
            self.assertFalse(same_source_text(a,b))
            b.write_bytes(b'int x =1;\n')
            self.assertFalse(same_source_text(a,b))
if __name__=='__main__': unittest.main()
