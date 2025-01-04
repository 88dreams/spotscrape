# SpotScrape

SpotScrape is a powerful tool that helps you discover and collect Spotify tracks from web pages. It can either scan for direct Spotify links or use GPT to analyze the content and find music references.

## Features

- Scan web pages for Spotify track links
- Use GPT to analyze web content and identify music references
- Create Spotify playlists from discovered tracks
- Web interface for easy interaction
- Real-time progress updates
- Command-line interface for automation

## Prerequisites

- Python 3.8 or higher
- Spotify Developer Account
- OpenAI API Key (for GPT scanning)
- Modern web browser (for web interface)

## Installation

1. Clone the repository:
```bash
git clone https://github.com/88dreams/spotscrape.git
cd spotscrape
```

2. Create and activate a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Install Playwright browsers:
```bash
playwright install
```

## Configuration

1. Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

2. Edit `.env` with your credentials:
```
# Spotify API Credentials
SPOTIPY_CLIENT_ID=your_spotify_client_id_here
SPOTIPY_CLIENT_SECRET=your_spotify_client_secret_here
SPOTIPY_REDIRECT_URI=http://localhost:8888/callback

# OpenAI API Key
OPENAI_API_KEY=your_openai_api_key_here
```

## Usage

### Web Interface

1. Start the web server:
```bash
cd web
python app.py
```

2. Open your browser and navigate to `http://localhost:5000`

3. Use the web interface to:
   - Scan web pages for Spotify tracks
   - View real-time scanning progress
   - Create playlists from scanned tracks
   - Manage your JSON files

### Command Line Interface

For command-line usage, run:
```bash
python spotscrape.py
```

Follow the interactive prompts to:
1. Choose scanning method (URL or GPT)
2. Enter the webpage URL
3. Create a playlist (optional)

## Development

1. Create a new feature branch:
```bash
git checkout -b feature/your-feature-name
```

2. Make your changes and commit:
```bash
git add .
git commit -m "Description of your changes"
```

3. Push to GitHub:
```bash
git push origin feature/your-feature-name
```

4. Create a Pull Request to merge into the development branch

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Contributing

1. Fork the repository
2. Create your feature branch
3. Commit your changes
4. Push to your fork
5. Submit a Pull Request
   
