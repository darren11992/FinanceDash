/// Supabase authentication service.
///
/// Wraps the supabase_flutter SDK auth methods to provide a clean
/// interface for the rest of the app. All auth state (session storage,
/// token refresh) is handled automatically by the Supabase SDK.
library;

import 'package:supabase_flutter/supabase_flutter.dart';

class AuthService {
  final SupabaseClient _client;

  AuthService(this._client);

  /// The currently signed-in user, or null.
  User? get currentUser => _client.auth.currentUser;

  /// The current session, or null.
  Session? get currentSession => _client.auth.currentSession;

  /// Stream of auth state changes (sign in, sign out, token refresh).
  Stream<AuthState> get onAuthStateChange => _client.auth.onAuthStateChange;

  /// Sign up with email and password.
  ///
  /// Returns the [AuthResponse] which contains the user and session.
  /// Throws [AuthException] on failure (e.g. email already registered).
  Future<AuthResponse> signUp({
    required String email,
    required String password,
  }) async {
    return await _client.auth.signUp(email: email, password: password);
  }

  /// Sign in with email and password.
  ///
  /// Returns the [AuthResponse] which contains the user and session.
  /// Throws [AuthException] on failure (e.g. invalid credentials).
  Future<AuthResponse> signIn({
    required String email,
    required String password,
  }) async {
    return await _client.auth.signInWithPassword(
      email: email,
      password: password,
    );
  }

  /// Sign out the current user.
  ///
  /// Clears the local session. The Supabase SDK handles token
  /// invalidation on the server side.
  Future<void> signOut() async {
    await _client.auth.signOut();
  }
}
