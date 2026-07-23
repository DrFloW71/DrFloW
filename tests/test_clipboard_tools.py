from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import patch

from clipboard_tools import (
    _build_cf_html,
    clear_text_clipboard,
    copy_rich_text_to_clipboard,
    copy_text_to_clipboard,
    read_text_from_clipboard,
)


class ClipboardToolsTests(unittest.TestCase):
    def test_pyperclip_backend_reads_copies_and_clears_text(self):
        state = {"text": "ancien"}

        fake_pyperclip = types.SimpleNamespace(
            copy=lambda value: state.__setitem__("text", value),
            paste=lambda: state["text"],
        )

        with patch.dict(sys.modules, {"pyperclip": fake_pyperclip}):
            self.assertEqual(read_text_from_clipboard(), (True, "ancien"))
            self.assertTrue(copy_text_to_clipboard("nouveau"))
            self.assertEqual(read_text_from_clipboard(), (True, "nouveau"))
            self.assertTrue(clear_text_clipboard())
            self.assertEqual(read_text_from_clipboard(), (True, ""))

    def test_tk_backend_is_used_when_pyperclip_is_unavailable(self):
        class FakeRoot:
            def __init__(self) -> None:
                self.text = "ancien"
                self.updated = False

            def clipboard_get(self) -> str:
                return self.text

            def clipboard_clear(self) -> None:
                self.text = ""

            def clipboard_append(self, value: str) -> None:
                self.text += value

            def update_idletasks(self) -> None:
                self.updated = True

        root = FakeRoot()

        with patch.dict(sys.modules, {"pyperclip": None}):
            self.assertEqual(read_text_from_clipboard(root), (True, "ancien"))
            self.assertTrue(copy_text_to_clipboard("nouveau", root))
            self.assertEqual(read_text_from_clipboard(root), (True, "nouveau"))
            self.assertTrue(clear_text_clipboard(root))
            self.assertEqual(read_text_from_clipboard(root), (True, ""))
            self.assertTrue(root.updated)

    def test_cf_html_offsets_wrap_exact_fragment(self):
        fragment = "<strong>Texte</strong><br><u>Suite</u>"
        data = _build_cf_html(fragment)
        header, _body = data.split(b"<!DOCTYPE html>", 1)
        offsets = {}
        for line in header.decode("ascii").splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                if value.isdigit():
                    offsets[key] = int(value)

        self.assertEqual(data[offsets["StartFragment"]:offsets["EndFragment"]], fragment.encode("utf-8"))
        self.assertIn(b"<!--StartFragment-->", data[offsets["StartHTML"]:offsets["EndHTML"]])
        self.assertIn(b"<!--EndFragment-->", data[offsets["StartHTML"]:offsets["EndHTML"]])

    def test_rich_clipboard_falls_back_to_plain_text(self):
        with patch("clipboard_tools._copy_html_to_windows_clipboard", return_value=False), \
             patch("clipboard_tools.copy_text_to_clipboard", return_value=True) as copy_text:
            self.assertTrue(copy_rich_text_to_clipboard("<strong>Texte</strong>", "Texte"))

        copy_text.assert_called_once_with("Texte", None)


if __name__ == "__main__":
    unittest.main()
