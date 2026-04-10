/// Lightweight local cache service for offline access to recent data.
///
/// Uses [SharedPreferences] to persist JSON-encoded API responses so the
/// app can display stale-but-useful data instantly while fresh data loads
/// from the network. Each cache entry includes a timestamp for staleness
/// checks.
///
/// Cache keys:
/// - `cache_connections`   — bank connections list
/// - `cache_net_worth`     — current net worth snapshot
/// - `cache_net_worth_history_{period}` — net worth history per period
/// - `cache_transactions`  — first page of transactions
library;

import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// How long before cached data is considered stale (still displayed, but
/// a background refresh is triggered).
const _staleDuration = Duration(hours: 1);

/// Wrapper around a cached value with a timestamp.
class CacheEntry {
  final dynamic data;
  final DateTime cachedAt;

  CacheEntry({required this.data, required this.cachedAt});

  bool get isStale => DateTime.now().difference(cachedAt) > _staleDuration;

  Map<String, dynamic> toJson() => {
    'data': data,
    'cached_at': cachedAt.toIso8601String(),
  };

  factory CacheEntry.fromJson(Map<String, dynamic> json) {
    return CacheEntry(
      data: json['data'],
      cachedAt: DateTime.parse(json['cached_at'] as String),
    );
  }
}

/// Service for reading and writing cached API responses.
class CacheService {
  static const _prefix = 'cache_';

  /// Write a value to the local cache.
  static Future<void> write(String key, dynamic data) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final entry = CacheEntry(data: data, cachedAt: DateTime.now());
      await prefs.setString('$_prefix$key', jsonEncode(entry.toJson()));
    } catch (e) {
      debugPrint('CacheService.write($key) failed: $e');
    }
  }

  /// Read a value from the local cache. Returns null if not cached.
  static Future<CacheEntry?> read(String key) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final raw = prefs.getString('$_prefix$key');
      if (raw == null) return null;
      final json = jsonDecode(raw) as Map<String, dynamic>;
      return CacheEntry.fromJson(json);
    } catch (e) {
      debugPrint('CacheService.read($key) failed: $e');
      return null;
    }
  }

  /// Remove a specific cache entry.
  static Future<void> remove(String key) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.remove('$_prefix$key');
    } catch (e) {
      debugPrint('CacheService.remove($key) failed: $e');
    }
  }

  /// Clear all cache entries (e.g. on sign-out).
  static Future<void> clearAll() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final keys = prefs.getKeys().where((k) => k.startsWith(_prefix));
      for (final key in keys) {
        await prefs.remove(key);
      }
    } catch (e) {
      debugPrint('CacheService.clearAll() failed: $e');
    }
  }
}
