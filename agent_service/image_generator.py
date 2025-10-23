"""
Character Image Generation using DALL-E 3

Generates anime-style profile pictures for characters based on their traits.
Images are saved to local filesystem for serving via web server.
"""

import os
import requests
from pathlib import Path
from typing import Dict, Any, Optional
import structlog
from openai import OpenAI
from datetime import datetime

logger = structlog.get_logger()

# Configure image storage
IMAGES_DIR = Path(os.getenv("IMAGES_DIR", "/var/www/love-diary-images"))
CDN_BASE_URL = os.getenv("CDN_BASE_URL", "http://localhost:8000")


class ImageGenerator:
    """Generates and stores character profile images"""

    def __init__(self):
        """Initialize OpenAI client"""
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            logger.warning("OPENAI_API_KEY not set - image generation will fail")

        self.client = OpenAI(api_key=api_key) if api_key else None

        # Ensure images directory exists
        IMAGES_DIR.mkdir(parents=True, exist_ok=True)
        logger.info(
            "image_generator_initialized",
            images_dir=str(IMAGES_DIR),
            cdn_base_url=CDN_BASE_URL
        )

    def _build_prompt(self, character_data: Dict[str, Any]) -> str:
        """
        Build DALL-E 3 prompt from character traits

        Args:
            character_data: Character traits from blockchain (with integer IDs)

        Returns:
            Formatted prompt for anime-style portrait generation
        """
        # Import mappings from character_agent
        from .character_agent import GENDER_MAP, OCCUPATION_NAMES, PERSONALITY_NAMES, ORIENTATION_MAP

        # Get character name
        name = character_data.get("name", "Character")

        # Convert IDs to readable strings
        gender_id = character_data.get("gender", 0)
        occupation_id = character_data.get("occupationId", 0)
        personality_id = character_data.get("personalityId", 0)
        orientation_id = character_data.get("sexualOrientation", 0)

        gender = GENDER_MAP.get(gender_id, "Person").lower()
        occupation = OCCUPATION_NAMES[occupation_id % len(OCCUPATION_NAMES)].lower()
        personality = PERSONALITY_NAMES[personality_id % len(PERSONALITY_NAMES)].lower()
        orientation = ORIENTATION_MAP.get(orientation_id, "Straight").lower()

        # Calculate age from birth year or timestamp
        birth_year = character_data.get("birthYear")
        if birth_year:
            age = datetime.now().year - birth_year
        else:
            # Fallback: try birthTimestamp
            birth_timestamp = character_data.get("birthTimestamp")
            if birth_timestamp:
                birth_date = datetime.fromtimestamp(birth_timestamp)
                age = datetime.now().year - birth_date.year
            else:
                age = 25  # Default

        # Clamp age to reasonable range
        age = max(18, min(35, age))

        prompt = f"""
High-quality anime portrait of {name}, a {age}-year-old {gender} {occupation}.
Personality: {personality}.
Sexual orientation: {orientation}.

Art style: Professional manga/anime character illustration, detailed facial features,
expressive eyes with highlights, clean linework, soft shading, vibrant colors.

Composition: Upper body shot, looking at camera, gentle smile, clean solid color background.

Quality: High detail, sharp focus, professional character design.

IMPORTANT: No text, no watermarks, no labels, no words, no preview images. Pure character portrait only.
"""
        return prompt.strip()

    async def generate_character_image(
        self,
        character_id: int,
        character_data: Dict[str, Any]
    ) -> Optional[str]:
        """
        Generate and save character profile image

        Args:
            character_id: Character NFT token ID
            character_data: Character traits dict

        Returns:
            Image URL path (e.g., "/character-images/123.png") or None if failed
        """
        if not self.client:
            logger.error(
                "image_generation_skipped_no_api_key",
                character_id=character_id
            )
            return None

        try:
            # Build prompt
            prompt = self._build_prompt(character_data)

            logger.info(
                "generating_character_image",
                character_id=character_id,
                character_data=character_data,
                full_prompt=prompt
            )

            # Generate image with DALL-E 3
            response = self.client.images.generate(
                model="dall-e-3",
                prompt=prompt,
                size="1024x1024",
                quality="standard",
                n=1
            )

            # Get image URL from response
            image_url = response.data[0].url

            logger.info(
                "image_generated_by_openai",
                character_id=character_id,
                image_url=image_url[:50] + "..."
            )

            # Download image
            image_response = requests.get(image_url, timeout=30)
            image_response.raise_for_status()
            image_data = image_response.content

            # Save to filesystem
            file_path = IMAGES_DIR / f"{character_id}.png"
            with open(file_path, 'wb') as f:
                f.write(image_data)

            # Return URL path for serving
            url_path = f"/character-images/{character_id}.png"

            logger.info(
                "character_image_saved",
                character_id=character_id,
                file_path=str(file_path),
                file_size_kb=len(image_data) // 1024,
                url_path=url_path
            )

            return url_path

        except Exception as e:
            logger.error(
                "image_generation_failed",
                character_id=character_id,
                error=str(e),
                error_type=type(e).__name__
            )
            return None


# Singleton instance
_generator: Optional[ImageGenerator] = None


def get_image_generator() -> ImageGenerator:
    """Get or create singleton ImageGenerator instance"""
    global _generator
    if _generator is None:
        _generator = ImageGenerator()
    return _generator
