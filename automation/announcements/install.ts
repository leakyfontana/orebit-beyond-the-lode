import { chmodSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';

const home = homedir();
const tokenPath = join(home, 'Library/Application Support/Orebit Intake/discord-token');
if (!readFileSync(tokenPath, 'utf8').trim()) throw new Error('Existing Orebit bot token is required');
chmodSync(tokenPath, 0o600);
const state = join(home, 'Library/Application Support/Orebit Intake/announcements');
mkdirSync(state, { recursive: true, mode: 0o700 });
chmodSync(state, 0o700);
const label = 'local.orebit.announcements';
const launchAgents = join(home, 'Library/LaunchAgents');
mkdirSync(launchAgents, { recursive: true });
const path = join(launchAgents, `${label}.plist`);
const [bun, script, cwd, userHome, log] = [process.execPath, join(import.meta.dir, 'service.ts'), import.meta.dir, home, join(state, 'service.log')]
  .map(value => value.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;'));
writeFileSync(path, `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>${label}</string>
<key>ProgramArguments</key><array><string>${bun}</string><string>${script}</string></array>
<key>WorkingDirectory</key><string>${cwd}</string>
<key>EnvironmentVariables</key><dict>
<key>HOME</key><string>${userHome}</string>
<key>PATH</key><string>/opt/homebrew/bin:${userHome}/.bun/bin:${userHome}/.local/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
</dict>
<key>RunAtLoad</key><true/>
<key>KeepAlive</key><true/>
<key>ThrottleInterval</key><integer>30</integer>
<key>Umask</key><integer>63</integer>
<key>StandardOutPath</key><string>${log}</string>
<key>StandardErrorPath</key><string>${log}</string>
</dict></plist>`, { mode: 0o600 });
const domain = `gui/${process.getuid!()}`;
const existing = Bun.spawnSync(['/bin/launchctl', 'print', `${domain}/${label}`]);
if (existing.exitCode === 0) {
  const stop = Bun.spawnSync(['/bin/launchctl', 'bootout', `${domain}/${label}`]);
  if (stop.exitCode) throw new Error('Could not unload existing release-announcement service');
}
const start = Bun.spawnSync(['/bin/launchctl', 'bootstrap', domain, path]);
if (start.exitCode) throw new Error('Could not start release-announcement service');
console.log(`Installed ${label}; inspect with: launchctl print ${domain}/${label}`);
