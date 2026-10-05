# Changelog

## 0.1.0 (unreleased)

First release.

- `/beam` page for signed-out devices: QR code, `XXX-XXX` code, matching number, countdown, landscape layout for car and TV screens, light and dark themes, English and French.
- BeamIn sidebar panel to approve a sign-in from any signed-in phone or computer, opened pre-filled by the QR code.
- Option to show a shorter address to type on devices in the panel, such as your own domain or a short link to `/beam`.
- Number matching, device and network details, 120-second single-use requests bound to a secret held by the requesting page.
- Sessions created through the Home Assistant auth API, listed and revocable in Profile → Security.
- Temporary sessions (1 hour by default) revoked on time, across restarts, and when BeamIn is disabled or removed.
- Administrators can sign a device in as another eligible user (never the owner unless they are the owner, never system or inactive users).
- Rate limits, per-address and global request caps, approver lockout after 5 wrong codes, and Home Assistant IP bans on secret guessing.
- Events `beamin_login_requested`, `beamin_login_approved`, `beamin_login_denied`, `beamin_login_expired`, and a notification blueprint.
