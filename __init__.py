def classFactory(iface):
    from .plugin import QuoteConverterPlugin
    return QuoteConverterPlugin(iface)
