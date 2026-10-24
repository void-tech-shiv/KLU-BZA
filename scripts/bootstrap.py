"""Generate Flutter platform scaffolding without replacing application source."""
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

root = Path(__file__).resolve().parents[1]
client = root / 'client'
subprocess.run(['flutter', 'create', '--platforms=android,web', '--org=in.shiv', '--project-name=klu_bza', '--no-pub', '.'], cwd=client, check=True)
(client / 'test/widget_test.dart').unlink(missing_ok=True)
manifest = client / 'android/app/src/main/AndroidManifest.xml'
ET.register_namespace('android', 'http://schemas.android.com/apk/res/android')
ns = '{http://schemas.android.com/apk/res/android}'
tree = ET.parse(manifest)
r = tree.getroot()
if not any(x.get(ns+'name') == 'android.permission.INTERNET' for x in r.findall('uses-permission')):
    ET.SubElement(r, 'uses-permission', {ns+'name':'android.permission.INTERNET'})
app = r.find('application')
app.set(ns+'label', 'KLU BZA')
app.set(ns+'allowBackup', 'false')
app.set(ns+'usesCleartextTraffic', 'false')
tree.write(manifest, encoding='unicode')
web = client / 'web/index.html'
s = web.read_text().replace('<title>klu_bza</title>', '<title>KLU BZA</title>').replace('A new Flutter project.', 'Unofficial KL University student attendance companion.')
web.write_text(s)
print('Android and web scaffolding prepared. Run flutter pub get inside client/.')
