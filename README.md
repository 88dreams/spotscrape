# SpotScrape

A Python tool for scraping music information from web pages and creating Spotify playlists.

## Features

- Scan webpages for Spotify album links
- Extract artist and album information from music-related content
- Create Spotify playlists from extracted data
- Efficient caching and rate limiting
- Asynchronous operations for better performance

## Prerequisites

- Python 3.8 or higher
- Spotify Developer Account
- OpenAI API Key

## Installation

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

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Install Playwright browsers:
```bash
playwright install
```

## Configuration

1. Create a `.env` file in the project root:
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

Run the script:
```bash
python spotscrape.py
```

Choose from the following options:
1. Scan webpage for Spotify links
2. Scan webpage for music content
3. Create Spotify playlist from JSON
4. Exit

## Development

- Main branch: Production-ready code
- Development branch: Work in progress features

## License

MIT License

## Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request
   
