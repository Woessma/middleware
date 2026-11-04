var request = olCoreReadHttpRequest(
    sourceMap,
    connectorMessage.getRawData()
);

olRouteApply(
    request,
    channelMap,
    'https://middleware.local.omnilink.ch',
    logger
);
