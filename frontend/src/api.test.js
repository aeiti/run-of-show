import { describe, expect, it } from 'vitest'
import { errorSummary } from './api'

// Trimmed from the page Django served when a migration hadn't run yet.
const DJANGO_PAGE = `<!DOCTYPE html> <html lang="en"> <head> <title>ProgrammingError at /api/runs/49/</title>
<style> html * { padding:0; } </style> <script> function hideAll(elems) {} </script> </head>
<body> <header id="summary"> <h1>ProgrammingError at /api/runs/49/</h1>
<pre class="exception_value">relation &quot;shows_act&quot; does not exist LINE 1: ..., &quot;shows_act&quot;.&quot;up_at&quot; FROM &quot;shows_act... ^</pre>
<table class="meta"> <tr> <th scope="row">Request Method:</th> <td>GET</td> </tr> </table> </header> ${'<li>frame</li>'.repeat(500)} </body> </html>`

describe('errorSummary', () => {
  it("gives the title and exception of Django's error page, not the page", () => {
    expect(errorSummary(DJANGO_PAGE)).toBe(
      'ProgrammingError at /api/runs/49/: relation "shows_act" does not exist LINE 1: ..., "shows_act"."up_at" FROM "shows_act... ^',
    )
  })

  it('gives the title of any other HTML page', () => {
    expect(errorSummary('<html><head><title>502 Bad Gateway</title></head><body><h1>502</h1></body></html>')).toBe(
      '502 Bad Gateway',
    )
    expect(errorSummary('<!doctype html><body>nothing useful</body>')).toBe('Server error')
  })

  it('keeps short plain text and cuts long text', () => {
    expect(errorSummary('Service Unavailable')).toBe('Service Unavailable')
    const long = errorSummary('x'.repeat(1000))
    expect(long).toHaveLength(300)
    expect(long.endsWith('…')).toBe(true)
  })
})
