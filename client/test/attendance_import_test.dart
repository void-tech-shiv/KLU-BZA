import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:klu_bza/attendance_import.dart';

void main() {
  const year = '2026-2027';
  const sem = 'Odd Sem';

  Map<String, String> row(String component, String attended) => {
        'code': 'TEST101',
        'name': 'Synthetic Test Subject',
        'component': component,
        'conducted': '20',
        'attended': attended,
        'year': year,
        'semester': sem,
      };

  test('imports exactly separate L/P/S course rows, not merged totals', () {
    final sample = jsonEncode([
      row('L', '20'),
      row('P', '14'),
      row('S', '10'),
    ]);
    final results = parseVisibleAttendance(
      sample, expectedYear: year, expectedSemester: sem);
    expect(results.length, 3);
    expect(results.map((r) => r.component).toList(), ['L', 'P', 'S']);
    expect(results.map((r) => r.percent).toList(), [100.0, 70.0, 50.0]);
    expect(results[0].code, 'TEST101');
  });

  test('accepts JSON string that WebView wraps in a second JSON string', () {
    final sample = jsonEncode(jsonEncode([row('L', '20')]));
    final results = parseVisibleAttendance(
      sample, expectedYear: year, expectedSemester: sem);
    expect(results.length, 1);
  });

  test('rejects mismatched term and impossible attendance values', () {
    final wrongTerm = {...row('L', '10'), 'semester': 'Even Sem'};
    expect(
      () => parseVisibleAttendance(jsonEncode([wrongTerm]),
          expectedYear: year, expectedSemester: sem),
      throwsFormatException,
    );
    final impossible = row('P', '22');
    expect(
      () => parseVisibleAttendance(jsonEncode([impossible]),
          expectedYear: year, expectedSemester: sem),
      throwsFormatException,
    );
  });

  test('does not invent attendance when no table or malformed data', () {
    for (final value in ['[]', '{}', 'not json']) {
      expect(
        () => parseVisibleAttendance(
            value, expectedYear: year, expectedSemester: sem),
        throwsFormatException,
      );
    }
    final bad = {...row('L', '20'), 'conducted': '20 hours'};
    expect(
      () => parseVisibleAttendance(
          jsonEncode([bad]), expectedYear: year, expectedSemester: sem),
      throwsFormatException,
    );
  });
}
