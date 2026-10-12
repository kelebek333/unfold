import os
import shutil
import tempfile
from gettext import ngettext

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, GObject, Gtk, Pango

from unfold import _, sevenzip
from unfold.config import DATA_DIR
from unfold.dialogs import (ask_conflicts, create_archive_task, extract_task, get_icon, message,
                            open_archive_task, unlock)

# The types that the file chooser offers as archives
ARCHIVE_TYPES = [
    "application/gzip",
    "application/vnd.comicbook+zip",
    "application/vnd.ms-cab-compressed",
    "application/vnd.rar",
    "application/x-7z-compressed",
    "application/x-archive",
    "application/x-bzip2",
    "application/x-bzip-compressed-tar",
    "application/x-compressed-tar",
    "application/x-cpio",
    "application/x-iso9660-image",
    "application/x-lzma",
    "application/x-lzma-compressed-tar",
    "application/x-rar",
    "application/x-tar",
    "application/x-xz",
    "application/x-xz-compressed-tar",
    "application/x-zstd-compressed-tar",
    "application/zip",
    "application/zstd",
    "application/x-zip",
    "application/x-zip-compressed",
    "application/x-rar-compressed",
    "application/x-gzip",
    "application/bzip2",
    "application/x-bzip",
    "application/x-gtar",
    "application/x-tarz",
    "application/x-compress",
    "application/java-archive",
    "application/x-java-archive",
    "application/x-war",
    "application/x-ear",
    "application/vnd.android.package-archive",
    "application/x-cabinet",
    "application/x-arj",
    "application/x-lha",
    "application/x-lhz",
    "application/x-ar",
    "application/x-cd-image",
    "application/x-ms-wim",
    "application/x-xar",
]

NAME, PATH, IS_DIR, SIZE, MODIFIED, TYPE = 1, 2, 3, 4, 5, 6


# File types (this lets us sort files by generic type)
TYPES = {
    "application-x-executable": _("Program"),
    "audio-x-generic": _("Audio"),
    "font-x-generic": _("Font"),
    "image-x-generic": _("Image"),
    "package-x-generic": _("Archive"),
    "text-html": _("Markup"),
    "text-x-generic": _("Text"),
    "text-x-generic-template": _("Text"),
    "text-x-script": _("Program"),
    "video-x-generic": _("Video"),
    "x-office-address-book": _("Contacts"),
    "x-office-calendar": _("Calendar"),
    "x-office-document": _("Document"),
    "x-office-presentation": _("Presentation"),
    "x-office-spreadsheet": _("Spreadsheet"),
}


def get_type(entry):
    """Returns what the entry is in a word: Folder, Image, Text..."""
    if entry.is_dir:
        return _("Folder")
    content_type = Gio.content_type_guess(entry.name, None)[0]
    if Gio.content_type_is_unknown(content_type):
        return _("Binary")
    return TYPES.get(Gio.content_type_get_generic_icon_name(content_type)) or \
        Gio.content_type_get_description(content_type)


def header_button(icon, label, action):
    box = Gtk.Box(spacing=6)
    box.add(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.BUTTON))
    box.add(Gtk.Label(label=label))
    button = Gtk.Button(action_name=action)
    button.add(box)
    return button


class UnfoldWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Unfold")
        self.set_default_size(800, 560)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_icon_name("unfold")
        self.archive = None
        self.folder = ""
        self.pending = False   # an archive is being opened
        self.closing = False
        self.temp_dirs = []

        self.header = Gtk.HeaderBar(title="Unfold", show_close_button=True)
        menu = Gtk.Menu()
        menu.append(Gtk.MenuItem(label=_("About"), action_name="app.about"))
        menu.append(Gtk.SeparatorMenuItem())
        menu.append(Gtk.MenuItem(label=_("Quit"), action_name="app.quit"))
        menu.show_all()
        menu_button = Gtk.MenuButton(popup=menu)
        menu_button.set_image(Gtk.Image.new_from_icon_name("xsi-open-menu-symbolic", Gtk.IconSize.BUTTON))
        self.header.pack_end(menu_button)
        self.extract_button = header_button("xsi-extract-archive-symbolic", _("Extract"), "win.extract")
        self.header.pack_end(self.extract_button)
        self.set_titlebar(self.header)
        self.header.show_all()
        self.extract_button.hide()   # nothing to extract on the welcome page

        self.stack = Gtk.Stack()
        self.stack.add_named(self.build_welcome(), "welcome")
        self.stack.add_named(self.build_browser(), "browser")
        self.add(self.stack)
        self.stack.show_all()

        self.actions = {}
        for name, handler in (("open", self.on_open), ("create", self.on_create),
                              ("extract", self.on_extract), ("up", self.on_up),
                              ("close", lambda *_args: self.close())):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", handler)
            self.add_action(action)
            self.actions[name] = action
        self.update_actions()
        self.connect("destroy", self.on_destroy)

    # -- layout ------------------------------------------------------------

    def build_welcome(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, valign=Gtk.Align.CENTER,
                      halign=Gtk.Align.CENTER)
        scale = self.get_scale_factor()
        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(os.path.join(DATA_DIR, "unfold.svg"), 96 * scale, 96 * scale)
        box.add(Gtk.Image.new_from_surface(Gdk.cairo_surface_create_from_pixbuf(pixbuf, scale, None)))
        label = Gtk.Label(label=_("Open an archive or create a new one"))
        label.get_style_context().add_class("dim-label")
        box.add(label)
        buttons = Gtk.Box(spacing=6, halign=Gtk.Align.CENTER)
        for text, action in ((_("Open…"), "win.open"), (_("Create…"), "win.create")):
            buttons.add(Gtk.Button(label=text, action_name=action))
        box.add(buttons)
        return box

    def build_browser(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, border_width=6)
        # The path as one button per folder, like the one of Nemo, with arrows to scroll it when it is long
        self.pathbar = Gtk.Box()
        self.pathbar.get_style_context().add_class("linked")
        self.path_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.EXTERNAL,
                                              vscrollbar_policy=Gtk.PolicyType.NEVER)
        self.path_scroll.add(self.pathbar)
        self.path_adjustment = self.path_scroll.get_hadjustment()
        self.path_to_end = True
        self.path_adjustment.connect("changed", self.on_path_resized)
        self.path_adjustment.connect("value-changed", self.update_path_arrows)
        self.path_left = Gtk.Button(tooltip_text=_("Scroll left"))
        self.path_left.add(Gtk.Image.new_from_icon_name("xsi-pan-start-symbolic", Gtk.IconSize.BUTTON))
        self.path_left.connect("clicked", self.scroll_path, -1)
        self.path_right = Gtk.Button(tooltip_text=_("Scroll right"))
        self.path_right.add(Gtk.Image.new_from_icon_name("xsi-pan-end-symbolic", Gtk.IconSize.BUTTON))
        self.path_right.connect("clicked", self.scroll_path, 1)
        bar = Gtk.Box(spacing=6)
        bar.pack_start(self.path_left, False, False, 0)
        bar.pack_start(self.path_scroll, True, True, 0)
        bar.pack_start(self.path_right, False, False, 0)
        box.pack_start(bar, False, False, 0)

        self.store = Gtk.ListStore(Gio.Icon, str, str, bool, GObject.TYPE_INT64, str, str)
        self.sorted = Gtk.TreeModelSort(model=self.store)
        for column in (NAME, SIZE, TYPE, MODIFIED):
            self.sorted.set_sort_func(column, self.compare, column)
        self.sorted.set_sort_column_id(NAME, Gtk.SortType.ASCENDING)
        self.view = Gtk.TreeView(model=self.sorted, enable_search=True, search_column=NAME)
        self.view.set_rubber_banding(True)
        self.selection = self.view.get_selection()
        self.selection.set_mode(Gtk.SelectionMode.MULTIPLE)
        self.selection.connect("changed", self.on_selection_changed)
        self.view.connect("row-activated", self.on_row_activated)

        column = Gtk.TreeViewColumn(title=_("Name"))
        column.set_expand(True)
        column.set_resizable(True)
        icon = Gtk.CellRendererPixbuf()
        column.pack_start(icon, False)
        column.add_attribute(icon, "gicon", 0)
        text = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.MIDDLE)
        column.pack_start(text, True)
        column.add_attribute(text, "text", NAME)
        column.set_sort_column_id(NAME)
        self.view.append_column(column)

        size = Gtk.CellRendererText(xalign=1)
        column = Gtk.TreeViewColumn(_("Size"), size)
        column.set_cell_data_func(size, self.size_data)
        column.set_sort_column_id(SIZE)
        self.view.append_column(column)

        column = Gtk.TreeViewColumn(_("Type"), Gtk.CellRendererText(), text=TYPE)
        column.set_sort_column_id(TYPE)
        self.view.append_column(column)

        column = Gtk.TreeViewColumn(_("Modified"), Gtk.CellRendererText(), text=MODIFIED)
        column.set_sort_column_id(MODIFIED)
        self.view.append_column(column)

        scrolled = Gtk.ScrolledWindow(shadow_type=Gtk.ShadowType.IN)
        scrolled.add(self.view)
        box.pack_start(scrolled, True, True, 0)
        self.status = Gtk.Label(xalign=0, margin_start=3)
        box.pack_start(self.status, False, False, 0)
        return box

    def size_data(self, _column, renderer, model, tree_iter, _data):
        renderer.set_property("text", "" if model[tree_iter][IS_DIR] else GLib.format_size(model[tree_iter][SIZE]))

    def compare(self, model, a, b, column):
        """The folders go first, whatever the order."""
        if model[a][IS_DIR] != model[b][IS_DIR]:
            descending = self.sorted.get_sort_column_id()[-1] == Gtk.SortType.DESCENDING
            return (-1 if model[a][IS_DIR] else 1) * (-1 if descending else 1)
        first, second = model[a][column], model[b][column]
        if column in (NAME, TYPE):
            first, second = first.casefold(), second.casefold()
        return (first > second) - (first < second)

    # -- state -------------------------------------------------------------

    def get_selected_paths(self):
        """Returns the paths of the entries that are selected."""
        model, paths = self.selection.get_selected_rows()
        return {model[path][PATH] for path in paths}

    def update_actions(self):
        self.actions["extract"].set_enabled(self.archive is not None)
        self.actions["up"].set_enabled(self.archive is not None and self.folder != "")

    def update_status(self):
        selected = len(self.get_selected_paths())
        if selected:
            text = ngettext("%d item selected", "%d items selected", selected) % selected
        else:
            count = len(self.store)
            text = ngettext("%d item", "%d items", count) % count
        self.status.set_text(text)

    def on_selection_changed(self, _selection):
        self.update_status()

    def show_folder(self, folder):
        self.folder = folder
        self.store.clear()
        for entry in self.archive.get_children(folder):
            self.store.append([get_icon(entry.name, entry.is_dir), entry.name, entry.path, entry.is_dir,
                               entry.size, entry.modified, get_type(entry)])
        self.update_pathbar()
        self.update_status()
        self.update_actions()

    def update_pathbar(self):
        for button in self.pathbar.get_children():
            button.destroy()
        parts = self.folder.split("/") if self.folder else []
        path = ""
        for index in range(len(parts) + 1):
            if index:
                path = parts[index - 1] if not path else path + "/" + parts[index - 1]
            current = index == len(parts)
            content = Gtk.Box(spacing=6)
            if index == 0:
                content.add(Gtk.Image.new_from_gicon(get_icon(os.path.basename(self.archive.path), False),
                                                     Gtk.IconSize.BUTTON))
            elif current:
                content.add(Gtk.Image.new_from_icon_name("xsi-folder-symbolic", Gtk.IconSize.BUTTON))
            content.add(Gtk.Label(label=os.path.basename(self.archive.path) if index == 0 else parts[index - 1]))
            button = Gtk.ToggleButton(active=current)
            button.add(content)
            # not while the button is handling the click: it is destroyed when the path is drawn again
            button.connect("clicked", lambda _button, target: GLib.idle_add(self.show_folder, target), path)
            self.pathbar.add(button)
        self.pathbar.show_all()
        self.path_to_end = True

    def on_path_resized(self, adjustment):
        """The bar has its size: show the end of the path, which is the folder that is open."""
        if self.path_to_end:
            adjustment.set_value(adjustment.get_upper() - adjustment.get_page_size())
        self.update_path_arrows()

    def scroll_path(self, _button, direction):
        self.path_to_end = False
        adjustment = self.path_adjustment
        adjustment.set_value(adjustment.get_value() + direction * adjustment.get_page_size() / 2)

    def update_path_arrows(self, *_args):
        adjustment = self.path_adjustment
        overflow = adjustment.get_upper() > adjustment.get_page_size() + 1
        self.path_left.set_visible(overflow)
        self.path_right.set_visible(overflow)
        self.path_left.set_sensitive(overflow and adjustment.get_value() > 0)
        self.path_right.set_sensitive(
            overflow and adjustment.get_value() < adjustment.get_upper() - adjustment.get_page_size() - 1)

    def set_archive(self, archive):
        if self.archive:
            self.archive.close()
        self.archive = archive
        self.header.set_title(os.path.basename(archive.path))
        self.header.set_subtitle(os.path.dirname(archive.path))
        self.stack.set_visible_child_name("browser")
        self.extract_button.show()
        self.show_folder("")
        self.view.grab_focus()

    def on_destroy(self, _window):
        self.closing = True
        if self.archive:
            self.archive.close()
        for folder in self.temp_dirs:
            shutil.rmtree(folder, ignore_errors=True)

    # -- opening -----------------------------------------------------------

    def open_archive(self, path, password=None):
        self.pending = True

        def finished(archive):
            self.pending = False
            if archive:
                self.set_archive(archive)

        open_archive_task(self, path, finished, password, lambda: not self.closing)

    def on_open(self, *_args):
        chooser = Gtk.FileChooserDialog(title=_("Open Archive"), transient_for=self,
                                        action=Gtk.FileChooserAction.OPEN)
        chooser.add_buttons(_("Cancel"), Gtk.ResponseType.CANCEL, _("Open"), Gtk.ResponseType.OK)
        archives = Gtk.FileFilter()
        archives.set_name(_("Archives"))
        for mime in ARCHIVE_TYPES:
            archives.add_mime_type(mime)
        everything = Gtk.FileFilter()
        everything.set_name(_("All files"))
        everything.add_pattern("*")
        chooser.add_filter(archives)
        chooser.add_filter(everything)
        path = chooser.get_filename() if chooser.run() == Gtk.ResponseType.OK else None
        chooser.destroy()
        if path:
            self.get_application().open_path(path)

    def on_row_activated(self, _view, tree_path, _column):
        row = self.sorted[tree_path]
        if row[IS_DIR]:
            self.show_folder(row[PATH])
        else:
            self.open_file(row[PATH])

    def on_up(self, *_args):
        self.show_folder(self.folder.rpartition("/")[0])

    # -- extracting --------------------------------------------------------

    def unlock(self, selection):
        return unlock(self, self.archive, selection)

    def extract_task(self, dest, selection, overwrite, success):
        extract_task(self, self.archive, dest, selection, overwrite, lambda ok: ok and success(),
                     lambda: not self.closing)

    def show_uri(self, path, error_title):
        try:
            Gio.AppInfo.launch_default_for_uri(Gio.File.new_for_path(path).get_uri(), None)
        except GLib.Error as error:
            message(self, error_title, "%s\n%s" % (os.path.basename(path), error.message))

    def open_file(self, path):
        if not self.unlock({path}):
            return
        folder = tempfile.mkdtemp(prefix="unfold-")
        self.temp_dirs.append(folder)
        self.extract_task(folder, {path}, True, lambda: self.show_uri(os.path.join(folder, path), _("Could not open the file")))

    def on_extract(self, *_args):
        selection = self.get_selected_paths() or None
        stem = sevenzip.get_archive_stem(self.archive.path)
        chooser = Gtk.FileChooserDialog(title=_("Extract to"), transient_for=self,
                                        action=Gtk.FileChooserAction.SELECT_FOLDER)
        chooser.add_buttons(_("Cancel"), Gtk.ResponseType.CANCEL, _("Extract"), Gtk.ResponseType.OK)
        chooser.set_current_folder(os.path.dirname(self.archive.path))
        wrap = None
        if selection is None:
            wrap = Gtk.CheckButton(label=_("Extract into a folder named “%s”") % stem)
            # an archive that has a single folder at its top already makes its own
            wrap.set_active(len(self.archive.get_children("")) != 1)
            wrap.show()
            chooser.set_extra_widget(wrap)
        accepted = chooser.run() == Gtk.ResponseType.OK
        dest = chooser.get_filename()
        wrapped = wrap is not None and wrap.get_active()
        chooser.destroy()
        if not accepted or not dest:
            return
        if wrapped:
            dest = os.path.join(dest, stem)
        if not self.unlock(selection):
            return
        overwrite = True
        existing = self.archive.get_conflicts(dest, selection)
        if existing:
            answer = ask_conflicts(self, len(existing))
            if answer is None:
                return
            overwrite = answer == "replace"
        self.extract_task(dest, selection, overwrite, lambda: self.show_uri(dest, _("Could not open the folder")))

    # -- creating ----------------------------------------------------------

    def create(self, paths=None):
        create_archive_task(self, paths or [], lambda out: out and self.get_application().open_path(out),
                            lambda: not self.closing)

    def on_create(self, *_args):
        self.create()
