"""
routes.py — FastAPI Router for the B2 Analytics Engine
Endpoints:
  GET /analytics/fatigue/{user_id}      → per-subscription fatigue scores
  GET /analytics/ghosts/{user_id}       → ghost/zombie subscription list
  GET /analytics/redundancy/{user_id}   → knowledge graph overlap analysis
  GET /analytics/report/{user_id}       → monthly spending report by category
  GET /analytics/graph/{user_id}        → full graph data for visualization
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from backend.db.connection import run_query
from backend.b2_analytics.graph_builder import (
    calculate_redundancy,
    get_full_graph,
    sync_user_graph
)

router = APIRouter(
    prefix="/analytics",
    tags=["B2 — Analytics Engine"]
)


# ──────────────────────────────────────────────────────────────
# GET /analytics/fatigue/{user_id}
# Calls the GenerateFatigueScore stored procedure
# ──────────────────────────────────────────────────────────────
@router.get("/fatigue/{user_id}")
def get_fatigue_scores(user_id: int):
    """
    Returns a fatigue score for each of the user's active
    subscriptions. Higher score = more wasteful.
    This calls the PostgreSQL stored function directly.
    """
    try:
        rows = run_query(
            "SELECT * FROM GenerateFatigueScore(%s)",
            params=(user_id,)
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB error: {str(e)}")

    if not rows:
        return {
            "user_id": user_id,
            "message": "No active subscriptions found for this user.",
            "scores": []
        }

    # Calculate aggregate stats
    total_monthly = sum(float(r["monthly_cost"]) for r in rows)
    avg_fatigue = sum(float(r["fatigue_score"]) for r in rows) / len(rows)
    ghost_count = sum(1 for r in rows if r["usage_count"] == 0)

    return {
        "user_id": user_id,
        "total_monthly_spend": total_monthly,
        "average_fatigue_score": round(avg_fatigue, 2),
        "active_subscriptions": len(rows),
        "ghost_subscriptions": ghost_count,
        "scores": rows
    }


# ──────────────────────────────────────────────────────────────
# GET /analytics/ghosts/{user_id}
# Queries the ghost_subscriptions_view
# ──────────────────────────────────────────────────────────────
@router.get("/ghosts/{user_id}")
def get_ghost_subscriptions(user_id: int):
    """
    Returns all ghost (zombie) subscriptions for a user.
    A ghost subscription is one the user pays for but doesn't use.
    """
    try:
        rows = run_query(
            "SELECT * FROM ghost_subscriptions_view WHERE user_id = %s",
            params=(user_id,)
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB error: {str(e)}")

    total_ghost_cost = sum(float(r["detected_cost"]) for r in rows) if rows else 0

    return {
        "user_id": user_id,
        "ghost_count": len(rows),
        "total_monthly_waste": total_ghost_cost,
        "message": (
            f"You have {len(rows)} ghost subscription(s) costing ₹{total_ghost_cost:.0f}/mo. "
            "These are services you pay for but don't actively use."
            if rows else
            "No ghost subscriptions detected. You're using all your services!"
        ),
        "ghosts": rows
    }


# ──────────────────────────────────────────────────────────────
# GET /analytics/redundancy/{user_id}
# Uses Neo4j Knowledge Graph for overlap detection
# ──────────────────────────────────────────────────────────────
@router.get("/redundancy/{user_id}")
def get_redundancy_analysis(user_id: int):
    """
    Analyzes the user's subscription graph in Neo4j to detect
    redundant/overlapping subscriptions within the same category.
    Example output:
      "You have 3 Streaming services (Netflix, Amazon Prime,
       Disney+) costing ₹1247/mo. Consider keeping only Netflix
       to save ₹598/mo."
    """
    try:
        result = calculate_redundancy(user_id)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Knowledge Graph error: {str(e)}. Is Neo4j running?"
        )

    return result


# ──────────────────────────────────────────────────────────────
# GET /analytics/report/{user_id}
# Calls GenerateMonthlyReport stored procedure
# ──────────────────────────────────────────────────────────────
@router.get("/report/{user_id}")
def get_monthly_report(user_id: int):
    """
    Returns a comprehensive monthly spending report grouped
    by service category, including ghost counts and savings.
    """
    try:
        rows = run_query(
            "SELECT * FROM GenerateMonthlyReport(%s)",
            params=(user_id,)
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB error: {str(e)}")

    if not rows:
        return {
            "user_id": user_id,
            "message": "No active subscriptions to report on.",
            "categories": [],
            "summary": {}
        }

    total_spend = sum(float(r["total_category_cost"]) for r in rows)
    total_savings = sum(float(r["potential_savings"]) for r in rows)
    total_subs = sum(int(r["service_count"]) for r in rows)
    total_ghosts = sum(int(r["ghost_count"]) for r in rows)

    return {
        "user_id": user_id,
        "categories": rows,
        "summary": {
            "total_monthly_spend": total_spend,
            "total_potential_savings": total_savings,
            "total_active_subscriptions": total_subs,
            "total_ghost_subscriptions": total_ghosts,
            "savings_percentage": round(
                (total_savings / total_spend * 100) if total_spend > 0 else 0, 1
            )
        }
    }


# ──────────────────────────────────────────────────────────────
# GET /analytics/graph/{user_id}
# Returns graph data for frontend visualization (D3/vis.js)
# ──────────────────────────────────────────────────────────────
@router.get("/graph/{user_id}")
def get_graph_data(user_id: int):
    """
    Returns the full knowledge graph structure (nodes + edges)
    for a user's subscriptions. Designed for rendering with
    D3.js or vis.js on the frontend.
    """
    try:
        graph = get_full_graph(user_id)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Knowledge Graph error: {str(e)}. Is Neo4j running?"
        )

    return {
        "user_id": user_id,
        "graph": graph
    }


# ──────────────────────────────────────────────────────────────
# GET /analytics/graph/{user_id}/view
# Returns an interactive HTML visualization of the knowledge graph
# ──────────────────────────────────────────────────────────────
@router.get("/graph/{user_id}/view", response_class=HTMLResponse)
def view_graph_visualization(user_id: int):
    """
    Renders an interactive vis.js network diagram of the user's
    Knowledge Graph directly in the browser.
    """
    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Subscription Knowledge Graph</title>
        <script type="text/javascript" src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
        <style type="text/css">
            body {{ font-family: sans-serif; background-color: #f8f9fa; padding: 20px; }}
            #mynetwork {{
                width: 100%;
                height: 800px;
                border: 1px solid #ddd;
                background-color: white;
                border-radius: 8px;
                box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            }}
            .header {{ text-align: center; margin-bottom: 20px; }}
        </style>
    </head>
    <body>
        <div class="header">
            <h2>Subscription Topology (User {user_id})</h2>
            <p>Interactive Knowledge Graph powered by Neo4j</p>
        </div>
        <div id="mynetwork"></div>
        <script type="text/javascript">
            // Fetch graph data from our API
            fetch('/analytics/graph/{user_id}')
                .then(response => response.json())
                .then(data => {{
                    const graphData = data.graph;
                    
                    // Transform api nodes to vis.js format
                    const nodes = new vis.DataSet(
                        graphData.nodes.map(n => {{
                            let color = "#97C2FC";
                            let shape = "ellipse";
                            
                            if (n.type === 'user') {{
                                color = "#fb7e81";
                                shape = "box";
                            }} else if (n.type === 'category') {{
                                color = "#7BE141";
                                shape = "circle";
                            }}
                            
                            return {{
                                id: n.id,
                                label: n.label + (n.cost ? "\\n₹" + n.cost : ""),
                                color: color,
                                shape: shape,
                                font: {{ multi: 'md', face: 'georgia' }}
                            }};
                        }})
                    );
                    // Transform api edges to vis.js format
                    const edges = new vis.DataSet(
                        graphData.edges.map(e => ({{
                            from: e.from,
                            to: e.to,
                            label: e.label,
                            arrows: 'to',
                            font: {{ align: 'middle' }}
                        }}))
                    );
                    // Provide the data in the vis format
                    const networkData = {{
                        nodes: nodes,
                        edges: edges
                    }};
                    
                    const options = {{
                        physics: {{
                            stabilization: false,
                            barnesHut: {{
                                gravitationalConstant: -8000,
                                springConstant: 0.04,
                                springLength: 95
                            }}
                        }},
                        interaction: {{ hover: true }},
                        nodes: {{
                            borderWidth: 2,
                            shadow: true
                        }},
                        edges: {{
                            width: 2,
                            shadow: true,
                            smooth: {{ type: 'continuous' }}
                        }}
                    }};
                    // Initialize the network!
                    const container = document.getElementById('mynetwork');
                    new vis.Network(container, networkData, options);
                }})
                .catch(err => console.error("Error loading graph:", err));
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)