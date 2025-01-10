from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# Collect all submodules
hiddenimports = collect_submodules('spotscrape')

# Collect all data files
datas = collect_data_files('spotscrape', include_py_files=True) 