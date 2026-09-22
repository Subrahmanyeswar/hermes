import time
from flask import Blueprint

# Create a blueprint for the health check endpoint
health_bp = Blueprint('health', __name__)

@health_bp.route('/health')
def get_health_status():
    # Get current time for uptime calculation (dummy value for simplicity)
    current_time = time.time()
    # Uptime is calculated as the current time in seconds since epoch (not real system uptime)
    uptime_seconds = int(current_time)
    return {
        'status': 'ok',
        'version': '1.0.0',
        'uptime': uptime_seconds
    }