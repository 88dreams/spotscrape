# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['C:\\Users\\lucas\\GIT\\spotscrape\\src\\spotscrape\\app.py'],
    pathex=[],
    binaries=[],
    datas=[('C:/Users/lucas/GIT/spotscrape/src/spotscrape/frontend', 'frontend'), ('C:/Users/lucas/GIT/spotscrape/src/spotscrape/config.json.example', '.'), ('C:/Users/lucas/GIT/spotscrape/src/spotscrape/.env.example', '.'), ('C:/Users/lucas/AppData/Local/ms-playwright/chromium-1148', 'playwright')],
    hiddenimports=['flask', 'flask_cors', 'webview', 'playwright', 'spotipy', 'openai', 'asyncio', 'aiohttp', 'requests', 'json', 'logging', 'bs4', 'lxml', 'jinja2', 'jinja2.ext', 'werkzeug', 'werkzeug.serving', 'werkzeug.debug', 'clr_loader', 'pythonnet', 'tzdata', 'zoneinfo'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=True,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [('v', None, 'OPTION')],
    exclude_binaries=True,
    name='spotscrape',
    debug=True,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['C:\\Users\\lucas\\GIT\\spotscrape\\src\\spotscrape\\frontend\\static\\img\\icon.ico'],
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
