import os
import threading
from gettext import ngettext

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib, Gtk, Pango

from unfold import _, sevenzip


def message(parent, text, secondary=None):
    dialog = Gtk.MessageDialog(transient_for=parent, modal=True, message_type=Gtk.MessageType.ERROR,
                               buttons=Gtk.ButtonsType.CLOSE, text=text, secondary_text=secondary)
    dialog.run()
    dialog.destroy()


def confirm(parent, text, secondary, label):
    dialog = Gtk.MessageDialog(transient_for=parent, modal=True, message_type=Gtk.MessageType.QUESTION,
                               text=text, secondary_text=secondary)
    dialog.add_buttons(_("Cancel"), Gtk.ResponseType.CANCEL, label, Gtk.ResponseType.OK)
    dialog.set_default_response(Gtk.ResponseType.OK)
    response = dialog.run()
    dialog.destroy()
    return response == Gtk.ResponseType.OK


def ask_conflicts(parent, count):
    """Returns "replace", "skip" or None."""
    dialog = Gtk.MessageDialog(transient_for=parent, modal=True, message_type=Gtk.MessageType.QUESTION,
                               text=ngettext("%d file already exists", "%d files already exist", count) % count,
                               secondary_text=_("Do you want to replace it with the one from the archive?")
                               if count == 1 else
                               _("Do you want to replace them with the ones from the archive?"))
    dialog.add_buttons(_("Cancel"), Gtk.ResponseType.CANCEL, _("Skip"), Gtk.ResponseType.NO,
                       _("Replace"), Gtk.ResponseType.YES)
    dialog.set_default_response(Gtk.ResponseType.YES)
    response = dialog.run()
    dialog.destroy()
    return {Gtk.ResponseType.YES: "replace", Gtk.ResponseType.NO: "skip"}.get(response)


def ask_password(parent, wrong=False):
    dialog = Gtk.MessageDialog(transient_for=parent, modal=True, message_type=Gtk.MessageType.QUESTION,
                               text=_("Password Required"),
                               secondary_text=_("The password was not accepted. Try again.") if wrong
                               else _("This archive is protected by a password."))
    dialog.add_buttons(_("Cancel"), Gtk.ResponseType.CANCEL, _("OK"), Gtk.ResponseType.OK)
    dialog.set_default_response(Gtk.ResponseType.OK)
    entry = Gtk.Entry(visibility=False, activates_default=True, input_purpose=Gtk.InputPurpose.PASSWORD)
    entry.show()
    dialog.get_message_area().add(entry)
    response = dialog.run()
    password = entry.get_text()
    dialog.destroy()
    return password if response == Gtk.ResponseType.OK else None


def run_task(parent, title, work, done):
    """Calls work(cancelled) in a thread, with a window to cancel it, then done(result, error) here."""
    cancel = threading.Event()
    dialog = Gtk.Dialog(title=title, transient_for=parent, modal=True, resizable=False)
    dialog.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
    dialog.connect("response", lambda *_args: cancel.set())
    box = dialog.get_content_area()
    box.set_spacing(12)
    box.set_border_width(12)
    bar = Gtk.ProgressBar(text=title, show_text=True)
    bar.set_size_request(320, -1)
    box.add(bar)
    box.show_all()
    timers = [GLib.timeout_add(300, lambda: dialog.show() and False),
              GLib.timeout_add(100, lambda: bar.pulse() or True)]

    def run():
        result = error = None
        try:
            result = work(cancel.is_set)
        except Exception as e:
            error = e
        GLib.idle_add(finish, result, error)

    def finish(result, error):
        for timer in timers:
            GLib.source_remove(timer)
        dialog.destroy()
        done(result, error)
        return False

    threading.Thread(target=run, daemon=True).start()


def get_icon(name, is_dir):
    """Returns the icon of a file or a folder."""
    if is_dir:
        return Gio.ThemedIcon.new("folder")
    return Gio.content_type_get_icon(Gio.content_type_guess(name, None)[0])


class CreateDialog(Gtk.Dialog):
    def __init__(self, parent, paths):
        super().__init__(title=_("Create Archive"), transient_for=parent, modal=True)
        self.set_default_size(460, 480)
        self.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
        self.create_button = self.add_button(_("Create"), Gtk.ResponseType.OK)
        self.create_button.get_style_context().add_class("suggested-action")
        self.set_default_response(Gtk.ResponseType.OK)
        self.name_edited = False

        box = self.get_content_area()
        box.set_spacing(8)
        box.set_border_width(12)

        self.store = Gtk.ListStore(Gio.Icon, str, str)
        view = Gtk.TreeView(model=self.store, headers_visible=False, tooltip_column=2)
        view.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)
        self.selection = view.get_selection()
        column = Gtk.TreeViewColumn()
        icon = Gtk.CellRendererPixbuf()
        column.pack_start(icon, False)
        column.add_attribute(icon, "gicon", 0)
        text = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.MIDDLE)
        column.pack_start(text, True)
        column.add_attribute(text, "text", 1)
        view.append_column(column)
        scrolled = Gtk.ScrolledWindow(shadow_type=Gtk.ShadowType.IN, vexpand=True)
        scrolled.add(view)
        box.pack_start(scrolled, True, True, 0)

        buttons = Gtk.Box(spacing=6)
        for label, handler in ((_("Add Files…"), self.on_add_files), (_("Add Folder…"), self.on_add_folder),
                               (_("Remove"), self.on_remove)):
            button = Gtk.Button(label=label)
            button.connect("clicked", handler)
            buttons.pack_start(button, False, False, 0)
        box.pack_start(buttons, False, False, 0)

        grid = Gtk.Grid(row_spacing=6, column_spacing=12)
        self.name_entry = Gtk.Entry(hexpand=True, activates_default=True)
        self.name_entry.connect("changed", self.on_name_changed)
        self.format_combo = Gtk.ComboBoxText()
        for suffix, _kind, _can_protect in sevenzip.FORMATS:
            self.format_combo.append_text(suffix)
        self.format_combo.set_active(0)
        self.format_combo.connect("changed", self.on_format_changed)
        self.folder_button = Gtk.FileChooserButton(title=_("Select a folder"),
                                                   action=Gtk.FileChooserAction.SELECT_FOLDER)
        self.password_entry = Gtk.Entry(visibility=False, activates_default=True,
                                        input_purpose=Gtk.InputPurpose.PASSWORD,
                                        placeholder_text=_("Optional"))
        show = Gtk.CheckButton(label=_("Show"))
        show.connect("toggled", lambda button: self.password_entry.set_visibility(button.get_active()))
        password = Gtk.Box(spacing=6)
        password.pack_start(self.password_entry, True, True, 0)
        password.pack_start(show, False, False, 0)
        self.password_row = password
        self.password_label = Gtk.Label(label=_("Password"), xalign=1)
        for row, (label, widget) in enumerate(((_("Name"), self.name_entry), (_("Format"), self.format_combo),
                                              (_("Location"), self.folder_button), (None, password))):
            if label:
                grid.attach(Gtk.Label(label=label, xalign=1), 0, row, 1, 1)
            else:
                grid.attach(self.password_label, 0, row, 1, 1)
            grid.attach(widget, 1, row, 1, 1)
        box.pack_start(grid, False, False, 0)

        self.folder_button.set_current_folder(os.path.dirname(paths[0]) if paths else GLib.get_home_dir())
        self.add_paths(paths)
        self.on_format_changed()
        box.show_all()

    def add_paths(self, paths):
        known = {row[2] for row in self.store}
        for path in paths:
            path = path.rstrip("/")
            if path not in known:
                known.add(path)
                name = os.path.basename(path)
                self.store.append([get_icon(name, os.path.isdir(path)), name, path])
        if len(self.store) and not self.name_edited:
            first = self.store[0]
            name = first[1] if os.path.isdir(first[2]) else os.path.splitext(first[1])[0]
            self.name_entry.set_text(name or first[1])
            self.name_edited = False
        self.update_state()

    def get_chosen_paths(self, title, action):
        """Returns the paths that the user picks."""
        chooser = Gtk.FileChooserDialog(title=title, transient_for=self, action=action, select_multiple=True)
        chooser.add_buttons(_("Cancel"), Gtk.ResponseType.CANCEL, _("Add"), Gtk.ResponseType.OK)
        paths = chooser.get_filenames() if chooser.run() == Gtk.ResponseType.OK else []
        chooser.destroy()
        return paths

    def on_add_files(self, _button):
        self.add_paths(self.get_chosen_paths(_("Add Files"), Gtk.FileChooserAction.OPEN))

    def on_add_folder(self, _button):
        self.add_paths(self.get_chosen_paths(_("Add Folder"), Gtk.FileChooserAction.SELECT_FOLDER))

    def on_remove(self, _button):
        model, paths = self.selection.get_selected_rows()
        for reference in [Gtk.TreeRowReference.new(model, path) for path in paths]:
            self.store.remove(self.store.get_iter(reference.get_path()))
        self.update_state()

    def on_name_changed(self, _entry):
        self.name_edited = True
        self.update_state()

    def on_format_changed(self, *_args):
        can_protect = sevenzip.FORMATS[self.format_combo.get_active()][2]
        self.password_label.set_sensitive(can_protect)
        self.password_row.set_sensitive(can_protect)

    def update_state(self):
        name = self.name_entry.get_text().strip()
        self.create_button.set_sensitive(len(self.store) > 0 and bool(name) and "/" not in name)

    def get_result(self):
        """Returns the files and folders, the path of the archive, its format and its password if any."""
        fmt = sevenzip.FORMATS[self.format_combo.get_active()]
        out = os.path.join(self.folder_button.get_filename(), self.name_entry.get_text().strip() + fmt[0])
        password = self.password_entry.get_text() if fmt[2] else ""
        return [row[2] for row in self.store], out, fmt, password or None


# The steps that a window or a file manager action both go through. parent is None without a window.

def unlock(parent, archive, selection):
    """Asks for the password if the files that are selected (None for all) need it."""
    if not archive.needs_password(selection):
        return True
    password = ask_password(parent)
    if password is None:
        return False
    archive.password = password
    return True


def open_archive_task(parent, path, finished, password=None, alive=lambda: True):
    """Opens an archive, asking for its password if it needs one. finished(archive) is called in any case,
    with None when the archive could not be opened."""
    def done(archive, error):
        if not alive() or isinstance(error, sevenzip.Cancelled):
            if archive:
                archive.close()
            finished(None)
        elif isinstance(error, sevenzip.PasswordError):
            new = ask_password(parent, wrong=password is not None)
            if new is None:
                finished(None)
            else:
                open_archive_task(parent, path, finished, new, alive)
        elif error:
            message(parent, _("Could not open the archive"), str(error))
            finished(None)
        else:
            finished(archive)

    run_task(parent, _("Opening"), lambda cancelled: sevenzip.Archive(path, password, cancelled), done)


def extract_task(parent, archive, dest, selection, overwrite, finished, alive=lambda: True):
    """Extracts. finished(True) is called when it worked, finished(False) otherwise."""
    def done(_result, error):
        if not alive() or isinstance(error, sevenzip.Cancelled):
            finished(False)
        elif isinstance(error, sevenzip.PasswordError):
            archive.password = None
            message(parent, _("Wrong password"), _("The password was not accepted."))
            finished(False)
        elif error:
            message(parent, _("Could not extract"), str(error))
            finished(False)
        else:
            finished(True)

    run_task(parent, _("Extracting"), lambda cancelled: archive.extract(dest, selection, overwrite, cancelled), done)


def create_archive_task(parent, paths, finished, alive=lambda: True):
    """Asks what to create, then creates it. finished(path) is called with the new archive, or None."""
    dialog = CreateDialog(parent, paths)
    accepted = dialog.run() == Gtk.ResponseType.OK
    sources, out, fmt, password = dialog.get_result()
    dialog.destroy()
    if not accepted:
        finished(None)
        return
    if os.path.lexists(out) and not confirm(parent, _("“%s” already exists") % os.path.basename(out),
                                            _("Do you want to replace it?"), _("Replace")):
        finished(None)
        return

    def done(_result, error):
        if not alive() or isinstance(error, sevenzip.Cancelled):
            finished(None)
        elif error:
            message(parent, _("Could not create the archive"), str(error))
            finished(None)
        else:
            finished(out)

    run_task(parent, _("Creating"), lambda cancelled: sevenzip.create(out, fmt, sources, password, cancelled), done)
