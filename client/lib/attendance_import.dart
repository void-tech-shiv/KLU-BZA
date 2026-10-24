import 'dart:convert';

import 'attendance.dart';

/// Imports only rows the student has made visible by pressing Search on the
/// official ERP page. Nothing is sent to KLU BZA's cloud backend.
List<Attendance> parseVisibleAttendance(
  String serialized, {
  required String expectedYear,
  required String expectedSemester,
}) {
  dynamic parsed;
  try {
    parsed = jsonDecode(serialized);
    // Android WebView implementations may JSON-encode the return string once.
    if (parsed is String) parsed = jsonDecode(parsed);
  } on FormatException {
    throw const FormatException('The visible ERP table could not be read.');
  }
  if (parsed is! List || parsed.isEmpty) {
    throw const FormatException(
      'No attendance table was found. Open Attendance Register, '
      'select your academic year and semester, then press Search.',
    );
  }
  if (parsed.length > 120) {
    throw const FormatException('The ERP result has too many course rows.');
  }
  final result = <Attendance>[];
  String canonicalYear(String s) => s.replaceAll(RegExp(r'[^0-9]'), '');
  String canonicalSemester(String s) =>
      s.toLowerCase().replaceAll(RegExp(r'[^a-z0-9]'), '');

  for (final entry in parsed) {
    if (entry is! Map) {
      throw const FormatException('An ERP attendance row has an invalid shape.');
    }
    String field(String key) => (entry[key] ?? '').toString().trim();
    final code = field('code');
    final name = field('name');
    final component = field('component').toUpperCase();
    final year = field('year');
    final semester = field('semester');
    if (code.isEmpty || code.length > 50 || name.isEmpty ||
        name.length > 180 || component.isEmpty || component.length > 15) {
      throw const FormatException('An ERP attendance row is incomplete.');
    }
    if (year.isEmpty || semester.isEmpty ||
        canonicalYear(year) != canonicalYear(expectedYear) ||
        canonicalSemester(semester) != canonicalSemester(expectedSemester)) {
      throw const FormatException(
        'The visible ERP result belongs to a different academic year or '
        'semester. Match the app filters and search again.',
      );
    }
    int parseCount(String key) {
      final raw = field(key).replaceAll(',', '');
      if (!RegExp(r'^\d{1,5}$').hasMatch(raw)) {
        throw const FormatException(
            'An ERP attendance row contains an invalid class count.');
      }
      return int.parse(raw);
    }
    final conducted = parseCount('conducted');
    final attended = parseCount('attended');
    if (attended > conducted) {
      throw const FormatException(
        'ERP attendance counts need review; no records were imported.',
      );
    }
    result.add(Attendance(code, name, component, attended, conducted));
  }
  return result;
}
