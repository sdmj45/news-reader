/**
 * Keeps package-lock.json pointing at the public npm registry.
 *
 * Why this exists: this project is developed behind a corporate proxy whose npm mirror
 * rewrites every `resolved` URL in the lockfile to an internal host. That lockfile installs
 * perfectly on the developer's machine and fails on every other machine in the world,
 * including GitHub Actions, which cannot resolve the internal hostname. The failure is
 * late, remote and unhelpful — npm prints its own usage text — so it is worth a guard.
 *
 * The rewrite is safe. These mirrors are path-prefixed proxies of registry.npmjs.org, so the
 * public URL is the mirror URL minus its prefix, and the `integrity` hashes are hashes of
 * the tarball contents, which are byte-identical whichever host served them. Nothing about
 * what gets installed changes; only where npm is told to fetch it from.
 *
 *   node scripts/lockfile-registry.mjs          rewrite in place
 *   node scripts/lockfile-registry.mjs --check   exit 1 if any private URL remains
 */

import { readFileSync, writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const PUBLIC = 'https://registry.npmjs.org'
const LOCKFILE = join(dirname(dirname(fileURLToPath(import.meta.url))), 'package-lock.json')

/** Matches any host proxying the public registry under a path prefix. */
const MIRROR = /"resolved":\s*"https?:\/\/(?!registry\.npmjs\.org)[^"]*?\/registry\.npmjs\.org\//g

const check = process.argv.includes('--check')
const original = readFileSync(LOCKFILE, 'utf8')
const rewritten = original.replace(MIRROR, `"resolved": "${PUBLIC}/`)

const remaining = [...rewritten.matchAll(/"resolved":\s*"https?:\/\/([^/"]+)/g)]
  .map((m) => m[1])
  .filter((host) => host !== 'registry.npmjs.org')

if (remaining.length) {
  const hosts = [...new Set(remaining)].join(', ')
  console.error(
    `package-lock.json resolves packages from ${hosts}, which CI cannot reach.\n` +
      `This pattern is not a known registry mirror, so it was left alone. Regenerate the\n` +
      `lockfile against the public registry, or extend the pattern in\n` +
      `frontend/scripts/lockfile-registry.mjs.`,
  )
  process.exit(1)
}

if (rewritten === original) {
  console.log('package-lock.json already resolves everything from registry.npmjs.org')
  process.exit(0)
}

const count = (original.match(MIRROR) ?? []).length
if (check) {
  console.error(
    `package-lock.json resolves ${count} packages from a private mirror, which CI cannot\n` +
      `reach. Fix it with:\n\n    npm run lockfile:fix\n\n` +
      `This happens whenever \`npm install\` runs behind a corporate npm proxy.`,
  )
  process.exit(1)
}

writeFileSync(LOCKFILE, rewritten)
console.log(`rewrote ${count} resolved URLs to ${PUBLIC}`)
