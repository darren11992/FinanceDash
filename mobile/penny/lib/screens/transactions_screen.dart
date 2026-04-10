/// Transaction list screen — unified feed across all connected accounts.
///
/// Displays transactions sorted by date (newest first) with:
/// - Description, amount (colour-coded debit/credit), category
/// - Pull-to-refresh triggers a sync then refetches
/// - Infinite scroll loads more pages
/// - Tap a transaction to view details / change category
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/transaction.dart';
import '../providers/transactions_provider.dart';
import '../services/api_service.dart';
import '../theme/penny_colors.dart';
import '../widgets/skeleton_loaders.dart';
import 'transaction_detail_screen.dart';

class TransactionsScreen extends ConsumerWidget {
  const TransactionsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final txnAsync = ref.watch(transactionsProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Transactions'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            tooltip: 'Refresh',
            onPressed: () => ref.read(transactionsProvider.notifier).refresh(),
          ),
        ],
      ),
      body: txnAsync.when(
        data: (txnState) => _TransactionListBody(txnState: txnState),
        loading: () => const TransactionsSkeleton(),
        error: (error, _) => _ErrorView(error: error),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Sub-widgets
// ---------------------------------------------------------------------------

class _TransactionListBody extends ConsumerWidget {
  final TransactionsState txnState;

  const _TransactionListBody({required this.txnState});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    if (txnState.transactions.isEmpty) {
      return _EmptyView(
        onRefresh: () async {
          await ref.read(transactionsProvider.notifier).refreshWithSync();
        },
      );
    }

    return RefreshIndicator(
      onRefresh: () =>
          ref.read(transactionsProvider.notifier).refreshWithSync(),
      child: Column(
        children: [
          // Syncing indicator
          if (txnState.isSyncing) const LinearProgressIndicator(),

          // Transaction count header
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
            child: Row(
              children: [
                Text(
                  '${txnState.total} transaction${txnState.total == 1 ? '' : 's'}',
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: PennyColors.textOnDarkMuted,
                  ),
                ),
              ],
            ),
          ),

          // Transaction list
          Expanded(child: _TransactionListView(txnState: txnState)),
        ],
      ),
    );
  }
}

class _TransactionListView extends ConsumerStatefulWidget {
  final TransactionsState txnState;

  const _TransactionListView({required this.txnState});

  @override
  ConsumerState<_TransactionListView> createState() =>
      _TransactionListViewState();
}

class _TransactionListViewState extends ConsumerState<_TransactionListView> {
  final _scrollController = ScrollController();

  @override
  void initState() {
    super.initState();
    _scrollController.addListener(_onScroll);
  }

  @override
  void dispose() {
    _scrollController.removeListener(_onScroll);
    _scrollController.dispose();
    super.dispose();
  }

  void _onScroll() {
    if (_scrollController.position.pixels >=
        _scrollController.position.maxScrollExtent - 200) {
      ref.read(transactionsProvider.notifier).loadMore();
    }
  }

  @override
  Widget build(BuildContext context) {
    final transactions = widget.txnState.transactions;

    return ListView.builder(
      controller: _scrollController,
      padding: const EdgeInsets.only(bottom: 16),
      itemCount: transactions.length + (widget.txnState.hasMore ? 1 : 0),
      itemBuilder: (context, index) {
        if (index >= transactions.length) {
          // Loading indicator for next page.
          return const Padding(
            padding: EdgeInsets.symmetric(vertical: 16),
            child: Center(child: CircularProgressIndicator()),
          );
        }

        final txn = transactions[index];
        final showDateHeader =
            index == 0 ||
            !_isSameDay(transactions[index - 1].timestamp, txn.timestamp);

        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (showDateHeader) _DateHeader(date: txn.timestamp),
            _TransactionTile(transaction: txn),
          ],
        );
      },
    );
  }

  bool _isSameDay(DateTime a, DateTime b) {
    return a.year == b.year && a.month == b.month && a.day == b.day;
  }
}

class _DateHeader extends StatelessWidget {
  final DateTime date;

  const _DateHeader({required this.date});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 4),
      child: Text(
        _formatDate(date),
        style: Theme.of(context).textTheme.labelLarge?.copyWith(
          color: PennyColors.textOnDarkMuted,
          fontWeight: FontWeight.w600,
        ),
      ),
    );
  }

  String _formatDate(DateTime date) {
    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day);
    final target = DateTime(date.year, date.month, date.day);
    final diff = today.difference(target).inDays;

    if (diff == 0) return 'Today';
    if (diff == 1) return 'Yesterday';
    if (diff < 7) return _weekdayName(date.weekday);

    const months = [
      '',
      'Jan',
      'Feb',
      'Mar',
      'Apr',
      'May',
      'Jun',
      'Jul',
      'Aug',
      'Sep',
      'Oct',
      'Nov',
      'Dec',
    ];
    return '${date.day} ${months[date.month]} ${date.year}';
  }

  String _weekdayName(int weekday) {
    const days = [
      '',
      'Monday',
      'Tuesday',
      'Wednesday',
      'Thursday',
      'Friday',
      'Saturday',
      'Sunday',
    ];
    return days[weekday];
  }
}

class _TransactionTile extends StatelessWidget {
  final Transaction transaction;

  const _TransactionTile({required this.transaction});

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 3),
      child: ListTile(
        leading: CircleAvatar(
          backgroundColor: PennyColors.categoryColor(
            transaction.category ?? 'General',
          ).withValues(alpha: 0.15),
          child: Icon(
            _categoryIcon(transaction.category),
            color: PennyColors.categoryColor(transaction.category ?? 'General'),
            size: 20,
          ),
        ),
        title: Text(
          transaction.merchantName ?? transaction.description,
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
        ),
        subtitle: Text(
          transaction.category ?? 'Uncategorised',
          style: Theme.of(
            context,
          ).textTheme.bodySmall?.copyWith(color: PennyColors.textOnDarkMuted),
        ),
        trailing: Text(
          transaction.formattedAmount,
          style: Theme.of(context).textTheme.titleMedium?.copyWith(
            color: transaction.isCredit ? PennyColors.positiveBright : null,
            fontWeight: FontWeight.w600,
          ),
        ),
        onTap: () {
          Navigator.of(context).push(
            MaterialPageRoute(
              builder: (_) => TransactionDetailScreen(transaction: transaction),
            ),
          );
        },
      ),
    );
  }

  IconData _categoryIcon(String? category) {
    switch (category) {
      case 'Groceries':
        return Icons.shopping_cart;
      case 'Eating Out':
        return Icons.restaurant;
      case 'Transport':
        return Icons.directions_bus;
      case 'Shopping':
        return Icons.shopping_bag;
      case 'Bills & Subscriptions':
        return Icons.receipt_long;
      case 'Salary & Income':
        return Icons.account_balance_wallet;
      case 'Transfers':
        return Icons.swap_horiz;
      case 'Cash & ATM':
        return Icons.local_atm;
      case 'Entertainment':
        return Icons.movie;
      case 'Health & Fitness':
        return Icons.fitness_center;
      case 'General':
        return Icons.category;
      default:
        return Icons.circle_outlined;
    }
  }
}

class _EmptyView extends StatelessWidget {
  final Future<void> Function() onRefresh;

  const _EmptyView({required this.onRefresh});

  @override
  Widget build(BuildContext context) {
    return RefreshIndicator(
      onRefresh: onRefresh,
      child: ListView(
        children: [
          const SizedBox(height: 120),
          Center(
            child: Column(
              children: [
                Icon(
                  Icons.receipt_long,
                  size: 64,
                  color: PennyColors.textOnDarkMuted,
                ),
                const SizedBox(height: 16),
                Text(
                  'No transactions yet',
                  style: Theme.of(context).textTheme.titleMedium?.copyWith(
                    color: PennyColors.textOnDarkMuted,
                  ),
                ),
                const SizedBox(height: 8),
                Text(
                  'Connect a bank and pull down to sync.',
                  style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                    color: PennyColors.textOnDarkMuted,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _ErrorView extends ConsumerWidget {
  final Object error;

  const _ErrorView({required this.error});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final message = error is ApiException
        ? (error as ApiException).message
        : '$error';

    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32.0),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(
              Icons.error_outline,
              size: 48,
              color: PennyColors.negativeBright,
            ),
            const SizedBox(height: 16),
            Text(
              'Failed to load transactions',
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 8),
            Text(message, textAlign: TextAlign.center),
            const SizedBox(height: 16),
            OutlinedButton.icon(
              onPressed: () => ref.invalidate(transactionsProvider),
              icon: const Icon(Icons.refresh),
              label: const Text('Retry'),
            ),
          ],
        ),
      ),
    );
  }
}
