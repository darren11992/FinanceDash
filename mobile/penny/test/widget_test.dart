// Basic smoke test for the Penny app.
//
// This is a placeholder — proper widget tests for auth screens
// will be added in Sprint 6.

import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('App smoke test placeholder', (WidgetTester tester) async {
    // Supabase.initialize() requires platform channels that aren't
    // available in a basic widget test. Full widget tests will use
    // mock Supabase clients (Sprint 6).
    expect(true, isTrue);
  });
}
