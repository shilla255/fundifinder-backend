from django.contrib.gis.geos import Point


def make_point(latitude: float, longitude: float) -> Point:
    # GEOS points are (x, y) = (longitude, latitude).
    return Point(float(longitude), float(latitude), srid=4326)
