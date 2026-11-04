var request = olCoreReadHttpRequest(
    sourceMap,
    connectorMessage.getRawData()
);

if (request.method === 'OPTIONS') {
    var headers = sourceMap.get('headers');
    request.origin = olCoreGetHeader(headers, 'Origin');
    request.preflightMethod = olCoreGetHeader(headers, 'Access-Control-Request-Method');
    request.preflightHeaders = olCoreGetHeader(headers, 'Access-Control-Request-Headers');
}

olRouteApply(
    request,
    channelMap,
    'https://middleware.local.omnilink.ch',
    logger
);
