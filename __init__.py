def classFactory(iface):
    from .plugin import TransitGtfsBuilder

    return TransitGtfsBuilder(iface)
