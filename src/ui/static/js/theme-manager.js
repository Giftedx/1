class ThemeController {
  constructor() {
    this.themeStyle = document.getElementById('theme-style');
  }

  async loadTheme(themeName) {
    try {
      const themePath = `/static/css/themes/${themeName}.css`;
      this.themeStyle.href = themePath;
      localStorage.setItem('theme', themeName);
    } catch (error) {
      console.error('Failed to load theme:', error);
    }
  }

  getCurrentTheme() {
    return localStorage.getItem('theme') || 'default';
  }
}

const themeController = new ThemeController();
