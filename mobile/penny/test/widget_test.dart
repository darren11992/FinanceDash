// Widget tests for key Penny screens (Sprint 6 + Tier 1 expansion).
//
// These tests use Riverpod ProviderScope overrides to inject mock data,
// avoiding the need for Supabase initialisation or network calls.
//
// Coverage:
// - TransactionsScreen: loading, empty, data, error states
// - ConnectionsScreen: loading, empty, data, expiring/expired banners
// - HomeScreen: loading, empty, data, error, expiry banners, chart, accounts
// - TransactionDetailScreen: rendering, merchant, balance, category picker
// - Model unit tests: BankConnection, Transaction, NetWorth
// - Widget sub-components: _TransactionTile, _ConnectionTile

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_fonts/google_fonts.dart';

import 'package:penny/models/connection.dart';
import 'package:penny/models/net_worth.dart';
import 'package:penny/models/transaction.dart';
import 'package:penny/providers/auth_provider.dart';
import 'package:penny/providers/connections_provider.dart';
import 'package:penny/providers/net_worth_provider.dart';
import 'package:penny/providers/transactions_provider.dart';
import 'package:penny/screens/connections_screen.dart';
import 'package:penny/screens/home_screen.dart';
import 'package:penny/screens/transaction_detail_screen.dart';
import 'package:penny/screens/transactions_screen.dart';
import 'package:penny/services/api_service.dart';
import 'package:penny/services/auth_service.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:shimmer/shimmer.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

/// Wrap a widget in a MaterialApp + ProviderScope for testing.
Widget _testApp({required Widget child, List<Override> overrides = const []}) {
  return ProviderScope(
    overrides: overrides,
    child: MaterialApp(home: child),
  );
}

// -- Fake data ---------------------------------------------------------------

final _now = DateTime.now();

BankConnection _activeConnection({String? id, String? name}) => BankConnection(
  id: id ?? 'conn-1',
  providerId: 'uk-ob-natwest',
  providerName: name ?? 'NatWest',
  status: 'active',
  lastSyncedAt: _now,
  consentCreatedAt: _now.subtract(const Duration(days: 30)),
  consentExpiresAt: _now.add(const Duration(days: 60)),
  createdAt: _now.subtract(const Duration(days: 30)),
);

BankConnection _expiringConnection() => BankConnection(
  id: 'conn-expiring',
  providerId: 'uk-ob-hsbc',
  providerName: 'HSBC',
  status: 'expiring_soon',
  lastSyncedAt: _now,
  consentCreatedAt: _now.subtract(const Duration(days: 85)),
  consentExpiresAt: _now.add(const Duration(days: 5)),
  createdAt: _now.subtract(const Duration(days: 85)),
);

BankConnection _expiredConnection() => BankConnection(
  id: 'conn-expired',
  providerId: 'uk-ob-barclays',
  providerName: 'Barclays',
  status: 'expired',
  lastSyncedAt: _now.subtract(const Duration(days: 5)),
  consentCreatedAt: _now.subtract(const Duration(days: 95)),
  consentExpiresAt: _now.subtract(const Duration(days: 5)),
  createdAt: _now.subtract(const Duration(days: 95)),
);

Transaction _sampleTransaction({
  String? id,
  String? description,
  double? amount,
  String? category,
  String? merchantName,
}) => Transaction(
  id: id ?? 'txn-1',
  accountId: 'acct-1',
  timestamp: _now.subtract(const Duration(hours: 2)),
  description: description ?? 'CARD PAYMENT TO TESCO STORES ON 01-01-2026',
  amount: amount ?? -45.20,
  currency: 'GBP',
  transactionType: 'DEBIT',
  merchantName: merchantName,
  category: category ?? 'Groceries',
);

// -- Fake net worth data -----------------------------------------------------

NetWorth _sampleNetWorth() => NetWorth(
  totalNetWorth: 4250.75,
  currency: 'GBP',
  accounts: [
    const NetWorthAccountBreakdown(
      accountId: 'a1',
      displayName: 'Current Account',
      accountType: 'current',
      currentBalance: 4600.75,
      currency: 'GBP',
      isLiability: false,
    ),
    const NetWorthAccountBreakdown(
      accountId: 'a2',
      displayName: 'Credit Card',
      accountType: 'credit_card',
      currentBalance: 350.00,
      currency: 'GBP',
      isLiability: true,
    ),
  ],
);

NetWorthHistory _sampleHistory({String period = '30d'}) => NetWorthHistory(
  period: period,
  dataPoints: [
    NetWorthHistoryPoint(
      date: _now.subtract(const Duration(days: 30)),
      netWorth: 4000.00,
    ),
    NetWorthHistoryPoint(
      date: _now.subtract(const Duration(days: 15)),
      netWorth: 4100.00,
    ),
    NetWorthHistoryPoint(date: _now, netWorth: 4250.75),
  ],
);

const NetWorthHistory _emptyHistory = NetWorthHistory(
  period: '30d',
  dataPoints: [],
);

// -- Fake services -----------------------------------------------------------

/// Minimal [ApiService] substitute that returns no-ops for tests.
///
/// ApiService is a concrete class with no restrictive modifiers, so we can
/// extend it directly. The no-arg super constructor works because
/// ApiService({http.Client? client}) has an optional parameter.
class _FakeApiService extends ApiService {
  @override
  Future<Map<String, dynamic>> triggerSync() async => {'status': 'ok'};

  @override
  Future<Map<String, dynamic>> updateTransactionCategory(
    String transactionId,
    String? category,
  ) async => {'status': 'ok'};
}

/// Minimal [AuthService] substitute for tests.
///
/// Uses the already-initialized [Supabase.instance.client] (from setUpAll)
/// so no extra SupabaseClient is created (which would leak timers).
class _FakeAuthService extends AuthService {
  _FakeAuthService() : super(Supabase.instance.client);

  @override
  Future<void> signOut() async {}
}

/// Common overrides for HomeScreen tests.
///
/// HomeScreen watches 3 providers + authServiceProvider + apiServiceProvider.
/// Every HomeScreen testWidget must include at least these overrides.
List<Override> _homeOverrides({
  AsyncValue<List<BankConnection>>? connections,
  AsyncValue<NetWorth>? netWorth,
  AsyncValue<NetWorthHistory>? history,
}) {
  return [
    connectionsProvider.overrideWith(
      () => _StubConnectionsNotifier(connections ?? const AsyncValue.data([])),
    ),
    netWorthProvider.overrideWith(
      () =>
          _StubNetWorthNotifier(netWorth ?? AsyncValue.data(_sampleNetWorth())),
    ),
    netWorthHistoryProvider.overrideWith(
      () => _StubNetWorthHistoryNotifier(
        history ?? AsyncValue.data(_sampleHistory()),
      ),
    ),
    authServiceProvider.overrideWithValue(_FakeAuthService()),
    apiServiceProvider.overrideWithValue(_FakeApiService()),
  ];
}

// =========================================================================
// Model unit tests
// =========================================================================

void main() {
  // Disable Google Fonts network fetching for all tests.
  // Initialize Supabase with dummy values so Supabase.instance doesn't throw.
  // HomeScreen reads Supabase.instance.client.auth.currentUser directly.
  setUpAll(() async {
    GoogleFonts.config.allowRuntimeFetching = false;
    // Provide a fake SharedPreferences so Supabase.initialize() doesn't
    // crash on the missing platform channel.
    SharedPreferences.setMockInitialValues({});
    await Supabase.initialize(
      url: 'https://fake.supabase.co',
      anonKey: 'fake-anon-key',
    );
  });

  // ---------------------------------------------------------------------------
  // BankConnection model tests
  // ---------------------------------------------------------------------------

  group('BankConnection model', () {
    test('fromJson parses all fields correctly', () {
      final json = {
        'id': 'abc-123',
        'provider_id': 'uk-ob-natwest',
        'provider_name': 'NatWest',
        'status': 'active',
        'last_synced_at': '2026-01-15T10:00:00Z',
        'consent_created_at': '2025-10-15T10:00:00Z',
        'consent_expires_at': '2026-04-15T10:00:00Z',
        'error_message': null,
        'created_at': '2025-10-15T10:00:00Z',
      };

      final conn = BankConnection.fromJson(json);
      expect(conn.id, 'abc-123');
      expect(conn.providerId, 'uk-ob-natwest');
      expect(conn.providerName, 'NatWest');
      expect(conn.status, 'active');
      expect(conn.lastSyncedAt, isNotNull);
      expect(conn.errorMessage, isNull);
    });

    test('statusLabel returns correct labels', () {
      expect(_activeConnection().statusLabel, 'Connected');
      expect(_expiringConnection().statusLabel, 'Expiring Soon');
      expect(_expiredConnection().statusLabel, 'Expired');
    });

    test('needsReconnect is true for expiring and expired', () {
      expect(_activeConnection().needsReconnect, isFalse);
      expect(_expiringConnection().needsReconnect, isTrue);
      expect(_expiredConnection().needsReconnect, isTrue);
    });

    test('isExpired and isExpiringSoon flags', () {
      expect(_activeConnection().isExpired, isFalse);
      expect(_activeConnection().isExpiringSoon, isFalse);
      expect(_expiringConnection().isExpiringSoon, isTrue);
      expect(_expiredConnection().isExpired, isTrue);
    });

    test('daysUntilExpiry calculates correctly', () {
      final conn = _activeConnection();
      // Consent expires ~60 days from now, so should be ~60
      expect(conn.daysUntilExpiry, greaterThanOrEqualTo(59));
      expect(conn.daysUntilExpiry, lessThanOrEqualTo(61));
    });
  });

  // ---------------------------------------------------------------------------
  // Transaction model tests
  // ---------------------------------------------------------------------------

  group('Transaction model', () {
    test('fromJson parses all fields including string amounts', () {
      final json = {
        'id': 'txn-abc',
        'account_id': 'acct-1',
        'timestamp': '2026-01-15T10:00:00Z',
        'description': 'CARD PAYMENT TO TESCO',
        'amount': '-45.20', // String (PostgREST format)
        'currency': 'GBP',
        'transaction_type': 'DEBIT',
        'merchant_name': null,
        'category': 'Groceries',
        'running_balance': '1205.30',
      };

      final txn = Transaction.fromJson(json);
      expect(txn.id, 'txn-abc');
      expect(txn.amount, -45.20);
      expect(txn.runningBalance, 1205.30);
      expect(txn.currency, 'GBP');
      expect(txn.category, 'Groceries');
    });

    test('fromJson parses numeric amounts', () {
      final json = {
        'id': 'txn-num',
        'account_id': 'acct-1',
        'timestamp': '2026-01-15T10:00:00Z',
        'description': 'TEST',
        'amount': -99.99,
        'currency': 'GBP',
      };

      final txn = Transaction.fromJson(json);
      expect(txn.amount, -99.99);
    });

    test('isDebit and isCredit', () {
      final debit = _sampleTransaction(amount: -50.0);
      final credit = _sampleTransaction(amount: 1500.0);

      expect(debit.isDebit, isTrue);
      expect(debit.isCredit, isFalse);
      expect(credit.isDebit, isFalse);
      expect(credit.isCredit, isTrue);
    });

    test('formattedAmount includes sign and currency symbol', () {
      final debit = _sampleTransaction(amount: -45.20);
      final credit = _sampleTransaction(amount: 1500.00);

      expect(debit.formattedAmount, '\u00A345.20'); // £45.20 (no +)
      expect(credit.formattedAmount, '+\u00A31500.00'); // +£1500.00
    });
  });

  // ---------------------------------------------------------------------------
  // NetWorth model tests
  // ---------------------------------------------------------------------------

  group('NetWorth model', () {
    test('fromJson parses correctly with string amounts', () {
      final json = {
        'total_net_worth': '900.50',
        'currency': 'GBP',
        'accounts': [
          {
            'account_id': 'a1',
            'display_name': 'Current Account',
            'account_type': 'current',
            'current_balance': '1250.50',
            'currency': 'GBP',
            'is_liability': false,
          },
          {
            'account_id': 'a2',
            'display_name': 'Credit Card',
            'account_type': 'credit_card',
            'current_balance': '350.00',
            'currency': 'GBP',
            'is_liability': true,
          },
        ],
        'last_updated': '2026-01-15T10:00:00Z',
      };

      final nw = NetWorth.fromJson(json);
      expect(nw.totalNetWorth, 900.50);
      expect(nw.accounts.length, 2);
      expect(nw.assets.length, 1);
      expect(nw.liabilities.length, 1);
      expect(nw.totalAssets, 1250.50);
      expect(nw.totalLiabilities, 350.00);
    });

    test('accountTypeLabel returns correct labels', () {
      final account = NetWorthAccountBreakdown.fromJson({
        'account_id': 'a1',
        'display_name': 'Test',
        'account_type': 'current',
        'current_balance': '100',
        'currency': 'GBP',
        'is_liability': false,
      });
      expect(account.accountTypeLabel, 'Current Account');

      final card = NetWorthAccountBreakdown.fromJson({
        'account_id': 'a2',
        'display_name': 'Test Card',
        'account_type': 'credit_card',
        'current_balance': '100',
        'currency': 'GBP',
        'is_liability': true,
      });
      expect(card.accountTypeLabel, 'Credit Card');
    });
  });

  // ---------------------------------------------------------------------------
  // NetWorthHistory model tests
  // ---------------------------------------------------------------------------

  group('NetWorthHistory model', () {
    test('changeAbsolute and changePercent calculated correctly', () {
      final history = NetWorthHistory.fromJson({
        'period': '30d',
        'currency': 'GBP',
        'data_points': [
          {'date': '2026-01-01', 'net_worth': '1000.00', 'is_estimated': false},
          {'date': '2026-01-15', 'net_worth': '1100.00', 'is_estimated': false},
          {'date': '2026-01-30', 'net_worth': '1200.00', 'is_estimated': false},
        ],
      });

      expect(history.hasData, isTrue);
      expect(history.changeAbsolute, 200.0);
      expect(history.changePercent, 20.0);
    });

    test('empty history returns null for change values', () {
      final history = NetWorthHistory.fromJson({
        'period': '7d',
        'currency': 'GBP',
        'data_points': [],
      });

      expect(history.hasData, isFalse);
      expect(history.changeAbsolute, isNull);
      expect(history.changePercent, isNull);
    });

    test('hasEstimatedData detects estimated points', () {
      final history = NetWorthHistory.fromJson({
        'period': '30d',
        'currency': 'GBP',
        'data_points': [
          {'date': '2026-01-01', 'net_worth': '1000', 'is_estimated': false},
          {'date': '2026-01-15', 'net_worth': '1050', 'is_estimated': true},
        ],
      });

      expect(history.hasEstimatedData, isTrue);
    });
  });

  // ---------------------------------------------------------------------------
  // TransactionListResponse model tests
  // ---------------------------------------------------------------------------

  group('TransactionListResponse model', () {
    test('fromJson parses pagination metadata', () {
      final json = {
        'transactions': [
          {
            'id': 'txn-1',
            'account_id': 'acct-1',
            'timestamp': '2026-01-15T10:00:00Z',
            'description': 'TEST',
            'amount': '-10.00',
            'currency': 'GBP',
          },
        ],
        'total': 150,
        'page': 2,
        'page_size': 50,
        'has_more': true,
      };

      final response = TransactionListResponse.fromJson(json);
      expect(response.transactions.length, 1);
      expect(response.total, 150);
      expect(response.page, 2);
      expect(response.pageSize, 50);
      expect(response.hasMore, isTrue);
    });
  });

  // =========================================================================
  // TransactionsScreen widget tests
  // =========================================================================

  group('TransactionsScreen', () {
    testWidgets('shows shimmer skeleton while data loads', (tester) async {
      await tester.pumpWidget(
        _testApp(
          overrides: [
            transactionsProvider.overrideWith(
              () => _StubTransactionsNotifier(const AsyncValue.loading()),
            ),
          ],
          child: const TransactionsScreen(),
        ),
      );

      expect(find.byType(Shimmer), findsWidgets);
    });

    testWidgets('shows empty state when no transactions', (tester) async {
      await tester.pumpWidget(
        _testApp(
          overrides: [
            transactionsProvider.overrideWith(
              () => _StubTransactionsNotifier(
                const AsyncValue.data(TransactionsState()),
              ),
            ),
          ],
          child: const TransactionsScreen(),
        ),
      );

      await tester.pumpAndSettle();
      expect(find.text('No transactions yet'), findsOneWidget);
      expect(
        find.text('Connect a bank and pull down to sync.'),
        findsOneWidget,
      );
    });

    testWidgets('displays transactions with description and category', (
      tester,
    ) async {
      final txns = [
        _sampleTransaction(
          id: 'txn-1',
          description: 'CARD PAYMENT TO TESCO STORES ON 01-01-2026',
          amount: -45.20,
          category: 'Groceries',
        ),
        _sampleTransaction(
          id: 'txn-2',
          description: 'CARD PAYMENT TO COSTA ON 02-01-2026',
          amount: -4.50,
          category: 'Eating Out',
        ),
      ];

      await tester.pumpWidget(
        _testApp(
          overrides: [
            transactionsProvider.overrideWith(
              () => _StubTransactionsNotifier(
                AsyncValue.data(
                  TransactionsState(
                    transactions: txns,
                    total: 2,
                    currentPage: 1,
                    pageSize: 50,
                    hasMore: false,
                  ),
                ),
              ),
            ),
          ],
          child: const TransactionsScreen(),
        ),
      );

      await tester.pumpAndSettle();

      // Check transaction descriptions are shown
      expect(
        find.text('CARD PAYMENT TO TESCO STORES ON 01-01-2026'),
        findsOneWidget,
      );
      expect(find.text('CARD PAYMENT TO COSTA ON 02-01-2026'), findsOneWidget);

      // Check categories
      expect(find.text('Groceries'), findsOneWidget);
      expect(find.text('Eating Out'), findsOneWidget);

      // Check transaction count header
      expect(find.text('2 transactions'), findsOneWidget);
    });

    testWidgets('shows merchant name when available', (tester) async {
      final txn = _sampleTransaction(
        merchantName: 'Tesco',
        description: 'CARD PAYMENT TO TESCO STORES ON 01-01-2026',
      );

      await tester.pumpWidget(
        _testApp(
          overrides: [
            transactionsProvider.overrideWith(
              () => _StubTransactionsNotifier(
                AsyncValue.data(
                  TransactionsState(
                    transactions: [txn],
                    total: 1,
                    currentPage: 1,
                    pageSize: 50,
                    hasMore: false,
                  ),
                ),
              ),
            ),
          ],
          child: const TransactionsScreen(),
        ),
      );

      await tester.pumpAndSettle();

      // Should show merchant name as title, not the full description
      expect(find.text('Tesco'), findsOneWidget);
    });

    testWidgets('shows error state on load failure', (tester) async {
      await tester.pumpWidget(
        _testApp(
          overrides: [
            transactionsProvider.overrideWith(
              () => _StubTransactionsNotifier(
                AsyncValue.error(
                  const ApiException(
                    statusCode: 500,
                    message: 'Internal server error',
                  ),
                  StackTrace.current,
                ),
              ),
            ),
          ],
          child: const TransactionsScreen(),
        ),
      );

      await tester.pumpAndSettle();
      expect(find.text('Failed to load transactions'), findsOneWidget);
      expect(find.text('Internal server error'), findsOneWidget);
    });

    testWidgets('credit transactions show positive amount with colour', (
      tester,
    ) async {
      final txn = _sampleTransaction(
        amount: 1500.00,
        description: 'SALARY FROM EMPLOYER',
        category: 'Salary & Income',
      );

      await tester.pumpWidget(
        _testApp(
          overrides: [
            transactionsProvider.overrideWith(
              () => _StubTransactionsNotifier(
                AsyncValue.data(
                  TransactionsState(
                    transactions: [txn],
                    total: 1,
                    currentPage: 1,
                    pageSize: 50,
                    hasMore: false,
                  ),
                ),
              ),
            ),
          ],
          child: const TransactionsScreen(),
        ),
      );

      await tester.pumpAndSettle();

      // Credit amount should show with + prefix
      expect(find.text('+\u00A31500.00'), findsOneWidget);
    });

    testWidgets('singular transaction count uses correct grammar', (
      tester,
    ) async {
      await tester.pumpWidget(
        _testApp(
          overrides: [
            transactionsProvider.overrideWith(
              () => _StubTransactionsNotifier(
                AsyncValue.data(
                  TransactionsState(
                    transactions: [_sampleTransaction()],
                    total: 1,
                    currentPage: 1,
                    pageSize: 50,
                    hasMore: false,
                  ),
                ),
              ),
            ),
          ],
          child: const TransactionsScreen(),
        ),
      );

      await tester.pumpAndSettle();
      expect(find.text('1 transaction'), findsOneWidget);
    });
  });

  // =========================================================================
  // ConnectionsScreen widget tests
  // =========================================================================

  group('ConnectionsScreen', () {
    testWidgets('shows shimmer skeleton while data loads', (tester) async {
      await tester.pumpWidget(
        _testApp(
          overrides: [
            connectionsProvider.overrideWith(
              () => _StubConnectionsNotifier(const AsyncValue.loading()),
            ),
          ],
          child: const ConnectionsScreen(),
        ),
      );

      expect(find.byType(Shimmer), findsWidgets);
    });

    testWidgets('shows empty state when no connections', (tester) async {
      await tester.pumpWidget(
        _testApp(
          overrides: [
            connectionsProvider.overrideWith(
              () => _StubConnectionsNotifier(const AsyncValue.data([])),
            ),
          ],
          child: const ConnectionsScreen(),
        ),
      );

      await tester.pumpAndSettle();
      expect(find.text('No banks connected yet'), findsOneWidget);
      expect(
        find.text('Tap the button below to connect your first bank account.'),
        findsOneWidget,
      );
    });

    testWidgets('shows Connect Bank FAB', (tester) async {
      await tester.pumpWidget(
        _testApp(
          overrides: [
            connectionsProvider.overrideWith(
              () => _StubConnectionsNotifier(const AsyncValue.data([])),
            ),
          ],
          child: const ConnectionsScreen(),
        ),
      );

      await tester.pumpAndSettle();
      expect(find.text('Connect Bank'), findsOneWidget);
      expect(find.byType(FloatingActionButton), findsOneWidget);
    });

    testWidgets('displays active connection with correct info', (tester) async {
      final conn = _activeConnection();

      await tester.pumpWidget(
        _testApp(
          overrides: [
            connectionsProvider.overrideWith(
              () => _StubConnectionsNotifier(AsyncValue.data([conn])),
            ),
          ],
          child: const ConnectionsScreen(),
        ),
      );

      await tester.pumpAndSettle();

      // Provider name shown
      expect(find.text('NatWest'), findsOneWidget);

      // Status label includes 'Connected'
      expect(find.textContaining('Connected'), findsOneWidget);

      // No reconnect banner for active connections
      expect(find.text('Reconnect'), findsNothing);
    });

    testWidgets('shows reconnect banner for expiring connection', (
      tester,
    ) async {
      final conn = _expiringConnection();

      await tester.pumpWidget(
        _testApp(
          overrides: [
            connectionsProvider.overrideWith(
              () => _StubConnectionsNotifier(AsyncValue.data([conn])),
            ),
          ],
          child: const ConnectionsScreen(),
        ),
      );

      await tester.pumpAndSettle();

      // Provider name
      expect(find.text('HSBC'), findsOneWidget);

      // Reconnect banner should be visible
      expect(find.text('Reconnect'), findsOneWidget);

      // Should mention expiry
      expect(find.textContaining('Expires in'), findsAtLeast(1));
    });

    testWidgets('shows reconnect banner for expired connection', (
      tester,
    ) async {
      final conn = _expiredConnection();

      await tester.pumpWidget(
        _testApp(
          overrides: [
            connectionsProvider.overrideWith(
              () => _StubConnectionsNotifier(AsyncValue.data([conn])),
            ),
          ],
          child: const ConnectionsScreen(),
        ),
      );

      await tester.pumpAndSettle();

      // Provider name
      expect(find.text('Barclays'), findsOneWidget);

      // Should show expired banner
      expect(find.textContaining('expired'), findsAtLeast(1));
      expect(find.text('Reconnect'), findsOneWidget);
    });

    testWidgets('shows disconnect button on each connection tile', (
      tester,
    ) async {
      await tester.pumpWidget(
        _testApp(
          overrides: [
            connectionsProvider.overrideWith(
              () => _StubConnectionsNotifier(
                AsyncValue.data([_activeConnection()]),
              ),
            ),
          ],
          child: const ConnectionsScreen(),
        ),
      );

      await tester.pumpAndSettle();
      expect(find.byIcon(Icons.delete_outline), findsOneWidget);
    });

    testWidgets('shows multiple connections', (tester) async {
      await tester.pumpWidget(
        _testApp(
          overrides: [
            connectionsProvider.overrideWith(
              () => _StubConnectionsNotifier(
                AsyncValue.data([
                  _activeConnection(id: 'c1', name: 'NatWest'),
                  _activeConnection(id: 'c2', name: 'Monzo'),
                ]),
              ),
            ),
          ],
          child: const ConnectionsScreen(),
        ),
      );

      await tester.pumpAndSettle();
      expect(find.text('NatWest'), findsOneWidget);
      expect(find.text('Monzo'), findsOneWidget);
    });

    testWidgets('shows error state on load failure', (tester) async {
      await tester.pumpWidget(
        _testApp(
          overrides: [
            connectionsProvider.overrideWith(
              () => _StubConnectionsNotifier(
                AsyncValue.error(
                  const ApiException(
                    statusCode: 500,
                    message: 'Server unavailable',
                  ),
                  StackTrace.current,
                ),
              ),
            ),
          ],
          child: const ConnectionsScreen(),
        ),
      );

      await tester.pumpAndSettle();
      expect(find.text('Failed to load connections'), findsOneWidget);
      expect(find.text('Server unavailable'), findsOneWidget);
    });
  });

  // =========================================================================
  // ApiException tests
  // =========================================================================

  group('ApiException', () {
    test('toString includes status code and message', () {
      const e = ApiException(statusCode: 404, message: 'Not found');
      expect(e.toString(), 'ApiException(404): Not found');
    });

    test('implements Exception', () {
      const e = ApiException(statusCode: 500, message: 'Error');
      expect(e, isA<Exception>());
    });
  });

  // =========================================================================
  // HomeScreen widget tests
  // =========================================================================

  group('HomeScreen', () {
    testWidgets('shows DashboardSkeleton while connections load', (
      tester,
    ) async {
      await tester.pumpWidget(
        _testApp(
          overrides: _homeOverrides(connections: const AsyncValue.loading()),
          child: const HomeScreen(),
        ),
      );

      // DashboardSkeleton uses Shimmer widgets
      expect(find.byType(Shimmer), findsWidgets);
    });

    testWidgets('shows empty state when no connections', (tester) async {
      await tester.pumpWidget(
        _testApp(
          overrides: _homeOverrides(connections: const AsyncValue.data([])),
          child: const HomeScreen(),
        ),
      );

      await tester.pumpAndSettle();

      expect(find.text('Welcome to Penny!'), findsOneWidget);
      expect(find.text('Connect a Bank'), findsOneWidget);
    });

    testWidgets('shows error state with retry button', (tester) async {
      await tester.pumpWidget(
        _testApp(
          overrides: _homeOverrides(
            connections: AsyncValue.error(
              const ApiException(statusCode: 500, message: 'Server down'),
              StackTrace.current,
            ),
          ),
          child: const HomeScreen(),
        ),
      );

      await tester.pumpAndSettle();

      expect(find.textContaining('Could not load your data'), findsOneWidget);
      expect(find.text('Retry'), findsOneWidget);
    });

    testWidgets('renders hero banner with net worth value', (tester) async {
      await tester.pumpWidget(
        _testApp(
          overrides: _homeOverrides(
            connections: AsyncValue.data([_activeConnection()]),
            netWorth: AsyncValue.data(_sampleNetWorth()),
            history: AsyncValue.data(_sampleHistory()),
          ),
          child: const HomeScreen(),
        ),
      );

      await tester.pumpAndSettle();

      // "Total Net Worth" label should be present
      expect(find.text('Total Net Worth'), findsOneWidget);

      // The formatted net worth (£4,250.75) should appear
      expect(find.textContaining('4,250.75'), findsOneWidget);
    });

    testWidgets('shows HeroBannerSkeleton while net worth loads', (
      tester,
    ) async {
      await tester.pumpWidget(
        _testApp(
          overrides: _homeOverrides(
            connections: AsyncValue.data([_activeConnection()]),
            netWorth: const AsyncValue.loading(),
            history: AsyncValue.data(_sampleHistory()),
          ),
          child: const HomeScreen(),
        ),
      );

      // HeroBannerSkeleton uses Shimmer
      expect(find.byType(Shimmer), findsWidgets);
    });

    testWidgets('shows chart when history has data', (tester) async {
      await tester.pumpWidget(
        _testApp(
          overrides: _homeOverrides(
            connections: AsyncValue.data([_activeConnection()]),
            netWorth: AsyncValue.data(_sampleNetWorth()),
            history: AsyncValue.data(_sampleHistory()),
          ),
          child: const HomeScreen(),
        ),
      );

      await tester.pumpAndSettle();

      // The Trend label in the chart section
      expect(find.text('Trend'), findsOneWidget);

      // Period toggle chips should be visible
      expect(find.text('7d'), findsOneWidget);
      expect(find.text('30d'), findsOneWidget);
      expect(find.text('90d'), findsOneWidget);
    });

    testWidgets('shows "No data yet" when history is empty', (tester) async {
      await tester.pumpWidget(
        _testApp(
          overrides: _homeOverrides(
            connections: AsyncValue.data([_activeConnection()]),
            netWorth: AsyncValue.data(_sampleNetWorth()),
            history: const AsyncValue.data(_emptyHistory),
          ),
          child: const HomeScreen(),
        ),
      );

      await tester.pumpAndSettle();

      expect(
        find.textContaining('No data yet for this period'),
        findsOneWidget,
      );
    });

    testWidgets('account breakdown shows assets and liabilities', (
      tester,
    ) async {
      await tester.pumpWidget(
        _testApp(
          overrides: _homeOverrides(
            connections: AsyncValue.data([_activeConnection()]),
            netWorth: AsyncValue.data(_sampleNetWorth()),
            history: AsyncValue.data(_sampleHistory()),
          ),
          child: const HomeScreen(),
        ),
      );

      await tester.pumpAndSettle();

      // The account breakdown is near the bottom of the ListView and may be
      // off-screen. Scroll until the section header becomes visible.
      await tester.scrollUntilVisible(
        find.text('Accounts'),
        200,
        scrollable: find.byType(Scrollable).first,
      );

      // Section headers
      expect(find.text('Accounts'), findsOneWidget);
      expect(find.text('Liabilities'), findsOneWidget);

      // Account names — note: the account type subtitle may duplicate the
      // display name (e.g. displayName = 'Current Account' and
      // accountTypeLabel = 'Current Account'), so we expect at least one.
      expect(find.text('Current Account'), findsAtLeastNWidgets(1));
      expect(find.text('Credit Card'), findsAtLeastNWidgets(1));
    });

    testWidgets('expiry banner shown for expiring connections', (tester) async {
      await tester.pumpWidget(
        _testApp(
          overrides: _homeOverrides(
            connections: AsyncValue.data([
              _activeConnection(),
              _expiringConnection(),
            ]),
            netWorth: AsyncValue.data(_sampleNetWorth()),
            history: AsyncValue.data(_sampleHistory()),
          ),
          child: const HomeScreen(),
        ),
      );

      await tester.pumpAndSettle();

      // Should show a banner mentioning HSBC expiry
      expect(find.textContaining('HSBC'), findsOneWidget);
      expect(find.textContaining('expires in'), findsOneWidget);
    });

    testWidgets('quick actions row shows correct labels', (tester) async {
      await tester.pumpWidget(
        _testApp(
          overrides: _homeOverrides(
            connections: AsyncValue.data([
              _activeConnection(id: 'c1', name: 'NatWest'),
              _activeConnection(id: 'c2', name: 'Monzo'),
            ]),
            netWorth: AsyncValue.data(_sampleNetWorth()),
            history: AsyncValue.data(_sampleHistory()),
          ),
          child: const HomeScreen(),
        ),
      );

      await tester.pumpAndSettle();

      // Quick actions are at the very bottom of the ListView — scroll to them.
      await tester.scrollUntilVisible(
        find.text('Transactions'),
        200,
        scrollable: find.byType(Scrollable).first,
      );

      // Quick action labels
      expect(find.text('Transactions'), findsOneWidget);
      expect(find.text('2 banks'), findsOneWidget);
    });

    testWidgets('AppBar has tooltips for accessibility', (tester) async {
      await tester.pumpWidget(
        _testApp(
          overrides: _homeOverrides(
            connections: AsyncValue.data([_activeConnection()]),
          ),
          child: const HomeScreen(),
        ),
      );

      await tester.pumpAndSettle();

      // The 3 AppBar action icons should have tooltips
      expect(find.byTooltip('Transactions'), findsOneWidget);
      expect(find.byTooltip('Bank Connections'), findsOneWidget);
      expect(find.byTooltip('Sign out'), findsOneWidget);
    });
  });

  // =========================================================================
  // TransactionDetailScreen widget tests
  // =========================================================================

  group('TransactionDetailScreen', () {
    testWidgets('displays transaction amount, description, category', (
      tester,
    ) async {
      final txn = _sampleTransaction(
        amount: -45.20,
        description: 'CARD PAYMENT TO TESCO STORES ON 01-01-2026',
        category: 'Groceries',
      );

      await tester.pumpWidget(
        _testApp(
          overrides: [
            transactionsProvider.overrideWith(
              () => _StubTransactionsNotifier(
                AsyncValue.data(
                  TransactionsState(
                    transactions: [txn],
                    total: 1,
                    currentPage: 1,
                    pageSize: 50,
                    hasMore: false,
                  ),
                ),
              ),
            ),
            apiServiceProvider.overrideWithValue(_FakeApiService()),
          ],
          child: TransactionDetailScreen(transaction: txn),
        ),
      );

      await tester.pumpAndSettle();

      // Amount header
      expect(find.text('\u00A345.20'), findsWidgets);

      // Description in detail row
      expect(
        find.text('CARD PAYMENT TO TESCO STORES ON 01-01-2026'),
        findsWidgets,
      );

      // Category
      expect(find.text('Groceries'), findsOneWidget);
    });

    testWidgets('shows merchant name row when present', (tester) async {
      final txn = _sampleTransaction(merchantName: 'Tesco');

      await tester.pumpWidget(
        _testApp(
          overrides: [
            transactionsProvider.overrideWith(
              () => _StubTransactionsNotifier(
                AsyncValue.data(
                  TransactionsState(
                    transactions: [txn],
                    total: 1,
                    currentPage: 1,
                    pageSize: 50,
                    hasMore: false,
                  ),
                ),
              ),
            ),
            apiServiceProvider.overrideWithValue(_FakeApiService()),
          ],
          child: TransactionDetailScreen(transaction: txn),
        ),
      );

      await tester.pumpAndSettle();

      // "Merchant" label and value should both be present
      expect(find.text('Merchant'), findsOneWidget);
      expect(find.text('Tesco'), findsWidgets);
    });

    testWidgets('hides merchant row when null', (tester) async {
      final txn = _sampleTransaction(merchantName: null);

      await tester.pumpWidget(
        _testApp(
          overrides: [
            transactionsProvider.overrideWith(
              () => _StubTransactionsNotifier(
                AsyncValue.data(
                  TransactionsState(
                    transactions: [txn],
                    total: 1,
                    currentPage: 1,
                    pageSize: 50,
                    hasMore: false,
                  ),
                ),
              ),
            ),
            apiServiceProvider.overrideWithValue(_FakeApiService()),
          ],
          child: TransactionDetailScreen(transaction: txn),
        ),
      );

      await tester.pumpAndSettle();

      // "Merchant" label should NOT appear
      expect(find.text('Merchant'), findsNothing);
    });

    testWidgets('shows running balance when present', (tester) async {
      final txn = Transaction(
        id: 'txn-rb',
        accountId: 'acct-1',
        timestamp: _now,
        description: 'TEST PAYMENT',
        amount: -20.00,
        currency: 'GBP',
        runningBalance: 1205.30,
      );

      await tester.pumpWidget(
        _testApp(
          overrides: [
            transactionsProvider.overrideWith(
              () => _StubTransactionsNotifier(
                AsyncValue.data(
                  TransactionsState(
                    transactions: [txn],
                    total: 1,
                    currentPage: 1,
                    pageSize: 50,
                    hasMore: false,
                  ),
                ),
              ),
            ),
            apiServiceProvider.overrideWithValue(_FakeApiService()),
          ],
          child: TransactionDetailScreen(transaction: txn),
        ),
      );

      await tester.pumpAndSettle();

      expect(find.text('Running Balance'), findsOneWidget);
      expect(find.text('\u00A31205.30'), findsOneWidget);
    });

    testWidgets('category tap opens bottom sheet picker', (tester) async {
      final txn = _sampleTransaction(category: 'Groceries');

      await tester.pumpWidget(
        _testApp(
          overrides: [
            transactionsProvider.overrideWith(
              () => _StubTransactionsNotifier(
                AsyncValue.data(
                  TransactionsState(
                    transactions: [txn],
                    total: 1,
                    currentPage: 1,
                    pageSize: 50,
                    hasMore: false,
                  ),
                ),
              ),
            ),
            apiServiceProvider.overrideWithValue(_FakeApiService()),
          ],
          child: TransactionDetailScreen(transaction: txn),
        ),
      );

      await tester.pumpAndSettle();

      // Tap the category ListTile (has chevron_right trailing icon)
      final categoryTile = find.widgetWithText(ListTile, 'Category');
      expect(categoryTile, findsOneWidget);
      await tester.tap(categoryTile);
      await tester.pumpAndSettle();

      // Bottom sheet should show "Choose a category"
      expect(find.text('Choose a category'), findsOneWidget);
    });

    testWidgets('all 11 categories shown in picker', (tester) async {
      final txn = _sampleTransaction(category: 'Groceries');

      await tester.pumpWidget(
        _testApp(
          overrides: [
            transactionsProvider.overrideWith(
              () => _StubTransactionsNotifier(
                AsyncValue.data(
                  TransactionsState(
                    transactions: [txn],
                    total: 1,
                    currentPage: 1,
                    pageSize: 50,
                    hasMore: false,
                  ),
                ),
              ),
            ),
            apiServiceProvider.overrideWithValue(_FakeApiService()),
          ],
          child: TransactionDetailScreen(transaction: txn),
        ),
      );

      await tester.pumpAndSettle();

      // Open the category picker
      await tester.tap(find.widgetWithText(ListTile, 'Category'));
      await tester.pumpAndSettle();

      // Verify all categories from availableCategories are shown.
      // Some may need scrolling in the DraggableScrollableSheet.
      for (final category in availableCategories) {
        final finder = find.text(category);
        // Scroll until visible if needed
        if (finder.evaluate().isEmpty) {
          await tester.dragUntilVisible(
            finder,
            find.byType(ListView).last,
            const Offset(0, -100),
          );
        }
        expect(finder, findsWidgets);
      }
    });

    testWidgets('"Revert to auto-category" button visible', (tester) async {
      final txn = _sampleTransaction(category: 'Groceries');

      await tester.pumpWidget(
        _testApp(
          overrides: [
            transactionsProvider.overrideWith(
              () => _StubTransactionsNotifier(
                AsyncValue.data(
                  TransactionsState(
                    transactions: [txn],
                    total: 1,
                    currentPage: 1,
                    pageSize: 50,
                    hasMore: false,
                  ),
                ),
              ),
            ),
            apiServiceProvider.overrideWithValue(_FakeApiService()),
          ],
          child: TransactionDetailScreen(transaction: txn),
        ),
      );

      await tester.pumpAndSettle();

      expect(find.text('Revert to auto-category'), findsOneWidget);
      expect(find.byIcon(Icons.restore), findsOneWidget);
    });
  });
}

// ===========================================================================
// Stub notifiers for provider overrides
// ===========================================================================

/// Stub [TransactionsNotifier] that returns a fixed [AsyncValue].
class _StubTransactionsNotifier extends TransactionsNotifier {
  final AsyncValue<TransactionsState> _value;

  _StubTransactionsNotifier(this._value);

  @override
  Future<TransactionsState> build() async {
    state = _value;
    // If the value is an error, throw so Riverpod propagates it.
    if (_value is AsyncError<TransactionsState>) {
      throw _value.asError!.error;
    }
    return _value.valueOrNull ?? const TransactionsState();
  }
}

/// Stub [ConnectionsNotifier] that returns a fixed [AsyncValue].
class _StubConnectionsNotifier extends ConnectionsNotifier {
  final AsyncValue<List<BankConnection>> _value;

  _StubConnectionsNotifier(this._value);

  @override
  Future<List<BankConnection>> build() async {
    state = _value;
    // If the value is an error, throw so Riverpod propagates it.
    if (_value is AsyncError<List<BankConnection>>) {
      throw _value.asError!.error;
    }
    return _value.valueOrNull ?? [];
  }
}

/// Stub [NetWorthNotifier] that returns a fixed [AsyncValue].
class _StubNetWorthNotifier extends NetWorthNotifier {
  final AsyncValue<NetWorth> _value;

  _StubNetWorthNotifier(this._value);

  @override
  Future<NetWorth> build() async {
    state = _value;
    if (_value is AsyncError<NetWorth>) {
      throw _value.asError!.error;
    }
    return _value.valueOrNull ?? const NetWorth(totalNetWorth: 0, accounts: []);
  }
}

/// Stub [NetWorthHistoryNotifier] that returns a fixed [AsyncValue].
class _StubNetWorthHistoryNotifier extends NetWorthHistoryNotifier {
  final AsyncValue<NetWorthHistory> _value;

  _StubNetWorthHistoryNotifier(this._value);

  @override
  Future<NetWorthHistory> build() async {
    state = _value;
    if (_value is AsyncError<NetWorthHistory>) {
      throw _value.asError!.error;
    }
    return _value.valueOrNull ??
        const NetWorthHistory(period: '30d', dataPoints: []);
  }
}
