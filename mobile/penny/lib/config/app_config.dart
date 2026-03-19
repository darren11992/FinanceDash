/// App-wide configuration loaded from environment variables.
///
/// Uses flutter_dotenv to read `.env` at runtime. The [AppConfig] class
/// provides typed access to all configuration values with fail-fast
/// behaviour if a required variable is missing.
library;

import 'package:flutter_dotenv/flutter_dotenv.dart';

class AppConfig {
  /// Supabase project URL (e.g. https://xxxxx.supabase.co)
  static String get supabaseUrl => _require('SUPABASE_URL');

  /// Supabase publishable (anon) key — safe to embed in the client.
  /// Uses the new key format: sb_publishable_...
  static String get supabasePublishableKey =>
      _require('SUPABASE_PUBLISHABLE_KEY');

  /// FastAPI backend base URL (e.g. http://localhost:8000)
  static String get apiBaseUrl => _require('API_BASE_URL');

  /// Helper that throws a clear error if a variable is missing.
  static String _require(String key) {
    final value = dotenv.env[key];
    if (value == null || value.isEmpty) {
      throw StateError(
        'Missing required environment variable: $key. '
        'Check your .env file.',
      );
    }
    return value;
  }
}
