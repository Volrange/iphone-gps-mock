"""Coordinate validation and approximate GCJ-02 -> WGS-84 conversion.

The conversion is an iterative inverse of the commonly used GCJ-02 model;
it is not an official survey transformation. Outside China no offset is used.
"""
import math

# Candidate carried from the initial lookup, not independently verified.
# Confirm the gate position in the phone map before treating it as exact.
SIYUAN_GCJ02 = (31.017785, 121.430895)


def validate(latitude, longitude):
    lat, lon = float(latitude), float(longitude)
    if not math.isfinite(lat) or not -90 <= lat <= 90:
        raise ValueError("纬度必须是 -90 到 90 之间的有限数字")
    if not math.isfinite(lon) or not -180 <= lon <= 180:
        raise ValueError("经度必须是 -180 到 180 之间的有限数字")
    return lat, lon


def wgs_to_gcj(lat, lon):
    lat, lon = validate(lat, lon)
    if not (72.004 <= lon <= 137.8347 and 0.8293 <= lat <= 55.8271):
        return lat, lon
    x, y, pi = lon - 105, lat - 35, math.pi
    a, ee = 6378245.0, 0.006693421622965943
    dlat = -100 + 2*x + 3*y + .2*y*y + .1*x*y + .2*math.sqrt(abs(x))
    dlon = 300 + x + 2*y + .1*x*x + .1*x*y + .1*math.sqrt(abs(x))
    common = (20*math.sin(6*x*pi) + 20*math.sin(2*x*pi))*2/3
    dlat += common + (20*math.sin(y*pi) + 40*math.sin(y*pi/3))*2/3
    dlat += (160*math.sin(y*pi/12) + 320*math.sin(y*pi/30))*2/3
    dlon += common + (20*math.sin(x*pi) + 40*math.sin(x*pi/3))*2/3
    dlon += (150*math.sin(x*pi/12) + 300*math.sin(x*pi/30))*2/3
    rad = math.radians(lat)
    magic = 1 - ee*math.sin(rad)**2
    dlat = dlat*180 / ((a*(1-ee)/(magic*math.sqrt(magic)))*pi)
    dlon = dlon*180 / ((a/math.sqrt(magic))*math.cos(rad)*pi)
    return lat+dlat, lon+dlon


def to_wgs84(latitude, longitude, system="WGS-84"):
    lat, lon = validate(latitude, longitude)
    if system == "WGS-84":
        return lat, lon
    if system != "GCJ-02":
        raise ValueError("请选择 WGS-84 或 GCJ-02 坐标系")
    result_lat, result_lon = lat, lon
    for _ in range(10):
        mapped_lat, mapped_lon = wgs_to_gcj(result_lat, result_lon)
        dy, dx = mapped_lat-lat, mapped_lon-lon
        result_lat -= dy
        result_lon -= dx
        if max(abs(dy), abs(dx)) < 1e-9:
            break
    return validate(result_lat, result_lon)
