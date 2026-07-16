# Registro pages (served from reenewtv.com/ricky/*.html)

These are the multi-step registration pages. As of 2026-07-16 they are VISUAL
PROTOTYPES only — they navigate and enforce the 5-photo cap (JS) but do NOT save
data or upload photos (no file inputs / fetch / field names / submit handler).

Pending work (David confirmed flow 2026-07-16):
- registro_artista.html: wire all fields -> backend, real photo upload (max 5/show),
  then on Finalizar route to the dashboard authenticated. Backend Artist model already
  has the fields; me.py update_my_profile exists; multi-show + pricing persistence + a
  photo-upload endpoint/storage still needed.
- registro_hotel.html: repurpose as a short PRE-REGISTRO (lead) — no account; lands as
  a "prospecto" in an admin panel + notification; David contacts for videollamada.

Copied here for version control before wiring; canonical live copies live in the addon
docroot ~/reenewtv.com/ricky/ (David's static dir).
