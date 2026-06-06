"""Render the repository graph visualization page without a template file."""

from textwrap import dedent


def build_graph_page(repo_owner: str, repo_name: str, github_user: str) -> str:
    page = dedent(
        """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>RepoHeal Graph - __REPO_OWNER__/__REPO_NAME__</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #08121f;
      --panel: rgba(11, 18, 30, 0.93);
      --border: rgba(125, 151, 184, 0.2);
      --text: #edf4fb;
      --muted: #9eb0c8;
      --accent: #4fd1c5;
      --accent-2: #7c9cff;
      --repo: #4fd1c5;
      --file: #5b8cff;
      --package: #ef5350;
      --module: #ff9f43;
      --symbol: #95a3b3;
      --function: #38d39f;
      --class: #b26cff;
      --api: #ff6fb1;
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      min-height: 100vh;
      font-family: "Aptos", "Segoe UI Variable Text", "Segoe UI", sans-serif;
      background:
        radial-gradient(circle at top left, rgba(79, 209, 197, 0.18), transparent 32%),
        radial-gradient(circle at bottom right, rgba(124, 156, 255, 0.18), transparent 30%),
        var(--bg);
      color: var(--text);
    }

    .shell {
      display: grid;
      grid-template-columns: 320px 1fr;
      gap: 20px;
      min-height: 100vh;
      padding: 20px;
    }

    .panel {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 18px;
      backdrop-filter: blur(16px);
      box-shadow: 0 20px 60px rgba(0, 0, 0, 0.35);
    }

    .sidebar {
      padding: 20px;
      display: flex;
      flex-direction: column;
      gap: 16px;
    }

    .eyebrow {
      margin: 0;
      text-transform: uppercase;
      letter-spacing: 0.18em;
      font-size: 11px;
      color: var(--accent);
    }

    h1 {
      margin: 0;
      font-size: 28px;
      line-height: 1.1;
      overflow-wrap: break-word;
      word-break: break-all;
    }

    .muted {
      color: var(--muted);
      font-size: 14px;
      line-height: 1.5;
    }

    .stat,
    .legend {
      display: grid;
      gap: 6px;
      padding: 14px 16px;
      border-radius: 14px;
      background: rgba(255, 255, 255, 0.03);
      border: 1px solid rgba(255, 255, 255, 0.06);
    }

    .stat strong { font-size: 14px; color: #fff; }

    .stat span,
    .legend-row {
      font-size: 13px;
      color: var(--muted);
      overflow-wrap: anywhere;
    }

    .legend { gap: 8px; }

    .legend-row {
      display: flex;
      align-items: center;
      gap: 10px;
    }

    .swatch {
      width: 10px;
      height: 10px;
      border-radius: 999px;
      flex: 0 0 auto;
    }

    .actions,
    .mini-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }

    .button {
      border: 0;
      border-radius: 999px;
      padding: 10px 14px;
      font-weight: 600;
      color: #021019;
      background: linear-gradient(135deg, var(--accent), var(--accent-2));
      cursor: pointer;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      justify-content: center;
    }

    .button.secondary {
      color: var(--text);
      background: rgba(255, 255, 255, 0.08);
      border: 1px solid rgba(255, 255, 255, 0.08);
    }

    .canvas {
      position: relative;
      overflow: hidden;
      min-height: 80vh;
    }

    #graph {
      width: 100%;
      height: 100%;
      min-height: calc(100vh - 40px);
      border-radius: 18px;
    }

    .overlay {
      position: absolute;
      inset: 18px auto auto 18px;
      padding: 12px 14px;
      border-radius: 12px;
      background: rgba(6, 10, 16, 0.75);
      border: 1px solid rgba(255, 255, 255, 0.08);
      color: var(--muted);
      font-size: 13px;
      max-width: min(520px, calc(100% - 36px));
      pointer-events: none;
      backdrop-filter: blur(10px);
    }

    .details {
      display: grid;
      gap: 6px;
      margin-top: 10px;
      color: var(--text);
    }

    .details span { color: var(--muted); }

    .details code {
      color: var(--text);
      background: rgba(255, 255, 255, 0.05);
      border: 1px solid rgba(255, 255, 255, 0.07);
      padding: 2px 6px;
      border-radius: 999px;
      font-size: 12px;
      width: fit-content;
    }

    .error { color: #ff7b7b; }

    @media (max-width: 960px) {
      .shell { grid-template-columns: 1fr; }

      #graph { min-height: 70vh; }
    }
  </style>
  <script src="https://unpkg.com/cytoscape@3.31.2/dist/cytoscape.min.js"></script>
</head>
<body>
  <div class="shell">
    <aside class="panel sidebar">
      <p class="eyebrow">RepoHeal Visualization</p>
      <h1>__REPO_OWNER__/__REPO_NAME__</h1>
      <div class="muted">Interactive repository intelligence for __GITHUB_USER__.</div>

      <div class="stat">
        <strong>Repository</strong>
        <span id="repoLabel">__REPO_OWNER__/__REPO_NAME__</span>
      </div>

      <div class="stat">
        <strong>Status</strong>
        <span id="statusLabel">Loading graph data...</span>
      </div>

      <div class="stat">
        <strong>Nodes</strong>
        <span id="nodeCount">0</span>
      </div>

      <div class="stat">
        <strong>Edges</strong>
        <span id="edgeCount">0</span>
      </div>

      <div class="stat">
        <strong>Hover</strong>
        <span>Inspect node type, namespace, version, usage count, and definitions.</span>
      </div>

      <div class="legend">
        <div class="legend-row"><span class="swatch" style="background: var(--repo);"></span>Repository</div>
        <div class="legend-row"><span class="swatch" style="background: var(--file);"></span>File</div>
        <div class="legend-row"><span class="swatch" style="background: var(--package);"></span>Package</div>
        <div class="legend-row"><span class="swatch" style="background: var(--module);"></span>Module</div>
        <div class="legend-row"><span class="swatch" style="background: var(--symbol);"></span>Symbol</div>
        <div class="legend-row"><span class="swatch" style="background: var(--function);"></span>Function</div>
        <div class="legend-row"><span class="swatch" style="background: var(--class);"></span>Class</div>
        <div class="legend-row"><span class="swatch" style="background: var(--api);"></span>API</div>
      </div>

      <div class="mini-actions">
        <button class="button secondary" id="resetLayout" type="button">Reset layout</button>
        <button class="button secondary" id="exportPNG" type="button">Download PNG</button>
      </div>

      <div class="actions">
        <a class="button" href="/dashboard">Back to dashboard</a>
        <a class="button secondary" href="/logout">Logout</a>
        <a class="button secondary" href="/graph/__REPO_OWNER__/__REPO_NAME__" target="_blank" rel="noreferrer">Open JSON</a>
      </div>
    </aside>

    <main class="panel canvas">
      <div id="graph"></div>
      <div class="overlay" id="overlay">Initializing graph and analyzing repository...</div>
    </main>
  </div>

  <script>
    (async () => {
      const repoOwner = "__REPO_OWNER__";
      const repoName = "__REPO_NAME__";
      const repoId = `${repoOwner}/${repoName}`;
      const statusLabel = document.getElementById("statusLabel");
      const nodeCount = document.getElementById("nodeCount");
      const edgeCount = document.getElementById("edgeCount");
      const overlay = document.getElementById("overlay");
      const resetLayoutButton = document.getElementById("resetLayout");
      const exportPNGButton = document.getElementById("exportPNG");

      let cy = null;

      const escapeHtml = (value) => String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");

      const defaultOverlay = (nodes, edges) => `Loaded <strong>${nodes}</strong> nodes and <strong>${edges}</strong> edges.`;

      const describeNode = (data) => {
        const details = [];
        const namespacePath = data.leaf_path || data.module_path || data.path || data.qualified_name || data.id;

        if (data.type) details.push(`Type: ${data.type}`);
        if (data.kind) details.push(`Kind: ${data.kind}`);
        if (data.repo_id) details.push(`Repo: ${data.repo_id}`);
        if (namespacePath) details.push(`Namespace: ${namespacePath}`);
        if (data.path) details.push(`Path: ${data.path}`);
        if (data.package_type) details.push(`Package type: ${data.package_type}`);
        if (data.version) details.push(`Version: ${data.version}`);
        if (data.status) details.push(`Status: ${data.status}`);
        if (typeof data.imports === "number") details.push(`Imports: ${data.imports}`);
        if (typeof data.usage_count === "number") details.push(`Usage count: ${data.usage_count}`);
        if (typeof data.line_start === "number" || typeof data.line_end === "number") {
          details.push(`Lines: ${data.line_start || "?"}-${data.line_end || "?"}`);
        }
        if (Array.isArray(data.libraries_used) && data.libraries_used.length) {
          details.push(`Libraries: ${data.libraries_used.join(", ")}`);
        }
        if (data.parent) details.push(`Parent: ${data.parent}`);
        if (data.scope) details.push(`Scope: ${data.scope}`);

        return `
          <strong>${escapeHtml(data.label || data.id || "Node")}</strong>
          <div class="details">
            ${details.map((item) => `<span>${escapeHtml(item)}</span>`).join("")}
          </div>
        `;
      };

      const setStatus = (message) => {
        overlay.innerHTML = message;
      };

      const hideDetailedNodes = () => {
        if (!cy) {
          return;
        }

        cy.nodes('[view_level > 0]').hide();
        cy.edges('[view_level > 0]').hide();
        cy.nodes().forEach((node) => node.data('expanded', false));
      };

      const expandNode = (node) => {
        const descendants = node.descendants().filter((descendant) => descendant.data('view_level') > 0);

        if (!descendants.nonempty()) {
          return false;
        }

        descendants.show();
        descendants.connectedEdges().show();
        node.data('expanded', true);
        return true;
      };

      const collapseNode = (node) => {
        const descendants = node.descendants().filter((descendant) => descendant.data('view_level') > 0);

        if (!descendants.nonempty()) {
          return false;
        }

        descendants.connectedEdges().hide();
        descendants.hide();
        node.data('expanded', false);
        return true;
      };

      const getLayoutDirection = () => {
        const container = cy?.container();
        const width = container?.clientWidth || window.innerWidth || 1;
        const height = container?.clientHeight || window.innerHeight || 1;

        return width >= height * 1.15 ? "right" : "down";
      };

      const runTreeLayout = () => {
        if (!cy) {
          return;
        }

        const rootNode = cy.nodes().filter((node) => node.id() === repoId);

        const layout = cy.layout({
          name: "breadthfirst",
          directed: true,
          roots: rootNode.nonempty() ? rootNode : undefined,
          circle: false,
          spacingFactor: 1.35,
          avoidOverlap: true,
          nodeDimensionsIncludeLabels: true,
          direction: getLayoutDirection(),
          padding: 60,
          animate: true
        });

        try {
          layout.run();
        } catch (error) {
          console.warn("tree layout failed, falling back to fit", error);
          cy.fit(undefined, 60);
        }
      };

      try {
        statusLabel.textContent = "Analyzing";
        setStatus(`Running analysis for <strong>${repoOwner}/${repoName}</strong>...`);

        const analyzeResponse = await fetch(`/analyze/${repoOwner}/${repoName}`, {
          credentials: "same-origin"
        });

        if (!analyzeResponse.ok) {
          throw new Error(`Analyze API returned ${analyzeResponse.status}`);
        }

        statusLabel.textContent = "Loading graph";
        setStatus(`Fetching graph data from <strong>/graph/${repoOwner}/${repoName}</strong>.`);

        const response = await fetch(`/graph/${repoOwner}/${repoName}`, {
          credentials: "same-origin"
        });

        if (!response.ok) {
          throw new Error(`Graph API returned ${response.status}`);
        }

        const payload = await response.json();
        const elements = [
          ...(payload.nodes || []),
          ...(payload.edges || [])
        ];

        nodeCount.textContent = String((payload.nodes || []).length);
        edgeCount.textContent = String((payload.edges || []).length);
        statusLabel.textContent = "Graph loaded";
        setStatus(defaultOverlay(payload.nodes?.length || 0, payload.edges?.length || 0));

        cy = cytoscape({
          container: document.getElementById("graph"),
          elements,
          style: [
            {
              selector: "node",
              style: {
                "label": "data(label)",
                "color": "#e8eef7",
                "text-outline-color": "#07111f",
                "text-outline-width": 2,
                "font-size": 12,
                "background-color": "#6b7a90",
                "border-width": 1,
                "border-color": "rgba(255,255,255,0.15)",
                "width": 34,
                "height": 34,
                "text-valign": "center",
                "text-halign": "center",
                "text-wrap": "ellipsis",
                "text-max-width": 150
              }
            },
            {
              selector: "node[type = 'repository']",
              style: {
                "width": 68,
                "height": 68,
                "background-color": "var(--repo)",
                "shape": "ellipse",
                "border-width": 2,
                "border-color": "rgba(79, 209, 197, 0.85)",
                "font-size": 12,
                "text-wrap": "wrap",
                "text-max-width": 100
              }
            },
            {
              selector: "node[type = 'file']",
              style: {
                "width": 46,
                "height": 32,
                "background-color": "var(--file)",
                "shape": "rectangle"
              }
            },
            {
              selector: "node[type = 'package']",
              style: {
                "width": 58,
                "height": 58,
                "background-color": "data(color)",
                "shape": "hexagon"
              }
            },
            {
              selector: "node[type = 'module']",
              style: {
                "width": 44,
                "height": 44,
                "background-color": "var(--module)",
                "shape": "round-rectangle"
              }
            },
            {
              selector: "node[type = 'symbol']",
              style: {
                "width": 34,
                "height": 34,
                "background-color": "var(--symbol)",
                "shape": "ellipse",
                "font-size": 11
              }
            },
            {
              selector: "node[type = 'function']",
              style: {
                "width": 34,
                "height": 34,
                "background-color": "var(--function)",
                "shape": "ellipse"
              }
            },
            {
              selector: "node[type = 'class']",
              style: {
                "width": 38,
                "height": 38,
                "background-color": "var(--class)",
                "shape": "diamond"
              }
            },
            {
              selector: "node[type = 'api']",
              style: {
                "width": 30,
                "height": 30,
                "background-color": "var(--api)",
                "shape": "octagon"
              }
            },
            {
              selector: "node:parent",
              style: {
                "padding": 34,
                "background-opacity": 0.08,
                "background-color": "#0d1523",
                "border-width": 1,
                "border-color": "rgba(255,255,255,0.14)",
                "text-valign": "top",
                "text-halign": "center",
                "text-wrap": "wrap",
                "text-max-width": 300
              }
            },
            {
              selector: "node[inferred = true]",
              style: {
                "border-style": "dashed",
                "border-width": 2,
                "border-color": "rgba(255,255,255,0.9)"
              }
            },
            {
              selector: "edge",
              style: {
                "width": 1.6,
                "line-color": "rgba(159, 176, 199, 0.42)",
                "target-arrow-color": "rgba(159, 176, 199, 0.42)",
                "target-arrow-shape": "triangle",
                "curve-style": "bezier"
              }
            },
            {
              selector: "edge[relationship = 'CONTAINS']",
              style: {
                "width": 1,
                "line-style": "solid",
                "target-arrow-shape": "none",
                "line-color": "rgba(125, 151, 184, 0.4)"
              }
            },
            {
              selector: "edge[relationship = 'IMPORTS']",
              style: {
                "width": 2,
                "line-style": "solid",
                "line-color": "rgba(91, 140, 255, 0.7)",
                "target-arrow-color": "rgba(91, 140, 255, 0.85)",
                "target-arrow-shape": "triangle"
              }
            },
            {
              selector: "edge[relationship = 'DEFINES']",
              style: {
                "width": 1.5,
                "line-color": "rgba(79, 209, 197, 0.55)",
                "target-arrow-color": "rgba(79, 209, 197, 0.75)",
                "target-arrow-shape": "triangle"
              }
            },
            {
              selector: "edge[relationship = 'CALLS']",
              style: {
                "width": 2.1,
                "line-color": "rgba(56, 211, 159, 0.72)",
                "target-arrow-color": "rgba(56, 211, 159, 0.92)",
                "curve-style": "unbundled-bezier",
                "control-point-distances": 50,
                "control-point-weights": 0.55
              }
            },
            {
              selector: "edge[relationship = 'USES_API']",
              style: {
                "width": 2,
                "line-style": "dashed",
                "line-color": "rgba(255, 111, 177, 0.8)",
                "target-arrow-color": "rgba(255, 111, 177, 0.9)",
                "target-arrow-shape": "triangle"
              }
            },
            {
              selector: "edge[relationship = 'INHERITS']",
              style: {
                "width": 3,
                "line-color": "rgba(178, 108, 255, 0.88)",
                "target-arrow-color": "rgba(178, 108, 255, 0.98)",
                "target-arrow-shape": "triangle"
              }
            }
          ],
          layout: {
            name: "preset"
          }
        });

        hideDetailedNodes();

        const downloadPng = (dataUrlOrBlob, filename) => {
          const link = document.createElement("a");
          link.download = filename;
          link.style.display = "none";

          if (typeof dataUrlOrBlob === "string") {
            link.href = dataUrlOrBlob;
            document.body.appendChild(link);
            link.click();
            link.remove();
            return;
          }

          const objectUrl = URL.createObjectURL(dataUrlOrBlob);
          link.href = objectUrl;
          document.body.appendChild(link);
          link.click();
          link.remove();
          setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
        };

        const applyLayout = () => {
          if (!cy) {
            return;
          }

          try {
            runTreeLayout();
          } catch (layoutError) {
            console.warn("tree relayout failed", layoutError);
            cy.fit(undefined, 60);
          }
        };

        resetLayoutButton.addEventListener("click", () => {
          hideDetailedNodes();
          applyLayout();
          setStatus(defaultOverlay(payload.nodes?.length || 0, payload.edges?.length || 0));
        });

        exportPNGButton.addEventListener("click", async () => {
          try {
            const filename = `${repoOwner}-${repoName}-graph.png`;
            const response = await fetch(`/visualize/${encodeURIComponent(repoOwner)}/${encodeURIComponent(repoName)}/export.png`, {
              credentials: "same-origin"
            });

            if (response.ok) {
              downloadPng(await response.blob(), filename);
              return;
            }

            throw new Error(`Server export returned ${response.status}`);
          } catch (e) {
            try {
              const filename = `${repoOwner}-${repoName}-graph.png`;
              downloadPng(cy.png({ full: true, scale: 2, bg: "#08121f" }), filename);
            } catch (fallbackError) {
              console.error('Failed to export PNG', e, fallbackError);
              alert('Export failed: ' + String(e));
            }
          }
        });

        applyLayout();

        cy.on("tap", "node", (event) => {
          const node = event.target;
          if (node.data('expanded')) {
            collapseNode(node);
          } else {
            expandNode(node);
          }
          setStatus(describeNode(node.data()));
          applyLayout();
        });

        cy.on("mouseover", "node", (event) => {
          setStatus(describeNode(event.target.data()));
        });

        cy.on("mouseout", "node", () => {
          setStatus(defaultOverlay(payload.nodes?.length || 0, payload.edges?.length || 0));
        });
      } catch (error) {
        statusLabel.innerHTML = `<span class="error">Failed to load graph</span>`;
        overlay.innerHTML = `<span class="error">${error.message}</span>`;
      }
    })();
  </script>
</body>
</html>"""
    )

    return (
        page.replace("__REPO_OWNER__", repo_owner)
        .replace("__REPO_NAME__", repo_name)
        .replace("__GITHUB_USER__", github_user)
    )