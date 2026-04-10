/// Penny — UK Personal Finance Aggregator
///
/// Application entry point. Initialises:
/// 1. Environment variables (flutter_dotenv)
/// 2. Supabase SDK (auth, database)
/// 3. Deep link service (TrueLayer OAuth callback)
/// 4. Riverpod for state management
/// 5. Branded splash screen during startup
/// 6. Auth gate for session-aware routing
library;

import 'package:flutter/material.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import 'config/app_config.dart';
import 'providers/connections_provider.dart';
import 'screens/auth_gate.dart';
import 'services/deep_link_service.dart';
import 'theme/penny_colors.dart';
import 'theme/penny_theme.dart';

/// Global deep link service instance.
///
/// Initialised in [main] and wired to the connections provider in
/// [_DeepLinkHandler].
final deepLinkService = DeepLinkService();

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

  // Show branded splash immediately, before async init completes.
  runApp(const ProviderScope(child: PennyApp()));
}

/// Handles async initialisation that was previously in [main].
///
/// Returns true once complete so the splash screen can transition
/// to the auth gate.
Future<void> _initApp() async {
  // Load environment variables from .env file.
  await dotenv.load(fileName: '.env');

  // Init Supabase with the publishable (anon) key.
  await Supabase.initialize(
    url: AppConfig.supabaseUrl,
    anonKey: AppConfig.supabasePublishableKey,
  );

  // listen for incoming deep links (pennyapp://callback).
  await deepLinkService.init();

  // Pre-warm Google Fonts so Inter is fetched before the first frame.
  await GoogleFonts.pendingFonts([
    GoogleFonts.inter(),
    GoogleFonts.inter(fontWeight: FontWeight.w500),
    GoogleFonts.inter(fontWeight: FontWeight.w600),
    GoogleFonts.inter(fontWeight: FontWeight.w700),
    GoogleFonts.jetBrainsMono(fontWeight: FontWeight.w700),
  ]);
}

class PennyApp extends StatefulWidget {
  const PennyApp({super.key});

  @override
  State<PennyApp> createState() => _PennyAppState();
}

class _PennyAppState extends State<PennyApp> {
  bool _ready = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _bootstrap();
  }

  Future<void> _bootstrap() async {
    try {
      await _initApp();
      if (mounted) setState(() => _ready = true);
    } catch (e) {
      if (mounted) setState(() => _error = e.toString());
    }
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Penny',
      debugShowCheckedModeBanner: false,
      theme: PennyTheme.dark,
      home: _ready
          ? const _DeepLinkHandler(child: AuthGate())
          : _SplashScreen(error: _error, onRetry: _bootstrap),
    );
  }
}

/// Branded splash screen shown during app startup.
///
/// Displays the Penny logo (a coin icon) and name with a subtle
/// loading indicator. If initialisation fails, shows the error
/// with a retry button.
class _SplashScreen extends StatelessWidget {
  final String? error;
  final VoidCallback onRetry;

  const _SplashScreen({this.error, required this.onRetry});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: PennyColors.surfaceDark,
      body: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            // Coin icon as logo placeholder.
            Container(
              width: 96,
              height: 96,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                gradient: LinearGradient(
                  begin: Alignment.topLeft,
                  end: Alignment.bottomRight,
                  colors: [PennyColors.primary, PennyColors.primaryAccent],
                ),
              ),
              child: const Icon(
                Icons.monetization_on_rounded,
                size: 56,
                color: PennyColors.onPrimary,
              ),
            ),
            const SizedBox(height: 24),
            Text(
              'Penny',
              style: TextStyle(
                fontFamily: 'Inter',
                fontSize: 32,
                fontWeight: FontWeight.w700,
                color: PennyColors.textOnDark,
                letterSpacing: -0.5,
              ),
            ),
            const SizedBox(height: 8),
            Text(
              'Your finances, simplified.',
              style: TextStyle(
                fontFamily: 'Inter',
                fontSize: 14,
                color: PennyColors.textOnDarkMuted,
              ),
            ),
            const SizedBox(height: 48),
            if (error != null) ...[
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 32),
                child: Text(
                  'Failed to start: $error',
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    color: PennyColors.negativeBright,
                    fontSize: 13,
                  ),
                ),
              ),
              const SizedBox(height: 16),
              OutlinedButton.icon(
                onPressed: onRetry,
                icon: const Icon(Icons.refresh),
                label: const Text('Retry'),
              ),
            ] else
              const SizedBox(
                width: 24,
                height: 24,
                child: CircularProgressIndicator(
                  strokeWidth: 2.5,
                  color: PennyColors.primaryAccent,
                ),
              ),
          ],
        ),
      ),
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
            backgroundColor: PennyColors.positive,
          ),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Failed to connect bank: $e'),
            backgroundColor: PennyColors.negative,
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
