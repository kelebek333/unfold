# Unfold

Archive Manager for Linux Desktops.

Create, browse and extract archives.

## Formats

Unfold uses a single compression backend: 7zip.

7zip supports a multitude of compression formats.

To support RAR archives, `7zip-rar` needs to be installed.

## Command line

```bash
unfold archive.zip            # open an archive
unfold --compress file...     # create an archive from files and folders
```

## Building from source

### For Mint with mint-dev-tools

```bash
# Install mint-dev-tools
apt install mint-dev-tools
# Remove any previous versions
apt remove 'unfold*'
# Build and install from github
mint-build -i -g https://github.com/xapp-project/unfold.git
```

### For other distributions with meson

```bash
meson setup build --prefix=/usr/local
meson compile -C build
sudo meson install -C build
```

#### Dependencies

```text
7zip
gir1.2-gtk-3.0
gir1.2-xapp-1.0
python3-gi
python3-setproctitle
python3-xapp
```

#### Dependencies for building

```text
gettext
libglib2.0-dev or libgio-2.0-dev
meson
pkg-config
```

#### Dependencies for runtime

```text
xapp-symbolic-icons
7zip-rar (to open rar archives)
```

## Translations

Please use Launchpad to translate this project: https://translations.launchpad.net/linuxmint/latest/.

The PO files in this project are imported from there.

## License

Code: GPLv3+
