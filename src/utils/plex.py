import requests
import logging

logger = logging.getLogger(__name__)

class PlexClient:
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url
        self.token = token

    def get_media_url(self, title: str) -> str:
        try:
            headers = {
                'X-Plex-Token': self.token
            }
            response = requests.get(f"{self.base_url}/library/sections/all/search?query={title}", headers=headers)
            response.raise_for_status()
            results = response.json()['MediaContainer']['Metadata']
            if not results:
                return None
            media_key = results[0]['key']
            return f"{self.base_url}{media_key}?X-Plex-Token={self.token}"
        except Exception as e:
            logger.error(f"Error fetching media URL: {str(e)}", exc_info=True)
            return None
