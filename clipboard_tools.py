from __future__ import annotations

import ctypes
import os
from ctypes import wintypes


CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002


def read_text_from_clipboard(tk_root=None) -> tuple[bool, str]:
    """Return the current text clipboard content when it is readable."""
    try:
        import pyperclip

        return True, str(pyperclip.paste() or "")
    except Exception:
        pass

    if tk_root is not None:
        try:
            return True, str(tk_root.clipboard_get() or "")
        except Exception:
            return False, ""

    return False, ""


def copy_text_to_clipboard(text: str, tk_root=None) -> bool:
    """Copy text with pyperclip when present, otherwise use the Tk clipboard."""
    value = str(text or "")
    if not value:
        return False

    try:
        import pyperclip

        pyperclip.copy(value)
        return True
    except Exception:
        pass

    if tk_root is not None:
        try:
            tk_root.clipboard_clear()
            tk_root.clipboard_append(value)
            tk_root.update_idletasks()
            return True
        except Exception:
            return False

    return False


def copy_rich_text_to_clipboard(html: str, text: str, tk_root=None) -> bool:
    """Copy rich HTML plus plain text when possible, otherwise copy plain text."""
    html_value = str(html or "")
    text_value = str(text or "")
    if not html_value and not text_value:
        return False

    if html_value and _copy_html_to_windows_clipboard(html_value, text_value):
        return True

    return copy_text_to_clipboard(text_value or html_value, tk_root)


def clear_text_clipboard(tk_root=None) -> bool:
    """Clear the text clipboard."""
    try:
        import pyperclip

        pyperclip.copy("")
        return True
    except Exception:
        pass

    if tk_root is not None:
        try:
            tk_root.clipboard_clear()
            tk_root.update_idletasks()
            return True
        except Exception:
            return False

    return False


def _copy_html_to_windows_clipboard(html_fragment: str, plain_text: str) -> bool:
    if os.name != "nt":
        return False

    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
    except Exception:
        return False

    try:
        user32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
        user32.RegisterClipboardFormatW.restype = wintypes.UINT
        user32.OpenClipboard.argtypes = [wintypes.HWND]
        user32.OpenClipboard.restype = wintypes.BOOL
        user32.EmptyClipboard.restype = wintypes.BOOL
        user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
        user32.SetClipboardData.restype = wintypes.HANDLE
        user32.CloseClipboard.restype = wintypes.BOOL
        kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
        kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalUnlock.restype = wintypes.BOOL
        kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalFree.restype = wintypes.HGLOBAL
    except Exception:
        return False

    html_format = user32.RegisterClipboardFormatW("HTML Format")
    if not html_format:
        return False

    html_handle = None
    text_handle = None
    opened = False

    try:
        html_handle = _global_alloc_bytes(_build_cf_html(html_fragment) + b"\0", kernel32)
        text_handle = _global_alloc_bytes((str(plain_text or "") + "\0").encode("utf-16le"), kernel32)
        if not html_handle and not text_handle:
            return False

        opened = bool(user32.OpenClipboard(None))
        if not opened:
            return False
        if not user32.EmptyClipboard():
            return False

        html_set = False
        text_set = False
        if html_handle:
            html_set = bool(user32.SetClipboardData(html_format, html_handle))
            if html_set:
                html_handle = None
        if text_handle:
            text_set = bool(user32.SetClipboardData(CF_UNICODETEXT, text_handle))
            if text_set:
                text_handle = None

        return html_set or text_set
    except Exception:
        return False
    finally:
        if opened:
            try:
                user32.CloseClipboard()
            except Exception:
                pass
        if html_handle:
            try:
                kernel32.GlobalFree(html_handle)
            except Exception:
                pass
        if text_handle:
            try:
                kernel32.GlobalFree(text_handle)
            except Exception:
                pass


def _global_alloc_bytes(data: bytes, kernel32) -> int | None:
    handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
    if not handle:
        return None

    pointer = kernel32.GlobalLock(handle)
    if not pointer:
        kernel32.GlobalFree(handle)
        return None

    try:
        ctypes.memmove(pointer, data, len(data))
    finally:
        kernel32.GlobalUnlock(handle)

    return handle


def _build_cf_html(html_fragment: str) -> bytes:
    fragment = str(html_fragment or "")
    before_fragment = "<!DOCTYPE html><html><body><!--StartFragment-->"
    after_fragment = "<!--EndFragment--></body></html>"
    body = f"{before_fragment}{fragment}{after_fragment}"
    header_template = (
        "Version:0.9\r\n"
        "StartHTML:{start_html:010d}\r\n"
        "EndHTML:{end_html:010d}\r\n"
        "StartFragment:{start_fragment:010d}\r\n"
        "EndFragment:{end_fragment:010d}\r\n"
    )
    empty_header = header_template.format(start_html=0, end_html=0, start_fragment=0, end_fragment=0).encode("ascii")
    body_bytes = body.encode("utf-8")
    before_fragment_bytes = before_fragment.encode("utf-8")
    fragment_bytes = fragment.encode("utf-8")
    start_html = len(empty_header)
    end_html = start_html + len(body_bytes)
    start_fragment = start_html + len(before_fragment_bytes)
    end_fragment = start_fragment + len(fragment_bytes)
    header = header_template.format(
        start_html=start_html,
        end_html=end_html,
        start_fragment=start_fragment,
        end_fragment=end_fragment,
    ).encode("ascii")
    return header + body_bytes
