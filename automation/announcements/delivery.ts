import { Database } from "bun:sqlite";
import { createHash } from "node:crypto";
import { chmodSync, closeSync, constants, fchmodSync, fstatSync, mkdirSync, openSync, realpathSync } from "node:fs";
import { homedir } from "node:os";
import { join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import type { DiscordAnnouncement } from "./message.ts";

const CHANNEL = "1565584282389454879";
const GUILD = "1565550697070596216";
const BOT = "1565565791590420520";
// Unlike $, this end assertion cannot accept a trailing newline.
const KEY = /^leakyfontana\/orebit-beyond-the-lode:[0-9a-f]{40}(?![\s\S])/;
const SNOWFLAKE = /^[1-9][0-9]{0,19}(?![\s\S])/;
const DEFAULT_STATE = process.env.OREBIT_ANNOUNCEMENTS_STATE_DIR ||
  join(homedir(), "Library/Application Support/Orebit Intake/announcements");

type DeliveryResult = { created: boolean; messageId: string };
enum IntentState {
  Pending = "pending",
  Sending = "sending",
  Sent = "sent",
}

type PendingIntent = { state: IntentState.Pending; payload: string; message_id: null };
type SendingIntent = { state: IntentState.Sending; payload: string; message_id: null };
type Intent = PendingIntent | SendingIntent | { state: IntentState.Sent; payload: string; message_id: string };

enum RequestOutcome {
  Uncertain,
  Rejected,
}

enum QueueState {
  Idle,
  Queued,
}

type DeliveryQueue = { state: QueueState.Idle } | { state: QueueState.Queued; tail: Promise<void> };

enum LeaseState {
  Released,
  Open,
  Held,
}

type OwnerLease =
  | { state: LeaseState.Released }
  | { state: LeaseState.Open | LeaseState.Held; database: Database };

enum RequestState {
  Ready,
  Waiting,
  Exhausted,
}

type RequestBudget =
  | { state: RequestState.Ready; attempt: number; waited: number }
  | { state: RequestState.Waiting; attempt: number; waited: number; delay: number }
  | { state: RequestState.Exhausted };

function rateLimited(budget: Extract<RequestBudget, { state: RequestState.Ready }>, delay: number): RequestBudget {
  if (budget.attempt === 3 || delay > 60_000 || budget.waited + delay > 120_000) {
    return { state: RequestState.Exhausted };
  }
  return { state: RequestState.Waiting, attempt: budget.attempt + 1, waited: budget.waited + delay, delay };
}

enum ReconciliationState {
  Found,
  Exhausted,
}

type Reconciliation =
  | { state: ReconciliationState.Found; messageId: string }
  | { state: ReconciliationState.Exhausted };

enum HistoryState {
  Latest,
  Before,
}

type HistoryCursor = { state: HistoryState.Latest } | { state: HistoryState.Before; messageId: string };
type JsonObject = Record<string, unknown>;

// Only these locally authored, fixed messages cross the public error boundary.
class DeliveryError extends Error {
  constructor(message: string, readonly outcome = RequestOutcome.Uncertain) {
    super(message);
    this.name = "AnnouncementDeliveryError";
  }
}

function object(value: unknown): value is JsonObject {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function exactKeys(value: JsonObject, keys: string[]): boolean {
  return Object.keys(value).length === keys.length && keys.every((key) => Object.hasOwn(value, key));
}

function checkKey(key: string): void {
  if (typeof key !== "string" || !KEY.test(key)) throw new DeliveryError("Invalid announcement deduplication key");
}

function isReleaseUrl(value: unknown): value is string {
  return typeof value === "string" &&
    /^https:\/\/github\.com\/leakyfontana\/orebit-beyond-the-lode\/releases\/tag\/v0\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?![\s\S])/.test(value);
}

function storedReleaseUrl(payload: string): string {
  const value: unknown = JSON.parse(payload);
  if (!object(value) || !Array.isArray(value.embeds) || value.embeds.length !== 1 ||
      !object(value.embeds[0]) || !isReleaseUrl(value.embeds[0].url)) {
    throw new DeliveryError("Pending announcement has no canonical public release URL; operator review required");
  }
  return value.embeds[0].url;
}

function text(value: unknown, maximum: number): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= maximum;
}

// Snapshot before entering the queue: later caller mutations cannot change an intent.
// The canonical release URL identifies the version; the durable key and nonce remain commit-based.
function freezePayload(key: string, payload: DiscordAnnouncement): string {
  try {
    const value: unknown = JSON.parse(JSON.stringify(payload));
    if (!object(value) || !exactKeys(value, ["embeds", "components", "allowed_mentions"])
      || !Array.isArray(value.embeds) || value.embeds.length !== 1
      || !object(value.allowed_mentions) || !exactKeys(value.allowed_mentions, ["parse"])
      || !Array.isArray(value.allowed_mentions.parse) || value.allowed_mentions.parse.length !== 0) {
      throw new Error();
    }
    const embed = value.embeds[0];
    if (!object(embed) || !exactKeys(embed, ["title", "url", "color", "description", "fields", "footer", "timestamp"])
      || !text(embed.title, 256) || !isReleaseUrl(embed.url)
      || !Number.isInteger(embed.color) || (embed.color as number) < 0 || (embed.color as number) > 0xffffff
      || !text(embed.description, 4096) || !text(embed.timestamp, 64)
      || !object(embed.footer) || !exactKeys(embed.footer, ["text"]) || !text(embed.footer.text, 2048)
      || !Array.isArray(embed.fields) || embed.fields.length > 25) throw new Error();
    let total = embed.title.length + embed.description.length + embed.footer.text.length;
    for (const field of embed.fields) {
      if (!object(field) || !exactKeys(field, Object.hasOwn(field, "inline") ? ["name", "value", "inline"] : ["name", "value"])
        || !text(field.name, 256) || !text(field.value, 1024)
        || (Object.hasOwn(field, "inline") && typeof field.inline !== "boolean")) throw new Error();
      total += field.name.length + field.value.length;
    }
    if (total > 6000) throw new Error();
    if (!Array.isArray(value.components) || value.components.length < 1 || value.components.length > 5) throw new Error();
    for (const row of value.components) {
      if (!object(row) || !exactKeys(row, ["type", "components"]) || row.type !== 1
        || !Array.isArray(row.components) || row.components.length < 1 || row.components.length > 5) throw new Error();
      for (const button of row.components) {
        if (!object(button) || !exactKeys(button, ["type", "style", "label", "url"])
          || button.type !== 2 || button.style !== 5 || !text(button.label, 80) || !text(button.url, 512)) throw new Error();
        const url = new URL(button.url);
        if (url.protocol !== "https:" || url.username || url.password
          || !["drive.google.com", "play.arcmonkeyswelding.com", "github.com", "discord.com"].includes(url.hostname)) throw new Error();
      }
    }
    return JSON.stringify({
      ...value,
      nonce: createHash("sha256").update(key).digest("hex").slice(0, 25),
      enforce_nonce: true,
    });
  } catch {
    throw new DeliveryError("Invalid frozen announcement payload or release identity");
  }
}

function privateFile(path: string, create = true): void {
  let descriptor: number;
  try {
    descriptor = openSync(path, constants.O_RDWR | constants.O_NOFOLLOW | (create ? constants.O_CREAT : 0), 0o600);
  } catch (error) {
    if (!create && object(error) && error.code === "ENOENT") return;
    throw error;
  }
  try {
    const info = fstatSync(descriptor);
    if (!info.isFile() || info.nlink !== 1) throw new Error();
    fchmodSync(descriptor, 0o600);
  } finally {
    closeSync(descriptor);
  }
}

class DeliveryLease {
  #lease: OwnerLease = { state: LeaseState.Released };

  constructor(private path: string) {}

  acquire(): void {
    try {
      const database = new Database(this.path, { create: false, strict: true });
      this.#lease = { state: LeaseState.Open, database };
      database.exec("PRAGMA busy_timeout=0; BEGIN EXCLUSIVE;");
      this.#lease = { state: LeaseState.Held, database };
    } catch (error) {
      if (object(error) && (error.code === "SQLITE_BUSY" || error.code === "SQLITE_LOCKED" || error.errno === 5 || error.errno === 6)) {
        throw new DeliveryError("Another announcement publisher holds the private delivery lock");
      }
      throw new DeliveryError("Announcement delivery lock is unavailable");
    }
  }

  release(): void {
    const lease = this.#lease;
    if (lease.state === LeaseState.Released) return;
    try {
      if (lease.state === LeaseState.Held) lease.database.exec("ROLLBACK");
    } finally {
      try {
        lease.database.close();
      } finally {
        this.#lease = { state: LeaseState.Released };
      }
    }
  }
}

/**
 * Private, single-channel outbox. A pending intent with an uncertain POST is never
 * blindly resent: subsequent calls only reconcile it until its bot marker exists.
 * SQLite's separate OS-backed exclusive lock survives awaits, but releases on exit.
 */
export class AnnouncementDelivery {
  static #queue: DeliveryQueue = { state: QueueState.Idle };
  readonly #token: string;
  readonly #database: Database;
  readonly #lockPath: string;

  constructor(options: { token: string; channelId: string; stateDir?: string }) {
    if (options.channelId !== CHANNEL) throw new DeliveryError("Announcement channel is not permitted");
    if (typeof options.token !== "string" || !options.token.trim() || /\s/.test(options.token.trim())) {
      throw new DeliveryError("Invalid Discord bot token configuration");
    }
    this.#token = options.token.trim();
    try {
      const sourceRoot = realpathSync(fileURLToPath(new URL("../../", import.meta.url)));
      let state = resolve(options.stateDir ?? DEFAULT_STATE);
      if (state === sourceRoot || state.startsWith(sourceRoot + sep)) throw new Error();
      mkdirSync(state, { recursive: true, mode: 0o700 });
      state = realpathSync(state);
      if (state === sourceRoot || state.startsWith(sourceRoot + sep)) throw new Error();
      chmodSync(state, 0o700);
      const ledgerPath = join(state, "delivery.sqlite");
      this.#lockPath = join(state, "delivery-lock.sqlite");
      for (const path of [ledgerPath, this.#lockPath]) {
        privateFile(path);
        for (const suffix of ["-journal", "-wal", "-shm"]) privateFile(path + suffix, false);
      }
      this.#database = new Database(ledgerPath, { create: true, strict: true });
      // Rollback journals inherit the database's 0600 mode; no WAL/SHM is created.
      this.#database.exec(`PRAGMA busy_timeout=0;
        PRAGMA journal_mode=DELETE;
        PRAGMA synchronous=EXTRA;
        PRAGMA fullfsync=ON;
        CREATE TABLE IF NOT EXISTS announcements (
          key TEXT PRIMARY KEY NOT NULL,
          state TEXT NOT NULL CHECK (state IN ('pending', 'sending', 'sent')),
          payload TEXT NOT NULL,
          message_id TEXT,
          CHECK ((state = 'sent' AND message_id IS NOT NULL) OR (state != 'sent' AND message_id IS NULL))
        );`);
    } catch {
      throw new DeliveryError("Announcement private state is unavailable");
    }
  }

  /** Local durable lookup only; never fetches Discord or publication URLs. */
  hasPublished(key: string): boolean {
    checkKey(key);
    try {
      const row = this.#database.query("SELECT state, message_id FROM announcements WHERE key=?").get(key) as Pick<Intent, "state" | "message_id"> | null;
      if (row?.state !== IntentState.Sent) return false;
      if (!row.message_id || !SNOWFLAKE.test(row.message_id)) throw new Error();
      return true;
    } catch {
      throw new DeliveryError("Announcement ledger lookup failed");
    }
  }

  async publish(key: string, payload: DiscordAnnouncement): Promise<DeliveryResult> {
    checkKey(key);
    const frozen = freezePayload(key, payload);
    const operation = AnnouncementDelivery.#serialize(() => this.#lockedPublish(key, frozen));
    try {
      return await operation;
    } catch (error) {
      if (error instanceof DeliveryError) throw error;
      throw new DeliveryError("Announcement ledger operation failed; pending intent retained");
    }
  }

  static #serialize(deliver: () => Promise<DeliveryResult>): Promise<DeliveryResult> {
    const predecessor = this.#queue.state === QueueState.Queued ? this.#queue.tail : Promise.resolve();
    const operation = predecessor.then(deliver);
    const tail: Promise<void> = operation.then(() => this.#finishQueue(tail), () => this.#finishQueue(tail));
    this.#queue = { state: QueueState.Queued, tail };
    return operation;
  }

  static #finishQueue(tail: Promise<void>): void {
    if (this.#queue.state === QueueState.Queued && this.#queue.tail === tail) {
      this.#queue = { state: QueueState.Idle };
    }
  }

  async #lockedPublish(key: string, frozen: string): Promise<DeliveryResult> {
    const lease = new DeliveryLease(this.#lockPath);
    try {
      lease.acquire();
      return await this.#deliver(key, frozen);
    } finally {
      lease.release();
    }
  }

  async #deliver(key: string, frozen: string): Promise<DeliveryResult> {
    let intent = this.#database.query("SELECT state, payload, message_id FROM announcements WHERE key=?").get(key) as Intent | null;
    if (intent?.state === IntentState.Sent) {
      if (!intent.message_id || !SNOWFLAKE.test(intent.message_id)) throw new DeliveryError("Announcement ledger contains an invalid message identity");
      return { created: false, messageId: intent.message_id };
    }
    if (!intent) intent = this.#createPending(key, frozen);
    const expectedUrl = storedReleaseUrl(intent.payload);
    await this.#verifyDestination();
    // Also scan for brand-new keys, so a restored/lost ledger cannot create a replay.
    const found = await this.#reconcile(expectedUrl);
    if (found.state === ReconciliationState.Found) return this.#confirmSent(key, found.messageId, false);
    if (intent.state === IntentState.Sending) {
      throw new DeliveryError("Announcement delivery remains uncertain; pending intent retained without reposting");
    }
    if (intent.state !== IntentState.Pending) throw new DeliveryError("Announcement ledger contains an invalid delivery state");

    // Persist 'sending' before fetch. A crash even just before fetch is deliberately
    // ambiguous: an absent history marker is not proof an in-flight POST cannot land.
    intent = this.#beginSending(key, intent);
    let message: unknown;
    try {
      message = await this.#request(`/channels/${CHANNEL}/messages`, "POST", intent.payload);
      if (!this.#matchingMessage(message, expectedUrl)) throw new DeliveryError("Discord create-message response could not confirm delivery");
    } catch (error) {
      if (error instanceof DeliveryError && error.outcome === RequestOutcome.Rejected) {
        // Discord explicitly rejected this request; there was no successful send.
        this.#rejectSending(key);
        throw error;
      }
      // Timeouts, 5xx and malformed success responses may all have created a message.
      // If history is unavailable or still empty, leave 'sending' intact forever
      // rather than eventually trusting Discord's short-lived nonce window.
      const recovered = await this.#reconcile(expectedUrl);
      if (recovered.state === ReconciliationState.Found) return this.#confirmSent(key, recovered.messageId, false);
      throw new DeliveryError("Announcement delivery remains uncertain; pending intent retained without reposting");
    }
    return this.#confirmSent(key, (message as JsonObject).id as string, true);
  }

  #createPending(key: string, payload: string): PendingIntent {
    // This autocommit must be durable before any possible create-message request.
    this.#database.query("INSERT INTO announcements(key, state, payload) VALUES (?, ?, ?)").run(key, IntentState.Pending, payload);
    return { state: IntentState.Pending, payload, message_id: null };
  }

  #beginSending(key: string, intent: PendingIntent): SendingIntent {
    this.#database.query("UPDATE announcements SET state=? WHERE key=? AND state=?").run(IntentState.Sending, key, IntentState.Pending);
    return { state: IntentState.Sending, payload: intent.payload, message_id: null };
  }

  #rejectSending(key: string): void {
    this.#database.query("UPDATE announcements SET state=? WHERE key=? AND state=?").run(IntentState.Pending, key, IntentState.Sending);
  }

  #confirmSent(key: string, messageId: string, created: boolean): DeliveryResult {
    this.#database.query("UPDATE announcements SET state=?, message_id=? WHERE key=?").run(IntentState.Sent, messageId, key);
    return { created, messageId };
  }

  async #verifyDestination(): Promise<void> {
    const user = await this.#request("/users/@me");
    if (!object(user) || user.id !== BOT || user.bot !== true) throw new DeliveryError("Discord token does not identify the permitted Orebit bot");
    const channel = await this.#request(`/channels/${CHANNEL}`);
    if (!object(channel) || channel.id !== CHANNEL || channel.guild_id !== GUILD || channel.type !== 0) {
      throw new DeliveryError("Discord announcement destination could not be verified");
    }
  }

  #matchingMessage(value: unknown, expectedUrl: string): boolean {
    return object(value) && typeof value.id === "string" && SNOWFLAKE.test(value.id)
      && value.channel_id === CHANNEL && value.type === 0 && !value.webhook_id
      && object(value.author) && value.author.id === BOT && value.author.bot === true
      && Array.isArray(value.embeds) && value.embeds.some((embed) => object(embed)
        && embed.url === expectedUrl);
  }

  async #reconcile(expectedUrl: string): Promise<Reconciliation> {
    let cursor: HistoryCursor = { state: HistoryState.Latest };
    for (;;) {
      const before = cursor.state === HistoryState.Before ? cursor.messageId : undefined;
      const page = await this.#request(`/channels/${CHANNEL}/messages?limit=100${before ? `&before=${before}` : ""}`);
      if (!Array.isArray(page) || page.length > 100) throw new DeliveryError("Discord message history response is invalid; pending intent retained");
      if (page.length === 0) return { state: ReconciliationState.Exhausted };
      let oldest: string | undefined;
      for (const message of page) {
        if (!object(message) || typeof message.id !== "string" || !SNOWFLAKE.test(message.id)
          || message.channel_id !== CHANNEL || !object(message.author) || !Array.isArray(message.embeds)
          || (before && BigInt(message.id) >= BigInt(before))) {
          throw new DeliveryError("Discord message history response is invalid; pending intent retained");
        }
        if (this.#matchingMessage(message, expectedUrl)) return { state: ReconciliationState.Found, messageId: message.id };
        if (!oldest || BigInt(message.id) < BigInt(oldest)) oldest = message.id;
      }
      // Even a short page is followed to exhaustion; never infer absence from a
      // partial page or inspect arbitrary users' text for the release marker.
      cursor = { state: HistoryState.Before, messageId: oldest! };
    }
  }

  async #request(path: string, method: "GET" | "POST" = "GET", body?: string): Promise<unknown> {
    let budget: RequestBudget = { state: RequestState.Ready, attempt: 0, waited: 0 };
    for (;;) {
      switch (budget.state) {
        case RequestState.Waiting:
          await Bun.sleep(budget.delay);
          budget = { state: RequestState.Ready, attempt: budget.attempt, waited: budget.waited };
          continue;
        case RequestState.Exhausted:
          throw new DeliveryError("Discord HTTP 429 retry bound exceeded; pending intent retained", RequestOutcome.Rejected);
        case RequestState.Ready:
          break;
      }
      let response: Response;
      try {
        response = await fetch(`https://discord.com/api/v10${path}`, {
          method,
          headers: {
            Authorization: `Bot ${this.#token}`,
            "Content-Type": "application/json",
            "User-Agent": "DiscordBot (Orebit Intake, 1.0)",
          },
          ...(body === undefined ? {} : { body }),
          redirect: "error",
          signal: AbortSignal.timeout(30_000),
        });
      } catch {
        throw new DeliveryError("Discord request failed without a confirmed HTTP outcome");
      }
      if (response.status === 429) {
        let limit: unknown;
        try {
          limit = await response.json();
        } catch {
          throw new DeliveryError("Discord returned HTTP 429 with an invalid rate-limit response", RequestOutcome.Rejected);
        }
        if (!object(limit) || typeof limit.retry_after !== "number" || !Number.isFinite(limit.retry_after) || limit.retry_after < 0) {
          throw new DeliveryError("Discord returned HTTP 429 with an invalid retry interval", RequestOutcome.Rejected);
        }
        const delay = Math.ceil(limit.retry_after * 1000);
        budget = rateLimited(budget, delay);
        continue;
      }
      if (response.status !== 200) {
        await response.body?.cancel().catch(() => {});
        // 408 and server failures are ambiguous, unlike explicit client rejection.
        const outcome = response.status >= 400 && response.status < 500 && response.status !== 408
          ? RequestOutcome.Rejected : RequestOutcome.Uncertain;
        throw new DeliveryError(`Discord returned HTTP ${response.status}; pending intent retained`, outcome);
      }
      try {
        return await response.json();
      } catch {
        throw new DeliveryError("Discord HTTP 200 response could not be decoded");
      }
    }
  }
}
