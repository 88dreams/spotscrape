import PyInstaller.__main__
import sys
import os
import shutil
import logging
from datetime import datetime
import subprocess
from pathlib import Path

def setup_logging():
    """Set up logging for the build process"""
    # Create logs directory in the project root
    base_dir = Path(__file__).parent.resolve()
    log_dir = base_dir / 'logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    
    # Set up log file with timestamp
    log_file = log_dir / f"spot-build-{datetime.now().strftime('%Y%m%d')}.log"
    
    # Create a logger
    logger = logging.getLogger('spot-build')
    logger.setLevel(logging.DEBUG)  # Set to DEBUG to capture everything
    
    # Remove any existing handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    # Create file handler with more detailed format
    file_handler = logging.FileHandler(str(log_file), mode='w', encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    
    # Create console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    
    # Create formatters - more detailed for file, concise for console
    file_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s\n'
        'Path: %(pathname)s\n'
        'Details: %(exc_info)s\n',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    console_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Add formatters to handlers
    file_handler.setFormatter(file_formatter)
    console_handler.setFormatter(console_formatter)
    
    # Add handlers to logger
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    # Prevent propagation to root logger
    logger.propagate = False
    
    # Test logging with full details
    logger.info(f"Build log file created at: {log_file}")
    logger.debug("Logging system initialized with full message capture")
    
    return logger

def cleanup_artifacts(logger):
    """Clean up build artifacts"""
    paths_to_clean = ['build', 'dist', '__pycache__', '.pytest_cache']
    spec_files = Path().glob('*.spec')
    
    for path in paths_to_clean:
        if os.path.exists(path):
            shutil.rmtree(path)
            logger.info(f"Removed {path}")
            
    for spec_file in spec_files:
        spec_file.unlink()
        logger.info(f"Removed {spec_file}")

def check_dependencies(logger):
    """Verify required dependencies are installed"""
    required = {
        'flask': 'flask',
        'webview': 'pywebview',
        'spotipy': 'spotipy',
        'playwright': 'playwright',
        'PyInstaller': 'pyinstaller'
    }
    
    missing = []
    for module, package in required.items():
        try:
            __import__(module)
            logger.info(f"Found required dependency: {package}")
        except ImportError:
            missing.append(package)
            logger.error(f"Missing dependency: {package}")
    
    if missing:
        raise ImportError(f"Missing dependencies: {', '.join(missing)}")

def get_browser_path(logger):
    """Get the Playwright browser path"""
    # Install Playwright browser
    logger.info("Installing Playwright browser...")
    subprocess.run(
        [sys.executable, '-m', 'playwright', 'install', 'chromium', '--with-deps'],
        check=True, capture_output=True
    )
    
    # Common browser locations
    search_paths = [
        Path.home() / 'AppData' / 'Local' / 'ms-playwright',  # Windows
        Path.home() / '.cache' / 'ms-playwright',  # Linux
        Path.cwd() / 'playwright-browsers',
        Path(sys.executable).parent / 'playwright-browsers'
    ]
    
    for base_dir in search_paths:
        if base_dir.exists():
            for item in base_dir.iterdir():
                if item.name.startswith('chromium'):
                    logger.info(f"Found Playwright browser at: {item}")
                    return str(item)
    
    logger.error("Playwright browser not found in any of the search paths")
    raise FileNotFoundError("Playwright browser not found")

def build_standalone(dev_mode=False):
    """Build the standalone executable"""
    logger = setup_logging()
    logger.info("Starting build process...")
    
    try:
        # Initial cleanup
        cleanup_artifacts(logger)
        check_dependencies(logger)
        
        # Set up paths - ensure all paths are absolute
        base_dir = Path(__file__).parent.resolve()  # Project root
        src_dir = (base_dir / 'src' / 'spotscrape').resolve()  # Source package
        dist_dir = (base_dir / 'dist').resolve()  # Build output
        build_dir = (base_dir / 'build').resolve()  # Build temp
        
        # Frontend source directories
        templates_dir = (src_dir / 'frontend' / 'templates').resolve()
        static_dir = (src_dir / 'frontend' / 'static').resolve()
        
        # Get browser path
        browser_path = Path(get_browser_path(logger)).resolve()
        
        # Log all paths
        logger.info("Build paths (all absolute):")
        logger.info(f"  Project root:      {base_dir}")
        logger.info(f"  Source package:    {src_dir}")
        logger.info(f"  Build directory:   {build_dir}")
        logger.info(f"  Output directory:  {dist_dir}")
        logger.info(f"  Templates source:  {templates_dir}")
        logger.info(f"  Static source:     {static_dir}")
        logger.info(f"  Browser binary:    {browser_path}")
        
        # Verify source directories
        if not templates_dir.exists():
            raise FileNotFoundError(f"Templates directory not found: {templates_dir}")
        if not static_dir.exists():
            raise FileNotFoundError(f"Static directory not found: {static_dir}")
            
        # Define data files - use relative paths for PyInstaller destinations
        data_files = [
            (str(templates_dir), 'frontend/templates'),  # Will be at root of _MEIPASS
            (str(static_dir), 'frontend/static'),       # Will be at root of _MEIPASS
            (str(src_dir / 'config.json.example'), '.'),
            (str(src_dir / '.env.example'), '.')
        ]
        
        # Base PyInstaller arguments
        args = [
            str(src_dir / 'app.py'),  # Entry point
            '--name=spotscrape',
            '--onedir',
            '--clean',
            '--noconfirm',
            '--distpath', str(dist_dir),
            '--workpath', str(build_dir),
            '--specpath', str(base_dir)
        ]
        
        # Add browser binary - will be at root of _MEIPASS
        separator = ";" if sys.platform.startswith('win') else ":"
        browser_arg = f"{str(browser_path)}{separator}playwright-browser"
        logger.info(f"Adding browser binary: {browser_arg}")
        args.extend(['--add-binary', browser_arg])
        
        # Add data files
        for src, dst in data_files:
            data_arg = f'{str(src)}{";" if sys.platform.startswith("win") else ":"}{dst}'
            args.extend(['--add-data', data_arg])
        
        # Add icon if available
        icon_path = static_dir / 'img' / 'icon.ico'
        if sys.platform.startswith('win') and icon_path.exists():
            args.extend(['--icon', str(icon_path)])
        
        # Add hidden imports
        hidden_imports = [
            'flask', 'flask_cors', 'webview', 'playwright', 'spotipy',
            'openai', 'asyncio', 'aiohttp', 'requests', 'json',
            'logging', 'bs4', 'lxml', 'jinja2', 'jinja2.ext',
            'werkzeug', 'werkzeug.serving', 'werkzeug.debug',
            'clr_loader', 'pythonnet', 'tzdata', 'zoneinfo',
            'email_validator'
        ]
        
        for imp in hidden_imports:
            args.extend(['--hidden-import', imp])
        
        # Add mode-specific settings
        if dev_mode:
            args.extend(['--debug=all', '--log-level=DEBUG'])
        else:
            args.extend(['--windowed', '--log-level=INFO'])
        
        # Log and run PyInstaller
        logger.info("PyInstaller command:")
        logger.info(" ".join(args))
        PyInstaller.__main__.run(args)
        
        # Verify build was created
        app_dir = (dist_dir / 'spotscrape').resolve()
        if not app_dir.exists():
            raise FileNotFoundError(f"Build directory not created: {app_dir}")
            
        # Log build contents
        logger.info("Build contents:")
        for item in app_dir.rglob('*'):
            logger.info(f"  {item.relative_to(app_dir)}")
            
        # Verify the executable was created
        if sys.platform.startswith('win'):
            exe_path = app_dir / 'spotscrape.exe'
        else:
            exe_path = app_dir / 'spotscrape'
            
        if not exe_path.exists():
            raise FileNotFoundError(f"Executable not created: {exe_path}")
        
        logger.info("Build completed successfully!")
        logger.info(f"Application built at: {app_dir}")
        
    except Exception as e:
        logger.error(f"Build failed: {str(e)}")
        raise

if __name__ == '__main__':
    try:
        build_standalone('--dev' in sys.argv)
    except Exception as e:
        logging.error(f"Fatal error: {e}")
        sys.exit(1) 