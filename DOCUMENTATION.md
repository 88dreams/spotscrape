# SpotScrape Documentation

## Project Overview
SpotScrape is a web application that extracts and processes music-related content from web pages, integrating with Spotify for playlist management and OpenAI's GPT for content analysis.

## Architecture

### Core Components

#### Frontend Layer
- **Technology**: Flask-based web application
- **Location**: `src/spotscrape/frontend/`
- **Key Files**:
  - `templates/index.html`: Main UI template
  - `static/js/app.js`: Frontend logic
  - `static/css/styles.css`: Styling

#### Backend Services
1. **Client Management (`ClientManager`)**
   - Singleton pattern for API client management
   - Handles Spotify and OpenAI client instances
   - Manages session handling and cleanup

2. **Spotify Integration (`SpotifySearchManager`)**
   - Playlist creation and modification
   - Music search and metadata retrieval
   - OAuth authentication handling

3. **Web Scraping (`WebContentExtractor`)**
   - Playwright-based web content extraction
   - Async operation support
   - Browser path management

4. **Content Processing (`ContentProcessor`)**
   - Music content analysis
   - Data transformation and normalization
   - Integration with GPT for content understanding

### File Structure
```
spotscrape/
├── src/spotscrape/
│   ├── app.py           # Main Flask application
│   ├── core.py          # Core functionality
│   ├── utils.py         # Utility functions
│   └── frontend/
│       ├── static/
│       │   ├── css/
│       │   └── js/
│       └── templates/
├── dist/                # Distribution builds
├── logs/                # Application logs
├── tests/              # Test suite
└── build_standalone.py # Build script
```

### Key Features
1. **Web Page Analysis**
   - Music content extraction
   - Spotify link detection
   - Intelligent content parsing

2. **Spotify Integration**
   - Playlist management
   - Track search and matching
   - OAuth authentication

3. **GPT-Powered Analysis**
   - Content understanding
   - Music recommendation
   - Context-aware processing

4. **System Features**
   - Rate limiting
   - Request caching
   - Comprehensive logging
   - Error handling

## Configuration

### Environment Variables
Required in `.env` file:
- `SPOTIPY_CLIENT_ID`: Spotify API client ID
- `SPOTIPY_CLIENT_SECRET`: Spotify API client secret
- `SPOTIPY_REDIRECT_URI`: Spotify OAuth redirect URI
- `OPENAI_API_KEY`: OpenAI API key

### Logging System
- Location: `logs/` directory
- File Types:
  - `spot-main-*.log`: Main application flow
  - `spot-spotify-*.log`: Spotify operations
  - `spot-debug-*.log`: Debug information
  - `spot-gpt-*.log`: GPT operations

## Development

### Build Process
- Uses PyInstaller for standalone builds
- Configuration in `build_standalone.py`
- Handles browser packaging for Playwright

### Testing
- Test suite in `tests/` directory
- Uses pytest framework
- Configuration in `pytest.ini`

### Error Handling
- Comprehensive try-catch blocks
- Graceful degradation
- User-friendly error messages
- Detailed logging for debugging

## Performance Features

### Caching
- Request caching with TTL
- Spotify API response caching
- Memory-efficient cache management

### Rate Limiting
- API call rate limiting
- Configurable limits per service
- Automatic retry mechanisms

## Security

### API Security
- Secure credential management
- OAuth flow implementation
- Environment variable protection

### Data Protection
- Secure file operations
- Safe path handling
- Input validation

## Future Development
The modular architecture allows for easy extension of functionality through:
1. New service integrations
2. Additional content processors
3. Enhanced analysis capabilities
4. UI/UX improvements

## Maintenance

### Logs
- Regular log rotation
- Debug logging for development
- Production logging configuration

### Updates
- Package version management
- Dependency updates
- API compatibility checks 