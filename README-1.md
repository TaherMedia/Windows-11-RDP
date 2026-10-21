# ⏱ TimeByte — a live clock in your channel & group names

A Telegram bot that adds the current time to the name of your channels and groups
(`My Channel | 𝟏𝟓:𝟑𝟓`), rewritten from `TimeByte.py` to run on **[Telegram Serverless](https://core.telegram.org/bots/serverless)**.

* 20 designer fonts + Classic, any time zone (daylight saving aware), 12/24-hour clock, optional `|`
* Owner-only adding, force-join channels with a 3-day grace period, coins, Telegram Stars shop, refunds
* Rich Messages UI with coloured buttons and date-time entities (automatic classic fallback)
* English only, no external services, no secrets to manage

---

## 1. What changed compared to `TimeByte.py`

| Your request | How it is solved | Where |
|---|---|---|
| Standard DB structure | 16 normalised tables, indexes, a coin ledger, no JSON blobs for business data | `tgcloud/schema.js` |
| Webhook / updates used correctly | One handler per update type (`message`, `callback_query`, `my_chat_member`, `chat_member`, `channel_post`, `pre_checkout_query`, `poll`); the platform derives `allowed_updates` from them | `tgcloud/handlers/*` |
| Send to all / channels / groups / users keeps formatting, hides the sender | `copyMessage` (not `sendMessage(text)`), paced at 25 msg/s, resumable job, blocked users flagged | `lib/broadcast.js` |
| Forward to channels / groups / users | Same engine with `forwardMessage` | `lib/broadcast.js` |
| Status pages with better info | Users, chats, economy, heartbeat health, last 10 ticks, flood waits, errors, Rich Message / fallback state | `lib/screens_admin.js` |
| New Bot API "connectors" in the user menu | Native chat picker (`KeyboardButtonRequestChat`, **owned chats only**, bot added as admin with exactly the needed rights) | `lib/screens_user.js` |
| Membership via `chat_member`, saved in DB | `memberships` table, one query per check, API only for unseen combinations, self-healing re-checks | `lib/gate.js`, `lib/membership.js` |
| Leaving a force-join channel → warn, reset after 3 days | Warning with a localised deadline (date-time entity) + explanation, reminder 24 h before, reset restores original names | `lib/membership.js` |
| Owner renames the chat, bot must not revert | `new_chat_title` service messages are classified: ours → deleted, owner's → becomes the new base name | `lib/chats.js` |
| Separator `\|` on/off | Per chat, plus a default for new chats | `u:sep`, `u:dsep` |
| "Allow other admins" setting, owner-only adding | Per-chat switch; admins verified live; a bot added by a non-owner leaves with "ask the owner" | `lib/chats.js`, `lib/flows.js` |
| Leave when not admin / missing rights | On add, on `my_chat_member`, on rename errors and in daily verification | `lib/chats.js` |
| Rich Messages, date-time entities, `RichMessageButton`, button colours | Every screen is one view rendered as a Rich Message (`blocks`, embedded buttons) or, if rejected, classic HTML + inline keyboard | `lib/ui.js` |
| Extra balance from `UserRating` | Coins per Telegram rating level (cap + rate configurable), paid once per new level | `lib/billing.js` |
| Buy coins with Stars, refund by transaction id | Invoices in `XTR`, pre-checkout validation, idempotent crediting, admin refund flow with confirmation | `lib/billing.js`, `lib/router.js` |
| 20 modern fonts | See [Fonts](#7-fonts) | `lib/fonts.js` |
| Rename limits | Lease-based work queue, adaptive worker pool, per-chat flood back-off, continuation ticks | `lib/engine.js` |
| Bot name from `getMe` | Every title and text reads it, so renaming the bot needs no redeploy | `lib/tg.js` |

---

## 2. How it works on Telegram Serverless

### No cron → the heartbeat
Serverless runs your code **only when Telegram delivers an update**; there is no scheduler. A clock needs one tick per
minute, so TimeByte schedules itself *through Telegram*:

```
sendPoll(close_date = next minute)  →  Telegram closes it on time  →  `poll` update
   →  handlers/poll.js: schedule the NEXT poll first, delete this one, run the tick  →  …
```

* The heartbeat poll lives in a chat you choose (a private channel is ideal) and is deleted on every beat.
* Any other update (a message to the bot, a chat event) **revives** a silent heartbeat automatically.
* Admin → Engine shows *last beat* and lets you start, stop, move or run a tick manually.

### The rename engine (`lib/engine.js`)
* Due chats are **claimed** in batches with one atomic `UPDATE … RETURNING` (a 40 s lease) → several invocations can work
  in parallel without ever renaming a chat twice.
* A bounded worker pool replaces the old one-at-a-time loop with random sleeps. Concurrency adapts: halved on `429`,
  +2 per calm tick. A large `retry_after` stands the whole engine down; small ones only delay the affected chat.
* Chats already showing the right title cost no API call. Identical looks share one computed suffix per minute.
* If a tick runs out of its time budget it schedules a continuation (`kick`) a few seconds later instead of being killed.
* Titles never exceed 128 UTF-16 units: the *name* is shortened, never the clock.

### Owner renames & the "ask the owner" rule
* Adding goes through the native picker with `chat_is_created: true` — only chats the user **owns** are offered. If the bot
  is added some other way, it checks that the adder is the creator; otherwise it posts *"ask the owner to add me"* and leaves.
* A `new_chat_title` service message is classified: made by the bot → deleted; made by anyone else → the owner's text
  (minus our clock) becomes the new base name and the clock is re-applied. A daily `getChat` check catches missed events.
* Non-owner admins can manage a chat only if the owner switches **Admin access** on; Telegram is asked live every time.

### Force-join (`lib/gate.js`, `lib/membership.js`)
* Make the bot an **admin** in each required channel so `chat_member` updates arrive. They are stored in `memberships`.
* `joined → left` sends the warning (deadline shown as a date-time entity in the reader's own time zone) and starts a 3-day
  grace period; a reminder follows 24 h before the end; rejoining cancels everything.
* A **reset** sets all settings back to defaults, pauses the user's chats and restores their original names. Coins are kept
  (`reset_keeps_balance`). Coming back = rejoin + open the bot.
* Before any reset the bot re-checks live, so a missed event can never reset someone wrongly.

---

## 3. Setup

You need Node.js 20+ on a computer (22.5+ only if you want to run `npm test`, which uses the built-in `node:sqlite`) and a bot from [@BotFather](https://t.me/BotFather).

1. **Enable Serverless** — BotFather → your bot → **Serverless** → enable, then copy the **CLI access token**.
2. **Create the project skeleton** (it brings the right CLI version and `tgcloud.jsonc`):
   ```bash
   npm create @tgcloud/bot timebyte
   cd timebyte
   npx tgcloud login          # paste the CLI access token
   ```
3. **Copy this project over it**: delete the sample files in `tgcloud/` and copy in `tgcloud/` from this archive
   (`handlers/`, `lib/`, `schema.js`). Optionally copy `test/` and the `test` script from `package.json`.
4. **Set your admin ID** in `tgcloud/lib/config.js`:
   ```js
   export const ADMIN_IDS = [123456789];   // send /id to the bot to learn yours
   ```
5. **Deploy**
   ```bash
   npx tgcloud push
   npx tgcloud migrate
   npx tgcloud webhook sync      # IMPORTANT: makes Telegram send chat_member, poll, my_chat_member …
   ```
6. **BotFather settings**: `/setjoingroups` → Enable. `/setcommands`:
   ```
   start - Open the menu
   menu - Main menu
   help - How it works
   id - Show your Telegram ID
   paysupport - Payment support
   cancel - Cancel the current action
   admin - Admin panel (admins only)
   ```
   Telegram Stars need no payment provider.
7. **Start the heartbeat**: open the bot → `/admin` → **Engine** → *Choose heartbeat chat* (create a private channel
   first, the picker adds the bot) or *Start / restart here* to use the DM. Within a minute **Status** should show
   *Heartbeat ✅ healthy*.
8. **Force-join** (optional): Admin → *Force join* → *Add channel*.
9. **Prices**: Admin → *Economy* (costs, free slots, referral/welcome/rating bonus, Stars packages).
10. Add a test channel through the bot and watch the name tick.

After code changes run `npx tgcloud push` (and `migrate` when `schema.js` changed). Adding a handler file needs
`npx tgcloud webhook sync` again.

---

## 4. Admin guide (`/admin`)

| Section | What it does |
|---|---|
| 📊 Status | Users, chats, economy, heartbeat, last 10 ticks (claimed / ok / failed / throttled / ms), flood waits, errors, Rich Message state |
| 📣 Broadcast | Audience: users · channels · groups · everyone · one user/chat. Mode: **Copy** (no sender name, formatting kept) or **Forward**. Confirm → live progress with cancel |
| 👥 Users | Find by ID, @username or forwarded message; add/remove coins, ban, reset, message the user, list chats |
| 🗂 Chats | All chats; pause, resume, verify, remove and leave |
| 💰 Economy | Slot costs, free slots, referral / welcome bonus, Stars on/off, **Packages**, **Rating bonus**, **Refund**, **Payments**, clawback and reset options |
| 🔐 Force join | Required channels with live health (is the bot admin?) and joined/left counts |
| ⚙️ Engine | Heartbeat start/stop/move, run a tick now, paid broadcast, log chat, verify all chats |
| 👑 Admins | Add/remove admins (config admins are locked) |

**Refund:** Economy → ↩️ Refund → send the transaction ID (`telegram_payment_charge_id`, shown on every receipt and in
Payments) → check the card → *Yes, refund*. Stars go back to the buyer; coins are clawed back as far as their balance allows.

**Rating bonus:** Telegram assigns each user a `UserRating` level. They receive *coins per level* once per newly reached
level (cap configurable). Checked at first start, then at most every 6 hours or when the user taps *Check rating bonus*.

---

## 5. Configuration (`tgcloud/lib/config.js`)

| Constant | Meaning |
|---|---|
| `ADMIN_IDS` | Super admins (more can be added in the bot) |
| `ADMINS_FREE` | Admins don't pay for chats |
| `BRAND_FOOTER` | Optional credit line on Help and receipts |
| `GRACE_DAYS`, `REMINDER_HOURS` | Force-join grace period (3 days) and last reminder |
| `RICH_UI` | Use Rich Messages (falls back automatically) |
| `REQUIRED_RIGHTS` | Rights the bot must have in a chat (`can_change_info`, `can_delete_messages`) |
| `PENDING_MINUTES` | Time a plain-member bot gets to be promoted |
| `ENGINE.*` | Batch size, concurrency limits, tick budget, lease, heartbeat offset, cleanup delay, verification rate |
| `DEFAULT_SETTINGS`, `DEFAULT_PACKAGES` | First-run values; afterwards edit them in the admin panel |

---

## 6. Database

`users` · `chats` · `chat_admins` · `force_channels` · `memberships` · `referrals` · `transactions` (coin ledger) ·
`packages` · `payments` · `settings` · `admins` · `timers` (heartbeat polls) · `jobs` (broadcasts) · `cleanup` · `ticks` · `errors`

Timestamps are unix seconds, flags are 0/1, there are no foreign keys (the platform disallows them); integrity is kept in
`lib/store.js`. Hot paths have indexes (`chats(status, title_minute)`, `memberships(user_id, channel_id)` unique, …).

---

## 7. Fonts

| # | Style | Sample |
|---|-------|--------|
| 0 | Classic | 15:35 |
| 1 | Bold | 𝟏𝟓:𝟑𝟓 |
| 2 | Double-struck | 𝟙𝟝:𝟛𝟝 |
| 3 | Sans | 𝟣𝟧:𝟥𝟧 |
| 4 | Sans Bold | 𝟭𝟱:𝟯𝟱 |
| 5 | Monospace | 𝟷𝟻:𝟹𝟻 |
| 6 | Fullwidth | １５：３５ |
| 7 | Circled | ①⑤:③⑤ |
| 8 | Black Circle | ❶❺:❸❺ |
| 9 | Double Circle | ⓵⓹:⓷⓹ |
| 10 | Sans Circle | ➀➄:➂➄ |
| 11 | Black Sans Circle | ➊➎:➌➎ |
| 12 | Superscript | ¹⁵:³⁵ |
| 13 | Subscript | ₁₅:₃₅ |
| 14 | Keycap | 1️⃣5️⃣:3️⃣5️⃣ |
| 15 | Underline | 1̲5̲:3̲5̲ |
| 16 | Double Underline | 1̳5̳:3̳5̳ |
| 17 | Overline | 1̅5̅:3̅5̅ |
| 18 | Dot Below | 1̣5̣:3̣5̣ |
| 19 | Square Frame | 1⃞5⃞:3⃞5⃞ |
| 20 | Round Frame | 1⃝5⃝:3⃝5⃝ |

Only characters with solid rendering on iOS, Android, Desktop and Web are used. Titles are stripped of any clock in any of
these styles when the bot needs to recover the owner's real name.

---

## 8. Testing

```bash
npm test
```
`test/run.mjs` drives the real handlers with Telegram-shaped updates against an in-memory SQLite and a scriptable fake
Bot API (`test/sdk`). It covers adding/rejecting chats, rights, rename detection, flood control, 300-chat ticks,
heartbeat chain and revival, force-join warnings/reset, broadcasts, Stars + refunds, rating bonus, referrals, migrations,
ownership changes and structural validation of every Rich Message.

---

## 9. Troubleshooting

| Symptom | Fix |
|---|---|
| Clock never updates | Admin → Status: *Heartbeat* must be healthy. Press **Start / restart here**. Make sure `webhook sync` was run after the last `push` |
| Heartbeat "silent" | The chat for the poll must let the bot post polls and delete messages; moving it: Engine → Choose heartbeat chat |
| `chat_member` never fires | The bot must be admin in the force-join channel, and `npx tgcloud webhook sync` must have been run |
| "Bot left immediately" | Only the chat **owner** can add it, with *Change info* + *Delete messages* (+ *Post messages* in channels for broadcasts) |
| Lots of "name changed" messages | Bot lacks *Delete messages*, or `ENGINE.CLEANUP_DELAY_S` is > 0 |
| 429 / flood waits | Normal under load: see Status → *Flood waits*. The engine slows down by itself |
| Rich messages look plain | Status shows *fallback mode*: Telegram rejected a Rich Message and the classic format is used |

---

## 10. Assumptions & limits (please read)

* **Heartbeat relies on Telegram sending a `poll` update when a bot-sent poll closes on schedule.** That is how Telegram
  documents bot polls, but verify it on your bot (step 7). Everything else works even if you trigger ticks manually.
* The platform does not document per-invocation time limits. `ENGINE.BUDGET_MS` (20 s) is conservative; lower it if you see
  timeouts. Long ticks and broadcasts continue through continuation timers.
* Rich Message block shapes follow Bot API 10.3. If Telegram rejects one, the same screen is sent as classic HTML.
* Because the bot is admin it receives every group message; the handler returns immediately without touching the database.
* Broadcast sends a **single message** per run (albums arrive as separate messages — send them one by one or forward them).
* Data from the old `TimeByte.py` SQLite file is not imported.

---

## 11. Project structure

```
tgcloud/
  schema.js                 database schema
  handlers/                 one file per Telegram update type
    message.js  callback_query.js  my_chat_member.js  chat_member.js
    channel_post.js  pre_checkout_query.js  poll.js
  lib/
    config.js  util.js  fonts.js  time.js  title.js      pure helpers
    tg.js  store.js  ui.js                               Bot API wrapper, data access, Rich/classic renderer
    chats.js  rename.js  engine.js  heartbeat.js         chat life cycle, rename engine, scheduler
    gate.js  membership.js  billing.js  broadcast.js     force-join, coins/Stars, broadcasts
    screens_user.js  screens_admin.js  router.js  inbox.js  flows.js   UI and routing
test/                       end-to-end tests with a fake Bot API
```
