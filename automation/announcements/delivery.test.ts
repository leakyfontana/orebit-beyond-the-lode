import { describe, expect, spyOn, test } from 'bun:test';
import { Database } from 'bun:sqlite';
import { createHash } from 'node:crypto';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { AnnouncementDelivery } from './delivery';
import { REPOSITORY } from './github';
import { renderAnnouncement } from './message';
import { commit, links, receipt } from './test-fixtures';

const channel = '1565584282389454879';
const bot = '1565565791590420520';
const key = `${REPOSITORY}:${commit}`;
function message(id = '123', author = bot) {
  return { id, channel_id: channel, type: 0, author: { id: author, bot: true }, embeds: [{ url: links.releaseUrl }] };
}
function setup() {
  const stateDir = mkdtempSync(join(tmpdir(), 'orebit-announcement-'));
  const delivery = new AnnouncementDelivery({ token: 'test-token', channelId: channel, stateDir });
  return { delivery, stateDir, payload: renderAnnouncement(receipt(), links) };
}
function destination(url: string): Response | undefined {
  if (url.endsWith('/users/@me')) return Response.json({ id: bot, bot: true });
  if (url.endsWith(`/channels/${channel}`)) return Response.json({ id: channel, guild_id: '1565550697070596216', type: 0 });
}

describe('canonical version delivery with commit identity', () => {
  test('posts a canonical URL once while retaining the commit-derived key and nonce', async () => {
    const { delivery, stateDir, payload } = setup();
    let posts = 0;
    const fetcher = spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input);
      const verified = destination(url);
      if (verified) return verified;
      if (init?.method === 'POST') {
        posts++;
        const body = JSON.parse(String(init.body));
        expect(body.embeds[0].url).toBe(links.releaseUrl);
        expect(body.nonce).toBe(createHash('sha256').update(key).digest('hex').slice(0, 25));
        expect(body.enforce_nonce).toBe(true);
        return Response.json(message());
      }
      return Response.json([]);
    });
    try {
      expect(await delivery.publish(key, payload)).toEqual({ created: true, messageId: '123' });
      expect(delivery.hasPublished(key)).toBe(true);
      expect(await delivery.publish(key, payload)).toEqual({ created: false, messageId: '123' });
      expect(posts).toBe(1);
    } finally { fetcher.mockRestore(); rmSync(stateDir, { recursive: true, force: true }); }
  });

  test('keeps historical sent commit records deduplicated without reading old beta payloads', async () => {
    const { delivery, stateDir, payload } = setup();
    const database = new Database(join(stateDir, 'delivery.sqlite'));
    database.query("INSERT INTO announcements(key, state, payload, message_id) VALUES (?, 'sent', ?, ?)")
      .run(key, JSON.stringify({ embeds: [{ url: `https://github.com/${REPOSITORY}/releases/tag/beta-${commit}` }] }), '123');
    database.close();
    const fetcher = spyOn(globalThis, 'fetch').mockImplementation(async () => { throw new Error('Must not contact Discord'); });
    try {
      expect(delivery.hasPublished(key)).toBe(true);
      expect(await delivery.publish(key, payload)).toEqual({ created: false, messageId: '123' });
      expect(fetcher).not.toHaveBeenCalled();
    } finally { fetcher.mockRestore(); rmSync(stateDir, { recursive: true, force: true }); }
  });

  test('retains old pending payloads for operator review instead of migrating or resending', async () => {
    const { delivery, stateDir, payload } = setup();
    const database = new Database(join(stateDir, 'delivery.sqlite'));
    const oldPayload = JSON.stringify({ embeds: [{ url: `https://github.com/${REPOSITORY}/releases/tag/beta-${commit}` }] });
    database.query("INSERT INTO announcements(key, state, payload) VALUES (?, 'sending', ?)").run(key, oldPayload);
    const fetcher = spyOn(globalThis, 'fetch').mockImplementation(async () => { throw new Error('Must not contact Discord'); });
    try {
      await expect(delivery.publish(key, payload)).rejects.toThrow('operator review');
      expect(database.query('SELECT state, payload FROM announcements WHERE key=?').get(key))
        .toEqual({ state: 'sending', payload: oldPayload });
      expect(fetcher).not.toHaveBeenCalled();
    } finally { database.close(); fetcher.mockRestore(); rmSync(stateDir, { recursive: true, force: true }); }
  });

  test('recovers canonical URL history only from the permitted bot, through pagination', async () => {
    const { delivery, stateDir, payload } = setup();
    let historyReads = 0;
    const fetcher = spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input);
      const verified = destination(url);
      if (verified) return verified;
      expect(init?.method).not.toBe('POST');
      historyReads++;
      return Response.json(url.includes('&before=456') ? [message()]
        : [message('456', '999')]);
    });
    try {
      expect(await delivery.publish(key, payload)).toEqual({ created: false, messageId: '123' });
      expect(historyReads).toBe(2);
    } finally { fetcher.mockRestore(); rmSync(stateDir, { recursive: true, force: true }); }
  });

  test('never blindly resends an uncertain canonical release intent', async () => {
    const { delivery, stateDir, payload } = setup();
    let posts = 0;
    const fetcher = spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const verified = destination(String(input));
      if (verified) return verified;
      if (init?.method === 'POST') { posts++; throw new Error('Ambiguous timeout'); }
      return Response.json([]);
    });
    try {
      await expect(delivery.publish(key, payload)).rejects.toThrow('uncertain');
      await expect(delivery.publish(key, payload)).rejects.toThrow('uncertain');
      expect(posts).toBe(1);
    } finally { fetcher.mockRestore(); rmSync(stateDir, { recursive: true, force: true }); }
  });

  test('rejects legacy or noncanonical release URLs for new intents before network access', async () => {
    const { delivery, stateDir, payload } = setup();
    const fetcher = spyOn(globalThis, 'fetch').mockImplementation(async () => { throw new Error('Must not contact Discord'); });
    try {
      for (const url of [`https://github.com/${REPOSITORY}/releases/tag/beta-${commit}`,
        links.releaseUrl + '?other=1', links.releaseUrl.replace('v0.3.2', 'v0.3.2-beta')]) {
        payload.embeds[0].url = url;
        await expect(delivery.publish(key, payload)).rejects.toThrow('release identity');
      }
      expect(fetcher).not.toHaveBeenCalled();
    } finally { fetcher.mockRestore(); rmSync(stateDir, { recursive: true, force: true }); }
  });
});
