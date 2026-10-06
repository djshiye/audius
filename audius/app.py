"""Audius: a native GTK window hosting the web-rendered control surface."""
import argparse
import json
import logging
import mimetypes
import os
import sys
import time
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("WebKit", "6.0")
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk, WebKit  # noqa: E402
from gi.repository import JavaScriptCore as JSC  # noqa: E402

from . import __version__  # noqa: E402
from . import alsa, babyface, meters, pipewire  # noqa: E402
from .config import CONFIG_DIR, Config  # noqa: E402
from .mixer import Mixer  # noqa: E402

log = logging.getLogger("audius")
APP_ID = "io.github.djshiye.Audius"
UI_DIR = Path(__file__).resolve().parent / "ui"
PAGES = (("overview", "Overview", "audius-overview-symbolic"),
         ("mixer", "Mixer", "audius-mixer-symbolic"),
         ("routing", "Routing", "audius-routing-symbolic"),
         ("device", "Device", "audius-device-symbolic"))
MIME = {".js": "text/javascript", ".css": "text/css", ".html": "text/html", ".svg": "image/svg+xml",
        ".png": "image/png", ".woff2": "font/woff2", ".json": "application/json"}

# Only the window chrome is native. It is transparent, so the interface runs edge to
# edge, and its colours come from the same tokens as the page (see ui/css/tokens.css).
NATIVE_CSS = """
window.audius { background-color: #0d0f12; }
window.audius toolbarview > revealer.top-bar,
window.audius toolbarview .top-bar,
window.audius windowhandle,
window.audius headerbar {
  background: none; background-color: transparent; box-shadow: none; border: none;
}
window.audius headerbar { min-height: 52px; padding: 0 10px; }
window.audius headerbar windowcontrols button { min-width: 24px; min-height: 24px; margin: 0 2px; }
window.audius.dark headerbar windowcontrols button { color: rgba(236, 239, 244, 0.82); }
window.audius.dark headerbar windowcontrols button:hover { background-color: rgba(255, 255, 255, 0.09); }
window.audius.light headerbar windowcontrols button { color: rgba(29, 29, 31, 0.78); }
window.audius.light headerbar windowcontrols button:hover { background-color: rgba(0, 0, 0, 0.06); }
.audius-nav {
  background-color: rgba(255, 255, 255, 0.055);
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.06);
  border-radius: 11px; padding: 3px;
}
.audius-nav > button {
  all: unset; padding: 5px 16px; border-radius: 8px;
  font-weight: 600; font-size: 13px; color: rgba(236, 239, 244, 0.62);
  transition: background-color 180ms ease, color 180ms ease, box-shadow 180ms ease;
}
.audius-nav > button:hover { color: rgba(236, 239, 244, 0.92); background-color: rgba(255, 255, 255, 0.04); }
.audius-nav > button:checked {
  color: #f2f4f8; background-color: rgba(255, 255, 255, 0.13);
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.35), inset 0 1px 0 rgba(255, 255, 255, 0.07);
}
.audius-nav > button:focus-visible { box-shadow: 0 0 0 2px @accent_color; }
.audius-nav > button image { margin-right: 0; }
.audius-nav.compact > button { padding: 5px 11px; }

window.audius.light { background-color: #f2f2f5; }
window.audius.light .audius-nav { background-color: rgba(0, 0, 0, 0.05); box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.04); }
window.audius.light .audius-nav > button { color: rgba(29, 29, 31, 0.62); }
window.audius.light .audius-nav > button:hover { color: rgba(29, 29, 31, 0.92); background-color: rgba(0, 0, 0, 0.035); }
window.audius.light .audius-nav > button:checked {
  color: #1d1d1f; background-color: #ffffff;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.14), 0 0 0 0.5px rgba(0, 0, 0, 0.06);
}
"""


def rgba_hex(c):
    return "#%02x%02x%02x" % (round(c.red * 255), round(c.green * 255), round(c.blue * 255))


class Window(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Audius")
        self.app = app
        self.add_css_class("audius")
        w = app.cfg["window"]
        size = app.args.size
        if size:
            self.set_default_size(*size)
        else:
            self.set_default_size(int(w.get("width", 1240)), int(w.get("height", 860)))
            if w.get("maximized"):
                self.maximize()
        self.set_size_request(560, 560)   # below this the title bar can't fit the page switcher and window controls

        self.view = Adw.ToolbarView(extend_content_to_top_edge=True, top_bar_style=Adw.ToolbarStyle.FLAT)
        self.header = Adw.HeaderBar(show_title=True)
        self.nav = Gtk.Box(css_classes=["audius-nav"], valign=Gtk.Align.CENTER)
        self.nav_buttons = {}
        group = None
        for key, label, _icon in PAGES:
            b = Gtk.ToggleButton(label=label, tooltip_text=f"{label} (Ctrl+{len(self.nav_buttons) + 1})")
            b.set_group(group)
            group = group or b
            b.connect("toggled", self._on_nav, key)
            self.nav.append(b)
            self.nav_buttons[key] = b
        self.header.set_title_widget(self.nav)
        self.view.add_top_bar(self.header)

        self.web = app.make_webview()
        self.view.set_content(self.web)
        self.set_content(self.view)

        bp = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 640sp"))
        bp.add_setter(self.nav, "css-classes", GObject.Value(GObject.TYPE_STRV, ["audius-nav", "compact"]))
        self.add_breakpoint(bp)
        self.connect("close-request", self._on_close)
        self.connect("notify::is-active", self._on_active)
        sm = Adw.StyleManager.get_default()
        sm.connect("notify::dark", lambda *_: self._sync_theme())
        self._sync_theme()
        self._inactive_since = None
        self._suppress_nav = False

    def _sync_theme(self):
        # GTK's colour-scheme media query doesn't track libadwaita, so drive the chrome with a class.
        dark = Adw.StyleManager.get_default().get_dark()
        self.remove_css_class("light" if dark else "dark")
        self.add_css_class("dark" if dark else "light")

    def _on_nav(self, button, key):
        if button.get_active() and not self._suppress_nav:
            self.app.set_page(key, from_native=True)

    def select_page(self, key):
        b = self.nav_buttons.get(key)
        if b and not b.get_active():
            self._suppress_nav = True
            b.set_active(True)
            self._suppress_nav = False

    def _on_active(self, *_):
        if self.is_active():
            if self._inactive_since is not None and time.monotonic() - self._inactive_since > 5:
                # Away long enough to have reached for the knob.
                if self.app.mixer:
                    self.app.mixer.forget_volumes()
            self._inactive_since = None
        else:
            self._inactive_since = time.monotonic()

    def _on_close(self, *_):
        w = self.app.cfg["window"]
        w["maximized"] = self.is_maximized()
        if not self.is_maximized() and not self.app.args.size:
            w["width"], w["height"] = self.get_width(), self.get_height()
        self.app.cfg.save()
        return False


class App(Adw.Application):
    def __init__(self, args):
        # Screenshot runs get their own id each time, so the shell doesn't restore an old geometry.
        super().__init__(application_id=APP_ID if not args.screenshot else f"{APP_ID}.Shot{os.getpid()}",
                         flags=Gio.ApplicationFlags.NON_UNIQUE if args.screenshot else Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.args = args
        # The demo never touches your real settings.
        self.cfg = Config(CONFIG_DIR / ("demo.json" if args.demo else "config.json"),
                          autosave=not args.screenshot)
        self.dev = None
        self.mixer = None
        self.win = None
        self.web = None
        self.page = args.page or self.cfg["ui"].get("page", "overview")
        self.ready = False
        self._levels = {}
        self._levels_dirty = False
        self._meter_inflight = False
        self._meter_source = None
        self._poll_id = None
        self._rate = None
        self._queue = []
        if args.demo:
            self.meters = meters.DemoMeters(self._on_levels)
        else:
            self.meters = meters.Meters(self._on_levels)

    # ------------------------------------------------------------------ lifecycle
    def do_startup(self):
        Adw.Application.do_startup(self)
        css = Gtk.CssProvider()
        css.load_from_string(NATIVE_CSS)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css, 900)
        sm = Adw.StyleManager.get_default()
        if self.args.theme == "light":
            sm.set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)
        elif self.args.theme == "dark":
            sm.set_color_scheme(Adw.ColorScheme.FORCE_DARK)
        sm.connect("notify::dark", lambda *_: self.push({"platform": self.platform()}))
        sm.connect("notify::accent-color", lambda *_: self.push({"platform": self.platform()}))
        for name, accels, cb in (("quit", ["<Control>q"], lambda *_: self.quit()),):
            a = Gio.SimpleAction.new(name, None)
            a.connect("activate", cb)
            self.add_action(a)
            self.set_accels_for_action(f"app.{name}", accels)
        close = Gio.SimpleAction.new("close", None)
        close.connect("activate", lambda *_: self.win and self.win.close())
        self.add_action(close)
        self.set_accels_for_action("app.close", ["<Control>w"])

    def do_activate(self):
        if self.win:
            self.win.present()
            return
        self.connect_device()
        self.win = Window(self)
        self.win.select_page(self.page)
        self.win.connect("notify::visible", lambda *_: self.update_meters())
        self.win.present()
        surface = self.win.get_surface()
        if surface is not None:
            surface.connect("notify::state", lambda *_: self.update_meters())
        GLib.timeout_add_seconds(2, self._tick)
        if self.args.screenshot:
            GLib.timeout_add(15000, lambda: (log.error("screenshot timed out"), self.quit()))

    def do_shutdown(self):
        self.meters.stop()
        self.cfg["ui"]["page"] = self.page
        if not self.args.screenshot:
            self.cfg.flush()
            self.cfg.save()
        if self.dev:
            self.dev.close()
        Adw.Application.do_shutdown(self)

    # ------------------------------------------------------------------ device
    def connect_device(self):
        if self.args.offline:      # --offline: show the "connect your Babyface" screen (for screenshots)
            self._start_polling()
            return False
        try:
            self.dev = babyface.DemoDevice() if self.args.demo else babyface.Babyface()
        except alsa.AlsaError as e:
            log.info("no device: %s", e)
            self.dev = None
            self.mixer = None
            self._start_polling()
            return False
        if self.args.demo:
            babyface.demo_volumes(self.dev, self.cfg)
        self.mixer = Mixer(self.dev, self.cfg)
        self.mixer.listener = self.push
        self.mixer.toast = lambda text: self.push({"toast": {"text": text}})
        self.dev.on_gone = self._on_gone
        self.dev.watch()
        self._rate = self.dev.stream_rate()
        if self._poll_id:
            GLib.source_remove(self._poll_id)
            self._poll_id = None
        return True

    def _on_gone(self):
        log.info("Babyface disconnected")
        self.meters.stop()
        try:
            self.dev.close()
        except Exception:  # noqa: BLE001
            pass
        self.dev = None
        self.mixer = None
        self.push({"device": {"connected": False}})
        self._start_polling()

    def _start_polling(self):
        if self._poll_id is None:
            self._poll_id = GLib.timeout_add_seconds(2, self._poll_device)

    def _poll_device(self):
        if self.args.offline or alsa.find_card(babyface.USB_ID) is None:
            return True
        self._poll_id = None
        # Give the driver and alsa-restore a moment to settle.
        GLib.timeout_add(1500, self._reconnect)
        return False

    def _reconnect(self):
        if self.connect_device():
            self.push(self.full_state())
            self.update_meters()
        return False

    def _tick(self):
        if self.mixer:
            self.mixer.expire()
            rate = self.dev.stream_rate()
            if rate != self._rate:
                self._rate = rate
                self.push({"device": self.mixer.device_view()})
        return True

    # ------------------------------------------------------------------ meters
    def meters_wanted(self):
        if not (self.mixer and self.win and self.win.get_visible()):
            return False
        if not self.cfg["prefs"].get("meters", True):
            return False
        surface = self.win.get_surface()
        if surface is not None and isinstance(surface, Gdk.Toplevel):
            if surface.get_state() & Gdk.ToplevelState.MINIMIZED:
                return False
        return True

    def update_meters(self):
        want = self.meters_wanted()
        if want and not self.meters.running:
            nodes = {} if self.args.demo else pipewire.find_nodes(self.dev.card_index)
            self.meters.start(nodes)
            self.push({"meters": {"channels": self.meters.channels, "enabled": True}})
            if self._meter_source is None:
                self._meter_source = GLib.timeout_add(33, self._flush_levels)
        elif not want and self.meters.running:
            self.meters.stop()
            self.push({"meters": {"channels": [], "enabled": False}})

    def _on_levels(self, levels):
        self._levels.update(levels)
        self._levels_dirty = True

    def _flush_levels(self):
        if not self.meters.running:
            self._meter_source = None
            return False
        if self._levels_dirty and self.ready and not self._meter_inflight:
            self._levels_dirty = False
            payload = {k: [round(p, 1), round(r, 1)] for k, (p, r) in self._levels.items()}
            self._meter_inflight = True
            self.web.evaluate_javascript(f"window.audius&&audius.levels({json.dumps(payload)})", -1,
                                         None, None, None, self._meter_done, None)
        return True

    def _meter_done(self, web, result, _data):
        self._meter_inflight = False
        try:
            web.evaluate_javascript_finish(result)
        except GLib.Error:
            pass

    # ------------------------------------------------------------------ web view
    def make_webview(self):
        ctx = WebKit.WebContext.get_default()
        ctx.register_uri_scheme("audius", self._serve)
        sec = ctx.get_security_manager()
        sec.register_uri_scheme_as_secure("audius")
        sec.register_uri_scheme_as_cors_enabled("audius")
        ucm = WebKit.UserContentManager()
        ucm.register_script_message_handler_with_reply("audius", None)
        ucm.connect("script-message-with-reply-received::audius", self._on_script_message)
        web = WebKit.WebView(user_content_manager=ucm, hexpand=True, vexpand=True)
        s = web.get_settings()
        s.set_hardware_acceleration_policy(WebKit.HardwareAccelerationPolicy.ALWAYS)
        s.set_enable_developer_extras(self.args.debug)
        s.set_enable_write_console_messages_to_stdout(self.args.debug)
        s.set_enable_back_forward_navigation_gestures(False)
        s.set_javascript_can_access_clipboard(False)
        s.set_enable_smooth_scrolling(True)
        web.set_background_color(Gdk.RGBA(red=0, green=0, blue=0, alpha=0))
        if not self.args.debug:
            web.connect("context-menu", lambda *_: True)
        web.connect("decide-policy", self._decide_policy)
        try:
            iface = Gio.Settings.new("org.gnome.desktop.interface")
            web.set_zoom_level(max(0.75, min(2.0, iface.get_double("text-scaling-factor"))))
            iface.connect("changed::text-scaling-factor",
                          lambda st, k: web.set_zoom_level(max(0.75, min(2.0, st.get_double(k)))))
        except GLib.Error:
            pass
        web.load_uri("audius://app/index.html")
        self.web = web
        return web

    def _serve(self, req):
        rel = req.get_path().lstrip("/") or "index.html"
        path = (UI_DIR / rel).resolve()
        if UI_DIR not in path.parents or not path.is_file():
            req.finish_error(GLib.Error.new_literal(Gio.io_error_quark(), "not found", Gio.IOErrorEnum.NOT_FOUND))
            return
        data = path.read_bytes()
        mime = MIME.get(path.suffix) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        req.finish(Gio.MemoryInputStream.new_from_bytes(GLib.Bytes.new(data)), len(data), mime)

    def _decide_policy(self, web, decision, kind):
        if kind == WebKit.PolicyDecisionType.NAVIGATION_ACTION:
            uri = decision.get_navigation_action().get_request().get_uri()
            if not uri.startswith("audius://"):
                decision.ignore()
                if uri.startswith(("https://", "http://")):
                    Gtk.UriLauncher.new(uri).launch(self.win, None, None, None)
                return True
        elif kind == WebKit.PolicyDecisionType.NEW_WINDOW_ACTION:
            decision.ignore()
            return True
        return False

    def push(self, patch):
        if not self.web:
            return
        if not self.ready:
            self._queue.append(patch)
            return
        self.web.evaluate_javascript(f"window.audius&&audius.receive({json.dumps(patch)})", -1,
                                     None, None, None, None, None)

    def _on_script_message(self, ucm, value, reply):
        try:
            msg = json.loads(value.to_json(0))
            result = self.dispatch(msg)
        except Exception as e:  # noqa: BLE001 - report to the page instead of crashing
            log.exception("message failed")
            result = {"error": str(e)}
        reply.return_value(JSC.Value.new_from_json(value.get_context(), json.dumps(result)))
        return True

    # ------------------------------------------------------------------ protocol
    def platform(self):
        sm = Adw.StyleManager.get_default()
        try:
            accent = rgba_hex(sm.get_accent_color_rgba())
        except (AttributeError, TypeError):
            accent = "#3584e4"
        anim = Gtk.Settings.get_default().get_property("gtk-enable-animations")
        layout = Gtk.Settings.get_default().get_property("gtk-decoration-layout") or ""
        th = self.win.header.get_height() if self.win else 0
        return {"dark": sm.get_dark(), "accent": accent, "reduce_motion": not anim, "version": __version__,
                "titlebar": th or 52, "decoration_layout": layout, "demo": self.args.demo}

    def full_state(self):
        state = {"platform": self.platform(), "page": self.page, "ui": dict(self.cfg["ui"]),
                 "meters": {"channels": self.meters.channels if self.meters.running else [],
                            "enabled": self.cfg["prefs"].get("meters", True)}}
        if self.mixer:
            state.update(self.mixer.view())
        else:
            state["device"] = {"connected": False}
        return state

    def set_page(self, page, from_native=False):
        if page not in {p[0] for p in PAGES}:
            return
        self.page = page
        self.cfg["ui"]["page"] = page
        if from_native:
            self.push({"page": page})
        elif self.win:
            self.win.select_page(page)

    def dispatch(self, msg):
        cmd = msg.get("cmd")
        if cmd == "hello":
            self.ready = True
            GLib.idle_add(self._after_ready)
            if self.args.screenshot:   # fallback if the page's own signal is delayed
                GLib.timeout_add(6000, lambda: self.dispatch({"cmd": "ready_to_shoot"}) and False)
            return self.full_state()
        if cmd == "page":
            self.set_page(msg["page"])
            return {"ok": True}
        if cmd == "ui":                      # small bits of interface state worth remembering
            if msg.get("key") in ("more_inputs", "mixer_output"):
                self.cfg["ui"][msg["key"]] = msg.get("value")
                self.cfg.changed()
            return {"ok": True}
        if cmd == "ready_to_shoot":
            if self.args.screenshot and not getattr(self, "_shot_scheduled", False):
                self._shot_scheduled = True
                if self.args.eval:   # scripted interaction for visual checks (--demo only)
                    self.web.evaluate_javascript(self.args.eval, -1, None, None, None, None, None)
                GLib.timeout_add(int(self.args.wait), self._shoot)
            return {"ok": True}
        if cmd == "open_url":
            uri = msg.get("url", "")
            if uri.startswith("https://"):
                Gtk.UriLauncher.new(uri).launch(self.win, None, None, None)
            return {"ok": True}
        m = self.mixer
        if m is None:
            return {"error": "Babyface not connected"}
        g = msg.get("gesture")
        if cmd == "send":
            m.set_send(msg["strip"], msg["out"], db=msg.get("db"), pan=msg.get("pan"), gesture=g,
                       keep_db=bool(msg.get("keep_db")))
        elif cmd == "send_mute":
            m.set_send_mute(msg["strip"], msg["out"], bool(msg["muted"]), gesture=g)
        elif cmd == "crosspoint":
            m.set_crosspoint(msg["ctl"], msg.get("db"), gesture=g)
        elif cmd == "volume":
            m.set_volume(msg["out"], msg.get("db"), gesture=g)
        elif cmd == "output_on":
            m.set_output_on(msg["out"], bool(msg["on"]), gesture=g)
        elif cmd == "listen":
            m.set_listen(msg["mode"])
        elif cmd == "gain":
            m.set_gain(msg["ch"], float(msg["db"]), gesture=g)
        elif cmd == "p48":
            m.set_switch(babyface.p48_ctl(msg["ch"]), bool(msg["on"]))
        elif cmd == "pad":
            m.set_switch(babyface.pad_ctl(msg["ch"]), bool(msg["on"]), gesture=g, label="PAD")
        elif cmd == "sens":
            m.set_enum(babyface.sens_ctl(msg["ch"]), 1 if msg["value"] == "+4dBu" else 0, gesture=g)
        elif cmd == "clock":
            m.set_enum(babyface.CLOCK, 1 if msg["mode"] == "internal" else 0)
        elif cmd == "optical_out":
            m.set_switch(babyface.OPTICAL_SPDIF, msg["format"] == "spdif")
        elif cmd == "spdif_pro":
            m.set_switch(babyface.SPDIF_PRO, bool(msg["on"]))
        elif cmd == "spdif_emphasis":
            m.set_switch(babyface.SPDIF_EMPHASIS, bool(msg["on"]))
        elif cmd == "link":
            m.set_link(msg["pair"], bool(msg["linked"]))
        elif cmd == "rename":
            m.rename(msg["id"], msg.get("name", ""))
        elif cmd == "overview_sources":
            m.set_overview_sources(msg["out"], msg["ids"])
        elif cmd == "limit":
            m.set_limit(msg["out"], float(msg["db"]))
        elif cmd == "pref":
            m.set_pref(msg["key"], msg["value"])
            if msg["key"] == "meters":
                self.update_meters()
        elif cmd == "end_gesture":
            m.end_gesture()
        elif cmd == "undo":
            m.undo()
        elif cmd == "redo":
            m.redo()
        elif cmd == "scene_save":
            return {"id": m.save_scene(msg.get("name", ""))}
        elif cmd == "scene_update":
            m.update_scene(msg["id"])
        elif cmd == "scene_recall":
            m.recall_scene(msg["id"])
        elif cmd == "scene_rename":
            m.rename_scene(msg["id"], msg.get("name", ""))
        elif cmd == "scene_delete":
            m.delete_scene(msg["id"])
        elif cmd == "resend":
            n = m.resend_all(include_volumes=bool(msg.get("volumes")))
            return {"count": n}
        else:
            return {"error": f"unknown command {cmd}"}
        return {"ok": True}

    def _after_ready(self):
        for patch in self._queue:
            self.push(patch)
        self._queue.clear()
        self.update_meters()
        return False

    def _shoot(self):
        # Capture on the next frame: a static page may have nothing cached to snapshot yet.
        self.win.queue_draw()
        self.win.add_tick_callback(lambda *_: self._capture() and False)
        return False

    def _web_shot_done(self, web, result, _data):
        try:
            tex = web.get_snapshot_finish(result)
            tex.save_to_png(self.args.screenshot)
            print(f"saved {self.args.screenshot} (page only)")
        except GLib.Error as e:
            log.error("snapshot failed: %s", e)
        self.quit()

    def _capture(self):
        win = self.win
        w, h = win.get_width(), win.get_height()
        paintable = Gtk.WidgetPaintable.new(win)
        snap = Gtk.Snapshot()
        paintable.snapshot(snap, w, h)
        node = snap.to_node()
        if node is None:
            # A hidden, static window may never get a frame; WebKit can still render the page.
            self.web.get_snapshot(WebKit.SnapshotRegion.VISIBLE, WebKit.SnapshotOptions.TRANSPARENT_BACKGROUND,
                                  None, self._web_shot_done, None)
            return False
        tex = win.get_renderer().render_texture(node, None)
        tex.save_to_png(self.args.screenshot)
        print(f"saved {self.args.screenshot} ({w}x{h})")
        self.quit()
        return False


def _size(text):
    w, h = text.lower().split("x")
    return int(w), int(h)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="audius", description="Control panel for the RME Babyface Pro FS")
    parser.add_argument("--demo", action="store_true", help="run without hardware, with simulated signals")
    parser.add_argument("--debug", action="store_true", help="enable the web inspector and verbose logs")
    parser.add_argument("--page", choices=[p[0] for p in PAGES])
    parser.add_argument("--theme", choices=["light", "dark"], help="force an appearance")
    parser.add_argument("--screenshot", metavar="PNG", help="render the window to a PNG and exit")
    parser.add_argument("--size", type=_size, metavar="WxH")
    parser.add_argument("--wait", type=int, default=900, metavar="MS", help="delay before a screenshot")
    parser.add_argument("--eval", metavar="JS", help=argparse.SUPPRESS)
    parser.add_argument("--offline", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--version", action="version", version=f"Audius {__version__}")
    args = parser.parse_args(argv)
    if args.eval and not args.demo:
        parser.error("--eval only runs with --demo")
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO, format="audius: %(message)s")
    app = App(args)
    return app.run([sys.argv[0]])
