/// Riverpod providers for transactions.
///
/// Provides:
/// - [transactionsProvider]: [AsyncNotifier] that manages the paginated
///   transaction list with pull-to-refresh (sync) and category updates.
library;

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import '../models/transaction.dart';
import '../services/cache_service.dart';
import 'connections_provider.dart';

/// State object for the transactions list.
///
/// Wraps [TransactionListResponse] plus loading/error states for
/// pagination and sync operations.
class TransactionsState {
  final List<Transaction> transactions;
  final int total;
  final int currentPage;
  final int pageSize;
  final bool hasMore;
  final bool isSyncing;

  const TransactionsState({
    this.transactions = const [],
    this.total = 0,
    this.currentPage = 1,
    this.pageSize = 50,
    this.hasMore = false,
    this.isSyncing = false,
  });

  TransactionsState copyWith({
    List<Transaction>? transactions,
    int? total,
    int? currentPage,
    int? pageSize,
    bool? hasMore,
    bool? isSyncing,
  }) {
    return TransactionsState(
      transactions: transactions ?? this.transactions,
      total: total ?? this.total,
      currentPage: currentPage ?? this.currentPage,
      pageSize: pageSize ?? this.pageSize,
      hasMore: hasMore ?? this.hasMore,
      isSyncing: isSyncing ?? this.isSyncing,
    );
  }
}

/// Notifier for the paginated transaction list.
///
/// Fetches transactions on first access. Supports:
/// - Pull-to-refresh (triggers sync, then refetches)
/// - Load more (next page)
/// - Category update (updates local state immediately)
class TransactionsNotifier extends AsyncNotifier<TransactionsState> {
  static const _cacheKey = 'transactions';

  @override
  Future<TransactionsState> build() async {
    final session = Supabase.instance.client.auth.currentSession;
    if (session == null) {
      debugPrint('TransactionsNotifier.build(): no session, returning empty');
      return const TransactionsState();
    }

    // Try local cache first for instant UI.
    final cached = await _loadFromCache();
    if (cached != null) {
      state = AsyncValue.data(cached);
      _refreshInBackground();
      return cached;
    }

    return _fetchPage(1);
  }

  Future<TransactionsState?> _loadFromCache() async {
    try {
      final entry = await CacheService.read(_cacheKey);
      if (entry == null) return null;
      final response = TransactionListResponse.fromJson(
        entry.data as Map<String, dynamic>,
      );
      final result = TransactionsState(
        transactions: response.transactions,
        total: response.total,
        currentPage: response.page,
        pageSize: response.pageSize,
        hasMore: response.hasMore,
      );
      debugPrint(
        'TransactionsNotifier: loaded ${result.transactions.length} '
        'transactions from cache (stale: ${entry.isStale})',
      );
      return result;
    } catch (e) {
      debugPrint('TransactionsNotifier: cache read failed: $e');
      return null;
    }
  }

  Future<void> _writeToCache(TransactionsState txState) async {
    final response = TransactionListResponse(
      transactions: txState.transactions,
      total: txState.total,
      page: txState.currentPage,
      pageSize: txState.pageSize,
      hasMore: txState.hasMore,
    );
    await CacheService.write(_cacheKey, response.toJson());
  }

  /// Fetch from network in the background and silently update state + cache.
  void _refreshInBackground() {
    Future(() async {
      try {
        final fresh = await _fetchPageFromNetwork(1);
        state = AsyncValue.data(fresh);
        await _writeToCache(fresh);
      } catch (e) {
        debugPrint('TransactionsNotifier: background refresh failed: $e');
      }
    });
  }

  Future<TransactionsState> _fetchPage(int page) async {
    final result = await _fetchPageFromNetwork(page);
    if (page == 1) await _writeToCache(result);
    return result;
  }

  Future<TransactionsState> _fetchPageFromNetwork(int page) async {
    final api = ref.read(apiServiceProvider);
    try {
      final data = await api.listTransactions(page: page);
      final response = TransactionListResponse.fromJson(data);
      debugPrint(
        'TransactionsNotifier: fetched ${response.transactions.length} '
        'transactions (page $page, total ${response.total})',
      );
      return TransactionsState(
        transactions: response.transactions,
        total: response.total,
        currentPage: response.page,
        pageSize: response.pageSize,
        hasMore: response.hasMore,
      );
    } catch (e) {
      debugPrint('TransactionsNotifier: fetch failed: $e');
      rethrow;
    }
  }

  /// Pull-to-refresh: trigger a backend sync, then refetch page 1.
  Future<void> refreshWithSync() async {
    final current = state.valueOrNull ?? const TransactionsState();
    state = AsyncValue.data(current.copyWith(isSyncing: true));

    try {
      final api = ref.read(apiServiceProvider);
      await api.triggerSync();
      // Give the sync a moment to process, then refetch.
      await Future<void>.delayed(const Duration(seconds: 2));
    } catch (e) {
      debugPrint('TransactionsNotifier: sync trigger failed: $e');
      // Continue to refetch even if sync trigger failed — show stale data.
    }

    state = const AsyncValue.loading();
    state = await AsyncValue.guard(() => _fetchPage(1));
  }

  /// Refresh without triggering a sync (just refetch from DB).
  Future<void> refresh() async {
    state = const AsyncValue.loading();
    state = await AsyncValue.guard(() => _fetchPage(1));
  }

  /// Load the next page of transactions and append to the current list.
  Future<void> loadMore() async {
    final current = state.valueOrNull;
    if (current == null || !current.hasMore) return;

    try {
      final api = ref.read(apiServiceProvider);
      final data = await api.listTransactions(
        page: current.currentPage + 1,
        pageSize: current.pageSize,
      );
      final response = TransactionListResponse.fromJson(data);

      state = AsyncValue.data(
        current.copyWith(
          transactions: [...current.transactions, ...response.transactions],
          total: response.total,
          currentPage: response.page,
          hasMore: response.hasMore,
        ),
      );
    } catch (e) {
      debugPrint('TransactionsNotifier: loadMore failed: $e');
      // Don't overwrite existing data on pagination failure.
    }
  }

  /// Update the category of a transaction.
  ///
  /// Optimistically updates the local state, then sends to backend.
  /// On failure, reverts and rethrows.
  Future<void> updateCategory(String transactionId, String? category) async {
    final current = state.valueOrNull;
    if (current == null) return;

    // Optimistic update.
    final updatedTransactions = current.transactions.map((t) {
      if (t.id == transactionId) {
        return Transaction(
          id: t.id,
          accountId: t.accountId,
          timestamp: t.timestamp,
          description: t.description,
          amount: t.amount,
          currency: t.currency,
          transactionType: t.transactionType,
          merchantName: t.merchantName,
          category: category,
          runningBalance: t.runningBalance,
        );
      }
      return t;
    }).toList();

    state = AsyncValue.data(
      current.copyWith(transactions: updatedTransactions),
    );

    try {
      final api = ref.read(apiServiceProvider);
      await api.updateTransactionCategory(transactionId, category);
    } catch (_) {
      // Roll back to previous state.
      state = AsyncValue.data(current);
      rethrow;
    }
  }
}

/// Provider for the paginated transactions list.
final transactionsProvider =
    AsyncNotifierProvider<TransactionsNotifier, TransactionsState>(
      TransactionsNotifier.new,
    );
