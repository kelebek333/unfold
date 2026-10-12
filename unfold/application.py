import os
import signal
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("XApp", "1.0")
from gi.repository import Gio, GLib, Gtk
from setproctitle import setproctitle

from unfold import _, sevenzip
from unfold.config import VERSION
from unfold.dialogs import (ask_conflicts, create_archive_task, extract_task, open_archive_task,
                            unlock)
from unfold.window import UnfoldWindow

APP_ID = "org.x.unfold"


class UnfoldApplication(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        for name, description in (("compress", "Ask how to create an archive from the files"),
                                  ("extract-here", "Extract the archives next to themselves"),
                                  ("extract", "Ask where to extract the archives")):
            self.add_main_option(name, 0, GLib.OptionFlags.NONE, GLib.OptionArg.NONE, description, None)

    def do_startup(self):
        Gtk.Application.do_startup(self)
        for name, handler in {
            "about": lambda *_args: self.show_about(),
            "quit": lambda *_args: self.quit(),
        }.items():
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", handler)
            self.add_action(action)
        for action, accels in {
            "app.quit": ["<Ctrl>q"],
            "win.open": ["<Ctrl>o"],
            "win.create": ["<Ctrl>n"],
            "win.extract": ["<Ctrl>e"],
            "win.up": ["<Alt>Up"],
            "win.close": ["<Ctrl>w"],
        }.items():
            self.set_accels_for_action(action, accels)

    def do_activate(self):
        windows = self.get_windows()
        if windows:
            windows[0].present()
        else:
            self.new_window()

    def do_command_line(self, cmdline):
        options = cmdline.get_options_dict().end().unpack()
        paths = [cmdline.create_file_for_arg(arg).get_path()
                 for arg in cmdline.get_arguments()[1:] if not arg.startswith("-")]
        if not paths:
            self.activate()
        elif "compress" in options:
            self.run_without_window(self.compress_files, paths)
        elif "extract-here" in options:
            self.run_without_window(self.extract_archives, paths)
        elif "extract" in options:
            self.run_without_window(self.extract_archives_to, paths)
        else:
            for path in paths:
                self.open_path(path)
        return 0

    def run_without_window(self, function, paths):
        """Without a window, the application would quit before this starts: it is held until it has."""
        self.hold()

        def start():
            function(paths)
            self.release()
            return False

        GLib.idle_add(start)

    def extract_archives(self, paths, destination=None):
        """Extracts each archive next to itself, or in the destination. An archive that has more than one
        thing at its top goes in a folder named after it, so that it does not make a mess."""
        self.hold()
        queue = list(paths)

        def next_archive():
            if not queue:
                self.release()
                return
            path = queue.pop(0)
            open_archive_task(None, path, lambda archive: extract_one(path, archive))

        def extract_one(path, archive):
            if archive is None:
                next_archive()
                return

            def finished(_ok=False):
                archive.close()
                next_archive()

            dest = destination or os.path.dirname(path)
            if len(archive.get_children("")) != 1:
                dest = os.path.join(dest, sevenzip.get_archive_stem(path))
            if not unlock(None, archive, None):
                finished()
                return
            overwrite = True
            existing = archive.get_conflicts(dest, None)
            if existing:
                answer = ask_conflicts(None, len(existing))
                if answer is None:
                    finished()
                    return
                overwrite = answer == "replace"
            extract_task(None, archive, dest, None, overwrite, finished)

        next_archive()

    def extract_archives_to(self, paths):
        """Asks where to extract the archives."""
        chooser = Gtk.FileChooserDialog(title=_("Extract to"), action=Gtk.FileChooserAction.SELECT_FOLDER)
        chooser.add_buttons(_("Cancel"), Gtk.ResponseType.CANCEL, _("Extract"), Gtk.ResponseType.OK)
        chooser.set_current_folder(os.path.dirname(paths[0]))
        destination = chooser.get_filename() if chooser.run() == Gtk.ResponseType.OK else None
        chooser.destroy()
        if destination:
            self.extract_archives(paths, destination)

    def compress_files(self, paths):
        """Asks what to create from these files and folders."""
        self.hold()
        create_archive_task(None, paths, lambda _out: self.release())

    def new_window(self):
        window = UnfoldWindow(self)
        window.present()
        return window

    def open_path(self, path):
        """Shows the archive in the window that has it, or in one that is empty, or in a new one."""
        windows = self.get_windows()
        for window in windows:
            if window.archive and window.archive.path == path:
                window.present()
                return
        for window in windows:
            if window.archive is None and not window.pending:
                window.present()
                window.open_archive(path)
                return
        self.new_window().open_archive(path)

    def show_about(self):
        about = Gtk.AboutDialog(transient_for=self.get_active_window(), modal=True, program_name="Unfold",
                                version=VERSION, comments=_("Create, browse and extract archives"),
                                logo_icon_name="unfold", license_type=Gtk.License.GPL_3_0,
                                website="https://github.com/xapp-project/unfold")
        about.connect("response", lambda dialog, _response: dialog.destroy())
        about.present()


def main(argv):
    setproctitle("unfold")
    GLib.set_prgname(APP_ID)
    GLib.set_application_name("Unfold")
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    return UnfoldApplication().run(argv)
