import 'package:flutter_test/flutter_test.dart';
import 'package:klu_bza/erp_browser_routes.dart';

void main() {
  test('only the exact official HTTPS ERP host is trusted', () {
    expect(isOfficialErpUrl('https://newerp.kluniversity.in/'), isTrue);
    expect(isOfficialErpUrl(
      'https://newerp.kluniversity.in/index.php?r=site%2Flogin'), isTrue);
    expect(isOfficialErpUrl('http://newerp.kluniversity.in/'), isFalse);
    expect(isOfficialErpUrl('https://newerp.kluniversity.in.evil.test/'), isFalse);
    expect(isOfficialErpUrl('https://newerp.kluniversity.in@evil.test/'),
        isFalse);
    expect(isOfficialErpUrl('https://newerp.kluniversity.in:444/'), isFalse);
    expect(isOfficialErpUrl('https://user@newerp.kluniversity.in/'), isFalse);
    expect(isOfficialErpUrl('javascript:alert(1)'), isFalse);
    expect(isOfficialErpUrl('about:blank'), isFalse);
  });

  test('five fixed modules use university routes, without arbitrary URLs', () {
    expect(erpRoutes.keys.toSet(), {
      'attendance', 'profile', 'cgpa', 'timetable', 'seating'
    });
    for (final section in erpRoutes.keys) {
      final uri = erpModuleUri(section);
      expect(isOfficialErpUrl(uri.toString()), isTrue);
      expect(uri.path, '/index.php');
      expect(uri.queryParameters['r'], isNotEmpty);
    }
    expect(() => erpModuleUri('https://example.org'), throwsArgumentError);
    expect(() => erpModuleUri('../../secret'), throwsArgumentError);
    expect(() => erpModuleUri('unknown-module'), throwsArgumentError);
  });
}
