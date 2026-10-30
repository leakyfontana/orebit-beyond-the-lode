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
const DEFAULT_STATE = join(homedir(), "Library/Application Support/Orebit Intake/announcements");

type DeliveryResult = { created: boolean; messageId: string };
type Intent = { state: "pending" | "sending" | "sent"; payload: string; message_id: string | null };
type JsonObject = Record<string, unknown>;

// Only these locally authored, fixed messages cross the public error boundary.
class DeliveryError extends Error {
  constructor(message: string, readonly rejected = false) {
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

function marker(key: string): string {
  return `orebit.release:${key}`;
}

function text(value: unknown, maximum: number): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= maximum;
}

// Snapshot before entering the queue: later caller mutations cannot change an intent.
// The renderer owns the exact footer marker and the complete, already budgeted embed.
function freezePayload(key: string, payload: DiscordAnnouncement): string {
  try {
    const value: unknown = JSON.parse(JSON.stringify(payload));
    if (!object(value) || !exactKeys(value, ["embeds", "allowed_mentions"])
      || !Array.isArray(value.embeds) || value.embeds.length !== 1
      || !object(value.allowed_mentions) || !exactKeys(value.allowed_mentions, ["parse"])
      || !Array.isArray(value.allowed_mentions.parse) || value.allowed_mentions.parse.length !== 0) {
      throw new Error();
    }
    const embed = value.embeds[0];
    if (!object(embed) || !exactKeys(embed, ["title", "url", "description", "fields", "footer", "timestamp"])
      || !text(embed.title, 256) || !text(embed.url, 2048) || !text(embed.description, 4096)
      || !text(embed.timestamp, 64) || !object(embed.footer) || !exactKeys(embed.footer, ["text"])
      || embed.footer.text !== marker(key) || !text(embed.footer.text, 2048)
      || !Array.isArray(embed.fields) || embed.fields.length > 25) throw new Error();
    let total = embed.title.length + embed.description.length + embed.footer.text.length;
    for (const field of embed.fields) {
      if (!object(field) || !exactKeys(field, Object.hasOwn(field, "inline") ? ["name", "value", "inline"] : ["name", "value"])
        || !text(field.name, 256) || !text(field.value, 1024)
        || (Object.hasOwn(field, "inline") && typeof field.inline !== "boolean")) throw new Error();
      total += field.name.length + field.value.length;
    }
    if (total > 6000) throw new Error();
    return JSON.stringify({
      ...value,
      nonce: createHash("sha256").update(key).digest("hex").slice(0, 25),
      enforce_nonce: true,
    });
  } catch {
    throw new DeliveryError("Invalid frozen announcement payload or footer marker");
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

/**
 * Private, single-channel outbox. A pending intent with an uncertain POST is never
 * blindly resent: subsequent calls only reconcile it until its bot marker exists.
 * SQLite's separate OS-backed exclusive lock survives awaits, but releases on exit.
 */
export class AnnouncementDelivery {
  static #queue: Promise<void> = Promise.resolve();
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
      if (row?.state !== "sent") return false;
      if (!row.message_id || !SNOWFLAKE.test(row.message_id)) throw new Error();
      return true;
    } catch {
      throw new DeliveryError("Announcement ledger lookup failed");
    }
  }

  async publish(key: string, payload: DiscordAnnouncement): Promise<DeliveryResult> {
    checkKey(key);
    const frozen = freezePayload(key, payload);
    const operation = AnnouncementDelivery.#queue.then(() => this.#lockedPublish(key, frozen));
    AnnouncementDelivery.#queue = operation.then(() => {}, () => {});
    try {
      return await operation;
    } catch (error) {
      if (error instanceof DeliveryError) throw error;
      throw new DeliveryError("Announcement ledger operation failed; pending intent retained");
    }
  }

  async #lockedPublish(key: string, frozen: string): Promise<DeliveryResult> {
    let lock: Database | undefined;
    let acquired = false;
    try {
      try {
        lock = new Database(this.#lockPath, { create: false, strict: true });
        lock.exec("PRAGMA busy_timeout=0; BEGIN EXCLUSIVE;");
        acquired = true;
      } catch (error) {
        if (object(error) && (error.code === "SQLITE_BUSY" || error.code === "SQLITE_LOCKED" || error.errno === 5 || error.errno === 6)) {
          throw new DeliveryError("Another announcement publisher holds the private delivery lock");
        }
        throw new DeliveryError("Announcement delivery lock is unavailable");
      }
      return await this.#deliver(key, frozen);
    } finally {
      if (lock) {
        try {
          if (acquired) lock.exec("ROLLBACK");
        } finally {
          lock.close();
        }
      }
    }
  }

  async #deliver(key: string, frozen: string): Promise<DeliveryResult> {
    let intent = this.#database.query("SELECT state, payload, message_id FROM announcements WHERE key=?").get(key) as Intent | null;
    if (intent?.state === "sent") {
      if (!intent.message_id || !SNOWFLAKE.test(intent.message_id)) throw new DeliveryError("Announcement ledger contains an invalid message identity");
      return { created: false, messageId: intent.message_id };
    }
    if (!intent) {
      // This autocommit must be durable before any possible create-message request.
      this.#database.query("INSERT INTO announcements(key, state, payload) VALUES (?, 'pending', ?)").run(key, frozen);
      intent = { state: "pending", payload: frozen, message_id: null };
    }
    await this.#verifyDestination();
    // Also scan for brand-new keys, so a restored/lost ledger cannot create a replay.
    const found = await this.#reconcile(key);
    if (found) return this.#sent(key, found, false);
    if (intent.state === "sending") {
      throw new DeliveryError("Announcement delivery remains uncertain; pending intent retained without reposting");
    }
    if (intent.state !== "pending") throw new DeliveryError("Announcement ledger contains an invalid delivery state");

    // Persist 'sending' before fetch. A crash even just before fetch is deliberately
    // ambiguous: an absent history marker is not proof an in-flight POST cannot land.
    this.#database.query("UPDATE announcements SET state='sending' WHERE key=? AND state='pending'").run(key);
    let message: unknown;
    try {
      message = await this.#request(`/channels/${CHANNEL}/messages`, "POST", intent.payload);
      if (!this.#matchingMessage(message, key)) throw new DeliveryError("Discord create-message response could not confirm delivery");
    } catch (error) {
      if (error instanceof DeliveryError && error.rejected) {
        // Discord explicitly rejected this request; there was no successful send.
        this.#database.query("UPDATE announcements SET state='pending' WHERE key=? AND state='sending'").run(key);
        throw error;
      }
      // Timeouts, 5xx and malformed success responses may all have created a message.
      // If history is unavailable or still empty, leave 'sending' intact forever
      // rather than eventually trusting Discord's short-lived nonce window.
      const recovered = await this.#reconcile(key);
      if (recovered) return this.#sent(key, recovered, false);
      throw new DeliveryError("Announcement delivery remains uncertain; pending intent retained without reposting");
    }
    return this.#sent(key, (message as JsonObject).id as string, true);
  }

  #sent(key: string, messageId: string, created: boolean): DeliveryResult {
    this.#database.query("UPDATE announcements SET state='sent', message_id=? WHERE key=?").run(messageId, key);
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

  #matchingMessage(value: unknown, key: string): boolean {
    return object(value) && typeof value.id === "string" && SNOWFLAKE.test(value.id)
      && value.channel_id === CHANNEL && value.type === 0 && !value.webhook_id
      && object(value.author) && value.author.id === BOT && value.author.bot === true
      && Array.isArray(value.embeds) && value.embeds.some((embed) => object(embed)
        && object(embed.footer) && embed.footer.text === marker(key));
  }

  async #reconcile(key: string): Promise<string | null> {
    let before: string | undefined;
    for (;;) {
      const page = await this.#request(`/channels/${CHANNEL}/messages?limit=100${before ? `&before=${before}` : ""}`);
      if (!Array.isArray(page) || page.length > 100) throw new DeliveryError("Discord message history response is invalid; pending intent retained");
      if (page.length === 0) return null;
      let oldest: string | undefined;
      for (const message of page) {
        if (!object(message) || typeof message.id !== "string" || !SNOWFLAKE.test(message.id)
          || message.channel_id !== CHANNEL || !object(message.author) || !Array.isArray(message.embeds)
          || (before && BigInt(message.id) >= BigInt(before))) {
          throw new DeliveryError("Discord message history response is invalid; pending intent retained");
        }
        if (this.#matchingMessage(message, key)) return message.id;
        if (!oldest || BigInt(message.id) < BigInt(oldest)) oldest = message.id;
      }
      // Even a short page is followed to exhaustion; never infer absence from a
      // partial page or inspect arbitrary users' text for the release marker.
      before = oldest!;
    }
  }

  async #request(path: string, method: "GET" | "POST" = "GET", body?: string): Promise<unknown> {
    let waited = 0;
    for (let attempt = 0; attempt < 4; attempt++) {
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
          throw new DeliveryError("Discord returned HTTP 429 with an invalid rate-limit response", true);
        }
        if (!object(limit) || typeof limit.retry_after !== "number" || !Number.isFinite(limit.retry_after) || limit.retry_after < 0) {
          throw new DeliveryError("Discord returned HTTP 429 with an invalid retry interval", true);
        }
        const delay = Math.ceil(limit.retry_after * 1000);
        if (attempt === 3 || delay > 60_000 || waited + delay > 120_000) {
          throw new DeliveryError("Discord HTTP 429 retry bound exceeded; pending intent retained", true);
        }
        waited += delay;
        await Bun.sleep(delay);
        continue;
      }
      if (response.status !== 200) {
        await response.body?.cancel().catch(() => {});
        // 408 and server failures are ambiguous, unlike explicit client rejection.
        const rejected = response.status >= 400 && response.status < 500 && response.status !== 408;
        throw new DeliveryError(`Discord returned HTTP ${response.status}; pending intent retained`, rejected);
      }
      try {
        return await response.json();
      } catch {
        throw new DeliveryError("Discord HTTP 200 response could not be decoded");
      }
    }
    throw new DeliveryError("Discord rate-limit retry bound exceeded", true);
  }
}
