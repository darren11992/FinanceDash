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

  /// Whether the consent is still valid.
  bool get isConsentValid => consentExpiresAt.isAfter(DateTime.now());

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
