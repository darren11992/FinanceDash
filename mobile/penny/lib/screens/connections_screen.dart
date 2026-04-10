/// Bank connections screen.
///
/// Displays the user's connected bank accounts with status indicators
/// and provides the ability to:
/// - Connect a new bank via TrueLayer OAuth
/// - View connection details (provider, status, consent expiry)
/// - Disconnect a bank (with confirmation dialog)
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:url_launcher/url_launcher.dart';

import '../models/connection.dart';
import '../providers/connections_provider.dart';
import '../services/api_service.dart';
import '../theme/penny_colors.dart';
import '../widgets/skeleton_loaders.dart';

class ConnectionsScreen extends ConsumerStatefulWidget {
  const ConnectionsScreen({super.key});

  @override
  ConsumerState<ConnectionsScreen> createState() => _ConnectionsScreenState();
}

class _ConnectionsScreenState extends ConsumerState<ConnectionsScreen>
    with WidgetsBindingObserver {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // When the user returns from the browser after completing OAuth,
    // refresh the connections list to pick up the newly created connection
    // (the GET callback already ran sync + backfill on the backend).
    if (state == AppLifecycleState.resumed) {
      ref.invalidate(connectionsProvider);
    }
  }

  @override
  Widget build(BuildContext context) {
    final connectionsAsync = ref.watch(connectionsProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Bank Connections'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            tooltip: 'Refresh',
            onPressed: () => ref.read(connectionsProvider.notifier).refresh(),
          ),
        ],
      ),
      body: connectionsAsync.when(
        data: (connections) => _ConnectionsList(connections: connections),
        loading: () => const ConnectionsSkeleton(),
        error: (error, _) => _ErrorView(error: error),
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => _connectBank(context, ref),
        icon: const Icon(Icons.add),
        label: const Text('Connect Bank'),
        tooltip: 'Connect Bank',
      ),
    );
  }

  Future<void> _connectBank(BuildContext context, WidgetRef ref) async {
    // Show a loading indicator while we fetch the auth URL.
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(
        content: Text('Preparing bank connection...'),
        duration: Duration(seconds: 2),
      ),
    );

    try {
      final notifier = ref.read(connectionsProvider.notifier);
      final authUrl = await notifier.initiateConnection();

      final uri = Uri.parse(authUrl);
      if (await canLaunchUrl(uri)) {
        await launchUrl(uri, mode: LaunchMode.externalApplication);
      } else {
        if (context.mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text('Could not open the bank authorization page.'),
            ),
          );
        }
      }
    } on ApiException catch (e) {
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Failed to start connection: ${e.message}')),
        );
      }
    } catch (e) {
      if (context.mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('Error: $e')));
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Sub-widgets
// ---------------------------------------------------------------------------

class _ConnectionsList extends StatelessWidget {
  final List<BankConnection> connections;

  const _ConnectionsList({required this.connections});

  @override
  Widget build(BuildContext context) {
    if (connections.isEmpty) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(32.0),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(
                Icons.account_balance,
                size: 64,
                color: PennyColors.textOnDarkMuted,
              ),
              const SizedBox(height: 16),
              Text(
                'No banks connected yet',
                style: Theme.of(context).textTheme.titleMedium?.copyWith(
                  color: PennyColors.textOnDarkMuted,
                ),
              ),
              const SizedBox(height: 8),
              Text(
                'Tap the button below to connect your first bank account.',
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                  color: PennyColors.textOnDarkMuted,
                ),
              ),
            ],
          ),
        ),
      );
    }

    return RefreshIndicator(
      onRefresh: () async {
        // This is handled via the provider; the RefreshIndicator
        // expects a Future, but we trigger it from the widget tree.
        // Since this is a ConsumerWidget child, we can't access ref here.
        // The actual refresh is done via the AppBar refresh button.
      },
      child: ListView.builder(
        padding: const EdgeInsets.only(bottom: 88), // FAB clearance
        itemCount: connections.length,
        itemBuilder: (context, index) {
          return _ConnectionTile(connection: connections[index]);
        },
      ),
    );
  }
}

class _ConnectionTile extends ConsumerWidget {
  final BankConnection connection;

  const _ConnectionTile({required this.connection});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          ListTile(
            leading: CircleAvatar(
              backgroundColor: PennyColors.connectionStatus(
                connection.status,
              ).withValues(alpha: 0.15),
              child: Icon(
                Icons.account_balance,
                color: PennyColors.connectionStatus(connection.status),
              ),
            ),
            title: Text(connection.providerName),
            subtitle: Text(
              '${connection.statusLabel} · Expires ${_formatDate(connection.consentExpiresAt)}',
            ),
            trailing: IconButton(
              icon: Icon(Icons.delete_outline, color: PennyColors.negative),
              tooltip: 'Disconnect',
              onPressed: () => _confirmDisconnect(context, ref),
            ),
          ),

          // Reconnect banner for expiring_soon / expired connections.
          if (connection.needsReconnect)
            _ReconnectBanner(connection: connection),
        ],
      ),
    );
  }

  String _formatDate(DateTime date) {
    return '${date.day}/${date.month}/${date.year}';
  }

  Future<void> _confirmDisconnect(BuildContext context, WidgetRef ref) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Disconnect Bank'),
        content: Text(
          'Are you sure you want to disconnect ${connection.providerName}? '
          'This will remove all synced accounts and transactions for this bank.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('Cancel'),
          ),
          TextButton(
            onPressed: () => Navigator.of(context).pop(true),
            style: TextButton.styleFrom(foregroundColor: PennyColors.negative),
            child: const Text('Disconnect'),
          ),
        ],
      ),
    );

    if (confirmed == true) {
      try {
        await ref
            .read(connectionsProvider.notifier)
            .deleteConnection(connection.id);
        if (context.mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('${connection.providerName} disconnected.')),
          );
        }
      } on ApiException catch (e) {
        if (context.mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('Failed to disconnect: ${e.message}')),
          );
        }
      }
    }
  }
}

/// Inline banner shown on connection tiles that need reconnection.
///
/// Displays an amber (expiring_soon) or red (expired) strip with a
/// "Reconnect" button. Handles both reconnect outcomes:
/// - `no_action_needed`: shows success snackbar (list auto-refreshes).
/// - `authentication_needed`: launches the bank's auth URL in a browser.
class _ReconnectBanner extends ConsumerStatefulWidget {
  final BankConnection connection;

  const _ReconnectBanner({required this.connection});

  @override
  ConsumerState<_ReconnectBanner> createState() => _ReconnectBannerState();
}

class _ReconnectBannerState extends ConsumerState<_ReconnectBanner> {
  bool _loading = false;

  @override
  Widget build(BuildContext context) {
    final conn = widget.connection;
    final isExpired = conn.isExpired;
    final color = isExpired ? PennyColors.negative : PennyColors.warning;

    final String label;
    if (isExpired) {
      label = 'Connection expired — tap to reconnect';
    } else {
      final days = conn.daysUntilExpiry;
      label = 'Expires in $days day${days == 1 ? '' : 's'} — tap to renew';
    }

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.1),
        borderRadius: const BorderRadius.only(
          bottomLeft: Radius.circular(12),
          bottomRight: Radius.circular(12),
        ),
      ),
      child: Row(
        children: [
          Icon(Icons.warning_amber_rounded, size: 18, color: color),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              label,
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                color: color,
                fontWeight: FontWeight.w500,
              ),
            ),
          ),
          if (_loading)
            const SizedBox(
              width: 20,
              height: 20,
              child: CircularProgressIndicator(strokeWidth: 2),
            )
          else
            TextButton(
              onPressed: _reconnect,
              style: TextButton.styleFrom(
                foregroundColor: color,
                padding: const EdgeInsets.symmetric(horizontal: 12),
                visualDensity: VisualDensity.compact,
              ),
              child: const Text('Reconnect'),
            ),
        ],
      ),
    );
  }

  Future<void> _reconnect() async {
    setState(() => _loading = true);

    try {
      final result = await ref
          .read(connectionsProvider.notifier)
          .reconnectConnection(widget.connection.id);

      if (!mounted) return;

      final action = result['action'] as String?;
      final message = result['message'] as String? ?? '';

      if (action == 'authentication_needed') {
        final authUrl = result['auth_url'] as String?;
        if (authUrl != null) {
          final uri = Uri.parse(authUrl);
          if (await canLaunchUrl(uri)) {
            await launchUrl(uri, mode: LaunchMode.externalApplication);
          } else {
            if (mounted) {
              ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(
                  content: Text('Could not open the bank authorization page.'),
                ),
              );
            }
          }
        }
      } else {
        // no_action_needed — consent renewed silently.
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text(message)));
      }
    } on ApiException catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Reconnect failed: ${e.message}')),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('Error: $e')));
      }
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }
}

class _ErrorView extends ConsumerWidget {
  final Object error;

  const _ErrorView({required this.error});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final message = error is ApiException
        ? (error as ApiException).message
        : '$error';

    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32.0),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(
              Icons.error_outline,
              size: 48,
              color: PennyColors.negativeBright,
            ),
            const SizedBox(height: 16),
            Text(
              'Failed to load connections',
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 8),
            Text(message, textAlign: TextAlign.center),
            const SizedBox(height: 16),
            OutlinedButton.icon(
              onPressed: () => ref.invalidate(connectionsProvider),
              icon: const Icon(Icons.refresh),
              label: const Text('Retry'),
            ),
          ],
        ),
      ),
    );
  }
}
