import { readFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';
import { PublicationSource, REPOSITORY, type Release, type WorkflowRun } from './github';
import { validateReceipt, renderAnnouncement } from './message';
import { AnnouncementDelivery } from './delivery';

const CHANNEL = '1565584282389454879';
export type PublicationOutcome = {
  outcome: 'announced' | 'already_announced' | 'not_successful' | 'waiting_for_publication' | 'waiting_for_successful_run';
  commit?: string;
  messageId?: string;
};

export class ReleaseAnnouncer {
  constructor(private source: PublicationSource, private delivery: AnnouncementDelivery) {}

  async processRelease(release: Release, knownRun?: WorkflowRun): Promise<PublicationOutcome> {
    if (release.draft || !release.prerelease || !release.published_at || !/^beta-[a-f0-9]{40}$/.test(release.tag_name)) {
      return { outcome: 'waiting_for_publication' };
    }
    const commit = release.tag_name.slice(5);
    const key = `${REPOSITORY}:${commit}`;
    if (this.delivery.hasPublished(key)) return { outcome: 'already_announced', commit };
    const run = knownRun ?? await this.source.successfulRun(commit);
    if (!run || !await this.source.isSuccessful(run, commit)) {
      return { outcome: 'waiting_for_successful_run', commit };
    }
    const asset = await this.source.receipt(release);
    const receipt = validateReceipt(asset.value);
    if (receipt.commit !== commit || receipt.release_id !== commit || receipt.repository !== REPOSITORY) {
      throw new Error('Publication receipt identity differs from its trusted GitHub release');
    }
    const message = renderAnnouncement(receipt, { releaseUrl: release.html_url, receiptUrl: asset.url });
    const result = await this.delivery.publish(key, message);
    return { outcome: result.created ? 'announced' : 'already_announced', commit, messageId: result.messageId };
  }

  /** A real workflow event/replay uses the same gate as polling. Failed/PR runs never reach delivery. */
  async processRun(run: WorkflowRun): Promise<PublicationOutcome> {
    if (!await this.source.isSuccessful(run, run.head_sha)) return { outcome: 'not_successful', commit: run.head_sha };
    const release = (await this.source.releases()).find(release => release.tag_name === `beta-${run.head_sha}`);
    return release ? this.processRelease(release, run) : { outcome: 'waiting_for_publication', commit: run.head_sha };
  }

  async cycle(): Promise<void> {
    for (const release of await this.source.releases()) {
      try {
        const result = await this.processRelease(release);
        if (result.outcome === 'announced') report(result);
      } catch (error) {
        report({ outcome: 'publication_error', release: release.id, error: String(error).slice(0, 500) });
      }
    }
  }
}

function report(value: object) {
  console.log(JSON.stringify({ at: new Date().toISOString(), ...value }));
}

async function main() {
  const args = process.argv.slice(2);
  if (args.length && !(args.length === 1 && args[0] === '--once') &&
      !(args.length === 2 && args[0] === '--run' && /^[1-9][0-9]*$/.test(args[1]))) {
    throw new Error('Usage: bun automation/announcements/service.ts [--once | --run GITHUB_RUN_ID]');
  }
  const token = readFileSync(join(homedir(), 'Library/Application Support/Orebit Intake/discord-token'), 'utf8').trim();
  if (!token) throw new Error('Missing existing Orebit Intake bot credential');
  const source = new PublicationSource();
  const announcer = new ReleaseAnnouncer(source, new AnnouncementDelivery({ token, channelId: CHANNEL }));
  if (args[0] === '--run') {
    report(await announcer.processRun(await source.run(Number(args[1]))));
    return;
  }
  if (args[0] === '--once') { await announcer.cycle(); return; }
  report({ outcome: 'ready', repository: REPOSITORY, channel: CHANNEL });
  for (;;) {
    try { await announcer.cycle(); }
    catch (error) { report({ outcome: 'source_error', error: String(error).slice(0, 500) }); }
    await Bun.sleep(60_000);
  }
}

if (import.meta.main) main().catch(error => {
  report({ outcome: 'fatal', error: String(error).slice(0, 500) });
  process.exitCode = 1;
});
