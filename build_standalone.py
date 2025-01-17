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
    """Get the path to the browser installation"""
    try:
        # First, ensure the browser is installed
        import subprocess
        logger.info("Installing/Verifying Playwright browser...")
        result = subprocess.run(['playwright', 'install', 'chromium'], 
                              check=True, capture_output=True, text=True)
        logger.info(f"Playwright install output: {result.stdout}")
        
        # The browser is installed in the user's home directory
        ms_playwright_path = Path.home() / 'AppData' / 'Local' / 'ms-playwright'
        logger.info(f"Checking ms-playwright path: {ms_playwright_path}")
        
        if not ms_playwright_path.exists():
            raise FileNotFoundError(f"ms-playwright directory not found at {ms_playwright_path}")
            
        # List all directories to help with debugging
        logger.info("Available browser directories:")
        for item in ms_playwright_path.iterdir():
            logger.info(f"  {item}")
            
        # Look specifically for the headless shell directory
        browser_dirs = list(ms_playwright_path.glob('chromium_headless_shell-*'))
        if not browser_dirs:
            raise FileNotFoundError(f"No chromium_headless_shell directory found in {ms_playwright_path}")
            
        browser_path = browser_dirs[0]  # Use the first found directory
        logger.info(f"Using browser directory: {browser_path}")
        
        # Verify chrome-win directory exists
        chrome_win = browser_path / 'chrome-win'
        if not chrome_win.exists():
            raise FileNotFoundError(f"chrome-win directory not found in {browser_path}")
            
        # Find the browser executable
        exe_files = list(chrome_win.glob('*.exe'))
        if not exe_files:
            raise FileNotFoundError(f"No browser executable found in {chrome_win}")
            
        logger.info(f"Found browser executable: {exe_files[0]}")
        return browser_path
        
    except Exception as e:
        logger.error(f"Failed to find Playwright browser path: {e}")
        raise

def copy_playwright_files(src_dir, dst_dir, logger):
    """Copy all necessary Playwright files"""
    logger.info(f"Copying Playwright files from {src_dir} to {dst_dir}")
    
    try:
        # First, copy the chrome-win directory
        src_chrome_win = src_dir / 'chrome-win'
        dst_chrome_win = dst_dir / 'chrome-win'
        
        logger.info(f"Copying chrome-win from {src_chrome_win} to {dst_chrome_win}")
        if dst_chrome_win.exists():
            shutil.rmtree(dst_chrome_win)
        shutil.copytree(src_chrome_win, dst_chrome_win)
        
        # Verify and rename the executable if needed
        exe_files = list(dst_chrome_win.glob('*.exe'))
        if not exe_files:
            raise FileNotFoundError(f"No executable found in {dst_chrome_win}")
            
        target_exe = dst_chrome_win / 'headless_shell.exe'
        if exe_files[0].name != 'headless_shell.exe':
            logger.info(f"Renaming {exe_files[0].name} to headless_shell.exe")
            if target_exe.exists():
                target_exe.unlink()
            shutil.copy2(exe_files[0], target_exe)
        
        # Copy metadata files
        for item in src_dir.glob('*'):
            if item.is_file():
                dest_file = dst_dir / item.name
                logger.info(f"Copying: {item.name}")
                shutil.copy2(item, dest_file)
        
        # Create validation files
        for filename in ['DEPENDENCIES_VALIDATED', 'INSTALLATION_COMPLETE']:
            metadata_file = dst_dir / filename
            if not metadata_file.exists():
                logger.info(f"Creating metadata file: {filename}")
                metadata_file.touch()
        
        logger.info("All Playwright files copied successfully")
        
    except Exception as e:
        logger.error(f"Error copying Playwright files: {e}")
        raise

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
        
        # Set up Playwright directory structure
        browser_dir = Path(get_browser_path(logger)).resolve()
        local_browsers_dir = build_dir / '_internal' / 'playwright' / 'driver' / 'package' / '.local-browsers'
        build_browser_dir = local_browsers_dir / browser_dir.name
        
        # Create directory and copy files
        local_browsers_dir.mkdir(parents=True, exist_ok=True)
        copy_playwright_files(browser_dir, build_browser_dir, logger)
        
        # Log paths for verification
        logger.info("Build paths (all absolute):")
        logger.info(f"  Project root:      {base_dir}")
        logger.info(f"  Source package:    {src_dir}")
        logger.info(f"  Build directory:   {build_dir}")
        logger.info(f"  Output directory:  {dist_dir}")
        logger.info(f"  Templates source:  {templates_dir}")
        logger.info(f"  Static source:     {static_dir}")
        logger.info(f"  Browser source:    {browser_dir}")
        logger.info(f"  Browser dest:      {build_browser_dir}")
        
        # Verify critical files
        expected_exe = build_browser_dir / 'chrome-win' / 'headless_shell.exe'
        if not expected_exe.exists():
            raise FileNotFoundError(f"Browser executable not found at expected location: {expected_exe}")
        logger.info(f"Verified browser executable at: {expected_exe}")
        
        # Verify source directories
        if not templates_dir.exists():
            raise FileNotFoundError(f"Templates directory not found: {templates_dir}")
        if not static_dir.exists():
            raise FileNotFoundError(f"Static directory not found: {static_dir}")
            
        # Define data files
        data_files = [
            (str(templates_dir), 'frontend/templates'),
            (str(static_dir), 'frontend/static'),
            (str(src_dir / 'config.json.example'), '.'),
            (str(src_dir / '.env.example'), '.')
        ]
        
        # Base PyInstaller arguments
        args = [
            str(src_dir / 'app.py'),
            '--name=spotscrape',
            '--onedir',
            '--clean',
            '--noconfirm',
            '--distpath', str(dist_dir),
            '--workpath', str(build_dir),
            '--specpath', str(base_dir),
            '--hidden-import=playwright._impl._api_types',  # Essential Playwright import
            '--collect-all=playwright',  # Include all Playwright files
            '--collect-submodules=playwright',  # Include all submodules
            '--collect-data=playwright',  # Include all data files
            '--collect-binaries=playwright'  # Include all binaries
        ]
        
        # Add the _internal directory (includes Playwright files)
        separator = ";" if sys.platform.startswith('win') else ":"
        
        # Add the main _internal directory
        internal_dir_arg = f"{str(build_dir / '_internal')}{separator}_internal"
        logger.info(f"Adding _internal directory to PyInstaller: {internal_dir_arg}")
        args.extend(['--add-data', internal_dir_arg])
        
        # Explicitly add the .local-browsers directory
        browsers_dir = build_dir / '_internal' / 'playwright' / 'driver' / 'package' / '.local-browsers'
        browsers_dir_arg = f"{str(browsers_dir)}{separator}playwright/driver/package/.local-browsers"
        logger.info(f"Adding .local-browsers directory to PyInstaller: {browsers_dir_arg}")
        args.extend(['--add-data', browsers_dir_arg])
        
        # Add data files
        for src, dst in data_files:
            data_arg = f'{str(src)}{separator}{dst}'
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