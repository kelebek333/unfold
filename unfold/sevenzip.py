"""Everything unfold knows about archives: it asks the 7-Zip command line tool."""
import os
import shutil
import subprocess
import tempfile

from unfold import _

# (suffix, 7-Zip type, whether it can be protected by a password)
FORMATS = [
    (".zip", "zip", True),
    (".7z", "7z", True),
    (".tar.gz", "gzip", False),
    (".tar.xz", "xz", False),
    (".tar.bz2", "bzip2", False),
    (".tar", "tar", False),
]
# 7-Zip sees a .tar.gz as a gzip file holding a .tar file
COMPRESSORS = ("gzip", "xz", "bzip2", "zstd", "lzma", "Z")


class Error(Exception):
    pass


class PasswordError(Error):
    pass


class Cancelled(Error):
    pass


def get_program():
    """Returns the path of the 7-Zip command, or None if it is not installed."""
    for name in ("7zz", "7z", "7za"):
        path = shutil.which(name)
        if path:
            return path
    return None


def run(args, cwd=None, password=None, protect=False, cancelled=None):
    """Returns the output of 7-Zip. The password goes through its standard input, where ps can't see it:
    7-Zip asks for it when an archive needs it, and when -p, without a password, tells it to protect one."""
    args = [get_program()] + args
    stdin = None
    if password is not None:
        if protect:
            args.append("-p")
        # twice: when it protects an archive, 7-Zip asks to confirm
        stdin = (password + "\n") * 2
    process = subprocess.Popen(args, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True, errors="replace")
    while True:
        try:
            output, _unused = process.communicate(input=stdin, timeout=0.2)
            break
        except subprocess.TimeoutExpired:
            if cancelled and cancelled():
                process.kill()
                process.communicate()
                raise Cancelled()
    lowered = output.lower()
    # 7-Zip shows its prompt even when it gets the password from the standard input
    if "wrong password" in lowered or "encrypted archive" in lowered or (
            password is None and "enter password" in lowered):
        raise PasswordError()
    if "Unsupported Method" in output:
        raise Error(_("This archive uses a compression method that 7-Zip cannot read.\n"
                      "For rar archives, install the 7zip-rar package."))
    if process.returncode >= 2 or (process.returncode == 1 and "ERROR" in output):
        lines = [line for line in output.splitlines() if "ERROR" in line or "Can not" in line or "Cannot" in line]
        lines = lines or [line for line in output.splitlines() if line.strip()][-3:]
        raise Error("\n".join(lines))
    return output


def get_fields(block):
    """Returns the "key = value" lines of a block of the listing, as a dict."""
    result = {}
    for line in block.splitlines():
        key, separator, value = line.partition(" = ")
        if separator:
            result[key] = value
    return result


class Entry:
    def __init__(self, info):
        self.path = info["Path"]
        self.is_dir = info.get("Folder") == "+" or info.get("Attributes", "").startswith("D")
        self.size = int(info.get("Size") or 0)
        self.modified = info.get("Modified", "")[:16]
        self.encrypted = info.get("Encrypted") == "+"

    @property
    def name(self):
        return self.path.rpartition("/")[2]

    @property
    def parent(self):
        return self.path.rpartition("/")[0]


def get_listing(path, password, cancelled):
    """Returns the type of the archive and its entries."""
    output = run(["l", "-slt", "-spd", "-scsUTF-8", path], password=password, cancelled=cancelled)
    header, _separator, body = output.partition("\n----------\n")
    entries = [Entry(info) for info in map(get_fields, body.split("\n\n")) if "Path" in info]
    return get_fields(header).get("Type", ""), entries


class Archive:
    def __init__(self, path, password=None, cancelled=None):
        self.path = path
        self.password = password
        self.source = path   # what 7-Zip works on: the .tar inside a .tar.gz
        self.tmp = None
        kind, entries = get_listing(path, password, cancelled)
        if kind in COMPRESSORS:
            # a compressed file: if what is inside is a tar, that is what we show
            self.tmp = tempfile.mkdtemp(prefix="unfold-")
            try:
                run(["x", "-y", "-o" + self.tmp, path], cancelled=cancelled)
                inner = os.path.join(self.tmp, os.listdir(self.tmp)[0])
                try:
                    inner_kind, inner_entries = get_listing(inner, None, cancelled)
                except Error:
                    inner_kind = None
                if inner_kind == "tar":
                    self.source = inner
                    entries = inner_entries
                else:
                    entries = [Entry({"Path": os.path.basename(inner), "Size": os.path.getsize(inner)})]
                    self.close()
            except BaseException:
                self.close()
                raise
        self.entries = {}
        for entry in entries:
            entry.path = "/".join(part for part in entry.path.split("/") if part not in ("", "."))
            if entry.path:
                self.entries[entry.path] = entry
        for path in list(self.entries):
            parent = self.entries[path].parent
            while parent and parent not in self.entries:
                self.entries[parent] = Entry({"Path": parent, "Folder": "+"})
                parent = self.entries[parent].parent
        self.encrypted = any(entry.encrypted for entry in entries)

    def close(self):
        if self.tmp:
            shutil.rmtree(self.tmp, ignore_errors=True)
            self.tmp = None

    def get_children(self, folder):
        """Returns the entries that are directly in this folder."""
        return [entry for entry in self.entries.values() if entry.parent == folder]

    def get_covered(self, selection):
        """Returns the entries that are selected, or inside a selected folder. None selects everything."""
        if selection is None:
            return list(self.entries.values())
        covered = []
        for path, entry in self.entries.items():
            parts = path.split("/")
            if any("/".join(parts[:i + 1]) in selection for i in range(len(parts))):
                covered.append(entry)
        return covered

    def needs_password(self, selection):
        """Whether an encrypted file is selected and the password is not known yet. None selects everything."""
        return self.password is None and any(entry.encrypted for entry in self.get_covered(selection))

    def get_conflicts(self, dest, selection):
        """Returns the files that extracting there would replace."""
        return [entry.path for entry in self.get_covered(selection)
                if not entry.is_dir and os.path.lexists(os.path.join(dest, entry.path))]

    def extract(self, dest, selection=None, overwrite=True, cancelled=None):
        args = ["x", "-y", "-aoa" if overwrite else "-aos", "-spd", "-scsUTF-8", "-o" + dest, self.source]
        listing = None
        if selection is not None:
            handle, listing = tempfile.mkstemp(prefix="unfold-list-")
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                stream.write("\n".join(sorted(selection)) + "\n")
            args.append("@" + listing)
        try:
            run(args, password=self.password, cancelled=cancelled)
        finally:
            if listing:
                os.remove(listing)


def create(out, fmt, sources, password=None, cancelled=None):
    """Makes the archive out of these files and folders, replacing any file that is already there."""
    suffix, kind, can_protect = fmt
    if not can_protect:
        password = None
    if os.path.lexists(out):
        os.remove(out)
    tmp = tempfile.mkdtemp(prefix="unfold-")
    try:
        target = out
        if kind in COMPRESSORS:
            target = os.path.join(tmp, os.path.basename(out)[:-len(suffix)] + ".tar")
        options = ["-t" + ("tar" if kind in COMPRESSORS else kind), "-spd"]
        if password and kind == "zip":
            options.append("-mem=AES256")
        if password and kind == "7z":
            options.append("-mhe=on")   # the names of the files are hidden too
        parents = {}
        for source in sources:
            source = source.rstrip("/")
            parents.setdefault(os.path.dirname(source), []).append(os.path.basename(source))
        for parent, names in parents.items():
            run(["a"] + options + [target] + names, cwd=parent, password=password or None,
                protect=bool(password), cancelled=cancelled)
        if kind in COMPRESSORS:
            run(["a", "-t" + kind, out, target], cancelled=cancelled)
    except BaseException:
        if os.path.lexists(out):
            os.remove(out)
        raise
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def get_archive_stem(path):
    """Returns the name of an archive without what makes it one: files.tar.gz gives files."""
    stem = os.path.splitext(os.path.basename(path))[0]
    if stem.lower().endswith(".tar"):
        stem = stem[:-4]
    return stem or os.path.basename(path)
