/// Penny — UK Personal Finance Aggregator
///
/// Application entry point. Initialises:
/// 1. Environment variables (flutter_dotenv)
/// 2. Supabase SDK (auth, database)
/// 3. Riverpod for state management
/// 4. Auth gate for session-aware routing
library;

import 'package:flutter/material.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import 'config/app_config.dart';
import 'screens/auth_gate.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

  // Load environment variables from .env file.
  await dotenv.load(fileName: '.env');

  // Initialise Supabase with the publishable (anon) key.
  // The SDK handles session persistence, token refresh, and
  // secure storage of the JWT automatically.
  await Supabase.initialize(
    url: AppConfig.supabaseUrl,
    anonKey: AppConfig.supabasePublishableKey,
  );

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
      home: const AuthGate(),
    );
  }
}
