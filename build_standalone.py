import PyInstaller.__main__
import sys
import os

def build_standalone():
    # Determine the appropriate file extension and additional options based on the OS
    if sys.platform.startswith('win'):
        ext = '.exe'
        icon = 'frontend/static/img/icon.ico'
        add_data = [
            ('frontend/static', 'frontend/static'),
            ('frontend/templates', 'frontend/templates'),
            ('config.json.example', '.'),
            ('.env.example', '.')
        ]
    elif sys.platform.startswith('darwin'):
        ext = '.app'
        icon = 'frontend/static/img/icon.icns'
        add_data = [
            ('frontend/static', 'frontend/static'),
            ('frontend/templates', 'frontend/templates'),
            ('config.json.example', '.'),
            ('.env.example', '.')
        ]
    else:  # Linux
        ext = ''
        icon = 'frontend/static/img/icon.png'
        add_data = [
            ('frontend/static', 'frontend/static'),
            ('frontend/templates', 'frontend/templates'),
            ('config.json.example', '.'),
            ('.env.example', '.')
        ]

    # Base PyInstaller arguments
    args = [
        'app.py',
        '--name=spotscrape',
        '--onefile',
        '--windowed',
        f'--icon={icon}',
        '--clean',
        '--noconfirm',
    ]

    # Add data files
    for src, dst in add_data:
        args.extend(['--add-data', f'{src}{os.pathsep}{dst}'])

    # Add hidden imports
    hidden_imports = [
        'engineio.async_drivers.threading',
        'flask',
        'flask_cors',
        'playwright',
        'spotipy',
        'openai'
    ]
    for imp in hidden_imports:
        args.extend(['--hidden-import', imp])

    # Run PyInstaller
    PyInstaller.__main__.run(args)

if __name__ == '__main__':
    build_standalone() 