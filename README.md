# SpotScrape

SpotScrape is a modern desktop application that helps you discover and create Spotify playlists from web content. It uses both direct URL scanning and AI-powered content analysis to find and organize music.

## Features

- 🎵 Scan web pages for Spotify album links
- 🤖 AI-powered music content extraction
- 📝 Create Spotify playlists automatically
- 🎨 Modern, user-friendly interface
- 🔄 Support for various music review sites and blogs

## Prerequisites

- Python 3.8 or higher
- Spotify Developer Account
- OpenAI API Key (for AI-powered scanning)
- Git (for cloning the repository)

## Setup Instructions

1. **Clone the Repository**
   ```bash
   git clone https://github.com/88dreams/spotscrape.git
   cd spotscrape
   ```

2. **Create and Activate Virtual Environment**
   ```bash
   # Windows
   python -m venv venv
   .\venv\Scripts\activate

   # macOS/Linux
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure API Keys**
   - Copy the example configuration file:
     ```bash
     cp config.json.example config.json
     ```
   - Edit `config.json` and add your API keys:
     - Spotify API credentials (from [Spotify Developer Dashboard](https://developer.spotify.com/dashboard))
     - OpenAI API key (from [OpenAI Platform](https://platform.openai.com/api-keys))

5. **Spotify Developer Setup**
   1. Go to [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)
   2. Create a new application
   3. Add `http://localhost:8888/callback` to the Redirect URIs
   4. Copy the Client ID and Client Secret to your `config.json`

## Running the Application

1. **Start the Application**
   ```bash
   # From the project root directory
   python -m spotscrape
   ```

2. **First-Time Setup**
   - On first run, you'll need to authorize the application with Spotify
   - A browser window will open for authentication
   - After authorizing, you can close the browser window

## Usage Guide

### URL Scanning
1. Enter a URL containing Spotify album links
2. Click "Scan URL"
3. Review the found albums
4. Select albums to include in playlist
5. Click "Create Playlist"

### AI-Powered Scanning
1. Enter a URL containing music content
2. Select "GPT Scan" option
3. Wait for the AI to analyze the content
4. Review the found albums
5. Create your playlist

### Playlist Creation Options
- Include all tracks from albums
- Include only the most popular track
- Include only the first track
- Customize playlist name and description

## Troubleshooting

### Common Issues

1. **Application Won't Start**
   - Check if all dependencies are installed
   - Verify `config.json` exists and is properly formatted
   - Ensure Python version is 3.8 or higher

2. **Authentication Errors**
   - Verify Spotify API credentials
   - Check redirect URI in Spotify Developer Dashboard
   - Delete `.cache` file and try again

3. **Scanning Issues**
   - Check internet connection
   - Verify URL is accessible
   - Ensure OpenAI API key is valid (for GPT scanning)

### Error Logs
- Check logs in `src/spotscrape/logs/` directory
- Debug logs are named `spot-debug-YYYYMMDD.log`
- Spotify-specific logs are in `spot-spotify-YYYYMMDD.log`

## Development Setup

For developers who want to contribute:

1. **Fork and Clone**
   ```bash
   git clone https://github.com/yourusername/spotscrape.git
   cd spotscrape
   ```

2. **Create Development Branch**
   ```bash
   git checkout -b feature/your-feature-name
   ```

3. **Install Development Dependencies**
   ```bash
   pip install -r requirements-dev.txt
   ```

4. **Run Tests**
   ```bash
   pytest
   ```

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgments

- Built with [Spotipy](https://spotipy.readthedocs.io/)
- UI powered by [Flask](https://flask.palletsprojects.com/) and [pywebview](https://pywebview.flowrl.com/)
- AI features powered by [OpenAI](https://openai.com/)
   
