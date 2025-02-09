function createClockWidget() {
  const element = document.createElement('div');
  element.classList.add('grid-stack-item');
  element.setAttribute('gs-id', 'clock');

  element.innerHTML = `
        <div class="grid-stack-item-content card metric-card">
            <div class="widget-header card-header">
                Clock
            </div>
            <div class="card-body">
                <div id="clock-time" style="font-size: 2rem; text-align: center;"></div>
            </div>
        </div>
    `;

  // Function to update the time
  function updateTime() {
    const now = new Date();
    const timeString = now.toLocaleTimeString();
    document.getElementById('clock-time').textContent = timeString;
  }

  // Update the time every second
  setInterval(updateTime, 1000);

  // Call updateTime once to set the initial time
  updateTime();

  return element;
}
