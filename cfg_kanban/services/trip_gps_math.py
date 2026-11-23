"""Validate device fixes without depending on Frappe, local timezone or implicit zeroes."""
import math

PUBLISH_SECONDS=15
STALE_SECONDS=90
LEASE_HOURS=12
PUBLISH_INTERVALS=(15,30,60,120,300)


def publish_interval(value=None):
    if isinstance(value,bool):raise ValueError('Select a GPS interval: 15, 30, 60, 120 or 300 seconds')
    if value in (None,'',0,'0'):return PUBLISH_SECONDS
    try:number=int(value)
    except (ValueError,TypeError,OverflowError):raise ValueError('Select a valid GPS publish interval') from None
    if number not in PUBLISH_INTERVALS or str(value) not in (str(number),str(float(number))):
        raise ValueError('Select a GPS interval: 15, 30, 60, 120 or 300 seconds')
    return number


def stale_after(value=None):
    return max(STALE_SECONDS,3*publish_interval(value))


def finite_number(value,label):
    if isinstance(value,bool) or not isinstance(value,(int,float)):raise ValueError(label+' must be a number')
    try:value=float(value)
    except OverflowError:raise ValueError(label+' must be finite') from None
    if not math.isfinite(value):raise ValueError(label+' must be finite')
    return value


def position(value,now_ms):
    if not isinstance(value,dict) or set(value)!={'latitude','longitude','accuracy','captured_ms'}:
        raise ValueError('GPS fix needs latitude, longitude, accuracy and capture time')
    result={name:finite_number(number,name) for name,number in value.items()}
    if not -90<=result['latitude']<=90 or not -180<=result['longitude']<=180:raise ValueError('Invalid GPS latitude or longitude')
    if not 0<=result['accuracy']<=1000000:raise ValueError('Invalid GPS accuracy')
    if result['captured_ms']>now_ms+30000:raise ValueError('Device GPS time is ahead; check automatic device date/time')
    if result['captured_ms']<now_ms-120000:raise ValueError('Device GPS fix is too old; obtain a fresh position')
    return result


def sequence(value):
    if isinstance(value,bool):raise ValueError('GPS sequence must be a positive whole number')
    if isinstance(value,str):
        if not value.isascii() or not value.isdecimal():raise ValueError('GPS sequence must be a positive whole number')
        value=int(value)
    if not isinstance(value,int) or not 1<=value<=2147483647:raise ValueError('GPS sequence must be a positive whole number')
    return value


def fix_age(fix,received_ms,now_ms):
    if not fix:return None
    return max(0,(now_ms-min(fix['captured_ms'],received_ms))/1000)
