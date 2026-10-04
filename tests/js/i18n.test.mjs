// Run with: node --test tests/js/
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import vm from "node:vm";

const FRONTEND = new URL("../../custom_components/beamin/frontend/", import.meta.url);
const read = (name) => readFileSync(new URL(name, FRONTEND), "utf8");

const context = { self: {} };
vm.runInNewContext(read("i18n.js"), context);
const { STRINGS, createTranslator, formatDuration, pickLanguage } = context.self.BeamInI18n;

const placeholders = (text) => [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();

test("English and French have the same keys and placeholders", () => {
  assert.deepEqual(Object.keys(STRINGS.fr).sort(), Object.keys(STRINGS.en).sort());
  for (const [key, text] of Object.entries(STRINGS.en)) {
    assert.deepEqual(placeholders(STRINGS.fr[key]), placeholders(text), key);
  }
});

test("every key used by the page and the panel exists", () => {
  const used = new Set();
  for (const name of ["beam.js", "beamin-panel.js"]) {
    for (const match of read(name).matchAll(/\bt\(\s*["'`]([a-z_]+)["'`]/g)) used.add(match[1]);
  }
  for (const match of read("beam.html").matchAll(/data-i18n(?:-alt)?="([a-z_]+)"/g)) {
    used.add(match[1]);
  }
  for (const kind of ["car", "tv", "tablet", "phone", "computer", "unknown"]) used.add(`kind_${kind}`);
  for (const network of ["local", "internet", "same_public_ip", "cloud", "unknown"]) {
    used.add(`network_${network}`);
  }
  for (const match of read("beamin-panel.js").matchAll(/:\s*"(error_[a-z_]+|invalid_format)"/g)) {
    used.add(match[1]);
  }
  const missing = [...used].filter((key) => !(key in STRINGS.en));
  assert.deepEqual(missing, []);
});

test("language selection falls back to English", () => {
  assert.equal(pickLanguage(["fr-FR", "en"]), "fr");
  assert.equal(pickLanguage(["de-DE", "fr"]), "fr");
  assert.equal(pickLanguage(["de"]), "en");
  assert.equal(pickLanguage([undefined]), "en");
});

test("placeholders are filled and unknown ones are kept", () => {
  const { t } = createTranslator(["fr"]);
  assert.equal(t("expires_in", { time: "1:30" }), "Expire dans 1:30");
  assert.equal(t("expires_in"), "Expire dans {time}");
  assert.equal(t("no_such_key"), "no_such_key");
});

test("durations read naturally", () => {
  const { t } = createTranslator(["en"]);
  assert.equal(formatDuration(t, 60), "1 hour");
  assert.equal(formatDuration(t, 120), "2 hours");
  assert.equal(formatDuration(t, 45), "45 min");
});
