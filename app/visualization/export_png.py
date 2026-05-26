import asyncio
import base64
import json


def _build_html(payload_json: str) -> str:
    template = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <script src="https://unpkg.com/cytoscape@3.31.2/dist/cytoscape.min.js"></script>
  <style>
    html, body, #graph { height: 100%; margin: 0; background: #08121f; }
  </style>
</head>
<body>
  <div id="graph"></div>
  <script>
    window.__GRAPH_PAYLOAD__ = __PAYLOAD__;
    (function() {
      const payload = window.__GRAPH_PAYLOAD__;
      const elements = [...(payload.nodes || []), ...(payload.edges || [])];
      const cy = cytoscape({
        container: document.getElementById('graph'),
        elements,
        style: [
          { selector: 'node', style: { 'label': 'data(label)', 'color': '#e8eef7', 'text-outline-color': '#07111f', 'text-outline-width': 2, 'font-size': 12, 'background-color': '#6b7a90', 'width': 34, 'height': 34 } },
          { selector: 'node:parent', style: { 'padding': 28, 'background-opacity': 0.08, 'background-color': '#0d1523', 'border-width': 1, 'border-color': 'rgba(255,255,255,0.14)' } },
          { selector: 'edge', style: { 'width': 1.6, 'line-color': 'rgba(159,176,199,0.42)', 'target-arrow-color': 'rgba(159,176,199,0.42)', 'target-arrow-shape': 'triangle', 'curve-style': 'bezier' } }
        ],
        layout: {
          name: 'breadthfirst',
          directed: true,
          spacingFactor: 1.8,
          avoidOverlap: true,
          padding: 60,
          animate: false
        }
      });

      setTimeout(function() {
        try {
          window.__GRAPH_PNG__ = cy.png({ full: true, scale: 2 });
        } catch (error) {
          window.__GRAPH_PNG_ERROR__ = String(error);
        }
      }, 900);
    })();
  </script>
</body>
</html>"""

    return template.replace("__PAYLOAD__", payload_json)


async def render_graph_png(graph: dict, timeout: int = 10000) -> bytes:
    try:
        from playwright.async_api import async_playwright
    except Exception as error:
        raise RuntimeError('Playwright is required for server-side PNG export: ' + str(error))

    payload_json = json.dumps(graph)
    html = _build_html(payload_json)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=['--no-sandbox'])
        page = await browser.new_page()
        await page.set_content(html, wait_until='networkidle')

        elapsed = 0
        interval = 200
        while elapsed < timeout:
            png_data = await page.evaluate('window.__GRAPH_PNG__')
            error = await page.evaluate('window.__GRAPH_PNG_ERROR__')

            if error:
                await browser.close()
                raise RuntimeError('Export failed: ' + str(error))

            if png_data:
                prefix = 'data:image/png;base64,'
                if png_data.startswith(prefix):
                    b64 = png_data[len(prefix):]
                else:
                    b64 = png_data.split(',')[-1]

                data = base64.b64decode(b64)
                await browser.close()
                return data

            await asyncio.sleep(interval / 1000.0)
            elapsed += interval

        await browser.close()
        raise RuntimeError('Timed out waiting for graph render')
