import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:webview_flutter/webview_flutter.dart';

import 'attendance.dart';
import 'attendance_import.dart';

const _officialHost = 'newerp.kluniversity.in';
const _attendanceUrl =
    'https://newerp.kluniversity.in/index.php?r=studentattendance%2Fstudentdailyattendance%2Fsearchgetinput';

// Executed only after the student presses "Import visible attendance".
// Read only the marked course table. Never access input fields, credentials,
// CAPTCHA, form actions, cookies, localStorage, tokens or student identity.
const _extractVisibleAttendance = r"""
(() => {
  const clean = (x) => (x || '').replace(/\\s+/g, ' ').trim();
  const norm = (x) => clean(x).toLowerCase().replace(/[^a-z0-9]/g, '');
  const aliases = {
    code: ['coursecode'],
    name: ['coursedesc', 'coursedescription', 'coursename', 'coursetitle'],
    component: ['ltps', 'component'],
    conducted: ['totalconducted', 'conductedhours', 'totalconductedhours'],
    attended: ['totalattended', 'attendedhours', 'totalattendedhours'],
    year: ['year', 'academicyear'],
    semester: ['semester']
  };
  for (const table of Array.from(document.querySelectorAll('table'))) {
    const headerRow = table.querySelector('thead tr') || table.querySelector('tr');
    if (!headerRow) continue;
    const headers = Array.from(headerRow.children).map(el => norm(el.textContent));
    const col = (name) => headers.findIndex(h => aliases[name].includes(h));
    const keys = Object.keys(aliases);
    const index = Object.fromEntries(keys.map(k => [k, col(k)]));
    if (keys.some(k => index[k] < 0)) continue;

    const trs = Array.from(table.querySelectorAll('tbody tr'));
    const body = trs.length ? trs : Array.from(table.querySelectorAll('tr')).slice(1);
    const records = [];
    for (const tr of body) {
      if (records.length >= 121) break;
      const cells = Array.from(tr.children).filter(el =>
        el.tagName.toLowerCase() === 'td');
      if (cells.length <= Math.max(...Object.values(index))) continue;
      const value = (key) => clean(cells[index[key]].textContent).slice(0, 200);
      const code = value('code');
      if (!code) continue;
      records.push(Object.fromEntries(keys.map(k => [k, value(k)])));
    }
    if (records.length) return JSON.stringify(records);
  }
  return JSON.stringify([]);
})()
""";

/// Android's native webview runs the official ERP page directly on the device.
/// Never forwards WebView cookies or scraped records to the backend.
class OfficialErpImportView extends StatefulWidget {
  const OfficialErpImportView({
    super.key,
    required this.expectedYear,
    required this.expectedSemester,
  });

  final String expectedYear;
  final String expectedSemester;

  @override
  State<OfficialErpImportView> createState() => _OfficialErpImportViewState();
}

class _OfficialErpImportViewState extends State<OfficialErpImportView> {
  late final WebViewController _controller;
  bool _loading = true;
  bool _importing = false;

  @override
  void initState() {
    super.initState();
    _controller = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..setNavigationDelegate(NavigationDelegate(
        onPageStarted: (_) {
          if (mounted) setState(() => _loading = true);
        },
        onPageFinished: (_) {
          if (mounted) setState(() => _loading = false);
        },
        onNavigationRequest: (request) {
          if (!request.isMainFrame) return NavigationDecision.navigate;
          final url = Uri.tryParse(request.url);
          // Restrict the login view to HTTPS and the exact college ERP host.
          // Never follow redirects to third-party login or lookalike hosts.
          if (url != null &&
              url.scheme == 'https' &&
              url.host == _officialHost &&
              url.userInfo.isEmpty &&
              url.port == 443) {
            return NavigationDecision.navigate;
          }
          if (mounted) {
            ScaffoldMessenger.of(context).showSnackBar(
              const SnackBar(
                content: Text(
                  'Only official HTTPS ERP pages open here. '
                  'Use your browser for other links.',
                ),
              ),
            );
          }
          return NavigationDecision.prevent;
        },
      ))
      ..loadRequest(Uri.parse(_attendanceUrl));
  }

  Future<void> _import() async {
    if (_importing) return;
    setState(() => _importing = true);
    try {
      final active = Uri.tryParse(await _controller.currentUrl() ?? '');
      if (active == null ||
          active.scheme != 'https' ||
          active.host != _officialHost ||
          active.userInfo.isNotEmpty) {
        throw const FormatException('Open the official ERP page before importing.');
      }
      final result = await _controller.runJavaScriptReturningResult(
        _extractVisibleAttendance,
      );
      final serialized = result is String ? result : jsonEncode(result);
      final rows = parseVisibleAttendance(
        serialized,
        expectedYear: widget.expectedYear,
        expectedSemester: widget.expectedSemester,
      );
      if (!mounted) return;
      Navigator.of(context).pop<List<Attendance>>(rows);
    } catch (e) {
      if (!mounted) return;
      final message = e is FormatException
          ? e.message
          : 'Could not read the visible attendance. '
              'Search again on the official ERP and retry.';
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(message)),
      );
    } finally {
      if (mounted) setState(() => _importing = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Official ERP attendance')),
        body: Column(
          children: [
            const Padding(
              padding: EdgeInsets.fromLTRB(12, 6, 12, 6),
              child: Text(
                'Official site: newerp.kluniversity.in. '
                'Sign in here, select year and semester, then press Search. '
                'Import reads only visible course attendance after your tap. '
                'No ERP password or page data is uploaded to KLU BZA.',
                style: TextStyle(fontSize: 12),
              ),
            ),
            if (_loading) const LinearProgressIndicator(),
            Expanded(child: WebViewWidget(controller: _controller)),
            SafeArea(
              top: false,
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: FilledButton.icon(
                  onPressed: _loading || _importing ? null : _import,
                  icon: const Icon(Icons.download_for_offline_outlined),
                  label: Text(_importing
                      ? 'Reading visible table…'
                      : 'Import visible attendance'),
                ),
              ),
            ),
          ],
        ),
      );
}
