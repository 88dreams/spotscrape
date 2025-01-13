import os
import sys
import json
from pathlib import Path
import logging
import webview
from typing import Dict, Any, Optional
from .config_manager import ConfigManager

logger = logging.getLogger('spot-setup')

class SetupHandler:
    """Handles first-run setup and configuration"""
    
    def __init__(self):
        self.config_manager = ConfigManager()
        self.window = None
    
    def check_first_run(self) -> bool:
        """Check if this is the first run and configuration is needed"""
        return not self.config_manager.is_configured()
    
    def create_setup_window(self):
        """Create and show the setup window"""
        html_content = self._get_setup_html()
        
        # Create a temporary HTML file in the user's config directory
        config_dir = Path.home() / '.spotscrape'
        config_dir.mkdir(parents=True, exist_ok=True)
        setup_html = config_dir / 'setup.html'
        
        with open(setup_html, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        # Create the setup window
        self.window = webview.create_window(
            'SpotScrape Setup',
            url=setup_html.as_uri(),
            width=800,
            height=600,
            resizable=True,
            min_size=(600, 400)
        )
        
        # Expose the save_config function to JavaScript
        self.window.expose(self.save_config)
        
        # Start the window
        webview.start(debug=False)
        
        # Clean up the temporary file
        setup_html.unlink()
    
    def _get_setup_html(self) -> str:
        """Generate the setup HTML content"""
        return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SpotScrape Setup</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            line-height: 1.6;
            margin: 0;
            padding: 20px;
            background-color: #f5f5f5;
        }
        .container {
            max-width: 600px;
            margin: 0 auto;
            background-color: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        h1 {
            color: #333;
            text-align: center;
            margin-bottom: 30px;
        }
        .form-group {
            margin-bottom: 20px;
        }
        label {
            display: block;
            margin-bottom: 5px;
            color: #555;
            font-weight: 500;
        }
        input[type="text"] {
            width: 100%;
            padding: 8px;
            border: 1px solid #ddd;
            border-radius: 4px;
            font-size: 14px;
        }
        .help-text {
            font-size: 12px;
            color: #666;
            margin-top: 4px;
        }
        button {
            background-color: #1DB954;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 4px;
            cursor: pointer;
            width: 100%;
            font-size: 16px;
        }
        button:hover {
            background-color: #1ed760;
        }
        .error {
            color: #dc3545;
            font-size: 14px;
            margin-top: 4px;
            display: none;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>SpotScrape Setup</h1>
        <form id="setupForm">
            <div class="form-group">
                <label for="clientId">Spotify Client ID</label>
                <input type="text" id="clientId" required>
                <div class="help-text">From your Spotify Developer Dashboard</div>
                <div class="error" id="clientIdError"></div>
            </div>
            
            <div class="form-group">
                <label for="clientSecret">Spotify Client Secret</label>
                <input type="text" id="clientSecret" required>
                <div class="help-text">From your Spotify Developer Dashboard</div>
                <div class="error" id="clientSecretError"></div>
            </div>
            
            <div class="form-group">
                <label for="openaiKey">OpenAI API Key</label>
                <input type="text" id="openaiKey" required>
                <div class="help-text">From your OpenAI Platform dashboard</div>
                <div class="error" id="openaiKeyError"></div>
            </div>
            
            <button type="submit">Save Configuration</button>
        </form>
    </div>
    
    <script>
        document.getElementById('setupForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            
            const config = {
                spotify: {
                    client_id: document.getElementById('clientId').value.trim(),
                    client_secret: document.getElementById('clientSecret').value.trim(),
                    redirect_uri: 'http://localhost:8888/callback'
                },
                openai: {
                    api_key: document.getElementById('openaiKey').value.trim()
                }
            };
            
            try {
                await pywebview.api.save_config(config);
                alert('Configuration saved successfully!');
                window.close();
            } catch (error) {
                alert('Error saving configuration: ' + error);
            }
        });
    </script>
</body>
</html>
"""
    
    def save_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Save the configuration and return the result"""
        try:
            # Validate the configuration
            if not self._validate_config(config):
                return {'success': False, 'error': 'Invalid configuration'}
            
            # Save the configuration
            self.config_manager.save_config(config)
            return {'success': True}
            
        except Exception as e:
            logger.error(f"Error saving configuration: {e}")
            return {'success': False, 'error': str(e)}
    
    def _validate_config(self, config: Dict[str, Any]) -> bool:
        """Validate the configuration"""
        try:
            spotify = config.get('spotify', {})
            openai = config.get('openai', {})
            
            # Check required fields
            if not all([
                spotify.get('client_id'),
                spotify.get('client_secret'),
                openai.get('api_key')
            ]):
                return False
            
            return True
        except Exception:
            return False 