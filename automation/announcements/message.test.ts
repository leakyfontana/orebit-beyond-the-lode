import { describe, expect, test } from 'bun:test';
import { renderAnnouncement, validateReceipt } from './message';
import { commit, links, receipt } from './test-fixtures';

describe('publication announcements', () => {

  test('rejects mismatched commit evidence rather than announcing an unverified build', () => {
    const input = receipt();
    input.web.commit = 'c'.repeat(40);
    expect(() => validateReceipt(input)).toThrow();
    const otherRelease = links.releaseUrl.replace('v0.3.2', 'v0.3.1');
    expect(() => renderAnnouncement(receipt(), { ...links, releaseUrl: otherRelease })).toThrow();
  });

  test('accepts only schema1 canonical publication versions without prerelease or build labels', () => {
    for (const version of ['0.1.0', '0.3.2', '0.20.101']) {
      expect(validateReceipt({ ...receipt(), version }).version).toBe(version);
    }
    for (const version of ['1.0.0', '0.3', 'v0.3.2', '0.03.2', '0.3.02', '0.3.2-beta.1', '0.3.2+aaaa', '0.3.2\n']) {
      expect(() => validateReceipt({ ...receipt(), version })).toThrow();
    }
    expect(() => validateReceipt({ ...receipt(), kind: 'orebit.beta.publication' })).toThrow();
    expect(() => validateReceipt({ ...receipt(), schema: 2 })).toThrow();
    expect(() => validateReceipt({ ...receipt(), release_id: 'c'.repeat(40) })).toThrow();
  });

  test('preserves historical beta artifact names without labelling the release as beta', () => {
    const input = receipt();
    input.platforms[0].artifacts[0].name = 'Orebit-1.0-beta.8+aaaaaaaaaaaa-web.zip';
    expect(validateReceipt(input).platforms[0].artifacts[0].name).toContain('beta');
    const embed = renderAnnouncement(input, links).embeds[0];
    expect(embed.title).toBe('Orebit 0.3.2');
    expect(embed.footer.text).toBe('Release');
    expect(JSON.stringify(embed)).not.toMatch(/beta/i);
  });

  test('requires version-matching canonical release and receipt URLs', () => {
    for (const releaseUrl of [links.releaseUrl + '?redirect=1', links.releaseUrl.replace('v0.3.2', `beta-${commit}`),
      links.releaseUrl.replace('github.com', 'github.com.evil.invalid')]) {
      expect(() => renderAnnouncement(receipt(), { ...links, releaseUrl })).toThrow();
    }
    expect(() => renderAnnouncement(receipt(), { ...links,
      receiptUrl: links.receiptUrl.replace('v0.3.2', 'v0.3.1') })).toThrow();
  });

  test('rejects download-host impersonation and unsupported package formats', () => {
    const external = receipt();
    external.platforms[0].artifacts[0].url = 'https://drive.google.com.evil.invalid/file/d/archive/view';
    expect(() => validateReceipt(external)).toThrow();
    const wrongPackage = receipt();
    wrongPackage.platforms[0].artifacts[0].name = 'web-installer.exe';
    expect(() => validateReceipt(wrongPackage)).toThrow();
  });

  test('bounds long notes without dropping platform links or enabling mentions', () => {
    const input = receipt();
    input.notes.commits = [];
    input.notes.markdown = ('@everyone [misleading link](https://evil.invalid/) 🚀 '.repeat(900));
    const message = renderAnnouncement(input, links);
    const embed = message.embeds[0];
    const aggregate = embed.title.length + embed.description.length + embed.footer.text.length +
      embed.fields.reduce((total, field) => total + field.name.length + field.value.length, 0);
    expect(aggregate).toBeLessThanOrEqual(6000);
    expect(embed.description.length).toBeLessThanOrEqual(4096);
    expect(embed.description).not.toContain('@everyone');
    expect(message.allowed_mentions.parse).toEqual([]);
    expect(embed.description.isWellFormed()).toBe(true);
    expect(message.components.flatMap(row => row.components).every(button => button.url.startsWith('https://'))).toBe(true);
    expect(message.components.every(row => row.components.length <= 5)).toBe(true);
    expect(embed.description.length).toBeLessThanOrEqual(510);
  });

  test('keeps player changes while omitting CI chatter, commit hashes and PR metadata', () => {
    const input = receipt();
    input.notes.markdown = "";
    input.notes.commits = [
      { commit, subject: 'Automate four-platform beta delivery (#1)' },
      { commit, subject: 'fix(ci): Repair publishing job' },
      { commit, subject: 'Use verified outbound beta deployment without inbound SSH (#3)' },
      { commit, subject: 'fix: Stop fuel draining while paused (#42)' },
    ];
    const embed = renderAnnouncement(input, links).embeds[0];
    expect(embed.description).toContain('fuel');
    expect(embed.description).toContain('paused');
    expect(embed.description).not.toMatch(/publishing|delivery|SSH|#42/);
    expect(embed.title + embed.description + embed.footer.text).not.toContain(commit);
  });
});
