import random
import math
import time
from datetime import datetime, timezone

SENSOR_DEFINITIONS = [
    {"id": "temp_01",   "name": "Temperature",  "unit": "C",     "min": 60.0,   "max": 80.0,   "anomaly_mult": 1.8},
    {"id": "vib_01",    "name": "Vibration",    "unit": "mm/s",  "min": 0.1,    "max": 0.5,    "anomaly_mult": 4.0},
    {"id": "pres_01",   "name": "Pressure",     "unit": "bar",   "min": 4.5,    "max": 5.5,    "anomaly_mult": 1.9},
    {"id": "curr_01",   "name": "Current",      "unit": "A",     "min": 8.0,    "max": 12.0,   "anomaly_mult": 2.0},
    {"id": "volt_01",   "name": "Voltage",      "unit": "V",     "min": 220.0,  "max": 240.0,  "anomaly_mult": 1.3},
    {"id": "rpm_01",    "name": "RPM",          "unit": "rpm",   "min": 1400.0, "max": 1600.0, "anomaly_mult": 1.6},
    {"id": "oil_01",    "name": "Oil Level",    "unit": "pct",   "min": 70.0,   "max": 90.0,   "anomaly_mult": 0.4},
    {"id": "cool_01",   "name": "Coolant Temp", "unit": "C",     "min": 35.0,   "max": 45.0,   "anomaly_mult": 2.2},
    {"id": "pow_01",    "name": "Power",        "unit": "kW",    "min": 1.8,    "max": 2.2,    "anomaly_mult": 2.5},
    {"id": "hum_01",    "name": "Humidity",     "unit": "pct",   "min": 40.0,   "max": 60.0,   "anomaly_mult": 1.7},
    {"id": "co2_01",    "name": "CO2",          "unit": "ppm",   "min": 400.0,  "max": 600.0,  "anomaly_mult": 2.3},
    {"id": "noise_01",  "name": "Noise",        "unit": "dB",    "min": 65.0,   "max": 75.0,   "anomaly_mult": 1.5},
    {"id": "flow_01",   "name": "Flow Rate",    "unit": "L/min", "min": 8.0,    "max": 12.0,   "anomaly_mult": 0.2},
    {"id": "torque_01", "name": "Torque",       "unit": "Nm",    "min": 45.0,   "max": 55.0,   "anomaly_mult": 1.8},
]


def _normal_reading(sensor):
    mid = (sensor["min"] + sensor["max"]) / 2
    std = (sensor["max"] - sensor["min"]) / 6
    value = random.gauss(mid, std)
    value = max(sensor["min"] * 0.95, min(sensor["max"] * 1.05, value))
    return round(value, 3)


def _anomaly_reading(sensor, anomaly_type):
    if anomaly_type == "spike":
        value = sensor["max"] * sensor["anomaly_mult"]
        value += random.uniform(-value * 0.05, value * 0.05)
    elif anomaly_type == "drift":
        value = sensor["max"] * random.uniform(1.20, 1.40)
    elif anomaly_type == "failure":
        value = random.uniform(0.0, sensor["min"] * 0.1)
    else:
        value = _normal_reading(sensor)
        anomaly_type = "none"
    return round(value, 3), anomaly_type


def generate_snapshot(anomaly_probability=0.05, force_anomaly_sensor_id=None):
    timestamp = datetime.now(timezone.utc).isoformat()
    snapshot = []
    for sensor in SENSOR_DEFINITIONS:
        is_forced = (force_anomaly_sensor_id == sensor["id"])
        is_random_anomaly = (random.random() < anomaly_probability)
        if is_forced or is_random_anomaly:
            anomaly_type = random.choice(["spike", "drift", "failure"])
            value, anomaly_type_used = _anomaly_reading(sensor, anomaly_type)
            is_anomaly = True
        else:
            value = _normal_reading(sensor)
            anomaly_type_used = "none"
            is_anomaly = False
        snapshot.append({
            "sensor_id":    sensor["id"],
            "sensor_name":  sensor["name"],
            "unit":         sensor["unit"],
            "value":        value,
            "normal_min":   sensor["min"],
            "normal_max":   sensor["max"],
            "is_anomaly":   is_anomaly,
            "anomaly_type": anomaly_type_used,
            "timestamp":    timestamp,
        })
    return snapshot


def generate_training_batch(n_samples=500):
    batch = []
    for _ in range(n_samples):
        snapshot = generate_snapshot(anomaly_probability=0.10)
        batch.extend(snapshot)
    return batch


def stream_snapshots(interval_seconds=1.0, count=10):
    generated = 0
    while count is None or generated < count:
        yield generate_snapshot()
        generated += 1
        time.sleep(interval_seconds)


if __name__ == "__main__":
    print("=" * 60)
    print("CORTEX Sensor Generator — Test Run")
    print("=" * 60)

    print("\n[1] Normal Snapshot (5% anomaly chance):")
    snapshot = generate_snapshot(anomaly_probability=0.05)
    for reading in snapshot:
        status = "ANOMALY" if reading["is_anomaly"] else "normal "
        print(f"  {status} | {reading['sensor_name']:15} | {reading['value']:8.3f} {reading['unit']:6} | range [{reading['normal_min']}, {reading['normal_max']}]")

    print("\n[2] Forced Anomaly on temp_01:")
    snapshot2 = generate_snapshot(force_anomaly_sensor_id="temp_01")
    for reading in snapshot2:
        if reading["sensor_id"] == "temp_01":
            print(f"  ANOMALY | {reading['sensor_name']}: {reading['value']} {reading['unit']} (type: {reading['anomaly_type']})")

    print("\n[3] Training Batch (100 samples):")
    batch = generate_training_batch(n_samples=100)
    anomalies = [r for r in batch if r["is_anomaly"]]
    print(f"  Total readings : {len(batch)}")
    print(f"  Anomalies      : {len(anomalies)} ({len(anomalies)/len(batch)*100:.1f}%)")
    print("\nOK sensor_generator.py working correctly")
