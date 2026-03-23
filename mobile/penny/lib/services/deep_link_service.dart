/// Deep link handler for the TrueLayer OAuth callback.
///
/// Listens for incoming `pennyapp://callback?code=...` links using the
/// `app_links` package. When a callback is received, extracts the
/// authorization code and sends it to the backend via the connections
/// provider.
///
/// This service is initialised once in [main.dart] and lives for the
/// app's lifetime.
library;

import 'dart:async';

import 'package:app_links/app_links.dart';
import 'package:flutter/foundation.dart';

class DeepLinkService {
  final AppLinks _appLinks = AppLinks();
  StreamSubscription<Uri>? _subscription;

  /// Callback that will be invoked with the OAuth authorization code
  /// when a `pennyapp://callback` deep link is received.
  void Function(String code)? onCallbackReceived;

  /// Start listening for incoming deep links.
  ///
  /// Call this once during app initialisation.
  Future<void> init() async {
    // Handle the link that launched the app (cold start).
    try {
      final initialUri = await _appLinks.getInitialLink();
      if (initialUri != null) {
        _handleUri(initialUri);
      }
    } catch (e) {
      debugPrint('DeepLinkService: failed to get initial link: $e');
    }

    // Handle links while the app is already running (warm start).
    _subscription = _appLinks.uriLinkStream.listen(
      _handleUri,
      onError: (error) {
        debugPrint('DeepLinkService: link stream error: $error');
      },
    );
  }

  void _handleUri(Uri uri) {
    debugPrint('DeepLinkService: received URI: $uri');

    // We only care about pennyapp://callback
    if (uri.scheme != 'pennyapp' || uri.host != 'callback') {
      debugPrint('DeepLinkService: ignoring non-callback URI');
      return;
    }

    final code = uri.queryParameters['code'];
    if (code == null || code.isEmpty) {
      debugPrint('DeepLinkService: callback URI missing "code" parameter');
      return;
    }

    debugPrint('DeepLinkService: extracted auth code (${code.length} chars)');
    onCallbackReceived?.call(code);
  }

  /// Stop listening for deep links.
  void dispose() {
    _subscription?.cancel();
    _subscription = null;
  }
}
