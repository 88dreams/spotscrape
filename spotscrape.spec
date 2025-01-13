# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['C:\\users\\lucas\\GIT\\spotscrape\\src\\spotscrape\\app.py'],
    pathex=[],
    binaries=[],
    datas=[('src\\spotscrape\\frontend\\templates', 'frontend/templates'), ('src\\spotscrape\\frontend\\static', 'frontend/static'), ('config.json.example', '.'), ('.env.example', '.')],
    hiddenimports=['flask', 'flask_cors', 'webview', 'playwright', 'spotipy', 'openai', 'asyncio', 'aiohttp', 'requests', 'json', 'logging', 'bs4', 'lxml', 'jinja2', 'jinja2.ext', 'werkzeug', 'werkzeug.serving', 'werkzeug.debug', 'clr_loader', 'pythonnet'],
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
    [],
    exclude_binaries=True,
    name='spotscrape',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['C:\\users\\lucas\\GIT\\spotscrape\\src\\spotscrape\\frontend\\static\\img\\icon.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='spotscrape',
)
