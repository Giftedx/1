from typing import Dict, Any
from dataclasses import dataclass

@dataclass
class Theme:
    name: str
    colors: Dict[str, str]
    effects: Dict[str, Any]
    fonts: Dict[str, str]

class ThemeManager:
    THEMES = {
        'default': Theme(
            name='Default',
            colors={
                'primary': '#4fc3f7',
                'secondary': '#f64f59',
                'background': 'rgba(255, 255, 255, 0.95)',
                'text': '#2d3748',
                'accent': '#c471ed'
            },
            effects={
                'blur': '5px',
                'shadow': '0 4px 8px rgba(0,0,0,0.2)',
                'transition': 'all 0.4s cubic-bezier(0.4, 0, 0.2, 1)'
            },
            fonts={
                'heading': '"Inter", sans-serif',
                'body': '"Roboto", sans-serif',
                'mono': '"Fira Code", monospace'
            }
        ),
        'cyberpunk': Theme(
            name='Cyberpunk',
            colors={
                'primary': '#00ff9f',
                'secondary': '#ff00ff',
                'background': 'rgba(10, 10, 30, 0.95)',
                'text': '#00ff9f',
                'accent': '#00ffff'
            },
            effects={
                'blur': '10px',
                'shadow': '0 0 20px rgba(0,255,159,0.3)',
                'transition': 'all 0.3s cubic-bezier(0.2, 0.8, 0.2, 1)'
            },
            fonts={
                'heading': '"Cyberpunk", sans-serif',
                'body': '"Share Tech Mono", monospace',
                'mono': '"Source Code Pro", monospace'
            }
        )
    }

    @classmethod
    def get_theme(cls, name: str) -> Theme:
        return cls.THEMES.get(name, cls.THEMES['default'])

    @classmethod
    def get_theme_css(cls, theme: Theme) -> str:
        return f"""
        :root {{
            --primary-color: {theme.colors['primary']};
            --secondary-color: {theme.colors['secondary']};
            --background-color: {theme.colors['background']};
            --text-color: {theme.colors['text']};
            --accent-color: {theme.colors['accent']};
            --blur-effect: {theme.effects['blur']};
            --box-shadow: {theme.effects['shadow']};
            --transition: {theme.effects['transition']};
            --font-heading: {theme.fonts['heading']};
            --font-body: {theme.fonts['body']};
            --font-mono: {theme.fonts['mono']};
        }}
        """
