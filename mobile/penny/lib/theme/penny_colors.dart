/// Penny design tokens — Electric Blue dark mode palette.
///
/// All colour constants are derived from the Pencil design file
/// (`designs/penny-ui.pen`) and should be the single source of truth
/// for colours across the app. Prefer these over `Colors.*` literals.
library;

import 'dart:ui';

abstract final class PennyColors {
  // ---------------------------------------------------------------------------
  // Core brand
  // ---------------------------------------------------------------------------

  /// Primary brand colour (Electric Blue).
  static const Color primary = Color(0xFF1565C0);

  /// Light variant used for tinted backgrounds on light surfaces.
  static const Color primaryLight = Color(0xFFE3F2FD);

  /// Lighter blue for chart lines, secondary accents on dark.
  static const Color primaryAccent = Color(0xFF64B5F6);

  /// Muted blue for secondary text on dark backgrounds.
  static const Color primaryMuted = Color(0xFF90CAF9);

  /// White — used for text/icons on primary or dark backgrounds.
  static const Color onPrimary = Color(0xFFFFFFFF);

  // ---------------------------------------------------------------------------
  // Surfaces (dark mode)
  // ---------------------------------------------------------------------------

  /// Main scaffold / page background.
  static const Color surfaceDark = Color(0xFF0D1520);

  /// Elevated cards, nav pills, input fields.
  static const Color surfaceDarkElevated = Color(0xFF121D2E);

  /// Secondary containers, icon backgrounds, chips.
  static const Color surfaceDarkSecondary = Color(0xFF1A2D45);

  /// Subtle borders on dark surfaces (with alpha).
  static const Color borderDark = Color(0x801A2D45); // #1A2D4580

  // ---------------------------------------------------------------------------
  // Surfaces (light mode — kept for auth screens / future use)
  // ---------------------------------------------------------------------------

  /// Light mode background.
  static const Color surfaceLight = Color(0xFFF5F5F7);

  /// Light mode card / surface.
  static const Color surface = Color(0xFFFFFFFF);

  /// Light mode secondary surface.
  static const Color surfaceSecondary = Color(0xFFEEF2F7);

  /// Light mode border.
  static const Color border = Color(0xFFE5E7EB);

  // ---------------------------------------------------------------------------
  // Foreground / text
  // ---------------------------------------------------------------------------

  /// Primary text on dark backgrounds.
  static const Color textOnDark = Color(0xFFFFFFFF);

  /// Secondary text on dark backgrounds.
  static const Color textOnDarkSecondary = Color(0xFF90CAF9);

  /// Muted / tertiary text on dark backgrounds.
  ///
  /// WCAG AA compliant (~5.0:1 against surfaceDark, ~4.5:1 against
  /// surfaceDarkElevated). Upgraded from #5A7A96 which failed at 3.4:1.
  static const Color textOnDarkMuted = Color(0xFF85A0B9);

  /// Primary text on light backgrounds.
  static const Color textPrimary = Color(0xFF1A1A2E);

  /// Secondary text on light backgrounds.
  static const Color textSecondary = Color(0xFF6B7080);

  /// Muted text on light backgrounds.
  static const Color textMuted = Color(0xFF9CA3AF);

  // ---------------------------------------------------------------------------
  // Semantic colours
  // ---------------------------------------------------------------------------

  /// Positive values: assets, gains, connected status.
  static const Color positive = Color(0xFF388E3C);

  /// Positive on dark — slightly lighter for readability.
  static const Color positiveBright = Color(0xFF66BB6A);

  /// Positive tinted background.
  static const Color positiveLight = Color(0xFFE8F5E9);

  /// Negative values: liabilities, losses, errors.
  static const Color negative = Color(0xFFD32F2F);

  /// Negative bright for dark backgrounds.
  static const Color negativeBright = Color(0xFFE57373);

  /// Negative tinted background.
  static const Color negativeLight = Color(0xFFFFEBEF);

  /// Warning: expiring soon, caution states.
  static const Color warning = Color(0xFFF57C00);

  /// Warning tinted background.
  static const Color warningLight = Color(0xFFFFF3E0);

  // ---------------------------------------------------------------------------
  // Category colours (transaction categorisation)
  // ---------------------------------------------------------------------------

  static const Color categoryGroceries = Color(0xFF4CAF50);
  static const Color categoryEatingOut = Color(0xFFFF9800);
  static const Color categoryTransport = Color(0xFF2196F3);
  static const Color categoryShopping = Color(0xFF9C27B0);
  static const Color categoryBills = Color(0xFFF44336);
  static const Color categoryIncome = Color(0xFF009688);
  static const Color categoryEntertainment = Color(0xFF3F51B5);
  static const Color categoryHealth = Color(0xFFFF5722);
  static const Color categoryTransfers = Color(0xFF3949AB);
  static const Color categoryCashAtm = Color(0xFFFFC107);
  static const Color categorySavings = Color(0xFFE91E63);
  static const Color categoryTravel = Color(0xFF00BCD4);
  static const Color categoryGeneral = Color(0xFF9E9E9E);

  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------

  /// Returns the category colour for the given category name.
  ///
  /// Matches exact display names used in the UI (e.g. 'Bills & Subscriptions')
  /// as well as lower-case slug variants from the backend.
  static Color categoryColor(String category) {
    return switch (category.toLowerCase()) {
      'groceries' => categoryGroceries,
      'eating_out' || 'eating out' || 'restaurants' => categoryEatingOut,
      'transport' || 'transportation' => categoryTransport,
      'shopping' => categoryShopping,
      'bills' || 'utilities' || 'bills & subscriptions' => categoryBills,
      'income' || 'salary' || 'salary & income' => categoryIncome,
      'transfers' => categoryTransfers,
      'cash & atm' || 'cash' || 'atm' => categoryCashAtm,
      'entertainment' => categoryEntertainment,
      'health' || 'fitness' || 'health & fitness' => categoryHealth,
      'savings' || 'investments' => categorySavings,
      'travel' || 'holidays' => categoryTravel,
      _ => categoryGeneral,
    };
  }

  /// Returns a status colour for bank connection states.
  static Color connectionStatus(String status) {
    return switch (status) {
      'active' => positive,
      'expiring_soon' => warning,
      'expired' || 'revoked' || 'error' => negative,
      _ => textMuted,
    };
  }
}
