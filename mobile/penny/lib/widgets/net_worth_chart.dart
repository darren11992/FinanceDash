/// Net worth trend line chart widget.
///
/// Displays the user's net worth over time using fl_chart. Supports
/// 7d, 30d, and 90d periods with interactive touch tooltips.
library;

import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../models/net_worth.dart';
import '../theme/penny_colors.dart';

/// Line chart showing net worth trend over time.
class NetWorthChart extends StatelessWidget {
  final NetWorthHistory history;

  const NetWorthChart({super.key, required this.history});

  @override
  Widget build(BuildContext context) {
    if (!history.hasData) {
      return const SizedBox.shrink();
    }

    final spots = _buildSpots();
    final minY = _minY(spots);
    final maxY = _maxY(spots);
    final theme = Theme.of(context);

    return Semantics(
      label: _chartSemanticLabel(),
      excludeSemantics: true,
      child: SizedBox(
        height: 200,
        child: Padding(
          padding: const EdgeInsets.only(right: 16, top: 8),
          child: LineChart(
            LineChartData(
              gridData: FlGridData(
                show: true,
                drawVerticalLine: false,
                horizontalInterval: _gridInterval(minY, maxY),
                getDrawingHorizontalLine: (value) => FlLine(
                  color: theme.dividerColor.withValues(alpha: 0.3),
                  strokeWidth: 0.5,
                ),
              ),
              titlesData: FlTitlesData(
                rightTitles: const AxisTitles(
                  sideTitles: SideTitles(showTitles: false),
                ),
                topTitles: const AxisTitles(
                  sideTitles: SideTitles(showTitles: false),
                ),
                leftTitles: AxisTitles(
                  sideTitles: SideTitles(
                    showTitles: true,
                    reservedSize: 56,
                    getTitlesWidget: (value, meta) => _leftTitle(value, meta),
                  ),
                ),
                bottomTitles: AxisTitles(
                  sideTitles: SideTitles(
                    showTitles: true,
                    reservedSize: 28,
                    interval: _bottomInterval(spots.length),
                    getTitlesWidget: (value, meta) => _bottomTitle(value, meta),
                  ),
                ),
              ),
              borderData: FlBorderData(show: false),
              minY: minY,
              maxY: maxY,
              lineBarsData: [
                LineChartBarData(
                  spots: spots,
                  isCurved: true,
                  preventCurveOverShooting: true,
                  color: _lineColor,
                  barWidth: 2.5,
                  isStrokeCapRound: true,
                  dotData: const FlDotData(show: false),
                  belowBarData: BarAreaData(
                    show: true,
                    gradient: LinearGradient(
                      colors: [
                        _lineColor.withValues(alpha: 0.25),
                        _lineColor.withValues(alpha: 0.0),
                      ],
                      begin: Alignment.topCenter,
                      end: Alignment.bottomCenter,
                    ),
                  ),
                ),
              ],
              lineTouchData: LineTouchData(
                touchTooltipData: LineTouchTooltipData(
                  getTooltipItems: (touchedSpots) {
                    return touchedSpots.map((spot) {
                      final point = history.dataPoints[spot.spotIndex];
                      final dateStr = DateFormat('d MMM').format(point.date);
                      final valueStr = _formatCurrency(point.netWorth);
                      return LineTooltipItem(
                        '$dateStr\n$valueStr',
                        TextStyle(
                          color: theme.colorScheme.onSurface,
                          fontWeight: FontWeight.w600,
                          fontSize: 12,
                        ),
                      );
                    }).toList();
                  },
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }

  /// Build a screen-reader description of the chart data.
  String _chartSemanticLabel() {
    final latest = history.dataPoints.last;
    final buf = StringBuffer('Net worth trend chart for ${history.period}. ');
    buf.write('Current value: ${_formatCurrency(latest.netWorth)}. ');
    final change = history.changeAbsolute;
    if (change != null) {
      final direction = change >= 0 ? 'Up' : 'Down';
      buf.write('$direction ${_formatCurrency(change.abs())}');
      final pct = history.changePercent;
      if (pct != null) {
        buf.write(' (${pct.toStringAsFixed(1)}%)');
      }
      buf.write(' over the period.');
    }
    return buf.toString();
  }

  /// Build [FlSpot] list from history data points.
  ///
  /// X axis = index (evenly spaced), Y axis = net worth value.
  List<FlSpot> _buildSpots() {
    return List.generate(history.dataPoints.length, (i) {
      return FlSpot(i.toDouble(), history.dataPoints[i].netWorth);
    });
  }

  /// Determine chart colour based on trend direction.
  Color get _lineColor {
    final change = history.changeAbsolute;
    if (change == null || change == 0) return PennyColors.primaryAccent;
    return change > 0 ? PennyColors.positiveBright : PennyColors.negativeBright;
  }

  /// Calculate min Y with some padding below the lowest value.
  double _minY(List<FlSpot> spots) {
    if (spots.isEmpty) return 0;
    final min = spots.map((s) => s.y).reduce((a, b) => a < b ? a : b);
    final max = spots.map((s) => s.y).reduce((a, b) => a > b ? a : b);
    final range = max - min;
    // Add 10% padding below, but don't go below 0 if all values are positive.
    final padded = min - (range * 0.1);
    return min >= 0 ? (padded < 0 ? 0 : padded) : padded;
  }

  /// Calculate max Y with some padding above the highest value.
  double _maxY(List<FlSpot> spots) {
    if (spots.isEmpty) return 100;
    final max = spots.map((s) => s.y).reduce((a, b) => a > b ? a : b);
    final min = spots.map((s) => s.y).reduce((a, b) => a < b ? a : b);
    final range = max - min;
    return max + (range * 0.1);
  }

  /// Calculate a reasonable grid line interval.
  double _gridInterval(double minY, double maxY) {
    final range = maxY - minY;
    if (range <= 0) return 1;
    // Aim for ~4-5 grid lines.
    final raw = range / 4;
    // Round to a nice number.
    final magnitude = _magnitude(raw);
    return (raw / magnitude).ceil() * magnitude;
  }

  double _magnitude(double value) {
    if (value <= 0) return 1;
    final log = value.abs();
    if (log >= 10000) return 5000;
    if (log >= 1000) return 500;
    if (log >= 100) return 50;
    if (log >= 10) return 5;
    return 1;
  }

  /// Determine how frequently to show bottom (date) labels.
  double _bottomInterval(int dataPointCount) {
    if (dataPointCount <= 7) return 1;
    if (dataPointCount <= 14) return 2;
    if (dataPointCount <= 30) return 5;
    return 10;
  }

  /// Format the left axis (value) labels.
  Widget _leftTitle(double value, TitleMeta meta) {
    return SideTitleWidget(
      meta: meta,
      child: Text(
        _formatCompact(value),
        style: const TextStyle(
          fontSize: 10,
          color: PennyColors.textOnDarkMuted,
        ),
      ),
    );
  }

  /// Format the bottom axis (date) labels.
  Widget _bottomTitle(double value, TitleMeta meta) {
    final index = value.toInt();
    if (index < 0 || index >= history.dataPoints.length) {
      return const SizedBox.shrink();
    }
    final point = history.dataPoints[index];
    final label = DateFormat('d/M').format(point.date);
    return SideTitleWidget(
      meta: meta,
      child: Text(
        label,
        style: const TextStyle(
          fontSize: 10,
          color: PennyColors.textOnDarkMuted,
        ),
      ),
    );
  }

  /// Format a value as compact currency (e.g. "12.3k").
  static String _formatCompact(double value) {
    if (value.abs() >= 1000000) {
      return '\u00A3${(value / 1000000).toStringAsFixed(1)}M';
    }
    if (value.abs() >= 1000) {
      return '\u00A3${(value / 1000).toStringAsFixed(1)}k';
    }
    return '\u00A3${value.toStringAsFixed(0)}';
  }

  /// Format a value as full currency with symbol.
  static String _formatCurrency(double value) {
    final formatter = NumberFormat.currency(
      locale: 'en_GB',
      symbol: '\u00A3',
      decimalDigits: 2,
    );
    return formatter.format(value);
  }
}
