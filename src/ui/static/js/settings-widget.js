function createSettingsWidget() {
  const element = document.createElement('div');
  element.classList.add('grid-stack-item');
  element.setAttribute('gs-id', 'settings');

  element.innerHTML = `
        <div class="grid-stack-item-content card metric-card">
            <div class="widget-header card-header">
                Settings
            </div>
            <div class="card-body">
                <label for="theme-selector">Theme:</label>
                <select class="form-control" id="widget-theme-selector">
                    <option value="default">Default</option>
                    <option value="dark">Dark</option>
                    <option value="light">Light</option>
                </select>
            </div>
        </div>
    `;

  // Set the initial theme in the selector
  const themeSelector = element.querySelector('#widget-theme-selector');
  themeSelector.value = themeController.getCurrentTheme();

  themeSelector.addEventListener('change', async (event) => {
    const themeName = event.target.value;
    await themeController.loadTheme(themeName);
  });

  return element;
}
