i18n = import('i18n')
gnome = import('gnome')

install_data(
  'unfold.svg',
  install_dir: join_paths(get_option('datadir'), 'icons', 'hicolor', 'scalable', 'apps'),
)

gnome.post_install(gtk_update_icon_cache: true, update_desktop_database: true)

i18n.merge_file(
  input: 'org.x.unfold.desktop.in',
  output: 'org.x.unfold.desktop',
  type: 'desktop',
  po_dir: join_paths(meson.project_source_root(), 'po'),
  install: true,
  install_dir: join_paths(get_option('datadir'), 'applications'),
)

foreach action : ['unfold-compress', 'unfold-extract-here', 'unfold-extract-to']
  i18n.merge_file(
    input: join_paths('nemo', action + '.nemo_action.in'),
    output: action + '.nemo_action',
    type: 'desktop',
    po_dir: join_paths(meson.project_source_root(), 'po'),
    install: true,
    install_dir: join_paths(get_option('datadir'), 'nemo', 'actions'),
  )
endforeach

install_data(
  'nemo/unfold-compress-visible',
  install_dir: join_paths(get_option('datadir'), 'nemo', 'actions'),
  install_mode: 'rwxr-xr-x',
)
