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
    return _fetchConnections();
  }

  Future<List<BankConnection>> _fetchConnections() async {
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
  /// After success, refreshes the connections list.
  Future<void> completeCallback(String code) async {
    final api = ref.read(apiServiceProvider);
    await api.connectionCallback(code);
    // Refresh the list to include the new connection.
    state = const AsyncValue.loading();
    state = await AsyncValue.guard(() => _fetchConnections());
  }

  /// Delete a bank connection.
  ///
  /// Optimistically removes from the list, then calls the backend.
  /// On failure, refetches the full list.
  Future<void> deleteConnection(String connectionId) async {
    final api = ref.read(apiServiceProvider);

    // Optimistic removal.
    final previous = state.valueOrNull ?? [];
    state = AsyncValue.data(
      previous.where((c) => c.id != connectionId).toList(),
    );

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
