/// Penny — UK Personal Finance Aggregator
///
/// Application entry point. Initialises:
/// 1. Environment variables (flutter_dotenv)
/// 2. Supabase SDK (auth, database)
/// 3. Deep link service (TrueLayer OAuth callback)
/// 4. Riverpod for state management
/// 5. Auth gate for session-aware routing
library;

import 'package:flutter/material.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import 'config/app_config.dart';
import 'providers/connections_provider.dart';
import 'screens/auth_gate.dart';
import 'services/deep_link_service.dart';

/// Global deep link service instance.
///
/// Initialised in [main] and wired to the connections provider in
/// [_DeepLinkHandler].
final deepLinkService = DeepLinkService();

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

  // Load environment variables from .env file.
  await dotenv.load(fileName: '.env');

  // Init Supabase with the publishable (anon) key.
  // SDK handles session persistence, token refresh, and
  // secure storage of the JWT automatically.
  await Supabase.initialize(
    url: AppConfig.supabaseUrl,
    anonKey: AppConfig.supabasePublishableKey,
  );

  // listen for incoming deep links (pennyapp://callback).
  await deepLinkService.init();

  runApp(
    // Wrap the entire app in a ProviderScope so all widgets
    // can access Riverpod providers.
    const ProviderScope(child: PennyApp()),
  );
}

class PennyApp extends StatelessWidget {
  const PennyApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Penny',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(
          seedColor: Colors.deepPurple,
          brightness: Brightness.light,
        ),
        useMaterial3: true,
        inputDecorationTheme: const InputDecorationTheme(
          border: OutlineInputBorder(),
          contentPadding: EdgeInsets.symmetric(horizontal: 16, vertical: 14),
        ),
      ),
      home: const _DeepLinkHandler(child: AuthGate()),
    );
  }
}

/// Invisible widget that wires the [DeepLinkService] to the
/// [ConnectionsNotifier] so incoming OAuth callbacks are processed.
///
/// Shows a [SnackBar] on success or failure so the user gets feedback
/// when they return to the app after authorising at their bank.
class _DeepLinkHandler extends ConsumerStatefulWidget {
  final Widget child;
  const _DeepLinkHandler({required this.child});

  @override
  ConsumerState<_DeepLinkHandler> createState() => _DeepLinkHandlerState();
}

class _DeepLinkHandlerState extends ConsumerState<_DeepLinkHandler> {
  @override
  void initState() {
    super.initState();
    deepLinkService.onCallbackReceived = _handleCallback;
  }

  @override
  void dispose() {
    deepLinkService.onCallbackReceived = null;
    super.dispose();
  }

  Future<void> _handleCallback(String code) async {
    // Only process if the user is signed in (has a session).
    final session = Supabase.instance.client.auth.currentSession;
    if (session == null) return;

    try {
      await ref.read(connectionsProvider.notifier).completeCallback(code);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Bank connected successfully!'),
            backgroundColor: Colors.green,
          ),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Failed to connect bank: $e'),
            backgroundColor: Colors.red,
          ),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return widget.child;
  }
}
