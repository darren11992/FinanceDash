/// Riverpod providers for authentication state.
///
/// Provides:
/// - [authServiceProvider]: The [AuthService] singleton.
/// - [authStateProvider]: A stream of auth state changes that widgets
///   can watch to reactively update when the user signs in/out.
library;

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import '../services/auth_service.dart';

/// Provides the [AuthService] instance backed by the global Supabase client.
final authServiceProvider = Provider<AuthService>((ref) {
  return AuthService(Supabase.instance.client);
});

/// Stream provider that emits auth state changes.
///
/// Widgets can watch this to reactively switch between auth/unauth UI:
/// ```dart
/// final authState = ref.watch(authStateProvider);
/// ```
final authStateProvider = StreamProvider<AuthState>((ref) {
  final authService = ref.watch(authServiceProvider);
  return authService.onAuthStateChange;
});
