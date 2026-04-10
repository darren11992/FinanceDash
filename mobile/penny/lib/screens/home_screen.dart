/// Dashboard home screen — the main view after authentication.
///
/// Displays:
/// - Net worth summary card (large formatted number, change indicator)
/// - Net worth trend chart (fl_chart, period toggle)
/// - Per-account breakdown (expandable, liabilities shown separately)
/// - Quick-action navigation (transactions, connections)
/// - Pull-to-refresh (triggers sync, refreshes all data)
/// - Loading, empty, and error states
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:intl/intl.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import '../models/connection.dart';
import '../models/net_worth.dart';
import '../providers/auth_provider.dart';
import '../providers/connections_provider.dart';
import '../providers/net_worth_provider.dart';
import '../providers/transactions_provider.dart';
import '../theme/penny_colors.dart';
import '../widgets/net_worth_chart.dart';
import '../widgets/skeleton_loaders.dart';
import 'connections_screen.dart';
import 'transactions_screen.dart';

class HomeScreen extends ConsumerWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final user = Supabase.instance.client.auth.currentUser;
    final connectionsAsync = ref.watch(connectionsProvider);
    final netWorthAsync = ref.watch(netWorthProvider);
    final historyAsync = ref.watch(netWorthHistoryProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Penny'),
        actions: [
          IconButton(
            icon: const Icon(Icons.receipt_long),
            tooltip: 'Transactions',
            onPressed: () {
              Navigator.of(context).push(
                MaterialPageRoute(builder: (_) => const TransactionsScreen()),
              );
            },
          ),
          IconButton(
            icon: const Icon(Icons.account_balance),
            tooltip: 'Bank Connections',
            onPressed: () {
              Navigator.of(context)
                  .push(
                    MaterialPageRoute(
                      builder: (_) => const ConnectionsScreen(),
                    ),
                  )
                  .then((_) {
                    // Refresh dashboard data in case a new bank was connected
                    // (sync runs during the GET callback, so data may be ready).
                    ref.invalidate(connectionsProvider);
                    ref.invalidate(netWorthProvider);
                    ref.invalidate(netWorthHistoryProvider);
                  });
            },
          ),
          IconButton(
            icon: const Icon(Icons.logout),
            tooltip: 'Sign out',
            onPressed: () async {
              final authService = ref.read(authServiceProvider);
              await authService.signOut();
            },
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: () => _onRefresh(ref),
        child: SafeArea(
          child: connectionsAsync.when(
            loading: () => const DashboardSkeleton(),
            error: (err, _) => _ErrorBody(
              message: 'Could not load your data.\n$err',
              onRetry: () {
                ref.invalidate(connectionsProvider);
                ref.invalidate(netWorthProvider);
                ref.invalidate(netWorthHistoryProvider);
              },
            ),
            data: (connections) {
              // No connections — show onboarding prompt.
              if (connections.isEmpty) {
                return _EmptyState(
                  email: user?.email,
                  onConnectBank: () {
                    Navigator.of(context)
                        .push(
                          MaterialPageRoute(
                            builder: (_) => const ConnectionsScreen(),
                          ),
                        )
                        .then((_) {
                          ref.invalidate(connectionsProvider);
                          ref.invalidate(netWorthProvider);
                          ref.invalidate(netWorthHistoryProvider);
                        });
                  },
                );
              }

              // Has connections — show full dashboard.
              return _DashboardBody(
                userEmail: user?.email,
                netWorthAsync: netWorthAsync,
                historyAsync: historyAsync,
                connections: connections,
              );
            },
          ),
        ),
      ),
    );
  }

  /// Pull-to-refresh: trigger sync, then refresh all providers.
  Future<void> _onRefresh(WidgetRef ref) async {
    try {
      final api = ref.read(apiServiceProvider);
      await api.triggerSync();
      // Brief pause to let the sync process data.
      await Future<void>.delayed(const Duration(seconds: 2));
    } catch (_) {
      // Non-fatal — still refresh the local data.
    }

    // Refresh all data providers.
    ref.invalidate(netWorthProvider);
    ref.invalidate(netWorthHistoryProvider);
    ref.invalidate(connectionsProvider);
    ref.invalidate(transactionsProvider);
  }
}

// ---------------------------------------------------------------------------
// Dashboard body (has data)
// ---------------------------------------------------------------------------

class _DashboardBody extends ConsumerWidget {
  final String? userEmail;
  final AsyncValue<NetWorth> netWorthAsync;
  final AsyncValue<NetWorthHistory> historyAsync;
  final List<BankConnection> connections;

  const _DashboardBody({
    this.userEmail,
    required this.netWorthAsync,
    required this.historyAsync,
    required this.connections,
  });

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // Connections that need user attention.
    final alertConnections = connections
        .where((c) => c.needsReconnect)
        .toList();

    return ListView(
      physics: const AlwaysScrollableScrollPhysics(),
      padding: EdgeInsets.zero,
      children: [
        // Expiry warning banners (if any connections need reconnection).
        if (alertConnections.isNotEmpty)
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
            child: Column(
              children: alertConnections
                  .map((conn) => _ExpiryBanner(connection: conn))
                  .toList(),
            ),
          ),

        // Hero gradient banner with greeting + net worth
        netWorthAsync.when(
          data: (netWorth) => _HeroBanner(
            netWorth: netWorth,
            historyAsync: historyAsync,
            userEmail: userEmail,
          ),
          loading: () => const HeroBannerSkeleton(),
          error: (err, _) => _ErrorCard(message: 'Failed to load net worth'),
        ),

        const SizedBox(height: 16),

        // Chart section
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: historyAsync.when(
            data: (history) => _ChartSection(history: history),
            loading: () => const ChartSkeleton(),
            error: (_, _) => const _ErrorCard(message: 'Failed to load chart'),
          ),
        ),

        const SizedBox(height: 16),

        // Account breakdown
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: netWorthAsync.when(
            data: (netWorth) => _AccountBreakdown(netWorth: netWorth),
            loading: () => const AccountBreakdownSkeleton(),
            error: (_, _) => const SizedBox.shrink(),
          ),
        ),

        const SizedBox(height: 16),

        // Quick actions
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: _QuickActionsRow(connectionCount: connections.length),
        ),

        const SizedBox(height: 24),
      ],
    );
  }
}

// ---------------------------------------------------------------------------
// Hero gradient banner (greeting + net worth + change pill)
// ---------------------------------------------------------------------------

class _HeroBanner extends StatelessWidget {
  final NetWorth netWorth;
  final AsyncValue<NetWorthHistory> historyAsync;
  final String? userEmail;

  const _HeroBanner({
    required this.netWorth,
    required this.historyAsync,
    this.userEmail,
  });

  @override
  Widget build(BuildContext context) {
    final formatted = _formatCurrency(netWorth.totalNetWorth);
    final greeting = _greeting();
    final displayName = _displayName();

    // Pull out the change values from history if available.
    final history = historyAsync.valueOrNull;
    final changeAbs = history?.changeAbsolute;
    final isPositive = (changeAbs ?? 0) >= 0;

    return Container(
      width: double.infinity,
      decoration: const BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topCenter,
          end: Alignment.bottomCenter,
          colors: [
            PennyColors.primary, // #1565C0 at top
            PennyColors.surfaceDark, // #0D1520 at bottom
          ],
        ),
      ),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(20, 12, 20, 24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Greeting row
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      greeting,
                      style: TextStyle(
                        color: PennyColors.primaryMuted,
                        fontSize: 14,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      displayName,
                      style: const TextStyle(
                        color: PennyColors.textOnDark,
                        fontSize: 20,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ],
                ),
                // Avatar circle
                Container(
                  width: 40,
                  height: 40,
                  decoration: const BoxDecoration(
                    color: PennyColors.surfaceDarkSecondary,
                    shape: BoxShape.circle,
                  ),
                  child: const Icon(
                    Icons.person,
                    color: PennyColors.primaryMuted,
                    size: 22,
                  ),
                ),
              ],
            ),

            const SizedBox(height: 16),

            // "Total Net Worth" label
            Center(
              child: Text(
                'Total Net Worth',
                style: TextStyle(color: PennyColors.primaryMuted, fontSize: 12),
              ),
            ),
            const SizedBox(height: 4),

            // Net worth amount in Geist Mono
            Center(
              child: Text(
                formatted,
                style: GoogleFonts.jetBrainsMono(
                  fontSize: 36,
                  fontWeight: FontWeight.w700,
                  color: netWorth.totalNetWorth >= 0
                      ? PennyColors.textOnDark
                      : PennyColors.negativeBright,
                ),
              ),
            ),

            const SizedBox(height: 8),

            // Change pill
            if (changeAbs != null)
              Center(
                child: Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 10,
                    vertical: 4,
                  ),
                  decoration: BoxDecoration(
                    color: isPositive
                        ? PennyColors.positive.withValues(alpha: 0.19)
                        : PennyColors.negative.withValues(alpha: 0.19),
                    borderRadius: BorderRadius.circular(100),
                  ),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(
                        isPositive ? Icons.trending_up : Icons.trending_down,
                        size: 14,
                        color: isPositive
                            ? PennyColors.positiveBright
                            : PennyColors.negativeBright,
                      ),
                      const SizedBox(width: 4),
                      Text(
                        '${isPositive ? '+' : ''}${_formatCurrency(changeAbs)} this ${_periodLabel(history?.period)}',
                        style: TextStyle(
                          fontSize: 12,
                          fontWeight: FontWeight.w500,
                          color: isPositive
                              ? PennyColors.positiveBright
                              : PennyColors.negativeBright,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }

  String _greeting() {
    final hour = DateTime.now().hour;
    if (hour < 12) return 'Good morning';
    if (hour < 17) return 'Good afternoon';
    return 'Good evening';
  }

  String _displayName() {
    if (userEmail == null) return '';
    // Use the part before @ as a display name, capitalised.
    final local = userEmail!.split('@').first;
    if (local.isEmpty) return '';
    return local[0].toUpperCase() + local.substring(1);
  }

  String _periodLabel(String? period) {
    return switch (period) {
      '7d' => 'week',
      '30d' => 'month',
      '90d' => '3 months',
      _ => 'week',
    };
  }
}

// ---------------------------------------------------------------------------
// Chart section with period toggle
// ---------------------------------------------------------------------------

class _ChartSection extends ConsumerWidget {
  final NetWorthHistory history;

  const _ChartSection({required this.history});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final selectedPeriod = ref.watch(netWorthPeriodProvider);

    return Card(
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text(
                  'Trend',
                  style: Theme.of(context).textTheme.titleSmall?.copyWith(
                    color: PennyColors.textOnDarkMuted,
                  ),
                ),
                // Change indicator
                if (history.changeAbsolute != null)
                  _ChangeIndicator(
                    changeAbsolute: history.changeAbsolute!,
                    changePercent: history.changePercent,
                  ),
              ],
            ),
            const SizedBox(height: 8),

            // Period toggle
            _PeriodToggle(
              selected: selectedPeriod,
              onChanged: (period) {
                ref.read(netWorthPeriodProvider.notifier).state = period;
              },
            ),

            const SizedBox(height: 12),

            // Chart
            if (history.hasData)
              NetWorthChart(history: history)
            else
              SizedBox(
                height: 200,
                child: Center(
                  child: Text(
                    'No data yet for this period.\nPull down to sync.',
                    textAlign: TextAlign.center,
                    style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                      color: PennyColors.textOnDarkMuted,
                    ),
                  ),
                ),
              ),

            // Estimated data note
            if (history.hasData && history.hasEstimatedData)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Row(
                  children: [
                    Icon(
                      Icons.info_outline,
                      size: 12,
                      color: PennyColors.textOnDarkMuted,
                    ),
                    const SizedBox(width: 4),
                    Expanded(
                      child: Text(
                        'Some values are estimated from transaction history',
                        style: Theme.of(context).textTheme.bodySmall?.copyWith(
                          color: PennyColors.textOnDarkMuted,
                          fontSize: 11,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
          ],
        ),
      ),
    );
  }
}

class _ChangeIndicator extends StatelessWidget {
  final double changeAbsolute;
  final double? changePercent;

  const _ChangeIndicator({required this.changeAbsolute, this.changePercent});

  @override
  Widget build(BuildContext context) {
    final isPositive = changeAbsolute >= 0;
    final color = isPositive
        ? PennyColors.positiveBright
        : PennyColors.negativeBright;
    final icon = isPositive ? Icons.arrow_upward : Icons.arrow_downward;

    final absFormatted = _formatCurrency(changeAbsolute.abs());
    final percentFormatted = changePercent != null
        ? '(${changePercent!.abs().toStringAsFixed(1)}%)'
        : '';

    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(icon, size: 16, color: color),
        const SizedBox(width: 2),
        Text(
          '$absFormatted $percentFormatted',
          style: Theme.of(context).textTheme.bodySmall?.copyWith(
            color: color,
            fontWeight: FontWeight.w600,
          ),
        ),
      ],
    );
  }
}

class _PeriodToggle extends StatelessWidget {
  final String selected;
  final ValueChanged<String> onChanged;

  const _PeriodToggle({required this.selected, required this.onChanged});

  static const _periods = ['7d', '30d', '90d'];

  @override
  Widget build(BuildContext context) {
    return Row(
      children: _periods.map((period) {
        final isSelected = period == selected;
        return Padding(
          padding: const EdgeInsets.only(right: 8),
          child: ChoiceChip(
            label: Text(period),
            selected: isSelected,
            onSelected: (_) => onChanged(period),
            visualDensity: VisualDensity.compact,
            labelStyle: TextStyle(
              fontSize: 12,
              fontWeight: isSelected ? FontWeight.w600 : FontWeight.normal,
            ),
          ),
        );
      }).toList(),
    );
  }
}

// ---------------------------------------------------------------------------
// Account breakdown
// ---------------------------------------------------------------------------

class _AccountBreakdown extends StatelessWidget {
  final NetWorth netWorth;

  const _AccountBreakdown({required this.netWorth});

  @override
  Widget build(BuildContext context) {
    if (netWorth.accounts.isEmpty) return const SizedBox.shrink();

    final assets = netWorth.assets;
    final liabilities = netWorth.liabilities;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // Assets section
        if (assets.isNotEmpty) ...[
          _SectionHeader(title: 'Accounts'),
          ...assets.map((a) => _AccountTile(account: a)),
        ],

        // Liabilities section
        if (liabilities.isNotEmpty) ...[
          const SizedBox(height: 12),
          _SectionHeader(title: 'Liabilities'),
          ...liabilities.map((a) => _AccountTile(account: a)),
        ],
      ],
    );
  }
}

class _SectionHeader extends StatelessWidget {
  final String title;

  const _SectionHeader({required this.title});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(left: 4, bottom: 8),
      child: Text(
        title,
        style: Theme.of(context).textTheme.titleSmall?.copyWith(
          color: PennyColors.textOnDarkMuted,
          letterSpacing: 0.5,
        ),
      ),
    );
  }
}

class _AccountTile extends StatelessWidget {
  final NetWorthAccountBreakdown account;

  const _AccountTile({required this.account});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final balance = account.currentBalance;
    final balanceStr = balance != null
        ? _formatCurrency(balance)
        : 'No balance';

    return Card(
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: BorderSide(color: theme.dividerColor.withValues(alpha: 0.3)),
      ),
      child: ListTile(
        leading: CircleAvatar(
          backgroundColor: _accountColor.withValues(alpha: 0.12),
          child: Icon(_accountIcon, color: _accountColor, size: 20),
        ),
        title: Text(
          account.displayName,
          style: theme.textTheme.bodyMedium?.copyWith(
            fontWeight: FontWeight.w500,
          ),
        ),
        subtitle: Text(
          account.accountTypeLabel,
          style: theme.textTheme.bodySmall?.copyWith(
            color: PennyColors.textOnDarkMuted,
          ),
        ),
        trailing: Text(
          account.isLiability ? '-$balanceStr' : balanceStr,
          style: theme.textTheme.titleSmall?.copyWith(
            fontWeight: FontWeight.w600,
            color: account.isLiability ? PennyColors.negativeBright : null,
          ),
        ),
      ),
    );
  }

  IconData get _accountIcon {
    switch (account.accountType) {
      case 'current':
        return Icons.account_balance;
      case 'savings':
        return Icons.savings;
      case 'credit_card':
        return Icons.credit_card;
      default:
        return Icons.account_balance_wallet;
    }
  }

  Color get _accountColor {
    switch (account.accountType) {
      case 'current':
        return PennyColors.primary;
      case 'savings':
        return PennyColors.positiveBright;
      case 'credit_card':
        return PennyColors.negativeBright;
      default:
        return PennyColors.textOnDarkMuted;
    }
  }
}

// ---------------------------------------------------------------------------
// Quick actions
// ---------------------------------------------------------------------------

class _QuickActionsRow extends StatelessWidget {
  final int connectionCount;

  const _QuickActionsRow({required this.connectionCount});

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Expanded(
          child: _QuickActionCard(
            icon: Icons.receipt_long,
            label: 'Transactions',
            color: PennyColors.primary,
            onTap: () {
              Navigator.of(context).push(
                MaterialPageRoute(builder: (_) => const TransactionsScreen()),
              );
            },
          ),
        ),
        const SizedBox(width: 12),
        Expanded(
          child: _QuickActionCard(
            icon: Icons.account_balance,
            label: '$connectionCount bank${connectionCount == 1 ? '' : 's'}',
            color: PennyColors.primaryAccent,
            onTap: () {
              Navigator.of(context).push(
                MaterialPageRoute(builder: (_) => const ConnectionsScreen()),
              );
            },
          ),
        ),
      ],
    );
  }
}

class _QuickActionCard extends StatelessWidget {
  final IconData icon;
  final String label;
  final Color color;
  final VoidCallback onTap;

  const _QuickActionCard({
    required this.icon,
    required this.label,
    required this.color,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Card(
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: BorderSide(
          color: Theme.of(context).dividerColor.withValues(alpha: 0.3),
        ),
      ),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(12),
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 16, horizontal: 12),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(icon, color: color, size: 20),
              const SizedBox(width: 8),
              Text(
                label,
                style: Theme.of(
                  context,
                ).textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w500),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Consent expiry banner (shown at top of dashboard)
// ---------------------------------------------------------------------------

/// Banner shown on the dashboard when a bank connection is expiring or expired.
///
/// Amber for `expiring_soon`, red for `expired`. Tapping navigates to the
/// connections screen where the user can trigger reconnection.
class _ExpiryBanner extends StatelessWidget {
  final BankConnection connection;

  const _ExpiryBanner({required this.connection});

  @override
  Widget build(BuildContext context) {
    final isExpired = connection.isExpired;
    final color = isExpired ? PennyColors.negative : PennyColors.warning;

    final String message;
    if (isExpired) {
      message =
          'Your ${connection.providerName} connection has expired. '
          'Reconnect to keep your data up to date.';
    } else {
      final days = connection.daysUntilExpiry;
      message =
          'Your ${connection.providerName} connection expires in '
          '$days day${days == 1 ? '' : 's'}.';
    }

    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Material(
        color: color.withValues(alpha: 0.1),
        borderRadius: BorderRadius.circular(12),
        child: InkWell(
          onTap: () {
            Navigator.of(context).push(
              MaterialPageRoute(builder: (_) => const ConnectionsScreen()),
            );
          },
          borderRadius: BorderRadius.circular(12),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
            child: Row(
              children: [
                Icon(
                  isExpired ? Icons.error_outline : Icons.warning_amber_rounded,
                  color: color,
                  size: 22,
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Text(
                    message,
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(
                      color: color,
                      fontWeight: FontWeight.w500,
                      height: 1.4,
                    ),
                  ),
                ),
                Icon(Icons.chevron_right, color: color, size: 20),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Empty state (no connections)
// ---------------------------------------------------------------------------

class _EmptyState extends StatelessWidget {
  final String? email;
  final VoidCallback onConnectBank;

  const _EmptyState({this.email, required this.onConnectBank});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return ListView(
      physics: const AlwaysScrollableScrollPhysics(),
      padding: const EdgeInsets.all(32),
      children: [
        const SizedBox(height: 48),
        Icon(
          Icons.account_balance_wallet,
          size: 80,
          color: PennyColors.primary.withValues(alpha: 0.3),
        ),
        const SizedBox(height: 24),
        Text(
          'Welcome to Penny!',
          textAlign: TextAlign.center,
          style: theme.textTheme.headlineSmall,
        ),
        if (email != null) ...[
          const SizedBox(height: 8),
          Text(
            email!,
            textAlign: TextAlign.center,
            style: theme.textTheme.bodyMedium?.copyWith(
              color: PennyColors.textOnDarkMuted,
            ),
          ),
        ],
        const SizedBox(height: 16),
        Text(
          'Connect your bank account to see your net worth, '
          'track spending, and manage your finances in one place.',
          textAlign: TextAlign.center,
          style: theme.textTheme.bodyMedium?.copyWith(
            color: PennyColors.textOnDarkMuted,
            height: 1.5,
          ),
        ),
        const SizedBox(height: 32),
        Center(
          child: FilledButton.icon(
            onPressed: onConnectBank,
            icon: const Icon(Icons.add),
            label: const Text('Connect a Bank'),
          ),
        ),
      ],
    );
  }
}

// ---------------------------------------------------------------------------
// Error / loading helpers
// ---------------------------------------------------------------------------

class _ErrorBody extends StatelessWidget {
  final String message;
  final VoidCallback onRetry;

  const _ErrorBody({required this.message, required this.onRetry});

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              Icons.error_outline,
              size: 48,
              color: PennyColors.negativeBright,
            ),
            const SizedBox(height: 16),
            Text(
              message,
              textAlign: TextAlign.center,
              style: TextStyle(color: PennyColors.negativeBright),
            ),
            const SizedBox(height: 16),
            OutlinedButton(onPressed: onRetry, child: const Text('Retry')),
          ],
        ),
      ),
    );
  }
}

class _ErrorCard extends StatelessWidget {
  final String message;

  const _ErrorCard({required this.message});

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Row(
          children: [
            Icon(Icons.error_outline, color: PennyColors.negativeBright),
            const SizedBox(width: 12),
            Expanded(
              child: Text(
                message,
                style: TextStyle(color: PennyColors.negativeBright),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Shared formatting
// ---------------------------------------------------------------------------

/// Format a value as GBP currency.
String _formatCurrency(double value) {
  final formatter = NumberFormat.currency(
    locale: 'en_GB',
    symbol: '\u00A3',
    decimalDigits: 2,
  );
  return formatter.format(value);
}
