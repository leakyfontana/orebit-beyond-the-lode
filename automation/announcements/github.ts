import { createHash } from 'node:crypto';
export const REPOSITORY = 'leakyfontana/orebit-beyond-the-lode';
const API = 'https://api.github.com/';
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
  target_commitish: string;
  draft: boolean;
  prerelease: boolean;
  published_at: string | null;
  html_url: string;
  assets: Array<{ id: number; name: string; size: number; browser_download_url: string }>;
}

/** Only final public versions with immutable source identity can reach the trusted-run gate. */
export function isPublicRelease(release: Release): boolean {
  return release.draft === false && release.prerelease === false &&
    typeof release.published_at === 'string' && Number.isFinite(Date.parse(release.published_at)) &&
    /^v0\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?![\s\S])/.test(release.tag_name) &&
    /^[a-f0-9]{40}(?![\s\S])/.test(release.target_commitish) && Array.isArray(release.assets);
}

async function publicGet(url: string, maximum: number, accept: string, headers: Record<string, string> = {}) {
  const signal = AbortSignal.timeout(60_000);
  for (let redirects = 0; redirects <= 5; redirects++) {
    const target = new URL(url);
    if (target.protocol !== 'https:' || target.username || target.password || target.port || target.hash ||
      !['github.com', 'api.github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com'].includes(target.hostname)) {
      throw new Error('GitHub publication redirect is outside approved HTTPS hosts');
    }
    const response = await fetch(target, {
      headers: { 'User-Agent': 'OrebitAnnouncements/1.0', Accept: accept, ...headers },
      redirect: 'manual', signal,
    });
    if ([301, 302, 303, 307, 308].includes(response.status)) {
      const location = response.headers.get('location');
      await response.body?.cancel();
      if (!location) throw new Error('GitHub publication redirect has no destination');
      url = new URL(location, target).toString();
      continue;
    }
    if (response.status === 304) return { status: 304, body: '', bytes: 0, etag: response.headers.get('etag'), next: false };
    if (response.status !== 200 || !response.body) {
      await response.body?.cancel();
      throw new Error(`Public GitHub publication read failed (HTTP ${response.status})`);
    }
    const chunks: Uint8Array[] = [];
    let bytes = 0;
    for await (const chunk of response.body) {
      bytes += chunk.byteLength;
      if (bytes > maximum) throw new Error('GitHub publication response exceeds limit');
      chunks.push(chunk);
    }
    return {
      status: 200, body: new TextDecoder('utf-8', { fatal: true }).decode(Buffer.concat(chunks)), bytes,
      etag: response.headers.get('etag'), next: /rel="next"/.test(response.headers.get('link') ?? ''),
    };
  }
  throw new Error('GitHub publication redirect limit exceeded');
}

async function github(path: string, options: { pages?: boolean } = {}): Promise<any> {
  const namespace = `repos/${REPOSITORY}`;
  if (!(path === namespace || path.startsWith(namespace + '/')) || /[\r\n]/.test(path)) {
    throw new Error('Unexpected GitHub API path');
  }
  const pages: unknown[] = [];
  let bytes = 0;
  for (let page = 1; ; page++) {
    const url = new URL(path, API);
    if (page > 1) url.searchParams.set('page', String(page));
    const response = await publicGet(url.toString(), MAX_RESPONSE - bytes, 'application/vnd.github+json');
    if (response.status !== 200) throw new Error('Unexpected GitHub API cache response');
    bytes += response.bytes;
    let value: unknown;
    try { value = JSON.parse(response.body); } catch { throw new Error('Invalid GitHub publication JSON'); }
    if (!options.pages) return value;
    pages.push(value);
    if (!response.next) return pages;
  }
}

export class PublicationSource {
  private defaultBranch: string | undefined;
  private releaseCache: Release[] | undefined;
  private releaseFeedTag: string | null = null;
  private releaseFeedDigest: string | undefined;

  async branch(): Promise<string> {
    if (!this.defaultBranch) {
      const repo = await github(`repos/${REPOSITORY}`);
      if (repo.full_name !== REPOSITORY || typeof repo.default_branch !== 'string' || !repo.default_branch) {
        throw new Error('Unexpected GitHub repository identity');
      }
      this.defaultBranch = repo.default_branch;
    }
    return this.defaultBranch!;
  }

  async releases(): Promise<Release[]> {
    // The public Atom feed is outside the API rate bucket. Unchanged minute polls
    // reuse inventory; pending trusted-run checks still run until publication.
    const feed = await publicGet(`https://github.com/${REPOSITORY}/releases.atom`, 256 * 1024,
      'application/atom+xml', this.releaseFeedTag ? { 'If-None-Match': this.releaseFeedTag } : {});
    const digest = createHash('sha256').update(feed.body).digest('hex');
    if (this.releaseCache && (feed.status === 304 || digest === this.releaseFeedDigest)) return this.releaseCache;
    const pages = await github(`repos/${REPOSITORY}/releases?per_page=100`, { pages: true });
    if (!Array.isArray(pages) || pages.some(page => !Array.isArray(page))) throw new Error('Invalid GitHub releases response');
    const releases = pages.flat().filter(isPublicRelease)
      .sort((a: Release, b: Release) => Date.parse(a.published_at!) - Date.parse(b.published_at!));
    this.releaseCache = releases;
    this.releaseFeedTag = feed.etag;
    this.releaseFeedDigest = digest;
    return releases;
  }

  async run(id: number): Promise<WorkflowRun> {
    if (!Number.isSafeInteger(id) || id < 1) throw new Error('Expected positive GitHub run ID');
    return github(`repos/${REPOSITORY}/actions/runs/${id}`);
  }

  async isSuccessful(run: WorkflowRun, commit: string): Promise<boolean> {
    return run.repository?.full_name === REPOSITORY && run.head_repository?.full_name === REPOSITORY &&
      run.path === WORKFLOW && run.event === 'push' && run.status === 'completed' && run.conclusion === 'success' &&
      run.head_sha === commit && run.head_branch === await this.branch();
  }

  async successfulRun(commit: string): Promise<WorkflowRun | null> {
    if (!/^[a-f0-9]{40}$/.test(commit)) throw new Error('Invalid release commit');
    const pages = await github(`repos/${REPOSITORY}/actions/workflows/beta.yml/runs?head_sha=${commit}&event=push&status=success&per_page=100`, { pages: true });
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
    const response = await publicGet(expected, asset.size, 'application/octet-stream');
    if (response.status !== 200 || response.bytes !== asset.size) throw new Error('Publication receipt size differs from GitHub asset metadata');
    return { value: JSON.parse(response.body), url: expected };
  }
}
