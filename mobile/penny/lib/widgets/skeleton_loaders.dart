/// Shimmer-based skeleton loading widgets used across the app.
///
/// Provides reusable skeleton placeholders that match the shape of real
/// content, giving users a visual hint of the layout while data loads.
library;

import 'package:flutter/material.dart';
import 'package:shimmer/shimmer.dart';

import '../theme/penny_colors.dart';

// ---------------------------------------------------------------------------
// Core building blocks
// ---------------------------------------------------------------------------

/// A single shimmering rounded rectangle.
class SkeletonBox extends StatelessWidget {
  final double width;
  final double height;
  final double borderRadius;

  const SkeletonBox({
    super.key,
    required this.width,
    required this.height,
    this.borderRadius = 8,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      width: width,
      height: height,
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(borderRadius),
      ),
    );
  }
}

/// A circle skeleton (for avatars / leading icons).
class SkeletonCircle extends StatelessWidget {
  final double size;

  const SkeletonCircle({super.key, this.size = 40});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: size,
      height: size,
      decoration: const BoxDecoration(
        color: Colors.white,
        shape: BoxShape.circle,
      ),
    );
  }
}

/// Wraps children in a shimmer animation.
class ShimmerWrap extends StatelessWidget {
  final Widget child;

  const ShimmerWrap({super.key, required this.child});

  @override
  Widget build(BuildContext context) {
    return Shimmer.fromColors(
      baseColor: PennyColors.surfaceDarkSecondary,
      highlightColor: PennyColors.surfaceDark.withValues(alpha: 0.6),
      child: child,
    );
  }
}

// ---------------------------------------------------------------------------
// Pre-built skeleton screens
// ---------------------------------------------------------------------------

/// Skeleton for the home/dashboard screen.
///
/// Mimics: hero banner, chart card, account tiles, quick actions.
class DashboardSkeleton extends StatelessWidget {
  const DashboardSkeleton({super.key});

  @override
  Widget build(BuildContext context) {
    return Semantics(
      label: 'Loading dashboard',
      excludeSemantics: true,
      child: ShimmerWrap(
        child: ListView(
          physics: const NeverScrollableScrollPhysics(),
          padding: EdgeInsets.zero,
          children: [
            // Hero banner skeleton
            Container(width: double.infinity, height: 200, color: Colors.white),
            const SizedBox(height: 16),

            // Chart card skeleton
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: SkeletonBox(
                width: double.infinity,
                height: 260,
                borderRadius: 16,
              ),
            ),
            const SizedBox(height: 16),

            // Account tiles (3 placeholder rows)
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const SkeletonBox(width: 80, height: 14),
                  const SizedBox(height: 12),
                  ...List.generate(
                    3,
                    (_) => const Padding(
                      padding: EdgeInsets.only(bottom: 8),
                      child: _SkeletonListTile(),
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 16),

            // Quick actions row
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: Row(
                children: [
                  Expanded(
                    child: SkeletonBox(
                      width: double.infinity,
                      height: 56,
                      borderRadius: 12,
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: SkeletonBox(
                      width: double.infinity,
                      height: 56,
                      borderRadius: 12,
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

/// Skeleton for the transactions list screen.
///
/// Mimics: date header + transaction rows, repeated.
class TransactionsSkeleton extends StatelessWidget {
  const TransactionsSkeleton({super.key});

  @override
  Widget build(BuildContext context) {
    return Semantics(
      label: 'Loading transactions',
      excludeSemantics: true,
      child: ShimmerWrap(
        child: ListView(
          physics: const NeverScrollableScrollPhysics(),
          padding: const EdgeInsets.symmetric(vertical: 8),
          children: [
            // Count header
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
              child: SkeletonBox(width: 120, height: 12),
            ),

            // Two groups of date header + transactions
            ...List.generate(
              2,
              (group) => Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  // Date header
                  Padding(
                    padding: const EdgeInsets.fromLTRB(16, 16, 16, 4),
                    child: SkeletonBox(width: 90, height: 14),
                  ),
                  // 4 transaction rows per group
                  ...List.generate(
                    4,
                    (_) => const Padding(
                      padding: EdgeInsets.symmetric(
                        horizontal: 12,
                        vertical: 3,
                      ),
                      child: _SkeletonTransactionTile(),
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

/// Skeleton for the connections list screen.
///
/// Mimics: connection card tiles.
class ConnectionsSkeleton extends StatelessWidget {
  const ConnectionsSkeleton({super.key});

  @override
  Widget build(BuildContext context) {
    return Semantics(
      label: 'Loading connections',
      excludeSemantics: true,
      child: ShimmerWrap(
        child: ListView(
          physics: const NeverScrollableScrollPhysics(),
          padding: const EdgeInsets.only(bottom: 88),
          children: List.generate(
            3,
            (_) => const Padding(
              padding: EdgeInsets.symmetric(horizontal: 16, vertical: 6),
              child: _SkeletonListTile(),
            ),
          ),
        ),
      ),
    );
  }
}

/// Skeleton for the hero banner + net worth area.
class HeroBannerSkeleton extends StatelessWidget {
  const HeroBannerSkeleton({super.key});

  @override
  Widget build(BuildContext context) {
    return Semantics(
      label: 'Loading net worth',
      excludeSemantics: true,
      child: ShimmerWrap(
        child: Container(
          width: double.infinity,
          padding: const EdgeInsets.fromLTRB(20, 12, 20, 24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // Greeting
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: const [
                      SkeletonBox(width: 100, height: 12),
                      SizedBox(height: 6),
                      SkeletonBox(width: 140, height: 18),
                    ],
                  ),
                  const SkeletonCircle(size: 40),
                ],
              ),
              const SizedBox(height: 16),
              // Label
              const Center(child: SkeletonBox(width: 100, height: 10)),
              const SizedBox(height: 8),
              // Big number
              const Center(
                child: SkeletonBox(width: 200, height: 36, borderRadius: 8),
              ),
              const SizedBox(height: 12),
              // Change pill
              Center(
                child: SkeletonBox(width: 150, height: 24, borderRadius: 100),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// Skeleton for the chart card.
class ChartSkeleton extends StatelessWidget {
  const ChartSkeleton({super.key});

  @override
  Widget build(BuildContext context) {
    return Semantics(
      label: 'Loading chart',
      excludeSemantics: true,
      child: ShimmerWrap(
        child: SkeletonBox(
          width: double.infinity,
          height: 260,
          borderRadius: 16,
        ),
      ),
    );
  }
}

/// Skeleton for the account breakdown section.
class AccountBreakdownSkeleton extends StatelessWidget {
  const AccountBreakdownSkeleton({super.key});

  @override
  Widget build(BuildContext context) {
    return Semantics(
      label: 'Loading accounts',
      excludeSemantics: true,
      child: ShimmerWrap(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const SkeletonBox(width: 80, height: 14),
            const SizedBox(height: 12),
            ...List.generate(
              2,
              (_) => const Padding(
                padding: EdgeInsets.only(bottom: 8),
                child: _SkeletonListTile(),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Internal reusable skeleton tiles
// ---------------------------------------------------------------------------

/// A generic list-tile shaped skeleton (avatar + two text lines + trailing).
class _SkeletonListTile extends StatelessWidget {
  const _SkeletonListTile();

  @override
  Widget build(BuildContext context) {
    return Card(
      elevation: 0,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        child: Row(
          children: [
            const SkeletonCircle(size: 40),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: const [
                  SkeletonBox(width: 140, height: 14),
                  SizedBox(height: 6),
                  SkeletonBox(width: 90, height: 10),
                ],
              ),
            ),
            const SkeletonBox(width: 60, height: 16),
          ],
        ),
      ),
    );
  }
}

/// A transaction-shaped skeleton tile (icon circle + description + amount).
class _SkeletonTransactionTile extends StatelessWidget {
  const _SkeletonTransactionTile();

  @override
  Widget build(BuildContext context) {
    return Card(
      elevation: 0,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
        child: Row(
          children: [
            const SkeletonCircle(size: 36),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: const [
                  SkeletonBox(width: 160, height: 14),
                  SizedBox(height: 5),
                  SkeletonBox(width: 70, height: 10),
                ],
              ),
            ),
            const SkeletonBox(width: 56, height: 16),
          ],
        ),
      ),
    );
  }
}
