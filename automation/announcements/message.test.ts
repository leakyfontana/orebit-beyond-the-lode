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
  test('includes only actually published platforms and preserves their download provenance', () => {
    const input = validateReceipt(receipt());
    const message = renderAnnouncement(input, links);
    expect(message.embeds[0].fields.map(field => field.name)).toEqual(['Web/PWA']);
    expect(message.embeds[0].fields[0].value).toContain(input.platforms[0].artifacts[0].url);
    expect(message.embeds[0].fields[0].value).toContain(input.web.url);
    expect(message.embeds[0].title).toContain(input.version);
    expect(message.embeds[0].description).toContain('Fix collision behavior');
    expect(message.embeds[0].description).toContain(links.receiptUrl);
  });

  test('preserves the UTC-offset timestamps emitted by the CI receipt producer', () => {
    const input = receipt();
    input.published_at = '2026-10-30T00:00:00.123456+00:00';
    expect(renderAnnouncement(validateReceipt(input), links).embeds[0].timestamp).toBe(input.published_at);
  });

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
    input.notes.markdown = ('@everyone [misleading link](https://evil.invalid/) 🚀 '.repeat(900));
    const message = renderAnnouncement(input, links);
    const embed = message.embeds[0];
    const aggregate = embed.title.length + embed.description.length + embed.footer.text.length +
      embed.fields.reduce((total, field) => total + field.name.length + field.value.length, 0);
    expect(aggregate).toBeLessThanOrEqual(6000);
    expect(embed.description.length).toBeLessThanOrEqual(4096);
    expect(embed.description).toContain(links.receiptUrl);
    expect(embed.fields[0].value).toContain(input.platforms[0].artifacts[0].url);
    expect(embed.description).not.toContain('@everyone');
    expect(message.allowed_mentions.parse).toEqual([]);
    expect(embed.description.isWellFormed()).toBe(true);
  });
});
