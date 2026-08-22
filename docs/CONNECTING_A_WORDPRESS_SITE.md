# Connecting a WordPress site to Titan

Written 2026-08-20 against **zashmart.com**, the first real WordPress site
Titan will touch. Everything in the first section was measured, not assumed.

## What Titan needs — and what it must never be given

| Needed | Not needed, never send |
|---|---|
| A WordPress **Application Password** (24 characters, shown once) | The site owner's WordPress login password |
| The site URL | The **Hostinger account** email and password |
| The WordPress **username** the app password belongs to | Any hosting control-panel credential |

An Application Password is scoped to one application, is revocable from the
WordPress profile screen without changing anything else, and cannot be used to
log in to wp-admin in a browser. A hosting account password is the keys to the
whole building, and it belongs to the person whose account it is.

**Do not paste any of these into a chat, a source file, a test fixture, or a
commit.** Titan stores the application password encrypted through
`core/site_access.py`, which derives its key from `core/appsecret.py`. That is
the only place it should ever exist.

---

## Measured on 2026-08-20 — the documented blocker is gone

`CONTINUE_HERE.md` lists as blocker #2: *"zashmart.com — the host must pass the
`Authorization` header through."* **That is no longer true.** Apache/LiteSpeed
commonly strips `Authorization` before PHP sees it, which is why the note
existed, but Hostinger is passing it on this site today.

Proved with a controlled pair of requests, using a deliberately **fake**
username so no real credential was involved:

```bash
# 1. No Authorization header at all
curl -s -o - https://zashmart.com/wp-json/wp/v2/users/me
# -> {"code":"rest_not_logged_in","message":"You are not currently logged in."}

# 2. Same URL, with a deliberately WRONG Authorization header
curl -s -u "nosuchuser:not a real password" https://zashmart.com/wp-json/wp/v2/users/me
# -> {"code":"invalid_username","message":"Unknown username. ..."}
```

**Two different errors is the whole proof.** If the header were being stripped,
request 2 would also have returned `rest_not_logged_in` — WordPress would never
have known credentials were offered. `invalid_username` means WordPress
received the header, parsed it, and tried to authenticate. The only thing
missing is a username that exists.

Also measured:

- `GET /wp-json/` → **200**, site name "Zash Mart". REST API is not disabled.
- `GET /wp-json/wp/v2/pages?per_page=1` → **200**. Public reads work.
- `Server: hcdn` (Hostinger CDN), `X-Powered-By: PHP/8.2.30`.

**So the remaining step is one thing: an Application Password.** No `.htaccess`
change, no hosting login, no plugin.

---

## What the site owner does — about five minutes

He does this himself, signed in to his own site. Nobody else needs his password.

1. Sign in to `https://zashmart.com/wp-admin`.
2. Go to **Users → Profile** (or Users → All Users → his own account).
3. Scroll to **Application Passwords**.
4. In *New Application Password Name*, type: `Titan Omega`
5. Click **Add New Application Password**.
6. WordPress shows a 24-character password **once**, like
   `abcd EFGH ijkl MNOP qrst UVWX`. The spaces are part of it and are fine to
   keep. Copy it now — it is never shown again.
7. Send it to Abdullah **only** through something private, and paste it
   straight into Titan's site-connection screen rather than into a chat log.

He can revoke it from the same screen at any moment, and revoking it affects
nothing else about his site.

### If the Application Passwords section is not there

- WordPress **5.6 or newer** is required. `/wp-json/` reported a live modern
  install, so this should be present.
- It is hidden on plain `http://`. The site is HTTPS, so this does not apply
  here.
- Some security plugins (Wordfence, iThemes/Solid Security) disable it. If it
  is missing, that is the thing to look for — **do not work around it by
  handing over the real password.**

---

## Verifying the connection actually works

Titan does not trust a 200. `core/site_fix.py` reads every write back off the
live site and calls a mismatch `failed`, never `applied` — because WordPress's
`wp_kses_post` silently strips content for users without `unfiltered_html`,
which would otherwise make a fix look successful and do nothing.

The same rule applies to the credential itself. Check it directly:

```bash
curl -s -u "USERNAME:APP PASSWORD HERE" https://zashmart.com/wp-json/wp/v2/users/me
```

- Returns the user's JSON, with a `capabilities` object → **connected**.
- `invalid_username` → wrong username (try the email address instead).
- `incorrect_password` → the app password was mistyped or has been revoked.
- `rest_not_logged_in` → the header is being stripped again; see the fallback
  below.

Titan checks one thing beyond authentication: the account must have
`edit_pages`. A credential that can log in but cannot edit is rejected at
connection time rather than failing later — there is a test for that
(`test_a_credential_that_cannot_edit_is_rejected`). An Editor or Administrator
account has it; an Author or Subscriber does not.

---

## Fallback — only if `rest_not_logged_in` ever appears with a header set

Not needed on zashmart.com today. Recorded so nobody has to re-derive it if
Hostinger changes its PHP handler, or when connecting a different host.

Add to `.htaccess` in the WordPress root, **above** the `# BEGIN WordPress`
block:

```apache
# Pass HTTP Basic credentials through to PHP.
SetEnvIf Authorization "(.*)" HTTP_AUTHORIZATION=$1
```

If that alone does not work, use the rewrite form instead:

```apache
<IfModule mod_rewrite.c>
RewriteEngine On
RewriteCond %{HTTP:Authorization} ^(.*)
RewriteRule .* - [E=HTTP_AUTHORIZATION:%1]
</IfModule>
```

Then re-run the controlled pair at the top of this file. **A wrong username
must produce `invalid_username`, not `rest_not_logged_in`** — that is the
signal, and it costs nothing to test because it needs no real credential.

---

## What Titan can and cannot change once connected

From `CONTINUE_HERE.md` §"Shipped 2026-08-13", and worth repeating to the site
owner before he agrees to anything:

- Titan proposes; a **named human approves**; only then is anything written.
  There is deliberately no auto-apply flag, and `fix_cycle` deliberately does
  not apply.
- Only **three** things are fixable over the WordPress REST API: page title,
  media alt text, and JSON-LD into content. **Meta description is not
  fixable** — core WordPress has no such field.
- Alt text is only proposed where the file name actually describes the image.
  `IMG_4821.jpg` is handed to a human, because Titan has not seen it.
- The exact prior value is snapshotted before any write, so a rollback
  restores rather than reconstructs.
- **Caveat, stated plainly:** on the current free-tier host those rollback
  snapshots do not survive a rebuild (`durable: false`). Until persistent
  storage exists, treat rollback as best-effort and keep a real backup of the
  site.
