/** Where another system pushes a source's new URL, and how. */

export function hookUrl(origin: string): string {
  return `${origin}/api/hooks/source-url`;
}

export function curlExample(origin: string, token: string): string {
  return [
    `curl -X POST ${hookUrl(origin)} \\`,
    `  -H 'Authorization: Bearer ${token}' \\`,
    `  -H 'Content-Type: application/json' \\`,
    `  -d '{"url": "https://…"}'`,
  ].join('\n');
}
