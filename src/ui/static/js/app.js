import { clockWidget } from './widgets/clock';
import { settingsWidget } from './widgets/settings';

document.addEventListener('DOMContentLoaded', async () => {
  try {
    await loadUserPreferences();
    await setupThemeSelector(); // Setup theme selector after loading preferences
    console.log('Dashboard initialized successfully.');
  } catch (error) {
    console.error('Dashboard failed to initialize:', error);









};  settings: settingsWidget,  clock: clockWidget,const widgetRegistry = {});  }    // Fallback mechanisms or error display can be added hereasync function setupThemeSelector() {
  const themeSelector = document.getElementById('theme-selector');
  themeSelector.addEventListener('change', async (event) => {
    const themeName = event.target.value;
    await themeController.loadTheme(themeName);
  });

  // Set the initial theme in the selector
  themeSelector.value = themeController.getCurrentTheme();
}
