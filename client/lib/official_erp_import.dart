import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:webview_flutter/webview_flutter.dart';

import 'attendance.dart';
import 'attendance_import.dart';
import 'erp_browser_routes.dart';

// Only an explicit import tap may read structured visible attendance cells.
// Credentials, CAPTCHA, form fields, storage, cookies and HTML are untouched.
// The result is returned to app memory, not posted to the backend.
const _extractVisibleAttendance = r"""
(() => {
  const clean = (x) => (x || '').replace(/\s+/g, ' ').trim();
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
    // Do not use hidden tables/templates, even when their headings match.
    if (!table.getClientRects().length || getComputedStyle(table).visibility === 'hidden') continue;
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

/// One in-app browser with a single WebView controller and shared site cookies
/// across fixed, allowlisted university modules. ERP sign-in happens on the
/// university site, not through a proxy or a copied gateway session.
class UnifiedErpBrowserView extends StatefulWidget {
  const UnifiedErpBrowserView({
    super.key,
    this.initialModule = 'attendance',
    this.expectedYear,
    this.expectedSemester,
  });

  final String initialModule;
  final String? expectedYear;
  final String? expectedSemester;

  @override
  State<UnifiedErpBrowserView> createState() => _UnifiedErpBrowserViewState();
}

class _UnifiedErpBrowserViewState extends State<UnifiedErpBrowserView> {
  late final WebViewController _controller;
  late String _selectedModule;
  bool _loading = true;
  bool _importing = false;

  bool get _allowAttendanceImport =>
      _selectedModule == 'attendance' &&
      (widget.expectedYear?.isNotEmpty ?? false) &&
      (widget.expectedSemester?.isNotEmpty ?? false);

  @override
  void initState() {
    super.initState();
    _selectedModule = erpRoutes.containsKey(widget.initialModule)
        ? widget.initialModule
        : 'attendance';
    _controller = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..setNavigationDelegate(
        NavigationDelegate(
          onPageStarted: (_) {
            if (mounted) setState(() => _loading = true);
          },
          onPageFinished: (_) {
            if (mounted) setState(() => _loading = false);
          },
          onNavigationRequest: (request) {
            if (!request.isMainFrame) return NavigationDecision.navigate;
            if (isOfficialErpUrl(request.url)) {
              return NavigationDecision.navigate;
            }
            if (mounted) {
              ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(
                  content: Text(
                    'This browser opens only the official university ERP. '
                    'Use your regular browser for external links.',
                  ),
                ),
              );
            }
            return NavigationDecision.prevent;
          },
        ),
      )
      ..loadRequest(erpModuleUri(_selectedModule));
  }

  Future<void> _openSection(String section) async {
    if (!erpRoutes.containsKey(section) || _importing) return;
    setState(() {
      _selectedModule = section;
      _loading = true;
    });
    try {
      // Reuse the SAME WebView controller. Never export its cookies.
      await _controller.loadRequest(erpModuleUri(section));
    } catch (_) {
      if (!mounted) return;
      setState(() => _loading = false);
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Could not open this ERP section.')),
      );
    }
  }

  Future<void> _reload() async {
    try {
      await _controller.reload();
    } catch (_) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('ERP page could not be refreshed.')),
      );
    }
  }

  Future<void> _back() async {
    if (await _controller.canGoBack()) {
      await _controller.goBack();
    } else if (mounted) {
      Navigator.of(context).pop();
    }
  }

  Future<void> _clearErpBrowserSession() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Sign out of ERP browser?'),
        content: const Text(
          'This clears this app\'s embedded browser cookies. '
          'It does not sign you out of Chrome or revoke other university sessions.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(ctx).pop(true),
            child: const Text('Clear sign-in'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    try {
      await WebViewCookieManager().clearCookies();
      await _controller.clearCache();
      await _controller.loadRequest(erpModuleUri(_selectedModule));
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Embedded ERP browser cookies cleared.')),
        );
      }
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Could not clear embedded browser sign-in.')),
        );
      }
    }
  }

  Future<void> _import() async {
    if (_importing || _loading || !_allowAttendanceImport) return;
    setState(() => _importing = true);
    try {
      final currentUrl = await _controller.currentUrl();
      if (currentUrl == null || !isOfficialErpUrl(currentUrl)) {
        throw const FormatException(
          'Open the official ERP Attendance Register before importing.',
        );
      }
      // Script reads a known attendance table only, never student identity or
      // session data. The strict Dart parser validates the selected term.
      final output = await _controller.runJavaScriptReturningResult(
        _extractVisibleAttendance,
      );
      final serialized = output is String ? output : jsonEncode(output);
      final rows = parseVisibleAttendance(
        serialized,
        expectedYear: widget.expectedYear!,
        expectedSemester: widget.expectedSemester!,
      );
      if (!mounted) return;
      Navigator.of(context).pop<List<Attendance>>(rows);
    } catch (e) {
      if (!mounted) return;
      final message = e is FormatException
          ? e.message
          : 'Attendance is not readable yet. On the official page, '
              'choose the same term and press Search before importing.';
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(message)),
      );
    } finally {
      if (mounted) setState(() => _importing = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(
          title: const Text('KLU BZA · ERP Browser'),
          actions: [
            IconButton(
              tooltip: 'Clear ERP browser sign-in',
              onPressed: _importing ? null : _clearErpBrowserSession,
              icon: const Icon(Icons.no_accounts_outlined),
            ),
            IconButton(
              tooltip: 'Back in ERP',
              onPressed: _importing ? null : _back,
              icon: const Icon(Icons.arrow_back),
            ),
            IconButton(
              tooltip: 'Reload ERP',
              onPressed: _importing ? null : _reload,
              icon: const Icon(Icons.refresh),
            ),
          ],
        ),
        body: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Padding(
              padding: EdgeInsets.fromLTRB(14, 6, 14, 4),
              child: Row(
                children: [
                  Icon(Icons.verified_user_outlined, size: 17,
                      color: Colors.green),
                  SizedBox(width: 7),
                  Expanded(
                    child: Text(
                      'Official university website · newerp.kluniversity.in',
                      style: TextStyle(fontSize: 12, color: Colors.blueGrey),
                    ),
                  ),
                ],
              ),
            ),
            SizedBox(
              height: 56,
              child: ListView(
                scrollDirection: Axis.horizontal,
                padding: const EdgeInsets.symmetric(horizontal: 12),
                children: [
                  for (final section in erpRoutes.keys)
                    Padding(
                      padding: const EdgeInsets.only(right: 8),
                      child: ChoiceChip(
                        label: Text(erpTitles[section] ?? section),
                        selected: _selectedModule == section,
                        onSelected: _importing || _loading
                            ? null
                            : (_) => _openSection(section),
                      ),
                    ),
                ],
              ),
            ),
            const Padding(
              padding: EdgeInsets.symmetric(horizontal: 14, vertical: 4),
              child: Text(
                'Sign in on the official site when prompted. '
                'Your browser session is separate from KLU BZA cloud login.',
                style: TextStyle(fontSize: 12, color: Colors.blueGrey),
              ),
            ),
            if (_loading) const LinearProgressIndicator(),
            Expanded(child: WebViewWidget(controller: _controller)),
            if (_allowAttendanceImport)
              SafeArea(
                top: false,
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(12, 6, 12, 12),
                  child: FilledButton.icon(
                    onPressed: _loading || _importing ? null : _import,
                    icon: const Icon(Icons.file_download_outlined),
                    label: Text(_importing
                        ? 'Reading visible attendance…'
                        : 'Import visible attendance'),
                  ),
                ),
              ),
          ],
        ),
      );
}

/// Backwards-compatible entry point for existing attendance links.
class OfficialErpImportView extends UnifiedErpBrowserView {
  const OfficialErpImportView({
    super.key,
    required String expectedYear,
    required String expectedSemester,
  }) : super(
          initialModule: 'attendance',
          expectedYear: expectedYear,
          expectedSemester: expectedSemester,
        );
}
