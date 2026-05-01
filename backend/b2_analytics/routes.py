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
# Detects overlapping subscriptions using PostgreSQL
# ──────────────────────────────────────────────────────────────
@router.get("/redundancy/{user_id}")
def get_redundancy_analysis(user_id: int):
    """
    Detects redundant/overlapping subscriptions within the same
    category using PostgreSQL GROUP BY. No Neo4j needed.
    """
    try:
        # Find categories with 2+ active subscriptions
        rows = run_query("""
            SELECT s2.category,
                   COUNT(*) as service_count,
                   SUM(s.detected_cost) as total_cost,
                   json_agg(json_build_object(
                       'name', s2.service_name,
                       'cost', s.detected_cost,
                       'usage_count', 0
                   )) as services
            FROM Subscriptions s
            JOIN Services s2 ON s.service_id = s2.service_id
            WHERE s.user_id = %s AND s.status = 'active'
            GROUP BY s2.category
            HAVING COUNT(*) >= 2
            ORDER BY SUM(s.detected_cost) DESC
        """, params=(user_id,))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB error: {str(e)}")

    if not rows:
        return {
            "user_id": user_id,
            "has_redundancy": False,
            "overlaps": [],
            "total_potential_savings": 0
        }

    overlaps = []
    total_savings = 0
    for row in rows:
        services = row['services'] if isinstance(row['services'], list) else []
        # Find most used service (keep it, cancel others)
        most_used = max(services, key=lambda s: s.get('usage_count', 0)) if services else None
        cheapest_cost = min(s['cost'] for s in services) if services else 0
        total_cat_cost = sum(s['cost'] for s in services)
        savings = total_cat_cost - cheapest_cost

        overlaps.append({
            "category": row['category'],
            "overlap_count": row['service_count'],
            "total_cost": total_cat_cost,
            "services": services,
            "most_used_service": most_used['name'] if most_used else None,
            "potential_savings": savings,
            "recommendation": f"You have {row['service_count']} {row['category']} services. "
                            f"Keep {most_used['name'] if most_used else 'one'} and save ₹{savings:.0f}/mo."
        })
        total_savings += savings

    return {
        "user_id": user_id,
        "has_redundancy": True,
        "overlaps": overlaps,
        "total_potential_savings": total_savings
    }


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
# Returns graph data built from PostgreSQL (no Neo4j needed)
# ──────────────────────────────────────────────────────────────
@router.get("/graph/{user_id}")
def get_graph_data(user_id: int):
    """
    Builds a knowledge graph structure from PostgreSQL data.
    Returns nodes (user, services, categories) and edges
    for frontend visualization.
    """
    try:
        # Get user info
        users = run_query("SELECT user_id, name FROM Users WHERE user_id = %s", params=(user_id,))
        user_name = users[0]['name'] if users else f"User {user_id}"

        # Get subscriptions with service details
        subs = run_query("""
            SELECT s.sub_id, s.detected_cost, s.status,
                   s2.service_name, s2.category, s2.service_id
            FROM Subscriptions s
            JOIN Services s2 ON s.service_id = s2.service_id
            WHERE s.user_id = %s
            ORDER BY s2.category, s2.service_name
        """, params=(user_id,))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB error: {str(e)}")

    nodes = []
    edges = []

    # User node
    user_node_id = f"user_{user_id}"
    nodes.append({"id": user_node_id, "label": user_name, "type": "user"})

    # Track categories to avoid duplicates
    categories_added = set()

    for sub in subs:
        service_id = f"svc_{sub['service_id']}"
        category_id = f"cat_{sub['category']}"

        # Service node
        nodes.append({
            "id": service_id,
            "label": sub['service_name'],
            "type": "service",
            "cost": float(sub['detected_cost']) if sub['detected_cost'] else 0
        })

        # Category node (only once per category)
        if sub['category'] not in categories_added:
            nodes.append({"id": category_id, "label": sub['category'], "type": "category"})
            categories_added.add(sub['category'])

        # User → Service edge
        edges.append({
            "from": user_node_id,
            "to": service_id,
            "label": "SUBSCRIBED_TO",
            "cost": float(sub['detected_cost']) if sub['detected_cost'] else 0,
            "status": sub['status'],
            "usage": 0
        })

        # Service → Category edge
        edges.append({
            "from": service_id,
            "to": category_id,
            "label": "BELONGS_TO"
        })

    return {
        "user_id": user_id,
        "graph": {
            "nodes": nodes,
            "edges": edges
        }
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