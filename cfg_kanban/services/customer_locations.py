"""A Customer Site delivery pin is optional and contains exactly one GeoJSON point."""
import json
import math


def delivery_pin(value):
    if value is None or (isinstance(value,str) and not value.strip()):
        return None
    if isinstance(value,str):
        if len(value)>65536:raise ValueError('Delivery Pin is too large; keep one marker')
        try:value=json.loads(value)
        except (ValueError,TypeError,RecursionError):raise ValueError('Delivery Pin must be valid map data') from None
    if value is None:return None
    if not isinstance(value,dict):raise ValueError('Delivery Pin must contain one map marker')
    if value.get('type')=='FeatureCollection':
        features=value.get('features')
        if not isinstance(features,list) or len(features)>1:raise ValueError('Keep exactly one Delivery Pin marker; remove extra markers or shapes')
        if not features:return None
        value=features[0]
    if not isinstance(value,dict) or value.get('type')!='Feature':raise ValueError('Delivery Pin must contain one map marker')
    props=value.get('properties');props={} if props is None else props
    if not isinstance(props,dict) or props.get('point_type') in ('circle','circlemarker'):
        raise ValueError('Use a Delivery Pin marker, not a circle or area')
    geometry=value.get('geometry') or {};coords=geometry.get('coordinates') if isinstance(geometry,dict) else None
    if not isinstance(geometry,dict) or geometry.get('type')!='Point' or not isinstance(coords,(list,tuple)) or len(coords)!=2:
        raise ValueError('Delivery Pin must be one point with longitude and latitude')
    if any(isinstance(n,bool) or not isinstance(n,(int,float)) for n in coords):
        raise ValueError('Delivery Pin coordinates must be finite numbers')
    try:longitude,latitude=[float(n) for n in coords]
    except OverflowError:raise ValueError('Delivery Pin coordinates must be finite numbers') from None
    if not math.isfinite(longitude) or not math.isfinite(latitude):
        raise ValueError('Delivery Pin coordinates must be finite numbers')
    if not -90<=latitude<=90 or not -180<=longitude<=180:
        raise ValueError('Delivery Pin latitude must be -90 to 90 and longitude -180 to 180')
    return dict(latitude=float(latitude),longitude=float(longitude))


def pin_geojson(pin):
    if pin is None:return None
    return json.dumps(dict(type='FeatureCollection',features=[dict(type='Feature',properties={},
        geometry=dict(type='Point',coordinates=[pin['longitude'],pin['latitude']]))]),separators=(',',':'))


def pin_projection(value):
    """Bad legacy/imported pin data must not prevent a delivery or produce a false destination."""
    try:pin=delivery_pin(value)
    except ValueError:return dict(delivery_pin=None,delivery_pin_status='Invalid')
    return dict(delivery_pin=pin,delivery_pin_status='Saved' if pin else 'Missing')
