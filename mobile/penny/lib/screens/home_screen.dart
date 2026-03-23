/// Home screen shown after successful authentication.
///
/// Displays the user's email, a summary of connected banks, and
/// quick actions to connect a bank or view connections.
/// Sprint 4 will add the full net worth dashboard here.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import '../providers/auth_provider.dart';
import '../providers/connections_provider.dart';
import 'connections_screen.dart';

class HomeScreen extends ConsumerWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final user = Supabase.instance.client.auth.currentUser;
    final connectionsAsync = ref.watch(connectionsProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Penny'),
        actions: [
          IconButton(
            icon: const Icon(Icons.account_balance),
            tooltip: 'Bank Connections',
            onPressed: () {
              Navigator.of(context).push(
                MaterialPageRoute(builder: (_) => const ConnectionsScreen()),
              );
            },
          ),
          IconButton(
            icon: const Icon(Icons.logout),
            tooltip: 'Sign out',
            onPressed: () async {
              final authService = ref.read(authServiceProvider);
              await authService.signOut();
              // Auth gate will handle navigation back to login.
            },
          ),
        ],
      ),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(24.0),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const SizedBox(height: 32),
              // Welcome card
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(24.0),
                  child: Column(
                    children: [
                      const Icon(
                        Icons.account_balance_wallet,
                        size: 48,
                        color: Colors.deepPurple,
                      ),
                      const SizedBox(height: 16),
                      Text(
                        'Welcome!',
                        style: Theme.of(context).textTheme.headlineSmall,
                      ),
                      const SizedBox(height: 8),
                      Text(
                        user?.email ?? 'Unknown user',
                        style: Theme.of(context).textTheme.bodyLarge?.copyWith(
                          color: Colors.grey[600],
                        ),
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 24),

              // Connected banks summary card
              connectionsAsync.when(
                data: (connections) => _BanksSummaryCard(
                  connectionCount: connections.length,
                  onTap: () {
                    Navigator.of(context).push(
                      MaterialPageRoute(
                        builder: (_) => const ConnectionsScreen(),
                      ),
                    );
                  },
                ),
                loading: () => const Card(
                  child: Padding(
                    padding: EdgeInsets.all(24.0),
                    child: Center(child: CircularProgressIndicator()),
                  ),
                ),
                error: (_, _) => Card(
                  child: Padding(
                    padding: const EdgeInsets.all(24.0),
                    child: Text(
                      'Could not load bank connections.',
                      style: TextStyle(color: Colors.red[400]),
                    ),
                  ),
                ),
              ),

              const SizedBox(height: 24),

              // Placeholder for future dashboard content
              Expanded(
                child: Center(
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Icon(
                        Icons.construction,
                        size: 64,
                        color: Colors.grey[400],
                      ),
                      const SizedBox(height: 16),
                      Text(
                        'Dashboard coming in Sprint 4',
                        style: Theme.of(context).textTheme.titleMedium
                            ?.copyWith(color: Colors.grey[500]),
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Sub-widgets
// ---------------------------------------------------------------------------

class _BanksSummaryCard extends StatelessWidget {
  final int connectionCount;
  final VoidCallback onTap;

  const _BanksSummaryCard({required this.connectionCount, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return Card(
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(12),
        child: Padding(
          padding: const EdgeInsets.all(20.0),
          child: Row(
            children: [
              Icon(
                Icons.account_balance,
                size: 36,
                color: connectionCount > 0 ? Colors.green : Colors.grey[400],
              ),
              const SizedBox(width: 16),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      connectionCount > 0
                          ? '$connectionCount bank${connectionCount == 1 ? '' : 's'} connected'
                          : 'No banks connected',
                      style: Theme.of(context).textTheme.titleMedium,
                    ),
                    const SizedBox(height: 4),
                    Text(
                      connectionCount > 0
                          ? 'Tap to manage your bank connections'
                          : 'Tap to connect your first bank account',
                      style: Theme.of(
                        context,
                      ).textTheme.bodySmall?.copyWith(color: Colors.grey[600]),
                    ),
                  ],
                ),
              ),
              const Icon(Icons.chevron_right),
            ],
          ),
        ),
      ),
    );
  }
}
