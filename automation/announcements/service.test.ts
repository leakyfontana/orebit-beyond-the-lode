import { describe, expect, mock, test } from 'bun:test';
import { PublicationSource, REPOSITORY } from './github';
import type { AnnouncementDelivery } from './delivery';
import { ReleaseAnnouncer } from './service';
import type { DiscordAnnouncement } from './message';
import { commit, links, receipt, release, run } from './test-fixtures';

function harness() {
  const source = new PublicationSource();
  source.branch = async () => 'main';
  source.releases = mock(async () => [release()]);
  source.successfulRun = mock(async () => run());
  source.receipt = mock(async () => ({ value: receipt(), url: links.receiptUrl }));
  const delivery = {
    hasPublished: mock((_key: string) => false),
    publish: mock(async (_key: string, _payload: DiscordAnnouncement) => ({ created: true, messageId: '123' })),
  };
  return { source, delivery, announcer: new ReleaseAnnouncer(source, delivery as unknown as AnnouncementDelivery) };
}

describe('canonical release service', () => {
  test('discovers a run publication by full target_commitish, not a commit-shaped tag', async () => {
    const { announcer, delivery } = harness();
    expect(await announcer.processRun(run())).toEqual({ outcome: 'announced', commit, messageId: '123' });
    expect(delivery.publish).toHaveBeenCalledTimes(1);
    expect(delivery.publish.mock.calls[0][0]).toBe(`${REPOSITORY}:${commit}`);
    expect(delivery.publish.mock.calls[0][1].embeds[0].url).toBe(links.releaseUrl);
  });

  test('preserves commit-key sent records without inspecting or reposting migrated receipts', async () => {
    const { source, announcer, delivery } = harness();
    delivery.hasPublished.mockImplementation(() => true);
    expect(await announcer.processRelease(release())).toEqual({ outcome: 'already_announced', commit });
    expect(delivery.hasPublished).toHaveBeenCalledWith(`${REPOSITORY}:${commit}`);
    expect(source.receipt).not.toHaveBeenCalled();
    expect(source.successfulRun).not.toHaveBeenCalled();
    expect(delivery.publish).not.toHaveBeenCalled();
  });

  test('excludes draft, prerelease, legacy, candidate and mutable-source publications', async () => {
    for (const changes of [{ draft: true }, { prerelease: true }, { published_at: null },
      { tag_name: `beta-${commit}` }, { tag_name: `candidate-${commit}` }, { tag_name: 'v0.3.2-beta.1' },
      { target_commitish: 'main' }, { target_commitish: commit.slice(0, 12) }]) {
      const { announcer, delivery } = harness();
      expect(await announcer.processRelease({ ...release(), ...changes })).toEqual({ outcome: 'waiting_for_publication' });
      expect(delivery.publish).not.toHaveBeenCalled();
    }
  });

  test('cross-checks receipt version and commit against the trusted release', async () => {
    for (const changes of [{ version: '0.3.1' }, { commit: 'c'.repeat(40) }, { release_id: 'c'.repeat(40) }]) {
      const { source, announcer, delivery } = harness();
      source.receipt = mock(async () => ({ value: { ...receipt(), ...changes }, url: links.receiptUrl }));
      await expect(announcer.processRelease(release())).rejects.toThrow();
      expect(delivery.publish).not.toHaveBeenCalled();
    }
    const { announcer, delivery } = harness();
    await expect(announcer.processRelease({ ...release(), target_commitish: 'c'.repeat(40) })).resolves.toEqual({
      outcome: 'waiting_for_successful_run', commit: 'c'.repeat(40),
    });
    expect(delivery.publish).not.toHaveBeenCalled();
    const coherent = harness();
    const otherCommit = 'c'.repeat(40);
    coherent.source.receipt = mock(async () => ({ value: { ...receipt(), commit: otherCommit,
      release_id: otherCommit, web: { ...receipt().web, commit: otherCommit } }, url: links.receiptUrl }));
    await expect(coherent.announcer.processRelease(release())).rejects.toThrow('trusted GitHub release');
    expect(coherent.delivery.publish).not.toHaveBeenCalled();
  });

  test('requires completed successful push on default branch in the trusted workflow and repository', async () => {
    for (const changes of [{ event: 'pull_request' }, { conclusion: 'failure' }, { status: 'in_progress' },
      { head_branch: 'feature' }, { path: '.github/workflows/untrusted.yml' },
      { repository: { full_name: 'attacker/fork' } }, { head_repository: { full_name: 'attacker/fork' } }]) {
      const { source, announcer, delivery } = harness();
      expect((await announcer.processRun({ ...run(), ...changes })).outcome).toBe('not_successful');
      expect(source.releases).not.toHaveBeenCalled();
      expect(delivery.publish).not.toHaveBeenCalled();
    }
  });

  test('keeps publications pending until their successful trusted workflow exists', async () => {
    const { source, announcer, delivery } = harness();
    source.successfulRun = mock(async () => null);
    expect(await announcer.processRelease(release())).toEqual({ outcome: 'waiting_for_successful_run', commit });
    expect(source.receipt).not.toHaveBeenCalled();
    expect(delivery.publish).not.toHaveBeenCalled();
    source.releases = mock(async () => []);
    expect(await announcer.processRun(run())).toEqual({ outcome: 'waiting_for_publication', commit });
  });
});
