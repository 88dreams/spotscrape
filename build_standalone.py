import PyInstaller.__main__
import sys
import os
import shutil
import hashlib
from pathlib import Path
import logging
from datetime import datetime
from importlib.metadata import version

def setup_build_logging():
    """Set up logging for the build process"""
    # Get the executable's directory or current directory
    if getattr(sys, 'frozen', False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Create dist/logs directory if it doesn't exist
    log_dir = os.path.join(base_dir, "dist", "logs")
    os.makedirs(log_dir, exist_ok=True)
    
    # Create or overwrite the build log file
    log_path = os.path.join(log_dir, f"spot-build-{datetime.now().strftime('%Y%m%d')}.log")
    
    # Configure root logger to capture all output
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    
    # Remove any existing handlers from both loggers
    root_logger.handlers = []
    
    # File handler for all output
    file_handler = logging.FileHandler(log_path, mode='w', encoding='utf-8')
    file_handler.setLevel(logging.INFO)
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    
    # Create formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    # Add handlers to root logger
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    
    # Create our build logger as a child of root
    build_logger = logging.getLogger('spot-build')
    build_logger.setLevel(logging.INFO)
    
    # Log initial message
    build_logger.info(f"Build log file created at: {log_path}")
    return build_logger

# Initialize build logger
build_logger = setup_build_logging()

def log_and_print(message, level=logging.INFO):
    """Helper function to log message and print to console"""
    if level == logging.ERROR:
        build_logger.error(message)
    elif level == logging.WARNING:
        build_logger.warning(message)
    else:
        build_logger.info(message)

def cleanup_build_artifacts():
    """Clean up previous build artifacts"""
    log_and_print("Cleaning up previous build artifacts...")
    
    # Clean build and dist directories
    paths_to_remove = ['build', '.pytest_cache']
    spec_files = [f for f in os.listdir('.') if f.endswith('.spec')]
    
    cleaned_count = {'dirs': 0, 'files': 0}
    
    # Special handling for dist directory to preserve logs
    if os.path.exists('dist'):
        try:
            for item in os.listdir('dist'):
                item_path = os.path.join('dist', item)
                if item != 'logs':  # Skip the logs directory
                    if os.path.isdir(item_path):
                        shutil.rmtree(item_path)
                        cleaned_count['dirs'] += 1
                        log_and_print(f"Removed directory: {item_path}")
                    elif os.path.isfile(item_path):
                        os.remove(item_path)
                        cleaned_count['files'] += 1
                        log_and_print(f"Removed file: {item_path}")
        except Exception as e:
            log_and_print(f"Error cleaning dist directory: {e}", logging.ERROR)
    
    # Remove other artifacts
    for path in paths_to_remove + spec_files:
        try:
            if os.path.isdir(path):
                shutil.rmtree(path)
                cleaned_count['dirs'] += 1
                log_and_print(f"Removed directory: {path}")
            elif os.path.isfile(path):
                os.remove(path)
                cleaned_count['files'] += 1
                log_and_print(f"Removed file: {path}")
        except Exception as e:
            log_and_print(f"Error removing {path}: {e}", logging.ERROR)
    
    # Clean __pycache__ directories and .pyc files
    for root, dirs, files in os.walk('.'):
        # Skip virtual environment directories
        if 'virtual' in dirs:
            dirs.remove('virtual')
        if '.git' in dirs:
            dirs.remove('.git')
            
        for dir_name in dirs:
            if dir_name == '__pycache__' or dir_name == '.pytest_cache':
                cache_dir = os.path.join(root, dir_name)
                try:
                    shutil.rmtree(cache_dir)
                    cleaned_count['dirs'] += 1
                    log_and_print(f"Removed cache directory: {cache_dir}")
                except Exception as e:
                    log_and_print(f"Error removing cache directory {cache_dir}: {e}", logging.ERROR)
        
        for file in files:
            if file.endswith('.pyc'):
                pyc_file = os.path.join(root, file)
                try:
                    os.remove(pyc_file)
                    cleaned_count['files'] += 1
                    log_and_print(f"Removed .pyc file: {pyc_file}")
                except Exception as e:
                    log_and_print(f"Error removing .pyc file {pyc_file}: {e}", logging.ERROR)
    
    log_and_print(f"Cleanup complete: Removed {cleaned_count['dirs']} directories and {cleaned_count['files']} files")

def calculate_file_hash(file_path):
    """Calculate SHA-256 hash of a file"""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

def verify_file_permissions(file_path):
    """Verify file permissions are correct"""
    try:
        # Check if file is readable
        if not os.access(file_path, os.R_OK):
            log_and_print(f"Warning: File not readable: {file_path}", logging.WARNING)
            return False
        # For executables, check if they're executable
        if file_path.endswith('.exe') and not os.access(file_path, os.X_OK):
            log_and_print(f"Warning: Executable not executable: {file_path}", logging.WARNING)
            return False
        return True
    except Exception as e:
        log_and_print(f"Error checking permissions for {file_path}: {e}", logging.ERROR)
        return False

def verify_build():
    """Verify that all required files are present in the build"""
    log_and_print("Verifying build...")
    
    # Get base paths
    base_dir = os.path.dirname(os.path.abspath(__file__))
    dist_dir = os.path.join(base_dir, 'dist', 'spotscrape')
    internal_dir = os.path.join(dist_dir, '_internal')
    frontend_dir = os.path.join(internal_dir, 'frontend')
    
    # Check executable
    exe_name = 'spotscrape.exe' if sys.platform == 'win32' else 'spotscrape'
    exe_path = os.path.join(dist_dir, exe_name)
    if not os.path.exists(exe_path):
        log_and_print(f"Error: Executable not found at {exe_path}", logging.ERROR)
        return False
    log_and_print(f"✓ Found executable: {exe_path}")
    
    # Required directories
    required_dirs = [
        frontend_dir,
        os.path.join(frontend_dir, 'templates'),
        os.path.join(frontend_dir, 'static'),
        os.path.join(frontend_dir, 'static', 'css'),
        os.path.join(frontend_dir, 'static', 'js')
    ]
    
    # Check directories
    for dir_path in required_dirs:
        if not os.path.exists(dir_path):
            log_and_print(f"Error: Directory not found at {dir_path}", logging.ERROR)
            # List parent directory contents for debugging
            parent_dir = os.path.dirname(dir_path)
            if os.path.exists(parent_dir):
                log_and_print(f"Contents of {parent_dir}:", logging.INFO)
                try:
                    log_and_print(str(os.listdir(parent_dir)), logging.INFO)
                except Exception as e:
                    log_and_print(f"Error listing directory contents: {e}", logging.ERROR)
            return False
        log_and_print(f"✓ Found directory: {dir_path}")
    
    # Required files
    required_files = [
        os.path.join(frontend_dir, 'templates', 'index.html'),
        os.path.join(frontend_dir, 'static', 'css', 'styles.css'),
        os.path.join(frontend_dir, 'static', 'js', 'app.js'),
        os.path.join(internal_dir, 'config.json.example'),
        os.path.join(internal_dir, '.env.example')
    ]
    
    # Check files
    for file_path in required_files:
        if not os.path.exists(file_path):
            log_and_print(f"Error: File not found at {file_path}", logging.ERROR)
            return False
        if not os.access(file_path, os.R_OK):
            log_and_print(f"Error: File not readable at {file_path}", logging.ERROR)
            return False
        log_and_print(f"✓ Found file: {file_path}")
    
    log_and_print("✓ Build verification complete")
    return True

def check_dependencies():
    """Check if all required dependencies are installed"""
    required_packages = [
        'flask',
        'webview',
        'spotipy',
        'playwright',
        'PyInstaller'
    ]
    
    missing_packages = []
    for package in required_packages:
        try:
            __import__(package)
        except ImportError:
            # Convert webview back to pywebview for pip install message
            pip_package = 'pywebview' if package == 'webview' else package
            missing_packages.append(pip_package)
    
    if missing_packages:
        error_msg = (
            f"Missing required dependencies: {', '.join(missing_packages)}\n"
            f"Please install them using: pip install {' '.join(missing_packages)}"
        )
        log_and_print(error_msg, logging.ERROR)
        raise ImportError(error_msg)

def build_standalone(dev_mode=False):
    """Build the standalone executable"""
    try:
        # Check dependencies first
        check_dependencies()
        
        # Install Playwright browser if not already installed
        log_and_print("\nChecking Playwright browser installation...")
        import subprocess
        try:
            subprocess.run([sys.executable, '-m', 'playwright', 'install', 'chromium'], 
                         check=True, capture_output=True)
            log_and_print("Chromium installation completed")
        except subprocess.CalledProcessError as e:
            log_and_print(f"Failed to install Chromium: {e.output.decode() if e.output else str(e)}", logging.ERROR)
            raise
        
        # Log versions of key dependencies using importlib.metadata
        log_and_print("\nDependency Versions:")
        log_and_print(f"Python: {sys.version.split()[0]}")
        log_and_print(f"Flask: {version('flask')}")
        log_and_print(f"PyWebView: {version('pywebview')}")
        log_and_print(f"Spotipy: {version('spotipy')}")
        log_and_print(f"Playwright: {version('playwright')}")
        log_and_print(f"PyInstaller: {version('pyinstaller')}")
        
        # Clean up before building
        cleanup_build_artifacts()

        # Get absolute base path and source paths
        base_path = os.path.abspath(os.path.dirname(__file__))
        src_path = os.path.join(base_path, 'src', 'spotscrape')
        frontend_path = os.path.join(src_path, 'frontend')
        
        # Find Playwright browser path
        import site
        site_packages = site.getsitepackages()[0]
        playwright_path = os.path.join(site_packages, 'playwright')
        browser_path = None
        
        # Look for the browser in common locations
        possible_paths = [
            os.path.join(os.path.expanduser('~'), 'AppData', 'Local', 'ms-playwright'),
            os.path.join(os.path.expanduser('~'), '.cache', 'ms-playwright'),
            os.path.join(os.getcwd(), 'playwright-browsers'),
            os.path.join(os.path.dirname(sys.executable), 'playwright-browsers')
        ]
        
        for base_dir in possible_paths:
            if os.path.exists(base_dir):
                for item in os.listdir(base_dir):
                    if item.startswith('chromium-'):
                        chrome_path = os.path.join(base_dir, item)
                        if os.path.exists(chrome_path):
                            browser_path = chrome_path
                            log_and_print(f"Found browser at: {browser_path}")
                            break
                if browser_path:
                    break
        
        if not browser_path:
            raise FileNotFoundError("Could not find Playwright browser installation")
        
        # Platform-specific settings
        if sys.platform.startswith('win'):
            icon = os.path.join(frontend_path, 'static', 'img', 'icon.ico')
        else:
            icon = None

        # Base PyInstaller arguments
        args = [
            os.path.join(src_path, 'app.py'),
            '--name=spotscrape',
            '--onedir',
            '--clean',
            '--noconfirm'
        ]

        # Add windowed mode in production
        if not dev_mode:
            args.append('--windowed')

        # Add icon if it exists
        if icon and os.path.exists(icon):
            args.append(f'--icon={icon}')
            log_and_print(f"Using icon: {icon}")

        # Add data files with consistent forward slashes
        data_args = [
            f'--add-data={os.path.join(src_path, "frontend").replace(os.sep, "/")};frontend',
            f'--add-data={os.path.join(src_path, "config.json.example").replace(os.sep, "/")};.',
            f'--add-data={os.path.join(src_path, ".env.example").replace(os.sep, "/")};.',
            f'--add-data={browser_path.replace(os.sep, "/")};playwright'  # Add Playwright browser
        ]
        args.extend(data_args)

        # Add hidden imports
        hidden_imports = [
            'flask', 'flask_cors', 'webview', 'playwright', 'spotipy',
            'openai', 'asyncio', 'aiohttp', 'requests', 'json',
            'logging', 'bs4', 'lxml', 'jinja2', 'jinja2.ext',
            'werkzeug', 'werkzeug.serving', 'werkzeug.debug',
            'clr_loader', 'pythonnet'
        ]

        # Add timezone imports if available
        try:
            import tzdata
            hidden_imports.extend(['tzdata', 'zoneinfo'])
        except ImportError:
            log_and_print("Warning: tzdata not found", logging.WARNING)

        # Add Windows-specific imports if available
        if sys.platform.startswith('win'):
            try:
                import win32api
                import win32con
                hidden_imports.extend(['win32api', 'win32con'])
            except ImportError:
                log_and_print("Warning: win32api/win32con not found", logging.WARNING)

        # Add hidden imports to arguments
        for imp in hidden_imports:
            args.extend(['--hidden-import', imp])
            log_and_print(f"Adding hidden import: {imp}")

        # Add debug options in dev mode
        if dev_mode:
            args.extend(['--debug=all', '--log-level=DEBUG'])
        else:
            args.append('--log-level=INFO')

        # Print final PyInstaller command
        log_and_print("\nPyInstaller command:")
        log_and_print(" ".join(args))
        log_and_print("\nBuilding application...")
        
        # Run PyInstaller
        PyInstaller.__main__.run(args)

        # Verify the build
        if not verify_build():
            log_and_print("\nBuild verification failed!", logging.ERROR)
            sys.exit(1)
        log_and_print("\nBuild completed successfully!")
    except Exception as e:
        log_and_print(f"\nError during build: {e}", logging.ERROR)
        sys.exit(1)

if __name__ == '__main__':
    try:
        # Check if --dev flag is passed
        dev_mode = '--dev' in sys.argv
        build_standalone(dev_mode)
    except Exception as e:
        log_and_print(f"Fatal error: {e}", logging.ERROR)
        sys.exit(1) 