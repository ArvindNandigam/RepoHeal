import asyncio
from io import BytesIO


NODE_COLORS = {
    "repository": "#4fd1c5",
    "file": "#5b8cff",
    "package": "#ef5350",
    "module": "#ff9f43",
    "symbol": "#95a3b3",
    "function": "#38d39f",
    "class": "#b26cff",
    "api": "#ff6fb1",
}


def _build_networkx_png(graph: dict) -> bytes:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import networkx as nx
    except Exception as error:
        raise RuntimeError("Python graph rendering requires networkx and matplotlib: " + str(error))

    nodes = graph.get("nodes", []) or []
    edges = graph.get("edges", []) or []

    node_map = {}
    for node in nodes:
        data = node.get("data", {})
        node_id = data.get("id")
        if not node_id:
            continue
        node_map[node_id] = data

    graph_nx = nx.DiGraph()
    for node_id, data in node_map.items():
        graph_nx.add_node(
            node_id,
            label=data.get("label", node_id),
            type=data.get("type", "symbol"),
            parent=data.get("parent"),
            depth=data.get("depth"),
        )

    for edge in edges:
        data = edge.get("data", {})
        source = data.get("source")
        target = data.get("target")
        if source and target and source in graph_nx and target in graph_nx:
            graph_nx.add_edge(source, target, relationship=data.get("relationship", "LINK"))

    if graph_nx.number_of_nodes() == 0:
        raise RuntimeError("Graph payload did not contain any nodes")

    def _hierarchical_positions(root_id: str, direction: str = "down") -> dict:
        children = {}
        for node_id, data in graph_nx.nodes(data=True):
            parent_id = data.get("parent")
            if parent_id and parent_id in graph_nx:
                children.setdefault(parent_id, []).append(node_id)

        for node_id in children:
            children[node_id].sort(key=lambda child_id: (
                graph_nx.nodes[child_id].get("type", "symbol"),
                graph_nx.nodes[child_id].get("label", child_id)
            ))

        subtree_widths = {}

        def measure(node_id: str) -> float:
            node_children = children.get(node_id, [])
            if not node_children:
                subtree_widths[node_id] = 1.0
                return 1.0

            total = 0.0
            for index, child_id in enumerate(node_children):
                total += measure(child_id)
                if index < len(node_children) - 1:
                    total += 0.35

            subtree_widths[node_id] = max(1.0, total)
            return subtree_widths[node_id]

        measure(root_id)

        positions = {}
        level_gap = 1.9
        sibling_gap = 0.35

        def assign(node_id: str, left: float, depth: int) -> None:
            width = subtree_widths.get(node_id, 1.0)
            x_center = left + width / 2.0
            y_value = -depth * level_gap

            if direction == "right":
                positions[node_id] = (depth * level_gap, x_center)
            else:
                positions[node_id] = (x_center, y_value)

            cursor = left
            for index, child_id in enumerate(children.get(node_id, [])):
                child_width = subtree_widths.get(child_id, 1.0)
                assign(child_id, cursor, depth + 1)
                cursor += child_width
                if index < len(children.get(node_id, [])) - 1:
                    cursor += sibling_gap

        assign(root_id, 0.0, 0)
        return positions

    root_id = None
    for node_id, data in graph_nx.nodes(data=True):
        if data.get("type") == "repository":
            root_id = node_id
            break

    if root_id is None:
        root_id = next(iter(graph_nx.nodes))

    node_count = graph_nx.number_of_nodes()
    figure_width = max(14, min(30, node_count * 0.42))
    figure_height = max(10, min(22, node_count * 0.28))
    direction = "right" if figure_width > figure_height * 1.15 else "down"
    positions = _hierarchical_positions(root_id, direction=direction)

    figure, axis = plt.subplots(figsize=(figure_width, figure_height), dpi=180)
    figure.patch.set_facecolor("#08121f")
    axis.set_facecolor("#08121f")

    node_groups = {}
    for node_id, data in graph_nx.nodes(data=True):
        node_type = data.get("type", "symbol")
        node_groups.setdefault(node_type, []).append(node_id)

    for node_type, group in node_groups.items():
        color = NODE_COLORS.get(node_type, "#6b7a90")
        size = 1300 if node_type == "repository" else 900 if node_type in {"package", "module"} else 650 if node_type in {"file", "function", "class"} else 420
        nx.draw_networkx_nodes(
            graph_nx,
            positions,
            nodelist=group,
            node_color=color,
            node_size=size,
            alpha=0.95,
            linewidths=1.1,
            edgecolors="#e8eef7",
            ax=axis,
        )

    edge_colors = []
    edge_widths = []
    for source, target, data in graph_nx.edges(data=True):
        relationship = data.get("relationship", "LINK")
        if relationship == "CONTAINS":
            edge_colors.append("#7d97b8")
            edge_widths.append(0.8)
        elif relationship == "IMPORTS":
            edge_colors.append("#5b8cff")
            edge_widths.append(1.5)
        elif relationship == "DEFINES":
            edge_colors.append("#4fd1c5")
            edge_widths.append(1.2)
        elif relationship == "USES_API":
            edge_colors.append("#ff6fb1")
            edge_widths.append(1.1)
        elif relationship == "CALLS":
            edge_colors.append("#b26cff")
            edge_widths.append(1.2)
        else:
            edge_colors.append("#9fb0c7")
            edge_widths.append(0.9)

    nx.draw_networkx_edges(
        graph_nx,
        positions,
        edge_color=edge_colors,
        width=edge_widths,
        arrows=True,
        arrowsize=12,
        arrowstyle="-|>",
        alpha=0.42,
        connectionstyle="arc3,rad=0.07",
        ax=axis,
    )

    labels = {node_id: data.get("label", node_id) for node_id, data in graph_nx.nodes(data=True)}
    nx.draw_networkx_labels(
        graph_nx,
        positions,
        labels=labels,
        font_size=7,
        font_color="#edf4fb",
        bbox={"facecolor": "#08121f", "edgecolor": "none", "alpha": 0.0},
        ax=axis,
    )

    axis.axis("off")
    figure.tight_layout(pad=1.0)

    buffer = BytesIO()
    figure.savefig(buffer, format="png", facecolor=figure.get_facecolor(), bbox_inches="tight")
    plt.close(figure)
    buffer.seek(0)
    return buffer.getvalue()


async def render_graph_png(graph: dict, timeout: int = 10000) -> bytes:
    try:
        return await asyncio.to_thread(_build_networkx_png, graph)
    except Exception as primary_error:
        try:
            from playwright.async_api import async_playwright
        except Exception:
            raise RuntimeError("Python graph rendering failed: " + str(primary_error))

        import base64
        import json

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

        payload_json = json.dumps(graph)
        html = template.replace("__PAYLOAD__", payload_json)

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
