import 'package:flutter_test/flutter_test.dart';
import 'package:flutter/material.dart';
import 'package:klu_bza/attendance.dart';
import 'package:klu_bza/main.dart';

void main() {
  test('attendance target math and empty classes', () {
    const low = Attendance('X', 'Course', 'L', 12, 36);
    expect(low.needed(75), 60);
    expect(low.canMiss(75), 0);
    const full = Attendance('X', 'Course', 'P', 20, 20);
    expect(full.canMiss(75), 6);
    expect(full.needed(75), 0);
    expect(const Attendance('X', 'Course', 'S', 0, 0).percent, isNull);
    expect(() => full.needed(100), throwsArgumentError);
  });
  testWidgets('demo is explicit and sign out clears records', (tester) async {
    await tester.pumpWidget(const KluApp());
    await tester.ensureVisible(find.text('Explore with sample data'));
    await tester.tap(find.text('Explore with sample data'));
    await tester.pumpAndSettle();
    expect(find.textContaining('DEMO — fictional'), findsOneWidget);
    await tester.tap(find.text('Sign out'));
    await tester.pumpAndSettle();
    expect(find.text('Student sign in'), findsOneWidget);
    expect(find.text('Data Structures & Algorithms'), findsNothing);
  });
  for (final width in [320.0, 390.0, 1200.0]) {
    testWidgets('dashboard fits width $width', (tester) async {
      await tester.binding.setSurfaceSize(Size(width, 844));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      await tester.pumpWidget(const KluApp());
      await tester.ensureVisible(find.text('Explore with sample data'));
      await tester.tap(find.text('Explore with sample data'));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
    });
  }
}
