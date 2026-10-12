project('unfold', version : '1.0.0', meson_version : '>= 0.59.0')

prefix = get_option('prefix')
datadir = get_option('datadir')
bindir = get_option('bindir')

python3 = import('python').find_installation('/usr/bin/python3')
python_module_dir = python3.get_install_dir()

# Debian uses different Python layouts for /usr and /usr/local. Meson uses
# the packaged-system layout, even with a /usr/local prefix. For Python's
# default installation prefix, use its default module directory instead.
python_default_paths = run_command(
  python3, '-c',
  'import sysconfig; print(sysconfig.get_path("data")); print(sysconfig.get_path("purelib"))',
  check: true,
).stdout().strip().split('\n')
python_default_prefix = python_default_paths[0]
python_default_module_dir = python_default_paths[1]
if prefix == python_default_prefix
  python_module_dir = python_default_module_dir
endif
python_module_dir = join_paths(python_module_dir, 'unfold')

install_data(
  'unfold/__init__.py',
  'unfold/application.py',
  'unfold/dialogs.py',
  'unfold/sevenzip.py',
  'unfold/window.py',
  install_dir: python_module_dir,
)

configure_file(
  input: 'unfold/config.py.in',
  output: 'config.py',
  configuration: {
    'version': meson.project_version(),
    'data_dir': join_paths(prefix, datadir, 'unfold'),
  },
  install: true,
  install_dir: python_module_dir,
)

install_data(
  'data/unfold',
  install_dir: bindir,
  install_mode: 'rwxr-xr-x',
)

subdir('data')
subdir('po')
