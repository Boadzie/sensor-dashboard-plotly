from collections import deque
import random
from datetime import datetime, timedelta
import polars as pl
from typing import List, Dict
from loguru import logger

# Configure Loguru for beautiful logging
logger.add(
    "logs/sensor_dashboard_{time}.log",
    rotation="1 day",
    retention="7 days", 
    level="INFO",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}"
)

class SensorData:
    def __init__(self):
        # Room temperature range (still comfortable)
        self.min_temp = 18.0
        self.max_temp = 26.0
        self.min_humidity = 30.0
        self.max_humidity = 65.0
        
        logger.info("Sensor data generator initialized")
        self._initialize_history()
    
    def _initialize_history(self):
        """Bootstrap with realistic historical data"""
        base_time = datetime.now() - timedelta(minutes=10)
        history = []
        
        logger.debug("Generating 50 historical sensor readings")
        for i in range(50):
            timestamp = base_time + timedelta(seconds=i * 12)  # Every 12 seconds
            history.append(self.generate_reading(timestamp))
        
        # Store in deque for efficient updates
        recent_readings.extend(history)
        logger.info(f"Initialized sensor history with {len(history)} readings")
    
    def generate_reading(self, timestamp: datetime = None) -> Dict:
        """Generate a sensor reading with optional timestamp"""
        if timestamp is None:
            timestamp = datetime.now()
            
        reading = {
            "timestamp": timestamp.isoformat(),
            "temperature": round(random.uniform(self.min_temp, self.max_temp), 1),
            "humidity": round(random.uniform(self.min_humidity, self.max_humidity), 1),
            "pressure": round(random.uniform(1000, 1030), 1),  # Added pressure
            "status": random.choice(["normal", "warning", "critical"])
        }
        
        # Log critical readings for monitoring
        if reading["status"] == "critical":
            logger.warning(
                f"Critical sensor reading: temp={reading['temperature']}°C, "
                f"humidity={reading['humidity']}%, pressure={reading['pressure']}hPa"
            )
        
        return reading

# Store the last 100 readings (more data = better Plotly charts)
recent_readings = deque(maxlen=100)

def get_sensor_dataframe() -> pl.DataFrame:
    """Convert readings to Polars DataFrame for easy manipulation"""
    if not recent_readings:
        logger.warning("No sensor readings available for DataFrame conversion")
        return pl.DataFrame()
    
    logger.debug(f"Converting {len(recent_readings)} readings to Polars DataFrame")
    
    # Polars DataFrame creation is lightning fast
    df = pl.DataFrame(list(recent_readings))
    
    # Parse timestamps (Polars handles this beautifully)
    df = df.with_columns([
        pl.col("timestamp").str.strptime(pl.Datetime, format="%Y-%m-%dT%H:%M:%S.%f")
    ])
    
    logger.debug(f"Created DataFrame with {len(df)} rows and {len(df.columns)} columns")
    return df

def get_statistical_summary() -> Dict:
    """Calculate statistics using Polars (because it's blazing fast)"""
    df = get_sensor_dataframe()
    
    if df.is_empty():
        logger.warning("Cannot calculate statistics: empty DataFrame")
        return {}
    
    logger.debug("Calculating statistical summary")
    
    # Polars makes complex aggregations simple
    stats = df.select([
        pl.col("temperature").mean().alias("temp_mean"),
        pl.col("temperature").std().alias("temp_std"),
        pl.col("humidity").mean().alias("humidity_mean"),
        pl.col("humidity").std().alias("humidity_std"),
        pl.col("pressure").mean().alias("pressure_mean"),
        pl.col("pressure").std().alias("pressure_std"),
        pl.col("status").value_counts().alias("status_counts")
    ]).to_dict(as_series=False)
    
    logger.info("Statistical summary calculated successfully")
    return stats

def detect_anomalies() -> List[Dict]:
    """Detect outliers using statistical methods (Polars style)"""
    df = get_sensor_dataframe()
    
    if len(df) < 10:  # Need enough data for meaningful stats
        logger.debug("Insufficient data for anomaly detection (need at least 10 readings)")
        return []
    
    logger.debug("Running anomaly detection using z-score method")
    
    # Calculate z-scores for temperature (Polars vectorized operations)
    df_with_zscore = df.with_columns([
        ((pl.col("temperature") - pl.col("temperature").mean()) / 
         pl.col("temperature").std()).alias("temp_zscore")
    ])
    
    # Find outliers (|z-score| > 2)
    anomalies = df_with_zscore.filter(
        pl.col("temp_zscore").abs() > 2
    ).select(["timestamp", "temperature", "temp_zscore"]).to_dicts()
    
    if anomalies:
        logger.warning(f"Detected {len(anomalies)} temperature anomalies")
        for anomaly in anomalies:
            logger.warning(
                f"Anomaly: {anomaly['temperature']}°C at {anomaly['timestamp']} "
                f"(z-score: {anomaly['temp_zscore']:.2f})"
            )
    else:
        logger.debug("No temperature anomalies detected")
    
    return anomalies