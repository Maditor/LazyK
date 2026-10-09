"""Graphics cards for the OCR device menu (Windows DXGI adapters, in the order DirectML numbers them).

The list is read in a short-lived child process (`main.py --list-gpus FILE`): a mistake in the native
calls can then only end that child, never LazyK. The result is cached; the menus show what is known.
"""
import json
import logging
import os
import subprocess
import sys
import tempfile
import threading

log = logging.getLogger(__name__)

_gpus = None        # None = not read yet | [] = none found / could not be read | [{"id", "name", "mb"}]
_started = False
_lock = threading.Lock()


def cached():
    """None while unknown, else the list of cards found."""
    return _gpus


def short_name(name: str, limit: int = 26) -> str:
    n = str(name or "")
    for a, b in (("(R)", ""), ("(TM)", ""), ("NVIDIA ", ""), ("AMD ", ""), ("GeForce ", ""), (" Graphics", ""),
                 ("Laptop GPU", "Laptop")):
        n = n.replace(a, b)
    n = " ".join(n.split())
    return n if len(n) <= limit else n[:limit - 1] + "…"


# ---------------------------------------------------------------- the child process
def enumerate_adapters():
    """DXGI adapters as [{"id", "name", "mb"}], software adapters left out (their numbers are kept).
    Run only in the child process."""
    if sys.platform != "win32":
        return []
    import ctypes
    from ctypes import POINTER, byref, c_int, c_long, c_size_t, c_ubyte, c_uint, c_uint16, c_uint32, c_ulong, c_void_p, c_wchar

    class GUID(ctypes.Structure):
        _fields_ = [("a", c_uint32), ("b", c_uint16), ("c", c_uint16), ("d", c_ubyte * 8)]

    class DESC1(ctypes.Structure):  # DXGI_ADAPTER_DESC1
        _fields_ = [("Description", c_wchar * 128), ("VendorId", c_uint), ("DeviceId", c_uint),
                    ("SubSysId", c_uint), ("Revision", c_uint), ("DedicatedVideoMemory", c_size_t),
                    ("DedicatedSystemMemory", c_size_t), ("SharedSystemMemory", c_size_t),
                    ("LuidLow", c_uint), ("LuidHigh", c_int), ("Flags", c_uint)]

    # IDXGIFactory1 {770aae78-f26f-4dba-a829-253c83d1b387}
    iid = GUID(0x770AAE78, 0xF26F, 0x4DBA, (c_ubyte * 8)(0xA8, 0x29, 0x25, 0x3C, 0x83, 0xD1, 0xB3, 0x87))

    def method(obj, index, restype, *argtypes):
        vtbl = ctypes.cast(obj, POINTER(POINTER(c_void_p))).contents
        return ctypes.WINFUNCTYPE(restype, c_void_p, *argtypes)(vtbl[index])

    factory = c_void_p()
    if ctypes.windll.dxgi.CreateDXGIFactory1(byref(iid), byref(factory)) != 0 or not factory.value:
        return []
    out = []
    try:
        enum_adapters1 = method(factory, 12, c_long, c_uint, POINTER(c_void_p))   # IDXGIFactory1::EnumAdapters1
        for i in range(32):
            adapter = c_void_p()
            if enum_adapters1(factory, i, byref(adapter)) != 0 or not adapter.value:
                break
            try:
                desc = DESC1()
                if method(adapter, 10, c_long, POINTER(DESC1))(adapter, byref(desc)) == 0:   # GetDesc1
                    software = bool(desc.Flags & 2) or desc.VendorId == 0x1414   # WARP / Basic Render Driver
                    if not software:
                        out.append({"id": i, "name": desc.Description.strip(),
                                    "mb": int(desc.DedicatedVideoMemory // (1024 * 1024))})
            finally:
                method(adapter, 2, c_ulong)(adapter)   # Release
    finally:
        method(factory, 2, c_ulong)(factory)
    return out


def write_listing(path: str):
    """`main.py --list-gpus FILE`: write the cards as JSON. Never raises."""
    try:
        data = enumerate_adapters()
    except Exception:
        data = []
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except OSError:
        pass


# ---------------------------------------------------------------- the parent side
def _child_cmd(out: str):
    if getattr(sys, "frozen", False):
        return [sys.executable, "--list-gpus", out]
    from .config import app_dir
    return [sys.executable, os.path.join(app_dir(), "main.py"), "--list-gpus", out]


def _read_in_child() -> list:
    fd, out = tempfile.mkstemp(prefix="lazyk_gpus_", suffix=".json")
    os.close(fd)
    try:
        # no window, and below normal priority: a second LazyK process starting must not make the PC stutter
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
        subprocess.run(_child_cmd(out), timeout=20, creationflags=flags, stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        with open(out, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [g for g in data if isinstance(g, dict) and isinstance(g.get("id"), int) and g.get("name")]
    except Exception as e:  # noqa: BLE001
        log.warning("Could not list the graphics cards: %s", e)
        return []
    finally:
        try:
            os.remove(out)
        except OSError:
            pass


def load(on_done=None):
    """Read the list once, in the background. `on_done()` runs on that thread when it is known."""
    global _started
    with _lock:
        if _started:
            return
        _started = True

    def work():
        global _gpus
        from . import winapi
        winapi.lower_this_thread()
        _gpus = _read_in_child() if sys.platform == "win32" else []
        log.info("Graphics cards: %s", [(g["id"], g["name"]) for g in _gpus] or "none found")
        if on_done:
            try:
                on_done()
            except Exception:
                log.exception("gpus on_done failed")
    threading.Thread(target=work, daemon=True, name="gpu-list").start()
