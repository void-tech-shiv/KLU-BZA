class Attendance {
  final String code, name, component;
  final int attended, conducted;
  const Attendance(this.code, this.name, this.component, this.attended, this.conducted);
  factory Attendance.fromJson(Map<String, dynamic> j) => Attendance(
    j['code'] as String, j['name'] as String, j['component'] as String,
    j['attended'] as int, j['conducted'] as int);
  double? get percent => conducted == 0 ? null : attended * 100 / conducted;
  int needed(int target) {
    if (target <= 0 || target >= 100) throw ArgumentError('Target must be 1–99');
    final deficit = target * conducted - 100 * attended;
    return deficit <= 0 ? 0 : (deficit / (100 - target)).ceil();
  }
  int canMiss(int target) {
    if (target <= 0 || target >= 100) throw ArgumentError('Target must be 1–99');
    final value = (100 * attended / target - conducted).floor();
    return value < 0 ? 0 : value;
  }
}
