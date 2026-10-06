"""Minimal ctypes binding to the ALSA control API (libasound).

Only what Audius needs: enumerate a card's controls, read and write them, and
receive change events so edits made elsewhere (alsamixer, alsactl) show up live.
A `Ctl` handle is not thread-safe; open one per thread.
"""
import ctypes
import ctypes.util
import errno
import glob
import os
from ctypes import POINTER, Structure, byref, c_char_p, c_int, c_long, c_short, c_uint, c_void_p

_lib = ctypes.CDLL(ctypes.util.find_library("asound") or "libasound.so.2", use_errno=True)

TYPE_BOOLEAN, TYPE_INTEGER, TYPE_ENUMERATED = 1, 2, 3
_EVENT_ELEM = 0
_MASK_VALUE, _MASK_INFO = 1, 2
_MASK_REMOVE = 0xFFFFFFFF


class _PollFd(Structure):
    _fields_ = [("fd", c_int), ("events", c_short), ("revents", c_short)]


def _fn(name, restype, *argtypes):
    f = getattr(_lib, name)
    f.restype = restype
    f.argtypes = list(argtypes)
    return f


_strerror = _fn("snd_strerror", c_char_p, c_int)
_ctl_open = _fn("snd_ctl_open", c_int, POINTER(c_void_p), c_char_p, c_int)
_ctl_close = _fn("snd_ctl_close", c_int, c_void_p)
_ctl_nonblock = _fn("snd_ctl_nonblock", c_int, c_void_p, c_int)
_ctl_subscribe = _fn("snd_ctl_subscribe_events", c_int, c_void_p, c_int)
_ctl_pfd_count = _fn("snd_ctl_poll_descriptors_count", c_int, c_void_p)
_ctl_pfds = _fn("snd_ctl_poll_descriptors", c_int, c_void_p, POINTER(_PollFd), c_uint)
_ctl_read = _fn("snd_ctl_read", c_int, c_void_p, c_void_p)

_ev_malloc = _fn("snd_ctl_event_malloc", c_int, POINTER(c_void_p))
_ev_free = _fn("snd_ctl_event_free", None, c_void_p)
_ev_type = _fn("snd_ctl_event_get_type", c_int, c_void_p)
_ev_mask = _fn("snd_ctl_event_elem_get_mask", c_uint, c_void_p)
_ev_numid = _fn("snd_ctl_event_elem_get_numid", c_uint, c_void_p)

_list_malloc = _fn("snd_ctl_elem_list_malloc", c_int, POINTER(c_void_p))
_list_free = _fn("snd_ctl_elem_list_free", None, c_void_p)
_list = _fn("snd_ctl_elem_list", c_int, c_void_p, c_void_p)
_list_alloc = _fn("snd_ctl_elem_list_alloc_space", c_int, c_void_p, c_uint)
_list_free_space = _fn("snd_ctl_elem_list_free_space", None, c_void_p)
_list_count = _fn("snd_ctl_elem_list_get_count", c_uint, c_void_p)
_list_used = _fn("snd_ctl_elem_list_get_used", c_uint, c_void_p)
_list_numid = _fn("snd_ctl_elem_list_get_numid", c_uint, c_void_p, c_uint)

_info_malloc = _fn("snd_ctl_elem_info_malloc", c_int, POINTER(c_void_p))
_info_free = _fn("snd_ctl_elem_info_free", None, c_void_p)
_info_set_numid = _fn("snd_ctl_elem_info_set_numid", None, c_void_p, c_uint)
_info = _fn("snd_ctl_elem_info", c_int, c_void_p, c_void_p)
_info_name = _fn("snd_ctl_elem_info_get_name", c_char_p, c_void_p)
_info_type = _fn("snd_ctl_elem_info_get_type", c_int, c_void_p)
_info_count = _fn("snd_ctl_elem_info_get_count", c_uint, c_void_p)
_info_min = _fn("snd_ctl_elem_info_get_min", c_long, c_void_p)
_info_max = _fn("snd_ctl_elem_info_get_max", c_long, c_void_p)
_info_items = _fn("snd_ctl_elem_info_get_items", c_uint, c_void_p)
_info_set_item = _fn("snd_ctl_elem_info_set_item", None, c_void_p, c_uint)
_info_item_name = _fn("snd_ctl_elem_info_get_item_name", c_char_p, c_void_p)
_info_iface = _fn("snd_ctl_elem_info_get_interface", c_int, c_void_p)

_val_malloc = _fn("snd_ctl_elem_value_malloc", c_int, POINTER(c_void_p))
_val_free = _fn("snd_ctl_elem_value_free", None, c_void_p)
_val_clear = _fn("snd_ctl_elem_value_clear", None, c_void_p)
_val_set_numid = _fn("snd_ctl_elem_value_set_numid", None, c_void_p, c_uint)
_elem_read = _fn("snd_ctl_elem_read", c_int, c_void_p, c_void_p)
_elem_write = _fn("snd_ctl_elem_write", c_int, c_void_p, c_void_p)
_get_int = _fn("snd_ctl_elem_value_get_integer", c_long, c_void_p, c_uint)
_set_int = _fn("snd_ctl_elem_value_set_integer", None, c_void_p, c_uint, c_long)
_get_bool = _fn("snd_ctl_elem_value_get_boolean", c_int, c_void_p, c_uint)
_set_bool = _fn("snd_ctl_elem_value_set_boolean", None, c_void_p, c_uint, c_long)
_get_enum = _fn("snd_ctl_elem_value_get_enumerated", c_uint, c_void_p, c_uint)
_set_enum = _fn("snd_ctl_elem_value_set_enumerated", None, c_void_p, c_uint, c_uint)

_IFACE_MIXER = 2


class AlsaError(OSError):
    pass


class DeviceGone(AlsaError):
    """The card disappeared (unplugged, powered off, or switched mode)."""


def _check(rc, what):
    if rc < 0:
        if -rc in (errno.ENODEV, errno.ENXIO, errno.EBADFD):
            raise DeviceGone(-rc, f"{what}: {_strerror(rc).decode()}")
        raise AlsaError(-rc, f"{what}: {_strerror(rc).decode()}")
    return rc


class Control:
    __slots__ = ("numid", "name", "type", "count", "min", "max", "items")

    def __init__(self, numid, name, type_, count, min_, max_, items):
        self.numid, self.name, self.type, self.count = numid, name, type_, count
        self.min, self.max, self.items = min_, max_, items

    def __repr__(self):
        return f"<Control {self.numid} {self.name!r} t={self.type} {self.min}..{self.max}>"


def find_card(usb_id):
    """Return (index, id) of the ALSA card with the given USB id ('vvvv:pppp'), or None."""
    for path in sorted(glob.glob("/proc/asound/card[0-9]*/usbid")):
        try:
            with open(path) as f:
                if f.read().strip().lower() != usb_id:
                    continue
            card_dir = os.path.dirname(path)
            index = int(card_dir.rsplit("card", 1)[1])
            with open(os.path.join(card_dir, "id")) as f:
                return index, f.read().strip()
        except (OSError, ValueError):
            continue
    return None


class Ctl:
    """One open control handle on `hw:<index>`."""

    def __init__(self, index):
        self.index = index
        self._h = c_void_p()
        _check(_ctl_open(byref(self._h), f"hw:{index}".encode(), 0), "open")
        self._val = c_void_p()
        _val_malloc(byref(self._val))
        self._ev = None

    def close(self):
        if self._h:
            _ctl_close(self._h)
            self._h = c_void_p()
        if self._val:
            _val_free(self._val)
            self._val = c_void_p()
        if self._ev:
            _ev_free(self._ev)
            self._ev = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ---- enumeration ----
    def controls(self):
        """All mixer controls as {name: Control}."""
        lst = c_void_p()
        info = c_void_p()
        _list_malloc(byref(lst))
        _info_malloc(byref(info))
        try:
            _check(_list(self._h, lst), "list")
            count = _list_count(lst)
            _check(_list_alloc(lst, count), "list alloc")
            _check(_list(self._h, lst), "list")
            out = {}
            for i in range(_list_used(lst)):
                numid = _list_numid(lst, i)
                _info_set_numid(info, numid)
                _check(_info(self._h, info), "info")
                if _info_iface(info) != _IFACE_MIXER:
                    continue
                t = _info_type(info)
                items = []
                if t == TYPE_ENUMERATED:
                    for k in range(_info_items(info)):
                        _info_set_item(info, k)
                        _check(_info(self._h, info), "info item")
                        items.append(_info_item_name(info).decode())
                min_ = _info_min(info) if t == TYPE_INTEGER else 0
                max_ = _info_max(info) if t == TYPE_INTEGER else (1 if t == TYPE_BOOLEAN else len(items) - 1)
                name = _info_name(info).decode()
                out[name] = Control(numid, name, t, _info_count(info), min_, max_, items)
            _list_free_space(lst)
            return out
        finally:
            _list_free(lst)
            _info_free(info)

    # ---- values ----
    def read(self, ctl):
        _val_clear(self._val)
        _val_set_numid(self._val, ctl.numid)
        _check(_elem_read(self._h, self._val), f"read {ctl.name}")
        if ctl.type == TYPE_BOOLEAN:
            return int(_get_bool(self._val, 0))
        if ctl.type == TYPE_ENUMERATED:
            return int(_get_enum(self._val, 0))
        return int(_get_int(self._val, 0))

    def write(self, ctl, value):
        """Write one value. Returns True if the driver reported a change."""
        value = int(value)
        if not ctl.min <= value <= ctl.max:
            raise ValueError(f"{ctl.name}: {value} outside {ctl.min}..{ctl.max}")
        _val_clear(self._val)
        _val_set_numid(self._val, ctl.numid)
        for i in range(ctl.count):
            if ctl.type == TYPE_BOOLEAN:
                _set_bool(self._val, i, value)
            elif ctl.type == TYPE_ENUMERATED:
                _set_enum(self._val, i, value)
            else:
                _set_int(self._val, i, value)
        return _check(_elem_write(self._h, self._val), f"write {ctl.name}") > 0

    # ---- events ----
    def subscribe(self):
        """Subscribe to change events; returns a pollable fd."""
        _check(_ctl_nonblock(self._h, 1), "nonblock")
        _check(_ctl_subscribe(self._h, 1), "subscribe")
        if _ctl_pfd_count(self._h) < 1:
            raise AlsaError(errno.EINVAL, "no poll descriptor")
        pfd = _PollFd()
        _ctl_pfds(self._h, byref(pfd), 1)
        self._ev = c_void_p()
        _ev_malloc(byref(self._ev))
        return pfd.fd

    def pending_events(self):
        """Drain queued events. Returns the set of numids whose value or info changed."""
        changed = set()
        while True:
            rc = _ctl_read(self._h, self._ev)
            if rc == 0 or rc == -errno.EAGAIN:
                return changed
            _check(rc, "read event")
            if _ev_type(self._ev) != _EVENT_ELEM:
                continue
            mask = _ev_mask(self._ev)
            if mask == _MASK_REMOVE:
                raise DeviceGone(errno.ENODEV, "control removed")
            if mask & (_MASK_VALUE | _MASK_INFO):
                changed.add(_ev_numid(self._ev))
