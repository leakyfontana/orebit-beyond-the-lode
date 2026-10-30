import { describe, expect, test } from 'bun:test';
import { renderAnnouncement, validateReceipt, type PublicationReceipt } from './message';

const commit = 'a'.repeat(40);
const links = {
  releaseUrl: `https://github.com/leakyfontana/orebit-beyond-the-lode/releases/tag/beta-${commit}`,
  receiptUrl: `https://github.com/leakyfontana/orebit-beyond-the-lode/releases/download/beta-${commit}/publication.json`,
};
function receipt(): PublicationReceipt {
  return {
    schema: 1,
    kind: 'orebit.beta.publication',
    repository: 'leakyfontana/orebit-beyond-the-lode',
    release_id: commit,
    version: `1.0-beta.2+${commit.slice(0, 12)}`,
    commit,
    published_at: '2026-10-30T00:00:00Z',
    platforms: [{
      platform: 'web', name: 'Web/PWA', url: 'https://drive.google.com/drive/folders/web-folder',
      artifacts: [{ name: 'Orebit-web.zip', url: 'https://drive.google.com/file/d/web-archive/view', sha256: 'b'.repeat(64), size: 123 }],
    }],
    web: { url: 'https://play.arcmonkeyswelding.com/', commit, verified: true },
    notes: { markdown: 'Fix collision behavior when drilling sideways.', commits: [{ commit, subject: 'Fix collision behavior when drilling sideways.' }] },
  };
}

describe('publication announcements', () => {

  test('rejects mismatched commit evidence rather than announcing an unverified build', () => {
    const input = receipt();
    input.web.commit = 'c'.repeat(40);
    expect(() => validateReceipt(input)).toThrow();
    const otherRelease = links.releaseUrl.replace(commit, 'c'.repeat(40));
    expect(() => renderAnnouncement(receipt(), { ...links, releaseUrl: otherRelease })).toThrow();
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
