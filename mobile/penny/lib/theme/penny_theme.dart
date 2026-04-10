/// Penny app theme — Electric Blue dark mode.
///
/// Provides a single [ThemeData] built on top of the colour tokens in
/// [PennyColors]. Uses Google Fonts (Inter for UI, Geist Mono reserved
/// for numeric / monospaced elements).
library;

import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

import 'penny_colors.dart';

abstract final class PennyTheme {
  // ---------------------------------------------------------------------------
  // Public API
  // ---------------------------------------------------------------------------

  /// The dark theme used throughout the app.
  static ThemeData get dark {
    final colorScheme = ColorScheme(
      brightness: Brightness.dark,
      primary: PennyColors.primary,
      onPrimary: PennyColors.onPrimary,
      primaryContainer: PennyColors.surfaceDarkSecondary,
      onPrimaryContainer: PennyColors.primaryAccent,
      secondary: PennyColors.primaryAccent,
      onSecondary: PennyColors.surfaceDark,
      secondaryContainer: PennyColors.surfaceDarkSecondary,
      onSecondaryContainer: PennyColors.primaryMuted,
      tertiary: PennyColors.warning,
      onTertiary: PennyColors.onPrimary,
      error: PennyColors.negative,
      onError: PennyColors.onPrimary,
      surface: PennyColors.surfaceDark,
      onSurface: PennyColors.textOnDark,
      surfaceContainerHighest: PennyColors.surfaceDarkElevated,
      onSurfaceVariant: PennyColors.textOnDarkSecondary,
      outline: PennyColors.borderDark,
      outlineVariant: PennyColors.borderDark,
      shadow: Colors.black,
    );

    final textTheme = _buildTextTheme(colorScheme);

    return ThemeData(
      useMaterial3: true,
      brightness: Brightness.dark,
      colorScheme: colorScheme,
      scaffoldBackgroundColor: PennyColors.surfaceDark,
      textTheme: textTheme,

      // -----------------------------------------------------------------------
      // AppBar
      // -----------------------------------------------------------------------
      appBarTheme: AppBarTheme(
        backgroundColor: PennyColors.surfaceDark,
        foregroundColor: PennyColors.textOnDark,
        elevation: 0,
        scrolledUnderElevation: 0,
        centerTitle: false,
        titleTextStyle: textTheme.titleLarge,
      ),

      // -----------------------------------------------------------------------
      // Cards
      // -----------------------------------------------------------------------
      cardTheme: CardThemeData(
        color: PennyColors.surfaceDarkElevated,
        elevation: 0,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(16),
          side: BorderSide(color: PennyColors.borderDark),
        ),
        margin: EdgeInsets.zero,
      ),

      // -----------------------------------------------------------------------
      // Bottom navigation
      // -----------------------------------------------------------------------
      bottomNavigationBarTheme: BottomNavigationBarThemeData(
        backgroundColor: PennyColors.surfaceDarkElevated,
        selectedItemColor: PennyColors.primary,
        unselectedItemColor: PennyColors.textOnDarkMuted,
        type: BottomNavigationBarType.fixed,
        elevation: 0,
      ),

      // -----------------------------------------------------------------------
      // Elevated / Filled buttons
      // -----------------------------------------------------------------------
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          backgroundColor: PennyColors.primary,
          foregroundColor: PennyColors.onPrimary,
          elevation: 0,
          padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 14),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(12),
          ),
          textStyle: GoogleFonts.inter(
            fontWeight: FontWeight.w600,
            fontSize: 16,
          ),
        ),
      ),

      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          foregroundColor: PennyColors.primaryAccent,
          side: BorderSide(color: PennyColors.borderDark),
          padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 14),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(12),
          ),
          textStyle: GoogleFonts.inter(
            fontWeight: FontWeight.w600,
            fontSize: 16,
          ),
        ),
      ),

      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(
          foregroundColor: PennyColors.primaryAccent,
          textStyle: GoogleFonts.inter(
            fontWeight: FontWeight.w600,
            fontSize: 14,
          ),
        ),
      ),

      // -----------------------------------------------------------------------
      // Input decoration (login, sign-up, search fields)
      // -----------------------------------------------------------------------
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: PennyColors.surfaceDarkElevated,
        contentPadding: const EdgeInsets.symmetric(
          horizontal: 16,
          vertical: 14,
        ),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: BorderSide(color: PennyColors.borderDark),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: BorderSide(color: PennyColors.borderDark),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: BorderSide(color: PennyColors.primary, width: 2),
        ),
        errorBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: BorderSide(color: PennyColors.negative),
        ),
        hintStyle: GoogleFonts.inter(
          color: PennyColors.textOnDarkMuted,
          fontSize: 14,
        ),
        labelStyle: GoogleFonts.inter(
          color: PennyColors.textOnDarkSecondary,
          fontSize: 14,
        ),
      ),

      // -----------------------------------------------------------------------
      // Divider
      // -----------------------------------------------------------------------
      dividerTheme: DividerThemeData(
        color: PennyColors.borderDark,
        thickness: 1,
        space: 1,
      ),

      // -----------------------------------------------------------------------
      // Snackbar
      // -----------------------------------------------------------------------
      snackBarTheme: SnackBarThemeData(
        backgroundColor: PennyColors.surfaceDarkSecondary,
        contentTextStyle: GoogleFonts.inter(
          color: PennyColors.textOnDark,
          fontSize: 14,
        ),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
        behavior: SnackBarBehavior.floating,
      ),

      // -----------------------------------------------------------------------
      // Chips
      // -----------------------------------------------------------------------
      chipTheme: ChipThemeData(
        backgroundColor: PennyColors.surfaceDarkSecondary,
        selectedColor: PennyColors.primary,
        labelStyle: GoogleFonts.inter(
          color: PennyColors.textOnDark,
          fontSize: 13,
        ),
        side: BorderSide(color: PennyColors.borderDark),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
      ),

      // -----------------------------------------------------------------------
      // ListTile
      // -----------------------------------------------------------------------
      listTileTheme: ListTileThemeData(
        textColor: PennyColors.textOnDark,
        iconColor: PennyColors.textOnDarkSecondary,
        tileColor: Colors.transparent,
      ),

      // -----------------------------------------------------------------------
      // Icon
      // -----------------------------------------------------------------------
      iconTheme: const IconThemeData(color: PennyColors.textOnDarkSecondary),

      // -----------------------------------------------------------------------
      // Dialog
      // -----------------------------------------------------------------------
      dialogTheme: DialogThemeData(
        backgroundColor: PennyColors.surfaceDarkElevated,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
      ),

      // -----------------------------------------------------------------------
      // BottomSheet
      // -----------------------------------------------------------------------
      bottomSheetTheme: BottomSheetThemeData(
        backgroundColor: PennyColors.surfaceDarkElevated,
        shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
        ),
      ),

      // -----------------------------------------------------------------------
      // FloatingActionButton
      // -----------------------------------------------------------------------
      floatingActionButtonTheme: FloatingActionButtonThemeData(
        backgroundColor: PennyColors.primary,
        foregroundColor: PennyColors.onPrimary,
        elevation: 0,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      ),
    );
  }

  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------

  /// Builds the app [TextTheme] using Inter via Google Fonts.
  static TextTheme _buildTextTheme(ColorScheme scheme) {
    return TextTheme(
      // Display
      displayLarge: GoogleFonts.inter(
        fontSize: 57,
        fontWeight: FontWeight.w400,
        color: scheme.onSurface,
      ),
      displayMedium: GoogleFonts.inter(
        fontSize: 45,
        fontWeight: FontWeight.w400,
        color: scheme.onSurface,
      ),
      displaySmall: GoogleFonts.inter(
        fontSize: 36,
        fontWeight: FontWeight.w400,
        color: scheme.onSurface,
      ),

      // Headline
      headlineLarge: GoogleFonts.inter(
        fontSize: 32,
        fontWeight: FontWeight.w700,
        color: scheme.onSurface,
      ),
      headlineMedium: GoogleFonts.inter(
        fontSize: 28,
        fontWeight: FontWeight.w600,
        color: scheme.onSurface,
      ),
      headlineSmall: GoogleFonts.inter(
        fontSize: 24,
        fontWeight: FontWeight.w600,
        color: scheme.onSurface,
      ),

      // Title
      titleLarge: GoogleFonts.inter(
        fontSize: 22,
        fontWeight: FontWeight.w600,
        color: scheme.onSurface,
      ),
      titleMedium: GoogleFonts.inter(
        fontSize: 16,
        fontWeight: FontWeight.w600,
        color: scheme.onSurface,
      ),
      titleSmall: GoogleFonts.inter(
        fontSize: 14,
        fontWeight: FontWeight.w600,
        color: scheme.onSurface,
      ),

      // Body
      bodyLarge: GoogleFonts.inter(
        fontSize: 16,
        fontWeight: FontWeight.w400,
        color: scheme.onSurface,
      ),
      bodyMedium: GoogleFonts.inter(
        fontSize: 14,
        fontWeight: FontWeight.w400,
        color: scheme.onSurface,
      ),
      bodySmall: GoogleFonts.inter(
        fontSize: 12,
        fontWeight: FontWeight.w400,
        color: scheme.onSurfaceVariant,
      ),

      // Label
      labelLarge: GoogleFonts.inter(
        fontSize: 14,
        fontWeight: FontWeight.w500,
        color: scheme.onSurface,
      ),
      labelMedium: GoogleFonts.inter(
        fontSize: 12,
        fontWeight: FontWeight.w500,
        color: scheme.onSurface,
      ),
      labelSmall: GoogleFonts.inter(
        fontSize: 11,
        fontWeight: FontWeight.w500,
        color: scheme.onSurfaceVariant,
      ),
    );
  }
}
