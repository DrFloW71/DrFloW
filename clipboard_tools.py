from __future__ import annotations


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
