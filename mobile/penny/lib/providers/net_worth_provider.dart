/// Riverpod providers for net worth data.
///
/// Provides:
/// - [netWorthProvider]: Current net worth with per-account breakdown.
/// - [netWorthHistoryProvider]: Net worth trend data for charting.
///
/// Both auto-fetch on first access and support manual refresh.
library;

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import '../models/net_worth.dart';
import '../services/cache_service.dart';
import 'connections_provider.dart';

/// The currently selected history period.
///
/// Dashboard UI can update this to switch between 7d/30d/90d views.
final netWorthPeriodProvider = StateProvider<String>((ref) => '30d');

/// Fetches the current net worth summary.
class NetWorthNotifier extends AsyncNotifier<NetWorth> {
  static const _cacheKey = 'net_worth';

  @override
  Future<NetWorth> build() async {
    final session = Supabase.instance.client.auth.currentSession;
    if (session == null) {
      debugPrint('NetWorthNotifier.build(): no session, returning empty');
      return const NetWorth(totalNetWorth: 0, accounts: []);
    }

    // Try local cache first for instant UI.
    final cached = await _loadFromCache();
    if (cached != null) {
      state = AsyncValue.data(cached);
      _refreshInBackground();
      return cached;
    }

    return _fetch();
  }

  Future<NetWorth?> _loadFromCache() async {
    try {
      final entry = await CacheService.read(_cacheKey);
      if (entry == null) return null;
      final result = NetWorth.fromJson(entry.data as Map<String, dynamic>);
      debugPrint(
        'NetWorthNotifier: loaded net worth from cache '
        '(stale: ${entry.isStale})',
      );
      return result;
    } catch (e) {
      debugPrint('NetWorthNotifier: cache read failed: $e');
      return null;
    }
  }

  Future<void> _writeToCache(NetWorth netWorth) async {
    await CacheService.write(_cacheKey, netWorth.toJson());
  }

  /// Fetch from network in the background and silently update state + cache.
  void _refreshInBackground() {
    Future(() async {
      try {
        final fresh = await _fetchFromNetwork();
        state = AsyncValue.data(fresh);
        await _writeToCache(fresh);
      } catch (e) {
        debugPrint('NetWorthNotifier: background refresh failed: $e');
      }
    });
  }

  Future<NetWorth> _fetch() async {
    final result = await _fetchFromNetwork();
    await _writeToCache(result);
    return result;
  }

  Future<NetWorth> _fetchFromNetwork() async {
    final api = ref.read(apiServiceProvider);
    try {
      final data = await api.getNetWorth();
      debugPrint(
        'NetWorthNotifier: fetched net worth '
        '(${data['accounts']?.length ?? 0} accounts)',
      );
      return NetWorth.fromJson(data);
    } catch (e) {
      debugPrint('NetWorthNotifier: fetch failed: $e');
      rethrow;
    }
  }

  /// Force-refresh the net worth data.
  Future<void> refresh() async {
    state = const AsyncValue.loading();
    state = await AsyncValue.guard(() => _fetch());
  }
}

/// Provider for current net worth.
final netWorthProvider = AsyncNotifierProvider<NetWorthNotifier, NetWorth>(
  NetWorthNotifier.new,
);

/// Fetches the net worth history for the selected period.
class NetWorthHistoryNotifier extends AsyncNotifier<NetWorthHistory> {
  static String _cacheKey(String period) => 'net_worth_history_$period';

  @override
  Future<NetWorthHistory> build() async {
    final session = Supabase.instance.client.auth.currentSession;
    if (session == null) {
      debugPrint(
        'NetWorthHistoryNotifier.build(): no session, returning empty',
      );
      return const NetWorthHistory(period: '30d', dataPoints: []);
    }

    // Watch the period so we refetch when it changes.
    final period = ref.watch(netWorthPeriodProvider);

    // Try local cache first for instant UI.
    final cached = await _loadFromCache(period);
    if (cached != null) {
      state = AsyncValue.data(cached);
      _refreshInBackground(period);
      return cached;
    }

    return _fetch(period);
  }

  Future<NetWorthHistory?> _loadFromCache(String period) async {
    try {
      final entry = await CacheService.read(_cacheKey(period));
      if (entry == null) return null;
      final result = NetWorthHistory.fromJson(
        entry.data as Map<String, dynamic>,
      );
      debugPrint(
        'NetWorthHistoryNotifier: loaded ${result.dataPoints.length} '
        'data points from cache for $period (stale: ${entry.isStale})',
      );
      return result;
    } catch (e) {
      debugPrint('NetWorthHistoryNotifier: cache read failed: $e');
      return null;
    }
  }

  Future<void> _writeToCache(String period, NetWorthHistory history) async {
    await CacheService.write(_cacheKey(period), history.toJson());
  }

  /// Fetch from network in the background and silently update state + cache.
  void _refreshInBackground(String period) {
    Future(() async {
      try {
        final fresh = await _fetchFromNetwork(period);
        state = AsyncValue.data(fresh);
        await _writeToCache(period, fresh);
      } catch (e) {
        debugPrint('NetWorthHistoryNotifier: background refresh failed: $e');
      }
    });
  }

  Future<NetWorthHistory> _fetch(String period) async {
    final result = await _fetchFromNetwork(period);
    await _writeToCache(period, result);
    return result;
  }

  Future<NetWorthHistory> _fetchFromNetwork(String period) async {
    final api = ref.read(apiServiceProvider);
    try {
      final data = await api.getNetWorthHistory(period: period);
      debugPrint(
        'NetWorthHistoryNotifier: fetched ${data['data_points']?.length ?? 0} '
        'data points for period $period',
      );
      return NetWorthHistory.fromJson(data);
    } catch (e) {
      debugPrint('NetWorthHistoryNotifier: fetch failed: $e');
      rethrow;
    }
  }

  /// Force-refresh the history data.
  Future<void> refresh() async {
    final period = ref.read(netWorthPeriodProvider);
    state = const AsyncValue.loading();
    state = await AsyncValue.guard(() => _fetch(period));
  }
}

/// Provider for net worth history trend.
final netWorthHistoryProvider =
    AsyncNotifierProvider<NetWorthHistoryNotifier, NetWorthHistory>(
      NetWorthHistoryNotifier.new,
    );
