import { readFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';
import { PublicationSource, REPOSITORY, isPublicRelease, type Release, type WorkflowRun } from './github';
import { validateReceipt, renderAnnouncement, type DiscordAnnouncement } from './message';
import { AnnouncementDelivery } from './delivery';

const CHANNEL = '1565584282389454879';
export type PublicationOutcome = {
  outcome: 'announced' | 'already_announced' | 'not_successful' | 'waiting_for_publication' | 'waiting_for_successful_run';
  commit?: string;
  messageId?: string;
};

enum AdmissionState {
  Ledger,
  SuccessfulRun,
  Receipt,
  Delivery,
  Finished,
}

type ReleaseAdmission =
  | { state: AdmissionState.Ledger | AdmissionState.SuccessfulRun | AdmissionState.Receipt; commit: string; key: string }
  | { state: AdmissionState.Delivery; commit: string; key: string; message: DiscordAnnouncement }
  | { state: AdmissionState.Finished; result: PublicationOutcome };

enum PollingState {
  Poll,
  Wait,
}

export class ReleaseAnnouncer {
  constructor(private source: PublicationSource, private delivery: AnnouncementDelivery) {}

  async processRelease(release: Release, knownRun?: WorkflowRun): Promise<PublicationOutcome> {
    let admission = this.publicationAdmission(release);
    for (;;) {
      switch (admission.state) {
        case AdmissionState.Finished:
          return admission.result;
        case AdmissionState.Ledger:
          if (this.delivery.hasPublished(admission.key)) {
            return { outcome: 'already_announced', commit: admission.commit };
          }
          admission = { ...admission, state: AdmissionState.SuccessfulRun };
          break;
        case AdmissionState.SuccessfulRun: {
          const run = knownRun ?? await this.source.successfulRun(admission.commit);
          if (!run || !await this.source.isSuccessful(run, admission.commit)) {
            return { outcome: 'waiting_for_successful_run', commit: admission.commit };
          }
          admission = { ...admission, state: AdmissionState.Receipt };
          break;
        }
        case AdmissionState.Receipt: {
          const asset = await this.source.receipt(release);
          const receipt = validateReceipt(asset.value);
          if (receipt.commit !== admission.commit || receipt.release_id !== admission.commit || receipt.repository !== REPOSITORY ||
              `v${receipt.version}` !== release.tag_name) {
            throw new Error('Publication receipt identity differs from its trusted GitHub release');
          }
          const message = renderAnnouncement(receipt, { releaseUrl: release.html_url, receiptUrl: asset.url });
          admission = { ...admission, state: AdmissionState.Delivery, message };
          break;
        }
        case AdmissionState.Delivery: {
          const result = await this.delivery.publish(admission.key, admission.message);
          return { outcome: result.created ? 'announced' : 'already_announced', commit: admission.commit, messageId: result.messageId };
        }
      }
    }
  }

  private publicationAdmission(release: Release): ReleaseAdmission {
    if (!isPublicRelease(release)) {
      return { state: AdmissionState.Finished, result: { outcome: 'waiting_for_publication' } };
    }
    return { state: AdmissionState.Ledger, commit: release.target_commitish, key: `${REPOSITORY}:${release.target_commitish}` };
  }

  /** A real workflow event/replay uses the same gate as polling. Failed/PR runs never reach delivery. */
  async processRun(run: WorkflowRun): Promise<PublicationOutcome> {
    if (!await this.source.isSuccessful(run, run.head_sha)) return { outcome: 'not_successful', commit: run.head_sha };
    const release = (await this.source.releases()).find(release =>
      isPublicRelease(release) && release.target_commitish === run.head_sha);
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
  const token = readFileSync(process.env.OREBIT_DISCORD_TOKEN_FILE ||
    join(homedir(), 'Library/Application Support/Orebit Intake/discord-token'), 'utf8').trim();
  if (!token) throw new Error('Missing existing Orebit Intake bot credential');
  const source = new PublicationSource();
  const announcer = new ReleaseAnnouncer(source, new AnnouncementDelivery({ token, channelId: CHANNEL }));
  if (args[0] === '--run') {
    report(await announcer.processRun(await source.run(Number(args[1]))));
    return;
  }
  if (args[0] === '--once') { await announcer.cycle(); return; }
  report({ outcome: 'ready', repository: REPOSITORY, channel: CHANNEL });
  let polling = PollingState.Poll;
  for (;;) {
    switch (polling) {
      case PollingState.Poll:
        try { await announcer.cycle(); }
        catch (error) { report({ outcome: 'source_error', error: String(error).slice(0, 500) }); }
        polling = PollingState.Wait;
        break;
      case PollingState.Wait:
        await Bun.sleep(60_000);
        polling = PollingState.Poll;
        break;
    }
  }
}

if (import.meta.main) main().catch(error => {
  report({ outcome: 'fatal', error: String(error).slice(0, 500) });
  process.exitCode = 1;
});
