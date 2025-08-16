from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sse_starlette import EventSourceResponse
from utils import SensorData, recent_readings, get_sensor_dataframe, get_statistical_summary, detect_anomalies
from chart_utils import ChartFactory
import json
import asyncio
import arel
import os
import time
from datetime import datetime
from loguru import logger

# Configure Loguru for production logging
logger.add(
    "logs/app_{time}.log",
    rotation="1 day",
    retention="7 days",
    level="INFO",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}",
    backtrace=True,
    diagnose=True
)

# Add console logging for development
if os.getenv("DEBUG"):
    logger.add(
        lambda msg: print(msg, end=""),
        level="DEBUG",
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | <level>{message}</level>",
        colorize=True
    )

app = FastAPI(debug=True)
templates = Jinja2Templates(directory="templates")
sensor = SensorData()
chart_factory = ChartFactory()

logger.info("FastAPI sensor dashboard starting up")

# Performance monitoring
class DashboardMetrics:
    def __init__(self):
        self.connection_count = 0
        self.chart_generation_times = []
        self.total_requests = 0
    
    def track_connection(self):
        self.connection_count += 1
        logger.info(f"New SSE connection established. Active connections: {self.connection_count}")
    
    def track_disconnection(self):
        self.connection_count = max(0, self.connection_count - 1)
        logger.info(f"SSE connection closed. Active connections: {self.connection_count}")
    
    def track_chart_generation(self, duration: float):
        self.chart_generation_times.append(duration)
        if duration > 1.0:  # Slow chart generation
            logger.warning(f"Slow chart generation detected: {duration:.2f}s")
        else:
            logger.debug(f"Chart generated in {duration:.3f}s")
    
    def track_request(self):
        self.total_requests += 1
        if self.total_requests % 100 == 0:  # Log every 100 requests
            logger.info(f"Total requests served: {self.total_requests}")

metrics = DashboardMetrics()

# Hot reload magic for development
# if os.getenv("DEBUG"):
#     logger.debug("Setting up hot reload for development")
#     hot_reload = arel.HotReload(paths=["."])
#     app.add_websocket_route("/hot-reload", route=hot_reload)
#     app.add_event_handler("startup", hot_reload.startup)
#     app.add_event_handler("shutdown", hot_reload.shutdown)
#     templates.env.globals["DEBUG"] = True
#     templates.env.globals["hot_reload"] = hot_reload

@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    """Main dashboard with real-time Plotly charts"""
    metrics.track_request()
    logger.info(f"Dashboard accessed from {request.client.host}")
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/stream")
async def stream_sensor_data():
    """Stream live sensor data via SSE"""
    metrics.track_connection()
    logger.info("Starting SSE stream for sensor data")
    
    async def event_generator():
        try:
            while True:
                # Generate new sensor reading
                data = sensor.generate_reading()
                recent_readings.append(data)
                
                logger.debug(f"Generated sensor reading: temp={data['temperature']}°C, status={data['status']}")
                
                # Send sensor update
                yield {
                    "event": "sensor_update",
                    "data": json.dumps(data)
                }
                
                await asyncio.sleep(3)  # Update every 3 seconds
                
        except asyncio.CancelledError:
            logger.info("SSE connection cancelled by client")
            metrics.track_disconnection()
        except Exception as e:
            logger.error(f"Error in SSE stream: {e}")
            metrics.track_disconnection()
            raise
    
    return EventSourceResponse(event_generator())

@app.get("/charts")
async def get_charts(request: Request):
    """Generate all Plotly charts as HTML"""
    start_time = time.time()
    metrics.track_request()
    
    logger.debug("Starting chart generation")
    
    try:
        df = get_sensor_dataframe()
        anomalies = detect_anomalies()
        
        logger.debug(f"Processing {len(df)} sensor readings for chart generation")
        
        # Generate all charts
        charts_html = {
            'timeseries': chart_factory.create_time_series_chart(df),
            'status': chart_factory.create_status_distribution(df),
            'correlation': chart_factory.create_correlation_heatmap(df),
            'anomalies': chart_factory.create_anomaly_highlights(df, anomalies)
        }
        
        # Get statistics
        stats = get_statistical_summary()
        
        duration = time.time() - start_time
        metrics.track_chart_generation(duration)
        
        logger.info(f"Charts generated successfully in {duration:.3f}s")
        
        return templates.TemplateResponse("charts.html", {
            "request": request,
            "charts": charts_html,
            "stats": stats,
            "anomaly_count": len(anomalies)
        })
        
    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"Chart generation failed after {duration:.3f}s: {e}")
        raise

@app.get("/sensor-data")
async def get_sensor_data(request: Request):
    """Get current sensor reading for display"""
    metrics.track_request()
    
    if recent_readings:
        latest = recent_readings[-1]
        logger.debug(f"Serving latest sensor data: {latest['status']} status")
        return templates.TemplateResponse("sensor_data.html", {
            "request": request,
            "data": latest
        })
    
    logger.warning("No sensor data available")
    return templates.TemplateResponse("sensor_data.html", {
        "request": request,
        "data": None
    })

@app.get("/health")
async def health_check():
    """Health check endpoint with system metrics"""
    metrics.track_request()
    
    health_data = {
        "status": "healthy", 
        "readings_count": len(recent_readings),
        "active_connections": metrics.connection_count,
        "total_requests": metrics.total_requests,
        "timestamp": datetime.now().isoformat()
    }
    
    # Add performance metrics if available
    if metrics.chart_generation_times:
        recent_times = metrics.chart_generation_times[-10:]  # Last 10 generations
        health_data["avg_chart_generation_time"] = sum(recent_times) / len(recent_times)
        health_data["max_chart_generation_time"] = max(recent_times)
    
    logger.debug(f"Health check: {health_data}")
    return health_data

@app.get("/metrics")
async def get_metrics():
    """Detailed metrics endpoint for monitoring"""
    metrics.track_request()
    
    detailed_metrics = {
        "connections": {
            "active": metrics.connection_count,
            "total_requests": metrics.total_requests
        },
        "data": {
            "readings_stored": len(recent_readings),
            "latest_reading_time": recent_readings[-1]["timestamp"] if recent_readings else None
        },
        "performance": {
            "chart_generations": len(metrics.chart_generation_times),
            "avg_chart_time": sum(metrics.chart_generation_times) / len(metrics.chart_generation_times) if metrics.chart_generation_times else 0,
            "slow_chart_count": len([t for t in metrics.chart_generation_times if t > 1.0])
        },
        "timestamp": datetime.now().isoformat()
    }
    
    logger.info("Detailed metrics requested")
    return detailed_metrics

# Application lifecycle events
@app.on_event("startup")
async def startup_event():
    logger.info("🚀 Sensor Dashboard application started successfully")
    logger.info(f"Debug mode: {bool(os.getenv('DEBUG'))}")
    logger.info(f"Initial sensor readings: {len(recent_readings)}")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("📊 Sensor Dashboard application shutting down")
    logger.info(f"Final metrics - Connections: {metrics.connection_count}, Requests: {metrics.total_requests}")

# Error handling
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception on {request.url}: {exc}")
    return {"error": "Internal server error", "timestamp": datetime.now().isoformat()}