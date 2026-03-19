/// Auth gate widget.
///
/// Listens to the Supabase auth state stream and routes the user to
/// either the login screen or the home screen. This is the root widget
/// below [MaterialApp] — all auth-dependent navigation flows through here.
///
/// The gate handles:
/// - Initial session check (is the user already logged in?)
/// - Reactive switching when the user signs in or out
/// - Loading state while the initial session is being resolved
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import 'home_screen.dart';
import 'login_screen.dart';

class AuthGate extends ConsumerWidget {
  const AuthGate({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // Check for an existing session on app launch.
    // The Supabase SDK persists the session to secure storage
    // automatically, so this handles the "already logged in" case.
    final session = Supabase.instance.client.auth.currentSession;

    // Also listen to the auth state stream for reactive updates.
    // This fires when the user signs in, signs out, or the token
    // is refreshed.
    ref.listen(_authStreamProvider, (_, next) {
      // Force a rebuild when auth state changes.
      // The session check below will pick up the new state.
    });

    if (session != null) {
      return const HomeScreen();
    }

    return const LoginScreen();
  }
}

/// Internal stream provider for auth state changes.
/// Used by [AuthGate] to trigger rebuilds.
final _authStreamProvider = StreamProvider<AuthState>((ref) {
  return Supabase.instance.client.auth.onAuthStateChange;
});
