export const REPOSITORY = 'leakyfontana/orebit-beyond-the-lode';
const GH = '/opt/homebrew/bin/gh';
const WORKFLOW = '.github/workflows/beta.yml';
const MAX_RESPONSE = 8 * 1024 * 1024;

export interface WorkflowRun {
  id: number;
  head_sha: string;
  head_branch: string;
  event: string;
  status: string;
  conclusion: string | null;
  path: string;
  html_url: string;
  repository: { full_name: string };
  head_repository: { full_name: string };
}
export interface Release {
  id: number;
  tag_name: string;
  draft: boolean;
  prerelease: boolean;
  published_at: string | null;
  html_url: string;
  assets: Array<{ id: number; name: string; size: number; browser_download_url: string }>;
}

async function github(path: string, options: { pages?: boolean; asset?: boolean } = {}): Promise<string> {
  // Only this repository's fixed API namespace is allowed, never an arbitrary release URL.
  if (!path.startsWith(`repos/${REPOSITORY}`) || /[\r\n]/.test(path)) throw new Error('Unexpected GitHub API path');
  const args = [GH, 'api', path];
  if (options.pages) args.push('--paginate', '--slurp');
  if (options.asset) args.push('-H', 'Accept: application/octet-stream');
  const child = Bun.spawn(args, { stdin: 'ignore', stdout: 'pipe', stderr: 'ignore' });
  const timer = setTimeout(() => child.kill('SIGKILL'), 60_000);
  let size = 0;
  const chunks: Uint8Array[] = [];
  try {
    for await (const chunk of child.stdout) {
      size += chunk.byteLength;
      if (size > MAX_RESPONSE) throw new Error('GitHub publication response exceeds limit');
      chunks.push(chunk);
    }
    if (await child.exited !== 0) throw new Error('GitHub publication query failed; check local gh authentication and repository availability');
    return Buffer.concat(chunks).toString('utf8');
  } catch (error) {
    child.kill('SIGKILL');
    await child.exited;
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

export class PublicationSource {
  private defaultBranch: string | undefined;

  async branch(): Promise<string> {
    if (!this.defaultBranch) {
      const repo = JSON.parse(await github(`repos/${REPOSITORY}`));
      if (repo.full_name !== REPOSITORY || typeof repo.default_branch !== 'string' || !repo.default_branch) {
        throw new Error('Unexpected GitHub repository identity');
      }
      this.defaultBranch = repo.default_branch;
    }
    return this.defaultBranch!;
  }

  async releases(): Promise<Release[]> {
    const pages = JSON.parse(await github(`repos/${REPOSITORY}/releases?per_page=100`, { pages: true }));
    if (!Array.isArray(pages) || pages.some(page => !Array.isArray(page))) throw new Error('Invalid GitHub releases response');
    return pages.flat().filter((release: Release) =>
      release.draft === false && release.prerelease === true && release.published_at !== null &&
      /^beta-[a-f0-9]{40}$/.test(release.tag_name) && Array.isArray(release.assets))
      .sort((a: Release, b: Release) => Date.parse(a.published_at!) - Date.parse(b.published_at!));
  }

  async run(id: number): Promise<WorkflowRun> {
    if (!Number.isSafeInteger(id) || id < 1) throw new Error('Expected positive GitHub run ID');
    return JSON.parse(await github(`repos/${REPOSITORY}/actions/runs/${id}`));
  }

  async isSuccessful(run: WorkflowRun, commit: string): Promise<boolean> {
    return run.repository?.full_name === REPOSITORY && run.head_repository?.full_name === REPOSITORY &&
      run.path === WORKFLOW && run.event === 'push' && run.status === 'completed' && run.conclusion === 'success' &&
      run.head_sha === commit && run.head_branch === await this.branch();
  }

  async successfulRun(commit: string): Promise<WorkflowRun | null> {
    if (!/^[a-f0-9]{40}$/.test(commit)) throw new Error('Invalid release commit');
    const pages = JSON.parse(await github(`repos/${REPOSITORY}/actions/workflows/beta.yml/runs?head_sha=${commit}&event=push&status=success&per_page=100`, { pages: true }));
    if (!Array.isArray(pages) || pages.some(page => !Array.isArray(page.workflow_runs))) throw new Error('Invalid GitHub workflow response');
    for (const run of pages.flatMap(page => page.workflow_runs)) {
      if (await this.isSuccessful(run, commit)) return run;
    }
    return null;
  }

  async receipt(release: Release): Promise<{ value: unknown; url: string }> {
    const receipts = release.assets.filter(asset => asset.name === 'publication.json');
    if (receipts.length !== 1 || !Number.isSafeInteger(receipts[0].id) || receipts[0].id < 1 ||
        !Number.isSafeInteger(receipts[0].size) || receipts[0].size < 1 || receipts[0].size > 1024 * 1024) {
      throw new Error('Published release must have exactly one bounded publication.json asset');
    }
    const asset = receipts[0];
    const expected = `https://github.com/${REPOSITORY}/releases/download/${release.tag_name}/publication.json`;
    if (asset.browser_download_url !== expected || release.html_url !== `https://github.com/${REPOSITORY}/releases/tag/${release.tag_name}`) {
      throw new Error('Unexpected GitHub publication source URL');
    }
    const text = await github(`repos/${REPOSITORY}/releases/assets/${asset.id}`, { asset: true });
    if (Buffer.byteLength(text) !== asset.size) throw new Error('Publication receipt size differs from GitHub asset metadata');
    return { value: JSON.parse(text), url: expected };
  }
}
