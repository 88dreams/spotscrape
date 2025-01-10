# SpotScrape

A Python tool for scraping music information from web pages and creating Spotify playlists.

## Features

- Scan webpages for Spotify album links
- Extract artist and album information from music-related content
- Create Spotify playlists from extracted data
- Efficient caching and rate limiting
- Asynchronous operations for better performance
- Modern web interface for easy interaction

## Prerequisites

- Python 3.8 or higher
- Spotify Developer Account
- OpenAI API Key

## Installation Options

### Option 1: Install from PyPI (Recommended)
```bash
pip install spotscrape
```

### Option 2: Install from Source
1. Clone the repository:
```bash
git clone https://github.com/yourusername/spotscrape.git
cd spotscrape
```

2. Create and activate a virtual environment:
```bash
python -m venv venv

# On Windows:
.\venv\Scripts\activate

# On macOS/Linux:
source venv/bin/activate
```

3. Install in development mode:
```bash
pip install -e .
```

### Option 3: Standalone Installation
1. Download the latest release from the releases page
2. Extract the archive
3. Run the installer:
```bash
# Windows
spotscrape-1.0.0-win.exe

# macOS
open spotscrape-1.0.0-mac.dmg

# Linux
chmod +x spotscrape-1.0.0-linux.AppImage
./spotscrape-1.0.0-linux.AppImage
```

## Configuration

1. Create a `.env` file in the project root (or user's home directory):
```env
SPOTIPY_CLIENT_ID=your_spotify_client_id
SPOTIPY_CLIENT_SECRET=your_spotify_client_secret
SPOTIPY_REDIRECT_URI=your_spotify_redirect_uri
OPENAI_API_KEY=your_openai_api_key
```

2. Replace the placeholder values with your actual API credentials:
   - Get Spotify credentials from [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)
   - Get OpenAI API key from [OpenAI Platform](https://platform.openai.com/api-keys)

## Usage

### Command Line Interface
```bash
spotscrape
```

### GUI Application
```bash
spotscrape-gui
```

The application will open in your default web browser, providing a user-friendly interface for:
- Scanning webpages for music content
- Managing Spotify playlists
- Configuring application settings

## Development

- Main branch: Production-ready code
- Development branch: Work in progress features

### Setting up Development Environment
```bash
git clone https://github.com/yourusername/spotscrape.git
cd spotscrape
python -m venv venv
source venv/bin/activate  # or .\venv\Scripts\activate on Windows
pip install -e ".[dev]"
```

## Troubleshooting

### Common Issues

1. **Browser doesn't open automatically**
   - Try running `spotscrape --no-browser` and manually open http://localhost:5000

2. **Authentication Errors**
   - Verify your Spotify and OpenAI credentials in the .env file
   - Check if the redirect URI matches your Spotify app settings

3. **Installation Issues**
   - Make sure you have Python 3.8 or higher installed
   - On Windows, you might need to run PowerShell as administrator
   - On Linux/macOS, you might need to use `sudo pip install spotscrape`

## License

MIT License

## Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request
   
