/// Known, read-only destinations inside the official university ERP.
/// No user-provided URLs or account parameters are accepted.
const officialErp = 'https://newerp.kluniversity.in';
const officialErpHost = 'newerp.kluniversity.in';

const erpRoutes = <String, String>{
  'attendance':
      '/index.php?r=studentattendance%2Fstudentdailyattendance%2Fsearchgetinput',
  'profile':
      '/index.php?r=studentinfo%2Fstudentprofileinfo%2Fviewprofileindi',
  'cgpa':
      '/index.php?r=studentinfo%2Fstudentendexamresult%2Fsearchgetmycgpa',
  'timetable':
      '/index.php?r=timetables%2Funiversitymasteracademictimetableview%2Findexstudentindisearch',
  'seating':
      '/index.php?r=examsection%2Fexam-invigilator-student-room-allotment-info%2Fstud_my_seating_plan',
};

const erpTitles = <String, String>{
  'attendance': 'Attendance',
  'profile': 'Profile',
  'cgpa': 'Overall CGPA',
  'timetable': 'Timetable',
  'seating': 'Exam seating',
};

/// Only HTTPS pages belonging to this exact university host may be opened
/// inside the credential-bearing WebView. This is for main-frame navigation;
/// subresources are managed by the actual university site.
bool isOfficialErpUrl(String input) {
  final uri = Uri.tryParse(input);
  return uri != null &&
      uri.scheme == 'https' &&
      uri.host == officialErpHost &&
      uri.port == 443 &&
      uri.userInfo.isEmpty;
}

Uri erpModuleUri(String module) {
  final path = erpRoutes[module];
  if (path == null) {
    throw ArgumentError.value(module, 'module', 'Unsupported ERP module');
  }
  return Uri.parse('$officialErp$path');
}
