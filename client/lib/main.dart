import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import 'attendance.dart';

const apiBase = String.fromEnvironment('API_BASE_URL');
void main() => runApp(const KluApp());

class KluApp extends StatelessWidget {
  const KluApp({super.key});
  @override
  Widget build(BuildContext context) => MaterialApp(
        title: 'KLU BZA',
        debugShowCheckedModeBanner: false,
        theme: ThemeData(
          useMaterial3: true,
          scaffoldBackgroundColor: const Color(0xfff5f7fb),
          colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xff244ad3)),
          inputDecorationTheme: const InputDecorationTheme(
            border: OutlineInputBorder(),
            filled: true,
            fillColor: Colors.white,
          ),
        ),
        home: const Home(),
      );
}

class Home extends StatefulWidget {
  const Home({super.key});
  @override
  State<Home> createState() => _HomeState();
}

class _HomeState extends State<Home> {
  final id = TextEditingController(),
      password = TextEditingController(),
      captcha = TextEditingController();
  final form = GlobalKey<FormState>();
  final client = http.Client();
  final pageScroll = ScrollController();
  String? token, captchaImage, error, year, semester, synced;
  bool busy = false, loggedIn = false, demo = false, hidePassword = true;
  int target = 75;
  List<Map<String, dynamic>> years = [], semesters = [];
  List<Attendance> rows = [];
  @override
  void dispose() {
    pageScroll.dispose();
    id.dispose();
    password.dispose();
    captcha.dispose();
    client.close();
    super.dispose();
  }

  Future<Map<String, dynamic>> api(
    String path, {
    String method = 'GET',
    Map<String, dynamic>? data,
  }) async {
    if (apiBase.isEmpty)
      throw Exception(
        'Live ERP connection is not configured. You can explore the demo.',
      );
    final uri = Uri.parse('${apiBase.replaceFirst(RegExp(r'/$'), '')}$path');
    if (uri.scheme != 'https' &&
        !(uri.scheme == 'http' &&
            ['localhost', '127.0.0.1'].contains(uri.host))) {
      throw Exception('Use an HTTPS gateway for your student account.');
    }
    final headers = {
      'Content-Type': 'application/json',
      if (token != null) 'Authorization': 'Bearer $token',
    };
    final response = await (method == 'POST'
            ? client.post(
                uri,
                headers: headers,
                body: jsonEncode(data ?? {}),
              )
            : method == 'DELETE'
                ? client.delete(uri, headers: headers)
                : client.get(uri, headers: headers))
        .timeout(const Duration(seconds: 60));
    Map<String, dynamic> body;
    try {
      body = jsonDecode(response.body) as Map<String, dynamic>;
    } catch (_) {
      throw Exception(
        'The gateway returned an unreadable response. Please retry.',
      );
    }
    if (response.statusCode >= 400) {
      if (response.statusCode == 401 && loggedIn && mounted) {
        setState(() {
          loggedIn = false;
          rows = [];
          synced = null;
          captchaImage = null;
        });
      }
      throw Exception(
        body['detail'] is String
            ? body['detail']
            : 'Request failed. Please retry.',
      );
    }
    return body;
  }

  Future<void> run(Future<void> Function() action) async {
    if (busy) return;
    setState(() {
      busy = true;
      error = null;
    });
    try {
      await action();
    } catch (e) {
      if (mounted)
        setState(() => error = e.toString().replaceFirst('Exception: ', ''));
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> challenge() async {
    if (token != null) await api('/api/session', method: 'DELETE');
    token = null;
    setState(() {
      captchaImage = null;
      captcha.clear();
    });
    final data = await api('/api/challenge', method: 'POST');
    setState(() {
      token = data['token'] as String;
      captchaImage = data['captcha'] as String;
    });
  }

  Future<void> loadFilters() async {
    final data = await api('/api/filters');
    setState(() {
      years = (data['years'] as List).cast<Map<String, dynamic>>();
      semesters = (data['semesters'] as List).cast<Map<String, dynamic>>();
      year = years.isEmpty ? null : years.first['value'] as String;
      semester = semesters.isEmpty ? null : semesters.first['value'] as String;
    });
  }

  Future<void> login() async {
    if (!form.currentState!.validate()) return;
    if (token == null || captchaImage == null)
      throw Exception('Load the ERP CAPTCHA first.');
    try {
      await api(
        '/api/login',
        method: 'POST',
        data: {
          'student_id': id.text.trim(),
          'password': password.text,
          'captcha': captcha.text.trim(),
        },
      );
    } finally {
      password.clear();
      captcha.clear();
    }
    setState(() {
      loggedIn = true;
      demo = false;
    });
    if (pageScroll.hasClients) pageScroll.jumpTo(0);
    await loadFilters();
  }

  Future<void> refresh() async {
    if (demo) {
      setState(() => synced = 'Demo · sample data');
      return;
    }
    if (year == null || semester == null)
      throw Exception('Select an academic year and semester.');
    final data = await api(
      '/api/attendance?${Uri(queryParameters: {
            'year': year!,
            'semester': semester!
          }).query}',
    );
    setState(() {
      rows = (data['rows'] as List)
          .map((j) => Attendance.fromJson(j as Map<String, dynamic>))
          .toList();
      synced = DateTime.parse(data['synced_at'] as String)
          .toLocal()
          .toString()
          .split('.')
          .first;
    });
  }

  void openDemo() {
    if (pageScroll.hasClients) pageScroll.jumpTo(0);
    password.clear();
    captcha.clear();
    setState(() {
      demo = true;
      loggedIn = true;
      error = null;
      years = [
        {'value': 'demo', 'label': 'Sample academic year'},
      ];
      semesters = [
        {'value': 'odd', 'label': 'Odd Sem'},
      ];
      year = 'demo';
      semester = 'odd';
      synced = 'Demo · sample data';
      rows = const [
        Attendance('DEMO101', 'Data Structures & Algorithms', 'L', 24, 28),
        Attendance('DEMO101', 'Data Structures & Algorithms', 'P', 15, 20),
        Attendance('DEMO102', 'Machine Learning', 'L', 18, 30),
        Attendance('DEMO103', 'Operating Systems', 'P', 22, 24),
      ];
    });
  }

  Future<void> logout() async {
    try {
      if (token != null) await api('/api/session', method: 'DELETE');
    } finally {
      id.clear();
      password.clear();
      captcha.clear();
      setState(() {
        token = null;
        loggedIn = false;
        demo = false;
        rows = [];
        years = [];
        semesters = [];
        year = null;
        semester = null;
        synced = null;
        captchaImage = null;
      });
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(
          title: const Row(
            children: [
              Icon(Icons.school_outlined),
              SizedBox(width: 10),
              Expanded(
                  child: Text('KLU BZA',
                      style: TextStyle(fontWeight: FontWeight.w800))),
            ],
          ),
          actions: [
            if (loggedIn)
              TextButton.icon(
                onPressed: busy ? null : () => run(logout),
                icon: const Icon(Icons.logout),
                label: const Text('Sign out'),
              ),
            const SizedBox(width: 12),
          ],
        ),
        body: SafeArea(
          child: SingleChildScrollView(
            controller: pageScroll,
            padding: const EdgeInsets.all(24),
            child: Center(
              child: ConstrainedBox(
                constraints: BoxConstraints(maxWidth: loggedIn ? 1100 : 480),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    if (busy) const LinearProgressIndicator(),
                    if (error != null)
                      Padding(
                        padding: const EdgeInsets.symmetric(vertical: 12),
                        child: Semantics(
                          liveRegion: true,
                          child: Card(
                            color: const Color(0xffffe9e7),
                            child: Padding(
                              padding: const EdgeInsets.all(16),
                              child: Text(error!),
                            ),
                          ),
                        ),
                      ),
                    if (loggedIn) ...dashboard() else ...loginView(),
                    const SizedBox(height: 28),
                    const Text(
                      'Unofficial student companion · Not affiliated with KL University',
                      textAlign: TextAlign.center,
                      style: TextStyle(color: Colors.blueGrey, fontSize: 12),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      );
  List<Widget> loginView() => [
        const SizedBox(height: 28),
        const Text(
          'Your campus.\nA little simpler.',
          style: TextStyle(
              fontSize: 38, fontWeight: FontWeight.w800, height: 1.15),
        ),
        const SizedBox(height: 14),
        const Text(
          'Attendance, clarity, and a plan for your next class.',
          style: TextStyle(fontSize: 17, color: Colors.blueGrey),
        ),
        const SizedBox(height: 30),
        Card(
          elevation: 0,
          color: Colors.white,
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Form(
              key: form,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const Text(
                    'Student sign in',
                    style: TextStyle(fontSize: 24, fontWeight: FontWeight.bold),
                  ),
                  const SizedBox(height: 8),
                  const Text(apiBase == ''
                      ? 'This demo is not connected to the university ERP.'
                      : 'Use your ERP ID, password and the CAPTCHA below.'),
                  const SizedBox(height: 24),
                  if (apiBase.isNotEmpty) ...[
                    TextFormField(
                      controller: id,
                      enabled: !busy,
                      keyboardType: TextInputType.number,
                      autocorrect: false,
                      decoration: const InputDecoration(
                        labelText: 'Student ID',
                        prefixIcon: Icon(Icons.badge_outlined),
                      ),
                      validator: (v) =>
                          RegExp(r'^\d{1,64}$').hasMatch(v?.trim() ?? '')
                              ? null
                              : 'Enter your numeric student ID',
                    ),
                    const SizedBox(height: 16),
                    TextFormField(
                      controller: password,
                      enabled: !busy,
                      obscureText: hidePassword,
                      autocorrect: false,
                      enableSuggestions: false,
                      decoration: InputDecoration(
                        labelText: 'Password',
                        prefixIcon: const Icon(Icons.lock_outline),
                        suffixIcon: IconButton(
                          tooltip:
                              hidePassword ? 'Show password' : 'Hide password',
                          onPressed: () =>
                              setState(() => hidePassword = !hidePassword),
                          icon: Icon(
                            hidePassword
                                ? Icons.visibility_outlined
                                : Icons.visibility_off_outlined,
                          ),
                        ),
                      ),
                      validator: (v) => (v == null || v.isEmpty)
                          ? 'Enter your password'
                          : null,
                    ),
                    const SizedBox(height: 18),
                    if (captchaImage != null)
                      Container(
                        padding: const EdgeInsets.all(8),
                        color: Colors.white,
                        child: Image.memory(
                          base64Decode(captchaImage!),
                          height: 75,
                          semanticLabel: 'ERP CAPTCHA challenge',
                        ),
                      ),
                    TextButton.icon(
                      onPressed:
                          busy || apiBase.isEmpty ? null : () => run(challenge),
                      icon: const Icon(Icons.refresh),
                      label: Text(
                        captchaImage == null
                            ? 'Load ERP CAPTCHA'
                            : 'New CAPTCHA',
                      ),
                    ),
                    TextFormField(
                      controller: captcha,
                      enabled: !busy,
                      autocorrect: false,
                      decoration:
                          const InputDecoration(labelText: 'CAPTCHA code'),
                      validator: (v) => (v == null || v.trim().isEmpty)
                          ? 'Enter the code shown above'
                          : null,
                    ),
                    const SizedBox(height: 24),
                    FilledButton(
                      onPressed: busy || apiBase.isEmpty || captchaImage == null
                          ? null
                          : () => run(login),
                      child: const Padding(
                        padding: EdgeInsets.all(12),
                        child: Text('Sign in to ERP'),
                      ),
                    ),
                    const SizedBox(height: 12),
                    const Text(
                      'Password is sent through the configured gateway to ERP and is never saved. Sessions stay in memory.',
                      style: TextStyle(fontSize: 12, color: Colors.blueGrey),
                    ),
                  ],
                  if (apiBase.isEmpty)
                    const Padding(
                      padding: EdgeInsets.only(top: 12),
                      child: Text(
                        'Demo build: CAPTCHA and sign-in are unavailable. Use a connected build for your real attendance. You can explore sample data below.',
                      ),
                    ),
                ],
              ),
            ),
          ),
        ),
        const SizedBox(height: 12),
        OutlinedButton(
          onPressed: busy ? null : openDemo,
          child: const Text('Explore with sample data'),
        ),
      ];
  List<Widget> dashboard() {
    final below =
        rows.where((r) => r.percent != null && r.percent! < target).length;
    return [
      const SizedBox(height: 20),
      Text(
        demo ? 'A look at your campus companion' : 'Attendance overview',
        style: const TextStyle(fontSize: 30, fontWeight: FontWeight.w800),
      ),
      const SizedBox(height: 8),
      Text(
        demo
            ? 'DEMO — fictional records. No ERP account connected.'
            : 'Keep track of each course component, one class at a time.',
        style: const TextStyle(color: Colors.blueGrey),
      ),
      const SizedBox(height: 24),
      Wrap(
        spacing: 12,
        runSpacing: 12,
        children: [
          metric('Components', '${rows.length}', Icons.view_module_outlined),
          metric('Below your target', '$below', Icons.flag_outlined),
          metric('Your target', '$target%', Icons.track_changes),
        ],
      ),
      const SizedBox(height: 24),
      Card(
        elevation: 0,
        color: Colors.white,
        child: Padding(
          padding: const EdgeInsets.all(18),
          child: Wrap(
            spacing: 16,
            runSpacing: 16,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              SizedBox(
                width: 240,
                child: DropdownButtonFormField<String>(
                  initialValue: year,
                  key: ValueKey('year-$year'),
                  isExpanded: true,
                  decoration: const InputDecoration(labelText: 'Academic year'),
                  items: years
                      .map(
                        (x) => DropdownMenuItem(
                          value: x['value'] as String,
                          child: Text(x['label'] as String),
                        ),
                      )
                      .toList(),
                  onChanged: busy || demo
                      ? null
                      : (v) => setState(() {
                            year = v;
                            rows = [];
                            synced = null;
                          }),
                ),
              ),
              SizedBox(
                width: 200,
                child: DropdownButtonFormField<String>(
                  initialValue: semester,
                  key: ValueKey('sem-$semester'),
                  isExpanded: true,
                  decoration: const InputDecoration(labelText: 'Semester'),
                  items: semesters
                      .map(
                        (x) => DropdownMenuItem(
                          value: x['value'] as String,
                          child: Text(x['label'] as String),
                        ),
                      )
                      .toList(),
                  onChanged: busy || demo
                      ? null
                      : (v) => setState(() {
                            semester = v;
                            rows = [];
                            synced = null;
                          }),
                ),
              ),
              FilledButton.icon(
                onPressed: busy
                    ? null
                    : () => run(years.isEmpty ? loadFilters : refresh),
                icon: const Icon(Icons.sync),
                label: Text(
                  years.isEmpty ? 'Load filters' : 'Refresh attendance',
                ),
              ),
            ],
          ),
        ),
      ),
      const SizedBox(height: 8),
      Text(
        synced == null
            ? 'Select your filters, then refresh.'
            : 'Last sync: $synced',
        style: const TextStyle(fontSize: 12, color: Colors.blueGrey),
      ),
      const Text('Attendance target'),
      Row(
        children: [
          Expanded(
            child: Slider(
              value: target.toDouble(),
              min: 50,
              max: 95,
              divisions: 45,
              label: '$target%',
              onChanged: (v) => setState(() => target = v.round()),
            ),
          ),
          Text('$target%'),
        ],
      ),
      const Text(
        'Planning estimate only. Your selected target is not a statement of university eligibility rules.',
        style: TextStyle(fontSize: 12, color: Colors.blueGrey),
      ),
      const SizedBox(height: 16),
      if (rows.isEmpty)
        const Padding(
          padding: EdgeInsets.all(36),
          child: Text('No attendance loaded yet.', textAlign: TextAlign.center),
        ),
      LayoutBuilder(
        builder: (context, box) {
          final width =
              box.maxWidth > 700 ? (box.maxWidth - 16) / 2 : box.maxWidth;
          return Wrap(
            spacing: 16,
            runSpacing: 16,
            children: rows
                .map((r) => SizedBox(width: width, child: attendanceCard(r)))
                .toList(),
          );
        },
      ),
    ];
  }

  Widget metric(String label, String value, IconData icon) => SizedBox(
        width: 190,
        child: Card(
          elevation: 0,
          color: Colors.white,
          child: Padding(
            padding: const EdgeInsets.all(20),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Icon(icon, color: const Color(0xff244ad3)),
                const SizedBox(height: 14),
                Text(
                  value,
                  style: const TextStyle(
                      fontSize: 30, fontWeight: FontWeight.bold),
                ),
                Text(label, style: const TextStyle(color: Colors.blueGrey)),
              ],
            ),
          ),
        ),
      );
  Widget attendanceCard(Attendance r) {
    final low = r.percent != null && r.percent! < target;
    final color = low ? const Color(0xffb24d17) : const Color(0xff17765e);
    return Card(
      elevation: 0,
      color: Colors.white,
      child: Padding(
        padding: const EdgeInsets.all(22),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    r.code,
                    style: const TextStyle(
                      color: Colors.blueGrey,
                      fontSize: 12,
                    ),
                  ),
                ),
                Chip(label: Text(r.component)),
              ],
            ),
            Text(
              r.name,
              style: const TextStyle(fontSize: 19, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 18),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Expanded(
                    child: Text('${r.attended} / ${r.conducted} attended')),
                const SizedBox(width: 12),
                Text(
                  r.percent == null ? '—' : '${r.percent!.toStringAsFixed(1)}%',
                  style: TextStyle(
                    fontSize: 26,
                    fontWeight: FontWeight.bold,
                    color: color,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            LinearProgressIndicator(
              value: (r.percent ?? 0) / 100,
              color: color,
              backgroundColor: const Color(0xffeef0f5),
              minHeight: 7,
              borderRadius: BorderRadius.circular(9),
            ),
            const SizedBox(height: 16),
            Text(
              r.conducted == 0
                  ? 'No classes conducted yet.'
                  : low
                      ? 'Attend the next ${r.needed(target)} classes to reach $target%.'
                      : 'Can miss ${r.canMiss(target)} classes and stay at $target% or above.',
              style: TextStyle(color: color),
            ),
          ],
        ),
      ),
    );
  }
}
