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
/// - Invalidating the connections provider on auth change so it
///   refetches (or clears) when the user signs in/out
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import '../providers/connections_provider.dart';
import 'home_screen.dart';
import 'login_screen.dart';

class AuthGate extends ConsumerWidget {
  const AuthGate({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // Watch the auth state stream so the widget rebuilds on every
    // auth event (sign in, sign out, token refresh).
    final authState = ref.watch(_authStreamProvider);

    return authState.when(
      data: (state) {
        if (state.session != null) {
          // Invalidate connections so they refetch with the current session.
          // This handles: sign-in after the provider returned [] with no session,
          // and re-sign-in as a different user.
          ref.invalidate(connectionsProvider);
          return const HomeScreen();
        }
        return const LoginScreen();
      },
      loading: () =>
          const Scaffold(body: Center(child: CircularProgressIndicator())),
      error: (_, _) => const LoginScreen(),
    );
  }
}

/// Internal stream provider for auth state changes.
/// Used by [AuthGate] to trigger rebuilds.
final _authStreamProvider = StreamProvider<AuthState>((ref) {
  return Supabase.instance.client.auth.onAuthStateChange;
});
