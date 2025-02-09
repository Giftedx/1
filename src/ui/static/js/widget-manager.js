const widgetRegistry = {
  activityFeed: {
    id: 'activityFeed',
    title: 'Activity Feed',
    w: 4,
    h: 4,
    content: '<div class="activity-feed">Activity data here</div>', // Example content
    initialize: (element) => {
      console.log('Initializing activity feed');
    },
    update: (data) => {
      console.log('Updating activity feed with data:', data);
    },
  },
  requestQueue: {
    id: 'requestQueue',
    title: 'Media Requests',
    w: 4,
    h: 4,
    content: '<div class="request-queue">Request queue data here</div>', // Example content
    initialize: (element) => {
      console.log('Initializing request queue');
    },
    update: (data) => {
      console.log('Updating request queue with data:', data);
    },
  },
  clock: {settings: {
    id: 'clock',    id: 'settings',
    title: 'Clock',
    w: 2,
    h: 2,
    content: '<div id="clock-time"></div>',s content here</div>', // Example content
    initialize: (element) => {    initialize: (element) => {
      function updateTime() {ializing settings');
        const now = new Date();
        const timeString = now.toLocaleTimeString();
        element.querySelector('#clock-time').textContent = timeString;
      }
      updateTime();
      setInterval(updateTime, 1000);
    },
  },idget) {
  settings: {= document.createElement('div');
    id: 'settings',
    title: 'Settings',', widget.id);
    w: 2,
    h: 2,
    content: `em-content card metric-card">
            <div>lass="widget-controls btn-group">
                <label for="theme-selector">Theme:</label>  <button class="btn btn-sm btn-light" onclick="pinWidget('${widget.id}')">
                <select class="form-control" id="widget-theme-selector">              <i class="bi bi-pin"></i>
                    <option value="default">Default</option>utton>
                    <option value="dark">Dark</option>             <button class="btn btn-sm btn-light" onclick="hideWidget('${widget.id}')">
                    <option value="light">Light</option>                  <i class="bi bi-x"></i>
                </select>
            </div>   </div>
        `,
    initialize: (element) => {
      const themeSelector = element.querySelector('#widget-theme-selector');          </div>
      themeSelector.value = themeController.getCurrentTheme();ss="card-body">
.content}
      themeSelector.addEventListener('change', async (event) => {
        const themeName = event.target.value;
        await themeController.loadTheme(themeName);
      });urn element;
    },}
  },
};etId) {
tionality here
function createWidget(widget) {sole.log(`Pinning widget: ${widgetId}`);
  const element = document.createElement('div');  // You might want to save the state to local storage or a server
  element.classList.add('grid-stack-item');
  element.setAttribute('gs-id', widget.id);

  element.innerHTML = `ere
      <div class="grid-stack-item-content card metric-card">dgetId}`);
          <div class="widget-controls btn-group">ack-item[gs-id="${widgetId}"]`);
              <button class="btn btn-sm btn-light" onclick="pinWidget('${widget.id}')">
                  <i class="bi bi-pin"></i>
              </button>ces
              <button class="btn btn-sm btn-light" onclick="hideWidget('${widget.id}')">
                  <i class="bi bi-x"></i>
              </button>
          </div>
          <div class="widget-header card-header">ion loadUserPreferences() {
              ${widget.title} {
          </div>= await fetch('/api/preferences');
          <div class="card-body">
              ${widget.content}
          </div>
      </div>
  `;   await themeController.loadTheme(prefs.theme);
  return element;   } else {
}      await themeController.loadTheme('default');









































}  }    loadLayout(); // Load layout from local storage    await themeController.loadTheme('default');    // Fallback to default theme and layout if loading fails    console.error('Failed to load user preferences:', error);  } catch (error) {    }        });          }            }              widget.initialize(widgetElement);            if (widget.initialize) {            grid.addWidget(widgetElement, widget);            const widgetElement = createWidget(widget);          if (widget) {          const widget = widgetRegistry[widgetId];        .forEach(([widgetId]) => {        .filter(([_, enabled]) => enabled)      Object.entries(prefs.widgets)    if (prefs.widgets) {    // Initialize enabled widgets    }      grid.load(prefs.layout);    if (prefs.layout) {    // Apply layout    }      await themeController.loadTheme('default');    } else {      await themeController.loadTheme(prefs.theme);    if (prefs.theme) {    // Apply theme    const prefs = await response.json();    const response = await fetch('/api/preferences');  try {async function loadUserPreferences() {    }

    // Apply layout
    if (prefs.layout) {
      grid.load(prefs.layout);
    }

    // Initialize enabled widgets
    if (prefs.widgets) {
      Object.entries(prefs.widgets)
        .filter(([_, enabled]) => enabled)
        .forEach(([widgetId]) => {
          const widget = widgetRegistry[widgetId];
          if (widget) {
            const widgetElement = createWidget(widget);
            grid.addWidget(widgetElement, widget);
            if (widget.initialize) {
              widget.initialize(widgetElement);
            }
          }
        });
    }
  } catch (error) {
    console.error('Failed to load user preferences:', error);
    // Fallback to default theme and layout if loading fails
    await themeController.loadTheme('default');
    loadLayout(); // Load layout from local storage
  }
}

function saveWidgetPreferences() {
  const widgets = {};
  Object.keys(widgetRegistry).forEach((widgetId) => {
    const element = document.querySelector(`.grid-stack-item[gs-id="${widgetId}"]`);
    widgets[widgetId] = !!element; // Check if the widget is currently in the grid
  });
  localStorage.setItem('widgetPreferences', JSON.stringify(widgets));
}
