# Calk

**Calk** (`@Calkbot`) is a Telegram **Business** automation bot written for **Telegram Serverless** (`tgcloud`).
It runs as plain JavaScript on Telegram's own infrastructure with the built-in SQLite database — no server to rent,
no webhook to host.

| For your customers | For you (admin) |
|---|---|
| **Name clock** — the account name shows the live time; 24 fonts, any time zone, 12/24 h | Real statistics, user search, balances, refunds |
| **Auto-read** of incoming business chats | **Broadcast** with audiences, live progress, cancel / resume |
| **Away messages** — several, any media type incl. stickers; send all / random / rotate; cooldown from every message to 24 h | **Premium + Stars billing**, checks (promo codes), invites with rewards |
| **Premium** by the day, free trial, balance top-ups with Telegram Stars | **Message Review** — three forum topics per reviewed user (Send / Received / bots) |
| **Invite** link — reward when a friend joins, verifies and connects | **Cron**, **Backup / Restore** (ZIP), Mini App **Console** |

Admins only ever see the admin menu; users never reach it. Every screen is one edited panel — pressing a button twice
never produces two answers, and notices are separate messages that dismiss with one tap.

---

## How the pieces fit

```
 Telegram ── webhook ──▶  Calk on Telegram Serverless ──▶ built-in SQLite
    ▲                      handlers/*.js · lib/**             ▲
    │  /tick@Calkbot KEY                                      │ /api/* (verified initData)
    │  every minute                                           │
 cron bot ◀── Cloudflare Worker (worker/worker.js)       Mini App console (public/index.html)
              cron trigger "* * * * *"
```

Telegram Serverless has no scheduler. A second bot (the *cron bot*) sits in a group together with Calk; a tiny
Cloudflare Worker makes it post `/tick@Calkbot KEY` every minute. Calk checks the key, **deletes the message**, and runs
whatever is due: name clocks, broadcast chunks, invite re-checks, auto-backups, housekeeping.

---

## Requirements

- A Telegram account with **Telegram Premium** on the *customer* side (Business features are a Premium feature; Calk itself needs none).
- Node.js **18+** to deploy (`@tgcloud/cli`). Running the test-suite needs **Node 22.5+** (it uses `node:sqlite`).
- A Cloudflare account (free plan is enough) for the cron Worker.

---

## Setup

### 1 · Create the bot

In **@BotFather**:

1. Create the bot (`/newbot`) — username `Calkbot`, or any you like; the code reads the real username with `getMe`.
2. *Bot Settings → **Business Mode** → On* (lets customers add it under Telegram Settings → Business → Chatbots).
3. Open your bot → **Serverless** → turn it on, then **CLI Access → Access token** (form `app<id>:<secret>`;
   it is *not* the bot token).

### 2 · Put yourself in as admin

You need your numeric Telegram id. Deploy once with the placeholder (step 3), send **`/id`** to the bot, then edit
`tgcloud/lib/config.js`:

```js
export const ADMIN_IDS = [123456789];          // your id(s); 0 is the placeholder and never matches anyone
```

and `npx tgcloud push` again. Admins are recognised by id only.

### 3 · Deploy

```bash
npm install
npx tgcloud login          # paste the app<id>:<secret> token
npx tgcloud push           # deploy handlers, endpoints, lib and the console
npx tgcloud migrate        # creates / updates the tables (push never touches the database)
npx tgcloud webhook sync   # makes Telegram deliver every update type Calk needs
npx tgcloud webhook        # should report "in sync"
```

Send `/start` to the bot. As an admin you get the admin menu:
**Stats · Users · Broadcast · Billing · Invites · Review · Cron · Backup · Settings**.

### 4 · Console (Mini App) — optional but recommended

After the first push the console lives at `https://app<id>.tgcloud.ai/`, where `<id>` is the number in your CLI token
(`app`**`123`**`:secret`). Put the address into `CONSOLE_URL` in `tgcloud/lib/config.js`, push again, and a
**🖥 Console** button appears in the admin menu. It shows live numbers, the webhook state (with the exact fix command if
anything is wrong), cron health, user search / actions, settings and backups. Every endpoint is admin-only: Telegram
verifies the Mini App's init data and Calk then checks the id against `ADMIN_IDS`.

### 5 · Cron (needed for clocks, broadcasts, auto-backup, invite checks)

1. In @BotFather create a **second bot** (the cron bot, e.g. `@CalkCronBot`) and copy its token.
2. Create a private **group**, add Calk **and** the cron bot. Make **Calk an admin with “Delete messages”**.
   In BotFather enable **Bot-to-Bot Communication** for both bots so they can see each other's messages in a group.
3. In the group send **`/id@Calkbot`** — it answers with the group id (`-100…`).
4. Edit `worker/wrangler.toml`: `GROUP_ID`, `CALK_USERNAME`. Optional: `LEAD_SECONDS`, `THREAD_ID`.
5. Deploy the Worker:

   ```bash
   cd worker
   npx wrangler kv namespace create STATE      # optional, recommended: paste the id into wrangler.toml
   npx wrangler deploy
   npx wrangler secret put CRON_BOT_TOKEN      # the cron bot's token
   npx wrangler secret put CRON_KEY            # Calk → ⏱ Cron → 🔑 Show key
   npx wrangler secret put ADMIN_TOKEN         # any long random string
   ```

6. In Calk → **⏱ Cron** set **Worker URL** (`https://calk-cron.<you>.workers.dev`) and **Worker token** (= `ADMIN_TOKEN`).
   From then on **🔄 Regenerate** changes the key everywhere by itself (the old key stops working immediately).
7. Within a minute the Cron screen turns **● healthy**. The first valid tick *pins* the cron bot and the group
   (trust on first use); a tick from anyone else, from another group, with a wrong key or older than 5 minutes is ignored.
   **📌 Reset pinning** if you ever move to another group.

`LEAD_SECONDS` (Worker variable, 0–25): the Worker sends the tick that many seconds early and tells Calk which minute it
belongs to; Calk then waits for the exact edge, so name clocks flip *on* the minute. It needs timers — the **⚙ Settings**
screen shows `timers ✓/✗`. With ✗ keep it at `0`.

### 6 · Message Review — optional

1. Create a group, switch on **Topics**, add Calk as admin with **Manage topics**.
2. In that group send **`/review_here@Calkbot`** (as an admin), or enter the group id under *Review → Review group*.
3. Turn the feature on under **🔎 Review** and add the users you want reviewed.

For every reviewed user Calk keeps three topics: `Name Send | 123456789`, `Name Received | 123456789` and
`Name bots Chats | 123456789` (both directions of that user's chats with *bots*, text and media only; inline / via-bot
messages are skipped). Media is relayed by `file_id` (all file types), formatting and entities are preserved, and
every sender is a working mention. Replies to relayed messages thread correctly.

> **Privacy.** Reading customers' conversations is a serious thing. Calk shows reviewed users a disclosure line; make
> sure you have their consent and that this is lawful where you operate. Telegram's Business terms apply.

### 7 · Backups

**💾 Backup** in the admin menu:

- **Back up now** sends the whole bot to you as a ZIP — split into **parts of at most ~14 MB** (Telegram bots can
  download 20 MB, upload 50 MB). Parts are named `calk-backup-<date>-<id>-p01.zip … -pNN-final.zip`.
- **Format: ZIP.** RAR cannot be created: the format is proprietary and no open implementation can write it. ZIP opens
  everywhere (Windows, macOS, Linux, phones) — it was checked against `unzip` and Python's `zipfile`.
- **Auto-backup** every N hours to a chat you choose; **history** of the last backups.
- What is inside: 17 tables — users, premium grants, ledger, invoices, checks, invites, business connections,
  automation, away messages, review topics and message map, peers, broadcasts, audit log, backup history, settings.
- **Restore** → *Replace everything* (takes a **safety backup of the current state first**, switches maintenance mode
  on) or *Merge* (adds / overwrites what is in the backup, deletes nothing). Drop **all parts at once, in any order**;
  duplicates are ignored, missing parts are named, damaged or foreign files are refused without touching anything.
- A restore never overwrites the bot's own identity or cron wiring (cron key, pinned bot / group, Worker URL / token),
  and every existing user keeps their open menu where it is (no orphaned or duplicated panels).

---

## Running it

| Area | What you do |
|---|---|
| **Users** | Find by id / @username / name; add balance or premium days, end premium, ban, message the user, refund a Stars payment |
| **Billing** | Price per day, trial, top-up range and buttons, invoice lifetime, **checks** (promo codes: `50 10` = 50 ⭐ for each of 10 people) |
| **Invites** | Reward, minimum Telegram rating level, minimum ⭐ spent (read from `UserRating`), recheck / expiry; a reward is paid once the invitee passed the captcha **and** connected an account or bought a package |
| **Broadcast** | Any text or media; audiences *everyone / premium / free / connected accounts*; paced with the shared rate limiter; resumable if a run is cut short |
| **Settings** | Maintenance, captcha, rich messages (`auto` falls back by itself if the API rejects them), pacing, concurrency, away limit, log chat, support username |

Money is a **ledger**: balances are sums of transactions, every credit / debit is idempotent (`kind`, `ref`), debits are
atomic and conditional, and premium is derived from grants — a retried webhook or double tap can never pay twice.

---

## Capacity and limits

- **Name clock:** one `setBusinessAccountName` per account per minute, paced at Telegram's rate — roughly
  **1,000–1,200 accounts per minute**; beyond that the budget (⏱ Cron → *Time budget*) resumes where it stopped.
- **Flood control for users:** 10 actions / 10 s (block 30 s) and 40 / 60 s (block 300 s). Admins are exempt.
- **Platform:** CPU / wall-time limits are not published by Telegram; everything long-running is chunked, leased and
  resumable, and everything is awaited before a handler returns.
- **Files:** bot downloads ≤ 20 MB, uploads ≤ 50 MB (hence 14 MB backup parts).

---

## Troubleshooting

| Symptom | Check |
|---|---|
| Nothing happens when a customer writes | `npx tgcloud webhook` — must be *in sync*; run `npx tgcloud webhook sync` (`--drop-pending` to clear a backlog). The Console's webhook card says the same. Business updates also need **Business Mode** in BotFather. |
| Cron says “waiting for the first tick” / “silent” | Worker deployed? `CRON_KEY` equals *Show key*? Both bots in the group, Bot-to-Bot Communication on, Calk may delete messages, `GROUP_ID` correct? `GET <worker>/status` (Bearer `ADMIN_TOKEN`) shows the Worker's last attempt and why it failed. |
| Name stays frozen | The customer must allow **Reply to messages, Read messages and Change name** for the bot under Settings → Business → Chatbots; their *Account* screen lists exactly what is missing. |
| Rich messages look plain | Expected when the API rejects them — Calk falls back automatically; set *Rich · off* to stop trying. |
| “Another part is still being applied” during restore | Parts are applied one at a time; send that file again. If the runtime has no timers, send parts one by one. |
| Restore refuses a file | It names the reason (not a ZIP, foreign backup, unknown table, part of another backup, > 20 MB). Nothing was changed. |
| After deploy a new table is missing | `npx tgcloud migrate`. Removing a table or column from `schema.js` never drops it — mark it `.deprecated()` first (Telegram's rule). |

---

## Things worth checking on the first day

These depend on parts of the platform and Bot API that Telegram documents only loosely; Calk detects or falls back, but
look once:

1. **⚙ Settings → Runtime** shows `timers`, `crypto`, `zip` support of your runtime.
2. **Rich messages** (Bot API 10.x `RichMessageButton`) and `<tg-time>` entities: if a screen looks plain, that is the
   automatic fallback working; nothing is lost.
3. A customer connects the bot and changes the name once — confirms the Business **rights** wiring.
4. Whether chats with *other bots* are delivered as business messages (needed for the “bots Chats” review topic) is up to Telegram.
5. Send a tick manually (**⏱ Cron → ▶ Run tick now**) and read the numbers on the Cron screen.

---

## Development

```
tgcloud/
  schema.js                 23 tables
  handlers/                 one file per update type (message, callback_query, business_*, …)
  endpoints/                Mini App API (admin only)
  lib/
    router.js ui.js         one-panel UI engine, flows, flood control
    features/               captcha, premium, payments, checks, referrals, clock, away, review, broadcast, cron, backup
    screens/                user and admin screens, settings metadata
    db/                     core · biz · sys · stats
    tg.js fmt.js fonts.js media.js textbuilder.js zip.js util.js
public/index.html           the console
worker/                     Cloudflare Worker for the cron bot
tests/                      188 tests + a fake Telegram and an in-memory tgcloud SDK
```

```bash
npm test          # node --test over tests/*.test.mjs   (Node ≥ 22.5)
npm run check     # every import resolves, no unused imports
npm run deploy    # tgcloud push
```

The tests run the real bot code against a fake Bot API and a SQLite-backed copy of the tgcloud SDK: money and refunds,
captcha, invites, clock (fonts, time zones, rate limits, 300 accounts, budget resume), away messages, review relay,
broadcast, cron (key, pinning, replay, edge), backup → restore into a **fresh database**, the console endpoints, the
Worker and its contract with Calk, plus a crawler that presses every button of every screen.

Settings that admins can change at runtime live in the `settings` table (defaults in `lib/config.js`); only what must
exist before the bot can recognise its owner (`ADMIN_IDS`, `CONSOLE_URL`) is in code.
