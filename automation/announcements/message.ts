const REPOSITORY = "leakyfontana/orebit-beyond-the-lode" as const;
const WEB_URL = "https://play.arcmonkeyswelding.com/" as const;
const SHA = /^[0-9a-f]{40}$/;
const PLATFORM_NAMES = {
  "android-arm64": "Android ARM64",
  "windows-x86_64": "Windows x86-64",
  "macos-arm64": "macOS ARM64",
  web: "Web/PWA",
} as const;

export interface PublicationReceipt {
  schema: 1;
  kind: "orebit.beta.publication";
  repository: typeof REPOSITORY;
  release_id: string;
  version: string;
  commit: string;
  published_at: string;
  platforms: Array<{
    platform: keyof typeof PLATFORM_NAMES;
    name: string;
    url: string;
    artifacts: Array<{ name: string; url: string; sha256: string; size: number }>;
  }>;
  web: { url: typeof WEB_URL; commit: string; verified: true };
  notes: { markdown: string; commits: Array<{ commit: string; subject: string }> };
}

/** Final Discord create-message body; the sender must not interpret receipt text. */
export interface DiscordAnnouncement {
  embeds: [{
    title: string;
    url: string;
    color: number;
    description: string;
    fields: Array<{ name: string; value: string; inline?: boolean }>;
    footer: { text: string };
    timestamp: string;
  }];
  components: Array<{ type: 1; components: Array<{ type: 2; style: 5; label: string; url: string }> }>;
  allowed_mentions: { parse: [] };
}

function requireValue(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(`Invalid publication receipt: ${message}`);
}

function object(value: unknown, keys: readonly string[], label: string): Record<string, unknown> {
  requireValue(value !== null && typeof value === "object" && !Array.isArray(value), `${label} must be an object`);
  const record = value as Record<string, unknown>;
  const actual = Object.keys(record);
  requireValue(actual.length === keys.length && actual.every((key) => keys.includes(key))
    && keys.every((key) => Object.hasOwn(record, key)), `${label} has unexpected or missing fields`);
  return record;
}

function text(value: unknown, maximum: number, label: string, multiline = false, empty = false): string {
  requireValue(typeof value === "string" && value.length <= maximum
    && (empty || value.trim().length > 0), `${label} must be a bounded string`);
  requireValue(!(multiline ? /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f]/ : /[\u0000-\u001f\u007f-\u009f]/).test(value),
    `${label} contains control characters`);
  return value;
}

function httpsUrl(value: unknown, label: string): URL {
  const raw = text(value, 2048, label);
  requireValue(!/[\s\\<>\u202a-\u202e\u2066-\u2069]/u.test(raw), `${label} contains unsafe URL characters`);
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    throw new Error(`Invalid publication receipt: ${label} is not a URL`);
  }
  requireValue(url.protocol === "https:" && !url.username && !url.password && !url.port && !url.hash
    && raw.startsWith(`https://${url.hostname}/`), `${label} must be a canonical HTTPS URL`);
  return url;
}

function driveUrl(value: unknown, folder: boolean, label: string): string {
  const url = httpsUrl(value, label);
  requireValue(typeof value === "string" && value.length <= 512, `${label} exceeds the download-link length limit`);
  requireValue(url.hostname === "drive.google.com", `${label} is not an allowlisted Drive host`);
  requireValue((folder ? /^\/drive\/folders\/[A-Za-z0-9_-]{1,256}$/ : /^\/file\/d\/[A-Za-z0-9_-]{1,256}\/view$/).test(url.pathname),
    `${label} is not a Drive ${folder ? "folder" : "file"} URL`);
  const seen = new Set<string>();
  for (const [key, val] of url.searchParams) {
    requireValue(!seen.has(key) && ((key === "usp" && /^(sharing|drivesdk|drive_link)$/.test(val))
      || (key === "resourcekey" && /^[A-Za-z0-9_-]{1,256}$/.test(val))), `${label} has an unsafe query`);
    seen.add(key);
  }
  return value as string;
}

/** Validate publication evidence only; GitHub workflow/release trust is checked by the poller. */
export function validateReceipt(value: unknown): PublicationReceipt {
  const receipt = object(value, ["schema", "kind", "repository", "release_id", "version", "commit", "published_at", "platforms", "web", "notes"], "receipt");
  requireValue(receipt.schema === 1 && receipt.kind === "orebit.beta.publication" && receipt.repository === REPOSITORY,
    "unsupported schema, kind, or repository");
  const commit = text(receipt.commit, 40, "commit");
  requireValue(SHA.test(commit) && receipt.release_id === commit, "release and commit identity disagree");
  const version = text(receipt.version, 128, "version");
  requireValue(/^[0-9]+\.[0-9]+(?:\.[0-9]+)?-beta(?:[.-][0-9A-Za-z]+)*\+[0-9a-f]{12}$/.test(version)
    && version.endsWith(`+${commit.slice(0, 12)}`), "version must identify this beta commit");
  const publishedAt = text(receipt.published_at, 32, "published_at");
  requireValue(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(publishedAt)
    && Number.isFinite(Date.parse(publishedAt))
    && new Date(publishedAt).toISOString().slice(0, 19) === publishedAt.slice(0, 19), "published_at must be a valid UTC timestamp");
  requireValue(Array.isArray(receipt.platforms) && receipt.platforms.length >= 1 && receipt.platforms.length <= 4,
    "platforms must contain one to four verified outputs");
  const platforms = new Set<string>();
  for (const item of receipt.platforms) {
    const platform = object(item, ["platform", "name", "url", "artifacts"], "platform");
    requireValue(typeof platform.platform === "string" && Object.hasOwn(PLATFORM_NAMES, platform.platform), "unknown platform");
    requireValue(!platforms.has(platform.platform), "duplicate platform");
    platforms.add(platform.platform);
    requireValue(platform.name === PLATFORM_NAMES[platform.platform as keyof typeof PLATFORM_NAMES], "platform name disagrees with identity");
    driveUrl(platform.url, true, "platform URL");
    requireValue(Array.isArray(platform.artifacts) && platform.artifacts.length >= 1 && platform.artifacts.length <= 16,
      "platform artifacts must contain one to sixteen verified files");
    const names = new Set<string>();
    const urls = new Set<string>();
    for (const item of platform.artifacts) {
      const artifact = object(item, ["name", "url", "sha256", "size"], "artifact");
      const name = text(artifact.name, 255, "artifact name");
      const url = driveUrl(artifact.url, false, "artifact URL");
      requireValue(!names.has(name) && !urls.has(url), "duplicate platform artifact");
      names.add(name);
      urls.add(url);
      requireValue(typeof artifact.sha256 === "string" && /^[0-9a-f]{64}$/.test(artifact.sha256), "artifact checksum must be SHA-256");
      requireValue(typeof artifact.size === "number" && Number.isSafeInteger(artifact.size) && artifact.size > 0,
        "artifact size must be a positive safe integer");
      // These instructions describe the actual published package, never a guessed format.
      requireValue(name.toLowerCase().endsWith(platform.platform === "android-arm64" ? ".apk" : ".zip"),
        "artifact extension does not match the published platform package");
    }
  }
  const web = object(receipt.web, ["url", "commit", "verified"], "web");
  requireValue(web.url === WEB_URL && web.commit === commit && web.verified === true, "live Web verification or identity mismatch");
  const notes = object(receipt.notes, ["markdown", "commits"], "notes");
  const markdown = text(notes.markdown, 65536, "notes markdown", true, true);
  requireValue(Array.isArray(notes.commits) && notes.commits.length <= 1000, "notes commits must be a bounded array");
  requireValue(markdown.trim().length > 0 || notes.commits.length > 0, "recorded release notes must not be empty");
  for (const item of notes.commits) {
    const note = object(item, ["commit", "subject"], "notes commit");
    requireValue(typeof note.commit === "string" && SHA.test(note.commit), "notes commit must be a full SHA");
    text(note.subject, 512, "commit subject");
  }
  return value as PublicationReceipt;
}

function escapeMarkdown(value: string): string {
  return value.replace(/[\u202a-\u202e\u2066-\u2069]/gu, "")
    .replace(/\\/g, "\\\\")
    .replace(/([`*_{}\[\]()<>#+.!|~\-])/g, "\\$1")
    .replace(/@/g, "@\u200b");
}

function excerpt(value: string, maximum: number): string {
  if (value.length <= maximum) return value;
  let end = maximum - 1;
  // Do not cut a surrogate pair or leave an unpaired Markdown escape.
  if (end > 0 && /[\ud800-\udbff]/u.test(value[end - 1]!)) end--;
  let slashes = 0;
  while (end > slashes && value[end - slashes - 1] === "\\") slashes++;
  if (slashes % 2) end--;
  return `${value.slice(0, end)}…`;
}

const UPDATE_INSTRUCTIONS: Record<keyof typeof PLATFORM_NAMES, string> = {
  "android-arm64": "**Android ARM64:** Install over the existing app. **Don’t uninstall**; stop if the signature doesn’t match.",
  "windows-x86_64": "**Windows 64-bit:** Quit, extract the whole ZIP into a fresh folder, and keep the EXE and DLLs together.",
  "macos-arm64": "**macOS · Apple Silicon only:** Replace the app in Applications. Not notarized; if blocked, use Privacy & Security → Open Anyway.",
  web: "**Web / PWA:** Reload the game to update.",
};

const PLATFORM_ORDER = ["web", "windows-x86_64", "macos-arm64", "android-arm64"] as const;
const BUTTON_LABELS = { web: "Play web", "windows-x86_64": "Windows", "macos-arm64": "macOS", "android-arm64": "Android" } as const;
const TOOLING_NOTE = /^(?:ci|build|chore|docs|test|style|refactor)(?:\([^)]*\))?!?:|\b(?:GitHub Actions|CI\/CD|CI|inbound SSH|outbound (?:beta )?deploy(?:ment)?|beta delivery|publication receipts?|release automation|(?:build|release|deployment) (?:pipelines?|workflows?))\b/i;

function highlights(receipt: PublicationReceipt): string[] {
  const candidates = receipt.notes.markdown.trim()
    ? receipt.notes.markdown.split("\n")
    : receipt.notes.commits.map(note => note.subject);
  const result: string[] = [];
  const seen = new Set<string>();
  let inCode = false;
  for (const candidate of candidates) {
    if (/^\s*(`{3,}|~{3,})/.test(candidate)) { inCode = !inCode; continue; }
    if (inCode || TOOLING_NOTE.test(candidate) || /^\s*(?:#{1,6}\s|https?:\/\/|<!--)/.test(candidate)) continue;
    const note = candidate.trim().replace(/^[-*•]\s+|^\d+\.\s+/, "")
      .replace(/\s*\(?`[0-9a-f]{7,40}`\)?\s*$/i, "")
      .replace(/\s*\(#\d+\)\s*$/, "")
      .replace(/^(?:feat|fix|perf)(?:\([^)]*\))?!?:\s*/i, "")
      .replace(/\s+/g, " ").trim();
    if (!note || TOOLING_NOTE.test(note) || seen.has(note.toLowerCase())) continue;
    seen.add(note.toLowerCase());
    result.push(`- ${excerpt(escapeMarkdown(note), 160)}`);
    if (result.length === 3) break;
  }
  return result;
}

/** Pure, deterministic rendering: no network requests, commands, or generated change claims. */
export function renderAnnouncement(receipt: PublicationReceipt, links: { releaseUrl: string; receiptUrl: string }): DiscordAnnouncement {
  receipt = validateReceipt(receipt);
  const release = httpsUrl(links.releaseUrl, "release URL");
  const asset = httpsUrl(links.receiptUrl, "receipt URL");
  const releasePath = `/${REPOSITORY}/releases/tag/beta-${receipt.commit}`;
  const assetPath = `/${REPOSITORY}/releases/download/beta-${receipt.commit}/publication.json`;
  requireValue(release.hostname === "github.com" && release.pathname === releasePath && !release.search,
    "release URL must identify this repository and commit");
  requireValue(asset.hostname === "github.com" && asset.pathname === assetPath && !asset.search,
    "receipt URL must identify this release's publication.json");
  const platforms = PLATFORM_ORDER.flatMap(key => receipt.platforms.filter(platform => platform.platform === key));
  const notes = highlights(receipt);
  const description = notes.length ? `**Highlights**\n${notes.join("\n")}` : "A new beta is ready to play.";
  const downloads = platforms.map(platform => ({
    type: 2 as const,
    style: 5 as const,
    label: BUTTON_LABELS[platform.platform],
    url: platform.platform === "web" ? WEB_URL
      : platform.artifacts.length === 1 ? platform.artifacts[0]!.url : platform.url,
  }));
  return {
    embeds: [{
      title: `Orebit · ${receipt.version.split("+")[0]}`,
      url: links.releaseUrl,
      color: 0xe6ab47,
      description,
      fields: [{ name: "Updating?", value: platforms.map(platform => `- ${UPDATE_INSTRUCTIONS[platform.platform]}`).join("\n") }],
      footer: { text: "Beta release" },
      timestamp: receipt.published_at,
    }],
    components: [
      { type: 1, components: downloads },
      { type: 1, components: [
        { type: 2, style: 5, label: "Full release notes", url: links.releaseUrl },
        { type: 2, style: 5, label: "Report a bug", url: "https://discord.com/channels/1565550697070596216/1565551259929284739" },
      ] },
    ],
    allowed_mentions: { parse: [] },
  };
}
