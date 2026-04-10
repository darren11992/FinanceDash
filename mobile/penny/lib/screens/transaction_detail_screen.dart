/// Transaction detail screen — shows full transaction info and category picker.
///
/// Displays all available transaction fields and allows the user to
/// change the category via a bottom sheet picker. Category updates are
/// sent to the backend via PATCH and optimistically applied locally.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/transaction.dart';
import '../providers/transactions_provider.dart';
import '../services/api_service.dart';
import '../theme/penny_colors.dart';

/// All user-facing categories from the categorisation service.
///
/// Matches the values in backend/app/services/categorisation.py.
/// "General" is the default/fallback category.
const List<String> availableCategories = [
  'Groceries',
  'Eating Out',
  'Transport',
  'Shopping',
  'Bills & Subscriptions',
  'Salary & Income',
  'Transfers',
  'Cash & ATM',
  'Entertainment',
  'Health & Fitness',
  'General',
];

class TransactionDetailScreen extends ConsumerWidget {
  final Transaction transaction;

  const TransactionDetailScreen({super.key, required this.transaction});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // Watch the provider so category updates are reflected immediately.
    final txnState = ref.watch(transactionsProvider);
    final currentTxn = txnState.whenData((state) {
      try {
        return state.transactions.firstWhere((t) => t.id == transaction.id);
      } catch (_) {
        return transaction;
      }
    });

    final txn = currentTxn.valueOrNull ?? transaction;

    return Scaffold(
      appBar: AppBar(title: const Text('Transaction')),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Amount header
            _AmountHeader(transaction: txn),
            const SizedBox(height: 24),

            // Details card
            Card(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  children: [
                    _DetailRow(label: 'Description', value: txn.description),
                    if (txn.merchantName != null) ...[
                      const Divider(),
                      _DetailRow(label: 'Merchant', value: txn.merchantName!),
                    ],
                    const Divider(),
                    _DetailRow(
                      label: 'Date',
                      value: _formatDateTime(txn.timestamp),
                    ),
                    const Divider(),
                    _DetailRow(label: 'Amount', value: txn.formattedAmount),
                    if (txn.transactionType != null) ...[
                      const Divider(),
                      _DetailRow(label: 'Type', value: txn.transactionType!),
                    ],
                    if (txn.runningBalance != null) ...[
                      const Divider(),
                      _DetailRow(
                        label: 'Running Balance',
                        value:
                            '\u00A3${txn.runningBalance!.toStringAsFixed(2)}',
                      ),
                    ],
                    const Divider(),
                    _DetailRow(label: 'Currency', value: txn.currency),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 16),

            // Category section
            Card(
              child: ListTile(
                leading: const Icon(Icons.category),
                title: const Text('Category'),
                subtitle: Text(txn.category ?? 'Uncategorised'),
                trailing: const Icon(Icons.chevron_right),
                onTap: () => _showCategoryPicker(context, ref, txn),
              ),
            ),
            const SizedBox(height: 8),

            // Revert to auto category
            if (txn.category != null)
              Center(
                child: TextButton.icon(
                  onPressed: () => _updateCategory(context, ref, txn.id, null),
                  icon: const Icon(Icons.restore, size: 18),
                  label: const Text('Revert to auto-category'),
                ),
              ),
          ],
        ),
      ),
    );
  }

  void _showCategoryPicker(
    BuildContext context,
    WidgetRef ref,
    Transaction txn,
  ) {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
      ),
      builder: (context) => _CategoryPickerSheet(
        currentCategory: txn.category,
        onSelected: (category) {
          Navigator.of(context).pop();
          _updateCategory(context, ref, txn.id, category);
        },
      ),
    );
  }

  Future<void> _updateCategory(
    BuildContext context,
    WidgetRef ref,
    String transactionId,
    String? category,
  ) async {
    try {
      await ref
          .read(transactionsProvider.notifier)
          .updateCategory(transactionId, category);
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              category != null
                  ? 'Category set to $category'
                  : 'Reverted to auto-category',
            ),
          ),
        );
      }
    } on ApiException catch (e) {
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Failed to update category: ${e.message}')),
        );
      }
    }
  }

  String _formatDateTime(DateTime dt) {
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
    final time =
        '${dt.hour.toString().padLeft(2, '0')}:${dt.minute.toString().padLeft(2, '0')}';
    return '${dt.day} ${months[dt.month]} ${dt.year} at $time';
  }
}

// ---------------------------------------------------------------------------
// Sub-widgets
// ---------------------------------------------------------------------------

class _AmountHeader extends StatelessWidget {
  final Transaction transaction;

  const _AmountHeader({required this.transaction});

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        children: [
          Text(
            transaction.formattedAmount,
            style: Theme.of(context).textTheme.displaySmall?.copyWith(
              color: transaction.isCredit ? PennyColors.positiveBright : null,
              fontWeight: FontWeight.bold,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            transaction.merchantName ?? transaction.description,
            style: Theme.of(context).textTheme.titleMedium?.copyWith(
              color: PennyColors.textOnDarkMuted,
            ),
          ),
        ],
      ),
    );
  }
}

class _DetailRow extends StatelessWidget {
  final String label;
  final String value;

  const _DetailRow({required this.label, required this.value});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(
            label,
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
              color: PennyColors.textOnDarkMuted,
            ),
          ),
          Flexible(
            child: Text(
              value,
              textAlign: TextAlign.end,
              style: Theme.of(
                context,
              ).textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w500),
            ),
          ),
        ],
      ),
    );
  }
}

class _CategoryPickerSheet extends StatelessWidget {
  final String? currentCategory;
  final ValueChanged<String> onSelected;

  const _CategoryPickerSheet({
    required this.currentCategory,
    required this.onSelected,
  });

  @override
  Widget build(BuildContext context) {
    return DraggableScrollableSheet(
      initialChildSize: 0.6,
      minChildSize: 0.4,
      maxChildSize: 0.85,
      expand: false,
      builder: (context, scrollController) {
        return Column(
          children: [
            // Handle bar
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 12),
              child: Container(
                width: 40,
                height: 4,
                decoration: BoxDecoration(
                  color: PennyColors.textOnDarkMuted,
                  borderRadius: BorderRadius.circular(2),
                ),
              ),
            ),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: Text(
                'Choose a category',
                style: Theme.of(context).textTheme.titleLarge,
              ),
            ),
            const SizedBox(height: 8),
            Expanded(
              child: ListView.builder(
                controller: scrollController,
                itemCount: availableCategories.length,
                itemBuilder: (context, index) {
                  final category = availableCategories[index];
                  final isSelected = category == currentCategory;

                  return ListTile(
                    leading: CircleAvatar(
                      backgroundColor: PennyColors.categoryColor(
                        category,
                      ).withValues(alpha: 0.15),
                      child: Icon(
                        _categoryIcon(category),
                        color: PennyColors.categoryColor(category),
                        size: 20,
                      ),
                    ),
                    title: Text(category),
                    trailing: isSelected
                        ? const Icon(Icons.check, color: PennyColors.primary)
                        : null,
                    onTap: () => onSelected(category),
                  );
                },
              ),
            ),
          ],
        );
      },
    );
  }

  IconData _categoryIcon(String category) {
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
