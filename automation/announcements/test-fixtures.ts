import type { Release, WorkflowRun } from './github';
import type { PublicationReceipt } from './message';

export const commit = 'a'.repeat(40);
export const links = {
  releaseUrl: 'https://github.com/leakyfontana/orebit-beyond-the-lode/releases/tag/v0.3.2',
  receiptUrl: 'https://github.com/leakyfontana/orebit-beyond-the-lode/releases/download/v0.3.2/publication.json',
};

export function receipt(): PublicationReceipt {
  return {
    schema: 1, kind: 'orebit.publication', repository: 'leakyfontana/orebit-beyond-the-lode',
    release_id: commit, version: '0.3.2', commit, published_at: '2026-10-30T00:00:00Z',
    platforms: [{
      platform: 'web', name: 'Web/PWA', url: 'https://drive.google.com/drive/folders/web-folder',
      artifacts: [{ name: 'Orebit-web.zip', url: 'https://drive.google.com/file/d/web-archive/view', sha256: 'b'.repeat(64), size: 123 }],
    }],
    web: { url: 'https://play.arcmonkeyswelding.com/', commit, verified: true },
    notes: { markdown: 'Fix collision behavior when drilling sideways.', commits: [{ commit, subject: 'Fix collision behavior when drilling sideways.' }] },
  };
}

export function release(): Release {
  return {
    id: 1, tag_name: 'v0.3.2', target_commitish: commit, draft: false, prerelease: false,
    published_at: '2026-10-30T00:00:00Z', html_url: links.releaseUrl,
    assets: [{ id: 2, name: 'publication.json', size: new TextEncoder().encode(JSON.stringify(receipt())).byteLength,
      browser_download_url: links.receiptUrl }],
  };
}

export function run(): WorkflowRun {
  return {
    id: 3, head_sha: commit, head_branch: 'main', event: 'push', status: 'completed', conclusion: 'success',
    path: '.github/workflows/beta.yml', html_url: 'https://github.com/leakyfontana/orebit-beyond-the-lode/actions/runs/3',
    repository: { full_name: 'leakyfontana/orebit-beyond-the-lode' },
    head_repository: { full_name: 'leakyfontana/orebit-beyond-the-lode' },
  };
}
