# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['src/spotscrape/app.py'],
    pathex=['src'],
    binaries=[],
    datas=[
        ('src/spotscrape/frontend/templates/*', 'spotscrape/frontend/templates'),
        ('src/spotscrape/frontend/static/*', 'spotscrape/frontend/static'),
        ('src/spotscrape/config', 'spotscrape/config'),
        ('src/spotscrape/logs', 'spotscrape/logs'),
        ('src/spotscrape/data', 'spotscrape/data'),
        ('build/playwright', 'playwright')
    ],
    hiddenimports=[
        'spotscrape',
        'spotscrape.core',
        'spotscrape.app',
        'spotscrape.utils',
        'spotscrape.web_extractor',
        'spotscrape.spotify_manager',
        'spotscrape.content_processor',
        'webview'
    ],
    hookspath=['.'],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
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
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='spotscrape'
)
