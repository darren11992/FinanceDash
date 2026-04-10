/// Data models for the net worth API responses.
///
/// Mirrors the backend's [NetWorthOut], [NetWorthAccountBreakdown],
/// [NetWorthHistoryPoint], and [NetWorthHistoryOut] Pydantic schemas.
library;

/// Per-account contribution to net worth.
class NetWorthAccountBreakdown {
  final String accountId;
  final String displayName;
  final String accountType;
  final double? currentBalance;
  final String currency;
  final bool isLiability;

  const NetWorthAccountBreakdown({
    required this.accountId,
    required this.displayName,
    required this.accountType,
    this.currentBalance,
    this.currency = 'GBP',
    required this.isLiability,
  });

  factory NetWorthAccountBreakdown.fromJson(Map<String, dynamic> json) {
    return NetWorthAccountBreakdown(
      accountId: json['account_id'] as String,
      displayName: json['display_name'] as String,
      accountType: json['account_type'] as String,
      currentBalance: _parseDouble(json['current_balance']),
      currency: (json['currency'] as String?) ?? 'GBP',
      isLiability: json['is_liability'] as bool,
    );
  }

  /// Serialise to JSON for local caching.
  Map<String, dynamic> toJson() => {
    'account_id': accountId,
    'display_name': displayName,
    'account_type': accountType,
    'current_balance': currentBalance,
    'currency': currency,
    'is_liability': isLiability,
  };

  /// Human-readable account type label.
  String get accountTypeLabel {
    switch (accountType) {
      case 'current':
        return 'Current Account';
      case 'savings':
        return 'Savings Account';
      case 'credit_card':
        return 'Credit Card';
      default:
        return accountType;
    }
  }
}

/// Response for GET /api/v1/net-worth/.
class NetWorth {
  final double totalNetWorth;
  final String currency;
  final List<NetWorthAccountBreakdown> accounts;
  final DateTime? lastUpdated;

  const NetWorth({
    required this.totalNetWorth,
    this.currency = 'GBP',
    required this.accounts,
    this.lastUpdated,
  });

  /// Serialise to JSON for local caching.
  Map<String, dynamic> toJson() => {
    'total_net_worth': totalNetWorth,
    'currency': currency,
    'accounts': accounts.map((a) => a.toJson()).toList(),
    'last_updated': lastUpdated?.toIso8601String(),
  };

  factory NetWorth.fromJson(Map<String, dynamic> json) {
    return NetWorth(
      totalNetWorth: _parseDouble(json['total_net_worth']) ?? 0.0,
      currency: (json['currency'] as String?) ?? 'GBP',
      accounts: (json['accounts'] as List<dynamic>)
          .map(
            (a) => NetWorthAccountBreakdown.fromJson(a as Map<String, dynamic>),
          )
          .toList(),
      lastUpdated: json['last_updated'] != null
          ? DateTime.parse(json['last_updated'] as String)
          : null,
    );
  }

  /// Accounts that contribute positively (current, savings).
  List<NetWorthAccountBreakdown> get assets =>
      accounts.where((a) => !a.isLiability).toList();

  /// Accounts that contribute negatively (credit cards).
  List<NetWorthAccountBreakdown> get liabilities =>
      accounts.where((a) => a.isLiability).toList();

  /// Total assets value.
  double get totalAssets =>
      assets.fold(0.0, (sum, a) => sum + (a.currentBalance ?? 0.0));

  /// Total liabilities value (as a positive number).
  double get totalLiabilities =>
      liabilities.fold(0.0, (sum, a) => sum + (a.currentBalance ?? 0.0));
}

/// A single data point in the net worth trend.
class NetWorthHistoryPoint {
  final DateTime date;
  final double netWorth;
  final bool isEstimated;

  const NetWorthHistoryPoint({
    required this.date,
    required this.netWorth,
    this.isEstimated = false,
  });

  /// Serialise to JSON for local caching.
  Map<String, dynamic> toJson() => {
    'date': date.toIso8601String(),
    'net_worth': netWorth,
    'is_estimated': isEstimated,
  };

  factory NetWorthHistoryPoint.fromJson(Map<String, dynamic> json) {
    return NetWorthHistoryPoint(
      date: DateTime.parse(json['date'] as String),
      netWorth: _parseDouble(json['net_worth']) ?? 0.0,
      isEstimated: (json['is_estimated'] as bool?) ?? false,
    );
  }
}

/// Response for GET /api/v1/net-worth/history.
class NetWorthHistory {
  final String period;
  final List<NetWorthHistoryPoint> dataPoints;
  final String currency;

  const NetWorthHistory({
    required this.period,
    required this.dataPoints,
    this.currency = 'GBP',
  });

  /// Serialise to JSON for local caching.
  Map<String, dynamic> toJson() => {
    'period': period,
    'data_points': dataPoints.map((p) => p.toJson()).toList(),
    'currency': currency,
  };

  factory NetWorthHistory.fromJson(Map<String, dynamic> json) {
    return NetWorthHistory(
      period: json['period'] as String,
      dataPoints: (json['data_points'] as List<dynamic>)
          .map((p) => NetWorthHistoryPoint.fromJson(p as Map<String, dynamic>))
          .toList(),
      currency: (json['currency'] as String?) ?? 'GBP',
    );
  }

  /// Whether there is any data to chart.
  bool get hasData => dataPoints.isNotEmpty;

  /// Whether any data points are estimated (reverse-computed from transactions).
  bool get hasEstimatedData => dataPoints.any((p) => p.isEstimated);

  /// Change from earliest to latest data point.
  double? get changeAbsolute {
    if (dataPoints.length < 2) return null;
    return dataPoints.last.netWorth - dataPoints.first.netWorth;
  }

  /// Percentage change from earliest to latest data point.
  double? get changePercent {
    if (dataPoints.length < 2) return null;
    final first = dataPoints.first.netWorth;
    if (first == 0) return null;
    return ((dataPoints.last.netWorth - first) / first) * 100;
  }
}

// ---------------------------------------------------------------------------
// Shared helper
// ---------------------------------------------------------------------------

/// Parse a numeric value that may arrive as [num] or [String] from the API.
///
/// Supabase PostgREST returns NUMERIC columns as strings to preserve
/// precision. This helper handles both representations.
double? _parseDouble(dynamic value) {
  if (value == null) return null;
  if (value is num) return value.toDouble();
  if (value is String) {
    final parsed = double.tryParse(value);
    if (parsed != null) return parsed;
  }
  return null;
}
