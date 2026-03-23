/// HTTP service for communicating with the Penny FastAPI backend.
///
/// Automatically injects the current Supabase JWT as a Bearer token
/// on every request. All methods throw [ApiException] on non-2xx
/// responses so callers get structured error information.
library;

import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:supabase_flutter/supabase_flutter.dart';

import '../config/app_config.dart';

/// Exception thrown when the backend returns a non-2xx status code.
class ApiException implements Exception {
  final int statusCode;
  final String message;

  const ApiException({required this.statusCode, required this.message});

  @override
  String toString() => 'ApiException($statusCode): $message';
}

class ApiService {
  final http.Client _client;

  ApiService({http.Client? client}) : _client = client ?? http.Client();

  /// Base URL for the FastAPI backend (from .env).
  String get _baseUrl => AppConfig.apiBaseUrl;

  /// Build headers with the current Supabase access token.
  ///
  /// Throws [StateError] if there is no active session (user not logged in).
  Map<String, String> _authHeaders() {
    final session = Supabase.instance.client.auth.currentSession;
    if (session == null) {
      throw StateError('No active session — user must be signed in.');
    }
    return {
      'Authorization': 'Bearer ${session.accessToken}',
      'Content-Type': 'application/json',
    };
  }

  /// Parse a response, throwing [ApiException] on non-2xx status codes.
  dynamic _handleResponse(http.Response response) {
    if (response.statusCode >= 200 && response.statusCode < 300) {
      if (response.body.isEmpty) return null;
      return jsonDecode(response.body);
    }

    // Try to extract the "detail" field from FastAPI error responses.
    String message;
    try {
      final body = jsonDecode(response.body);
      message = body['detail'] ?? response.body;
    } catch (_) {
      message = response.body;
    }

    throw ApiException(statusCode: response.statusCode, message: message);
  }

  // -----------------------------------------------------------------------
  // Connections
  // -----------------------------------------------------------------------

  /// POST /api/v1/connections/initiate
  ///
  /// Returns the TrueLayer auth URL to open in a browser.
  Future<String> initiateConnection() async {
    final response = await _client.post(
      Uri.parse('$_baseUrl/api/v1/connections/initiate'),
      headers: _authHeaders(),
    );
    final data = _handleResponse(response) as Map<String, dynamic>;
    return data['auth_url'] as String;
  }

  /// POST /api/v1/connections/callback
  ///
  /// Sends the OAuth authorization code to the backend.
  /// Returns the connection metadata (id, provider_name, status).
  Future<Map<String, dynamic>> connectionCallback(String code) async {
    final response = await _client.post(
      Uri.parse('$_baseUrl/api/v1/connections/callback'),
      headers: _authHeaders(),
      body: jsonEncode({'code': code}),
    );
    return _handleResponse(response) as Map<String, dynamic>;
  }

  /// GET /api/v1/connections/
  ///
  /// Returns the list of bank connections for the authenticated user.
  Future<List<Map<String, dynamic>>> listConnections() async {
    final response = await _client.get(
      Uri.parse('$_baseUrl/api/v1/connections/'),
      headers: _authHeaders(),
    );
    final data = _handleResponse(response) as List<dynamic>;
    return data.cast<Map<String, dynamic>>();
  }

  /// DELETE /api/v1/connections/{connectionId}
  ///
  /// Disconnects a bank connection. Returns nothing (204).
  Future<void> deleteConnection(String connectionId) async {
    final response = await _client.delete(
      Uri.parse('$_baseUrl/api/v1/connections/$connectionId'),
      headers: _authHeaders(),
    );
    _handleResponse(response);
  }

  /// Clean up the HTTP client when the service is disposed.
  void dispose() {
    _client.close();
  }
}
