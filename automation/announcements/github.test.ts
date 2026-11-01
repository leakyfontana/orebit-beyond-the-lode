import { describe, expect, spyOn, test } from 'bun:test';
import { isPublicRelease, PublicationSource, REPOSITORY } from './github';
import { commit, links, receipt, release, run } from './test-fixtures';

describe('public release discovery', () => {
  test('accepts only plain v0.x.y public releases with a full immutable target commit', () => {
    expect(isPublicRelease(release())).toBe(true);
    for (const changes of [{ draft: true }, { prerelease: true }, { published_at: null },
      { published_at: 'invalid' }, { target_commitish: 'main' }, { target_commitish: commit + '\n' },
      ...['v1.0.0', 'v0.3', 'v0.03.2', 'v0.3.02', 'v0.3.2-beta', 'v0.3.2+build', 'v0.3.2\n',
        `beta-${commit}`, `candidate-${commit}`].map(tag_name => ({ tag_name }))]) {
      expect(isPublicRelease({ ...release(), ...changes })).toBe(false);
    }
  });

  test('filters API inventory and reuses feed cache without skipping pending run checks', async () => {
    let inventoryReads = 0;
    let feedReads = 0;
    let runReads = 0;
    const fetcher = spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith('/releases.atom')) {
        feedReads++;
        return feedReads === 1 ? new Response('<feed/>', { headers: { ETag: '"release-feed"' } })
          : new Response(null, { status: 304 });
      }
      if (url.includes('/releases?')) {
        inventoryReads++;
        return Response.json([release(), { ...release(), tag_name: `candidate-${commit}` },
          { ...release(), prerelease: true }, { ...release(), tag_name: `beta-${commit}` }]);
      }
      if (url.includes('/actions/workflows/beta.yml/runs?')) {
        runReads++;
        return Response.json({ workflow_runs: [run()] });
      }
      if (url === `https://api.github.com/repos/${REPOSITORY}`) {
        return Response.json({ full_name: REPOSITORY, default_branch: 'main' });
      }
      throw new Error(`Unexpected test URL: ${url}`);
    });
    try {
      const source = new PublicationSource();
      expect(await source.releases()).toEqual([release()]);
      expect(await source.releases()).toEqual([release()]);
      expect(await source.successfulRun(commit)).toEqual(run());
      expect(inventoryReads).toBe(1);
      expect(feedReads).toBe(2);
      expect(runReads).toBe(1);
    } finally { fetcher.mockRestore(); }
  });

  test('reads only the unique bounded version-tagged receipt URL', async () => {
    const fetcher = spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      expect(String(input)).toBe(links.receiptUrl);
      return new Response(JSON.stringify(receipt()));
    });
    try {
      const source = new PublicationSource();
      expect(await source.receipt(release())).toEqual({ value: receipt(), url: links.receiptUrl });
      for (const invalid of [
        { ...release(), assets: [] },
        { ...release(), assets: [...release().assets, ...release().assets] },
        { ...release(), html_url: links.releaseUrl + '?other=1' },
        { ...release(), assets: [{ ...release().assets[0], size: 1024 * 1024 + 1 }] },
        { ...release(), assets: [{ ...release().assets[0], browser_download_url: links.receiptUrl.replace('v0.3.2', 'v0.3.1') }] },
      ]) await expect(source.receipt(invalid)).rejects.toThrow();
      expect(fetcher).toHaveBeenCalledTimes(1);
    } finally { fetcher.mockRestore(); }
  });

  test('rejects unsafe receipt redirects and size mismatches', async () => {
    const fetcher = spyOn(globalThis, 'fetch').mockImplementation(async () =>
      new Response(null, { status: 302, headers: { Location: 'https://attacker.invalid/publication.json' } }));
    try {
      await expect(new PublicationSource().receipt(release())).rejects.toThrow('approved HTTPS hosts');
      expect(fetcher).toHaveBeenCalledTimes(1);
      fetcher.mockImplementation(async () => new Response('{}'));
      await expect(new PublicationSource().receipt(release())).rejects.toThrow('size differs');
    } finally { fetcher.mockRestore(); }
  });
});
