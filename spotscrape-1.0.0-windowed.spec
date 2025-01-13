# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['src\\spotscrape\\app.py'],
    pathex=[],
    binaries=[],
    datas=[('src/spotscrape/frontend/static', 'frontend/static'), ('src/spotscrape/frontend/templates', 'frontend/templates'), ('config.json.example', '.'), ('src/spotscrape/setup_handler.py', 'spotscrape'), ('src/spotscrape/config_manager.py', 'spotscrape'), ('.env.example', '.')],
    hiddenimports=['engineio.async_drivers.threading', 'flask', 'flask_cors', 'playwright', 'spotipy', 'openai', 'dotenv', 'pathlib', 'spotscrape.setup_handler', 'spotscrape.config_manager'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='spotscrape-1.0.0-windowed',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['src\\spotscrape\\frontend\\static\\img\\icon.ico'],
)
