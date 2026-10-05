# Security policy

BeamIn signs devices in to Home Assistant, so its security matters more than its features. This document describes what it protects, how, and what it does not cover.

## Reporting a vulnerability

Please **do not open a public issue**. Use GitHub's private reporting instead: **Security → Report a vulnerability** on this repository. Include the version, a description, and steps to reproduce if you have them.

You can expect an acknowledgement within 7 days. Fixes for confirmed issues are released as soon as possible, and you will be credited in the release notes unless you prefer otherwise.

Only the latest release receives security fixes.

## What BeamIn protects

- Home Assistant sessions (refresh and access tokens) and the accounts behind them, in particular administrators and the owner.
- The approver's decision: only a person, on a signed-in session, can let a device in.
- The availability of normal login: BeamIn never changes the regular login page or the existing users.

## Threat model

| Threat | Mitigation |
| --- | --- |
| Someone on the internet opens `/beam`, reads or guesses a code and hopes to get a session. | The code grants nothing. Tokens are only delivered to the page that created the request, which holds a 256-bit secret (`secrets.token_urlsafe(32)`) kept in page memory, never displayed, never in the QR code, never logged. The server stores a SHA-256 hash and compares with `hmac.compare_digest`. |
| An attacker tries to collect the tokens of someone else's request. | Polling needs the request id (128 bits) **and** the secret. A wrong secret destroys the request and counts as a failed login in Home Assistant's IP ban mechanism (`ip_ban_enabled`, `login_attempts_threshold`). |
| Phishing: an attacker sends their QR code or code to a user and asks them to approve it. | No notification is ever sent for a new request. The approval screen shows the device, its IP address, whether it is on the local network or the internet (and whether it shares the phone's public address), the request age and a warning to approve only screens in front of you. Codes live 120 seconds. Approved sign-ins fire events (notification blueprint) and every session is listed in Profile → Security. This remains the main residual risk: users must not approve codes they received from someone else. |
| MFA fatigue (many prompts until the user taps Approve). | There are no prompts: the approver must type or scan the code. |
| A short link or redirect used to reach `/beam` sends a device to a fake page that shows someone else's code. | The "Address to type on the device" option is only displayed in the panel: BeamIn never fetches or follows it. The README recommends your own domain or a short link nobody can change. A code shown on a fake page belongs to another device: the approval screen shows that device's type, IP address and network, which do not match the screen in front of you. |
| A compromised low-privilege account brute-forces codes. | 31⁶ ≈ 887 million codes, at most 10 waiting at once, and a 5-minute lockout after 5 failures (wrong code or wrong number) per user. Successes never reset the counter. |
| "Login CSRF": an attacker approves a victim's request so that the victim's device is signed in as the attacker. | Requires guessing the code (above) and the right number among three; a wrong number destroys the request. |
| Cross-site request forgery or clickjacking against the approval. | Approval is a POST that needs a `Bearer` token (Home Assistant does not use cookies), and an explicit number choice. GET requests never change anything (`/approve` and `/deny` answer 405 to GET). `/beam` forbids framing with `frame-ancestors 'none'`; Home Assistant's frontend sends `X-Frame-Options: SAMEORIGIN`. |
| Privilege escalation through "sign in as another user". | Checked on the server: administrators only; never system-generated or inactive users; never the owner unless the approver is the owner; local-only users only on local devices, as in Home Assistant's own login. |
| Automated approval by a script. | Requests authenticated with a long-lived access token, by a system user, or without a refresh token (Supervisor socket) are refused. |
| A temporary session turning permanent. | Temporary BeamIn sessions cannot approve other devices. Revocation is persisted before the tokens leave the server, rescheduled at startup (overdue ones are revoked immediately), and every temporary session is revoked when BeamIn is disabled or removed. |
| Token leakage. | Tokens are only in POST response bodies with `Cache-Control: no-store`, never in URLs, never logged, never in events or diagnostics. Diagnostics contain counters and redacted options only. |
| Cross-site scripting on `/beam` or through a crafted User-Agent. | A strict Content-Security-Policy without inline scripts (`default-src 'none'; script-src 'self'; …`); all dynamic values are inserted with `textContent`; the device description is mapped to a fixed vocabulary (raw User-Agent text is never displayed or logged). |
| Denial of service by flooding requests. | Per-address rate limits on the page, request creation and polling (IPv6 grouped per /64), 3 waiting requests per address and 10 overall, bounded memory. Residual risk accepted: an attacker with many addresses can make BeamIn temporarily unavailable; regular login keeps working. |

## Design choices

- Tokens are created with the official auth API (`async_create_refresh_token`, then `async_create_access_token`) **when the device collects them**, not when the approver taps Approve: no token exists for a device that never comes back, the recorded IP address is the device's, and local-only rules are checked in the device's own request.
- The refresh token uses the client ID the Home Assistant frontend uses for that address (`<origin>/`), checked against the `Origin` header, so the device refreshes its session through the normal `/auth/token` endpoint.
- The only non-public Home Assistant function used is `homeassistant.components.http.ban.process_wrong_login`, to share Home Assistant's own failed-login counter and IP bans. It is isolated in `auth_helpers.py`; if it ever disappears, BeamIn logs a warning and keeps its own rate limits.
- Everything is served by Home Assistant itself: no CDN, no external call, no telemetry.

## Out of scope

- A compromised phone or a compromised Home Assistant account: whoever controls a signed-in session can approve devices as that user, as they could already use Home Assistant.
- A user who approves a code received from someone else despite the warnings.
- Network attackers when Home Assistant is served over plain HTTP: use HTTPS for remote access.
