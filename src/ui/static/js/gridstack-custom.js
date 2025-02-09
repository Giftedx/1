const grid = GridStack.init({
  selector: '.grid-stack',
  draggable: { handle: '.widget-header' },
  resizable: { handles: 'e, se, s, sw, w' },
});

function saveLayout() {
  const layout = grid.save();
  localStorage.setItem('dashboardLayout', JSON.stringify(layout));
}

function loadLayout() {
  const savedLayout = localStorage.getItem('dashboardLayout');
  if (savedLayout) {
    grid.load(JSON.parse(savedLayout));
  }
}

grid.on('change', saveLayout);
