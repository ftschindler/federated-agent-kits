#!/usr/bin/env node
// Install the exact Chrome puppeteer drives, then run linkspector.
//
// This was `bash -c 'npx ... && linkspector ...'` in .pre-commit-config.yaml.
// Two commands joined by `&&` is a shell sentence, and the hook config is run by
// contributors on Windows, where bash is not something the repo may assume. The
// hook's language is already node, so node is the one interpreter guaranteed to
// be present wherever it runs.

import { spawnSync } from "node:child_process";

// ATTENTION: keep in sync with the @umbrelladocs/linkspector version pinned in
// .pre-commit-config.yaml, as the comment there says.
const CHROME = "chrome@152.0.7977.64";

const steps = [
  ["npx", ["--yes", "puppeteer", "browsers", "install", CHROME]],
  ["linkspector", ["check", "-c", ".linkspector.yml"]],
];

for (const [command, args] of steps) {
  // `shell: true` because both are npm-installed bins, which on Windows are
  // `.cmd` shims the OS cannot spawn directly. The arguments are constants in
  // this file, so there is nothing here for a shell to reinterpret.
  const result = spawnSync(command, args, { stdio: "inherit", shell: true });
  if (result.error) {
    console.error(`linkspector hook: could not run ${command}: ${result.error.message}`);
    process.exit(1);
  }
  if (result.status !== 0) {
    process.exit(result.status ?? 1);
  }
}
