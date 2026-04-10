/// Data model for a bank connection returned by the backend.
///
/// Mirrors the backend's [ConnectionOut] Pydantic schema. Used by
/// the connections provider and UI screens.
library;

class BankConnection {
  final String id;
  final String providerId;
  final String providerName;
  final String status;
  final DateTime? lastSyncedAt;
  final DateTime consentCreatedAt;
  final DateTime consentExpiresAt;
  final String? errorMessage;
  final DateTime createdAt;

  const BankConnection({
    required this.id,
    required this.providerId,
    required this.providerName,
    required this.status,
    this.lastSyncedAt,
    required this.consentCreatedAt,
    required this.consentExpiresAt,
    this.errorMessage,
    required this.createdAt,
  });

  /// Create a [BankConnection] from the JSON map returned by the API.
  factory BankConnection.fromJson(Map<String, dynamic> json) {
    return BankConnection(
      id: json['id'] as String,
      providerId: json['provider_id'] as String,
      providerName: json['provider_name'] as String,
      status: json['status'] as String,
      lastSyncedAt: json['last_synced_at'] != null
          ? DateTime.parse(json['last_synced_at'] as String)
          : null,
      consentCreatedAt: DateTime.parse(json['consent_created_at'] as String),
      consentExpiresAt: DateTime.parse(json['consent_expires_at'] as String),
      errorMessage: json['error_message'] as String?,
      createdAt: DateTime.parse(json['created_at'] as String),
    );
  }

  /// Serialise to JSON for local caching.
  Map<String, dynamic> toJson() => {
    'id': id,
    'provider_id': providerId,
    'provider_name': providerName,
    'status': status,
    'last_synced_at': lastSyncedAt?.toIso8601String(),
    'consent_created_at': consentCreatedAt.toIso8601String(),
    'consent_expires_at': consentExpiresAt.toIso8601String(),
    'error_message': errorMessage,
    'created_at': createdAt.toIso8601String(),
  };

  /// Whether the consent is still valid.
  bool get isConsentValid => consentExpiresAt.isAfter(DateTime.now());

  /// Number of days until consent expires (negative if already expired).
  int get daysUntilExpiry => consentExpiresAt.difference(DateTime.now()).inDays;

  /// Whether the backend has marked this connection as expiring soon.
  bool get isExpiringSoon => status == 'expiring_soon';

  /// Whether the backend has marked this connection as expired.
  bool get isExpired => status == 'expired';

  /// Whether the connection needs user action to reconnect
  /// (expiring soon or already expired).
  bool get needsReconnect => isExpiringSoon || isExpired;

  /// Human-readable status label for the UI.
  String get statusLabel {
    switch (status) {
      case 'active':
        return 'Connected';
      case 'expiring_soon':
        return 'Expiring Soon';
      case 'expired':
        return 'Expired';
      case 'revoked':
        return 'Revoked';
      case 'error':
        return 'Error';
      default:
        return status;
    }
  }
}
