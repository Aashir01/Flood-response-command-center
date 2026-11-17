/* eslint-disable @next/next/no-html-link-for-pages -- static redirect page; each language is its own root layout */
// `/` redirects to /en/ (Caddy also redirects; this static page is the fallback).
export default function Root() {
  return (
    <html lang="en">
      <head>
        <meta httpEquiv="refresh" content="0; url=/en/" />
        <title>Stitch</title>
      </head>
      <body style={{ background: '#07090c', color: '#eef3f2', fontFamily: 'system-ui, sans-serif' }}>
        <p>
          <a href="/en/" style={{ color: '#9fd3ff' }}>
            Stitch (English)
          </a>{' '}
          ·{' '}
          <a href="/ur/" lang="ur" style={{ color: '#9fd3ff' }}>
            اسٹچ (اردو)
          </a>
        </p>
      </body>
    </html>
  );
}
