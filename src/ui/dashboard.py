from flask import Flask, render_template
from src.utils.config import settings
from src.monitoring.metrics import ACTIVE_CONNECTIONS  # Assuming this is updated to reflect active streams

app = Flask(__name__)

@app.route("/")
def index():
    # Replace placeholders with real metrics if available.
    metrics = {
        "active_streams": ACTIVE_CONNECTIONS._value if hasattr(ACTIVE_CONNECTIONS, "_value") else "N/A",
        "system_health": "OK"  # This may be replaced with actual health check results.
    }
    return render_template("dashboard.html", metrics=metrics)

@app.route("/metrics")
def metrics_endpoint():
    # Return metrics data as JSON for external monitoring integrations.
    # In production, consider using Prometheus' /metrics endpoint.
    metrics = {
        "active_streams": ACTIVE_CONNECTIONS._value if hasattr(ACTIVE_CONNECTIONS, "_value") else "N/A",
        "system_health": "OK"
    }
    return metrics

def run_dashboard():
    app.run(host="0.0.0.0", port=8080, debug=False)

if __name__ == "__main__":
    run_dashboard()
