/// Riverpod providers for bank connections.
///
/// Provides:
/// - [apiServiceProvider]: Singleton [ApiService] for backend calls.
/// - [connectionsProvider]: [AsyncNotifier] that manages the list of
///   bank connections with methods to initiate, complete callback, and
///   delete connections.
library;

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import '../models/connection.dart';
import '../services/api_service.dart';
import '../services/cache_service.dart';
import 'transactions_provider.dart';

/// Singleton [ApiService] instance for communicating with the backend.
final apiServiceProvider = Provider<ApiService>((ref) {
  final service = ApiService();
  ref.onDispose(service.dispose);
  return service;
});

/// State notifier for the bank connections list.
///
/// Fetches connections on first access (see build() ) and exposes methods to
/// initiate the connect flow, handle the callback, and delete.
class ConnectionsNotifier extends AsyncNotifier<List<BankConnection>> {
  static const _cacheKey = 'connections';

  @override
  Future<List<BankConnection>> build() async {
    // Only fetch if there is an active session. This avoids firing
    // a request before the user is signed in (which would throw a
    // StateError from _authHeaders and permanently cache the error).
    final session = Supabase.instance.client.auth.currentSession;
    if (session == null) {
      debugPrint('ConnectionsNotifier.build(): no session, returning empty');
      return [];
    }

    // Try local cache first for instant UI.
    final cached = await _loadFromCache();
    if (cached != null) {
      // Show cached data immediately, then refresh in the background.
      state = AsyncValue.data(cached);
      _refreshInBackground();
      return cached;
    }

    return _fetchConnections();
  }

  Future<List<BankConnection>?> _loadFromCache() async {
    try {
      final entry = await CacheService.read(_cacheKey);
      if (entry == null) return null;
      final list = (entry.data as List<dynamic>)
          .map((j) => BankConnection.fromJson(j as Map<String, dynamic>))
          .toList();
      debugPrint(
        'ConnectionsNotifier: loaded ${list.length} connections from cache '
        '(stale: ${entry.isStale})',
      );
      return list;
    } catch (e) {
      debugPrint('ConnectionsNotifier: cache read failed: $e');
      return null;
    }
  }

  Future<void> _writeToCache(List<BankConnection> connections) async {
    await CacheService.write(
      _cacheKey,
      connections.map((c) => c.toJson()).toList(),
    );
  }

  /// Fetch from network in the background and silently update state + cache.
  void _refreshInBackground() {
    Future(() async {
      try {
        final fresh = await _fetchConnectionsFromNetwork();
        state = AsyncValue.data(fresh);
        await _writeToCache(fresh);
      } catch (e) {
        // Network failed but we already have cached data — keep showing it.
        debugPrint('ConnectionsNotifier: background refresh failed: $e');
      }
    });
  }

  Future<List<BankConnection>> _fetchConnections() async {
    final connections = await _fetchConnectionsFromNetwork();
    await _writeToCache(connections);
    return connections;
  }

  Future<List<BankConnection>> _fetchConnectionsFromNetwork() async {
    final api = ref.read(apiServiceProvider);
    try {
      final data = await api.listConnections();
      debugPrint('ConnectionsNotifier: fetched ${data.length} connections');
      return data.map((json) => BankConnection.fromJson(json)).toList();
    } catch (e) {
      debugPrint('ConnectionsNotifier: fetch failed: $e');
      rethrow;
    }
  }

  /// Initiate the TrueLayer OAuth flow.
  ///
  /// Returns the auth URL to open in the browser.
  Future<String> initiateConnection() async {
    final api = ref.read(apiServiceProvider);
    return await api.initiateConnection();
  }

  /// Complete the OAuth callback by sending the auth code to the backend.
  ///
  /// After success, refreshes the connections list, triggers a backend sync
  /// so TrueLayer data is fetched immediately, then invalidates the
  /// transactions provider so the UI picks up the new data.
  Future<void> completeCallback(String code) async {
    final api = ref.read(apiServiceProvider);
    await api.connectionCallback(code);

    // Refresh the connections list to include the new connection.
    state = const AsyncValue.loading();
    state = await AsyncValue.guard(() => _fetchConnections());

    // Trigger a sync so accounts + transactions are fetched from TrueLayer.
    try {
      debugPrint('ConnectionsNotifier: triggering post-connection sync');
      await api.triggerSync();
      debugPrint('ConnectionsNotifier: post-connection sync complete');
    } catch (e) {
      // Non-fatal — the scheduled sync will pick it up later.
      debugPrint('ConnectionsNotifier: post-connection sync failed: $e');
    }

    // Invalidate transactions so the UI refetches from the DB.
    ref.invalidate(transactionsProvider);
  }

  /// Delete a bank connection.
  ///
  /// Optimistically removes from the list, then calls the backend.
  /// On failure, refetches the full list.
  Future<void> deleteConnection(String connectionId) async {
    final api = ref.read(apiServiceProvider);

    // Optimistic removal.
    final previous = state.valueOrNull ?? [];
    final updated = previous.where((c) => c.id != connectionId).toList();
    state = AsyncValue.data(updated);
    await _writeToCache(updated);

    try {
      await api.deleteConnection(connectionId);
    } catch (_) {
      // Roll back: refetch from server.
      state = await AsyncValue.guard(() => _fetchConnections());
      rethrow;
    }
  }

  /// Force-refresh the connections list.
  Future<void> refresh() async {
    state = const AsyncValue.loading();
    state = await AsyncValue.guard(() => _fetchConnections());
  }

  /// Attempt to reconnect an expiring / expired bank connection.
  ///
  /// Returns a map with `action`, `auth_url` (nullable), and `message`.
  ///
  /// If the backend renewed the consent silently (`no_action_needed`), the
  /// connections list is automatically refreshed. If re-authentication is
  /// required (`authentication_needed`), the caller should launch `auth_url`
  /// in a browser.
  Future<Map<String, dynamic>> reconnectConnection(String connectionId) async {
    final api = ref.read(apiServiceProvider);
    final result = await api.reconnectConnection(connectionId);

    // Silent renewal succeeded — refresh so the UI shows the updated status.
    if (result['action'] == 'no_action_needed') {
      state = await AsyncValue.guard(() => _fetchConnections());
    }

    return result;
  }
}

/// Provider for the bank connections list.
///
/// Usage:
/// ```dart
/// final connections = ref.watch(connectionsProvider);
/// ```
final connectionsProvider =
    AsyncNotifierProvider<ConnectionsNotifier, List<BankConnection>>(
      ConnectionsNotifier.new,
    );
