/// Data model for a transaction returned by the backend.
///
/// Mirrors the backend's [TransactionOut] Pydantic schema. The `category`
/// field is the effective category: user_category if overridden, otherwise
/// auto_category from the categorisation service.
library;

class Transaction {
  final String id;
  final String accountId;
  final DateTime timestamp;
  final String description;
  final double amount;
  final String currency;
  final String? transactionType;
  final String? merchantName;
  final String? category;
  final double? runningBalance;

  const Transaction({
    required this.id,
    required this.accountId,
    required this.timestamp,
    required this.description,
    required this.amount,
    this.currency = 'GBP',
    this.transactionType,
    this.merchantName,
    this.category,
    this.runningBalance,
  });

  /// Parse a numeric value that may arrive as [num] or [String] from the API.
  ///
  /// Supabase PostgREST returns `numeric` / `decimal` columns as strings
  /// to preserve precision. This helper handles both representations.
  static double _parseDouble(dynamic value) {
    if (value is num) return value.toDouble();
    if (value is String) return double.parse(value);
    throw FormatException('Cannot parse "$value" as double');
  }

  /// Create a [Transaction] from the JSON map returned by the API.
  factory Transaction.fromJson(Map<String, dynamic> json) {
    return Transaction(
      id: json['id'] as String,
      accountId: json['account_id'] as String,
      timestamp: DateTime.parse(json['timestamp'] as String),
      description: json['description'] as String,
      amount: _parseDouble(json['amount']),
      currency: (json['currency'] as String?) ?? 'GBP',
      transactionType: json['transaction_type'] as String?,
      merchantName: json['merchant_name'] as String?,
      category: json['category'] as String?,
      runningBalance: json['running_balance'] != null
          ? _parseDouble(json['running_balance'])
          : null,
    );
  }

  /// Serialise to JSON for local caching.
  Map<String, dynamic> toJson() => {
    'id': id,
    'account_id': accountId,
    'timestamp': timestamp.toIso8601String(),
    'description': description,
    'amount': amount,
    'currency': currency,
    'transaction_type': transactionType,
    'merchant_name': merchantName,
    'category': category,
    'running_balance': runningBalance,
  };

  /// Whether this is a debit (spend) transaction.
  bool get isDebit => amount < 0;

  /// Whether this is a credit (income) transaction.
  bool get isCredit => amount > 0;

  /// Display-friendly amount string with sign and currency symbol.
  String get formattedAmount {
    final sign = isCredit ? '+' : '';
    return '$sign$_currencySymbol${amount.abs().toStringAsFixed(2)}';
  }

  String get _currencySymbol {
    switch (currency) {
      case 'GBP':
        return '\u00A3'; // £
      case 'EUR':
        return '\u20AC'; // €
      case 'USD':
        return '\$';
      default:
        return '$currency ';
    }
  }
}

/// Response wrapper for paginated transaction lists.
class TransactionListResponse {
  final List<Transaction> transactions;
  final int total;
  final int page;
  final int pageSize;
  final bool hasMore;

  const TransactionListResponse({
    required this.transactions,
    required this.total,
    required this.page,
    required this.pageSize,
    required this.hasMore,
  });

  /// Serialise to JSON for local caching.
  Map<String, dynamic> toJson() => {
    'transactions': transactions.map((t) => t.toJson()).toList(),
    'total': total,
    'page': page,
    'page_size': pageSize,
    'has_more': hasMore,
  };

  factory TransactionListResponse.fromJson(Map<String, dynamic> json) {
    return TransactionListResponse(
      transactions: (json['transactions'] as List<dynamic>)
          .map((t) => Transaction.fromJson(t as Map<String, dynamic>))
          .toList(),
      total: json['total'] as int,
      page: json['page'] as int,
      pageSize: json['page_size'] as int,
      hasMore: json['has_more'] as bool,
    );
  }
}
