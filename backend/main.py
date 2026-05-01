import os
from dotenv import load_dotenv
load_dotenv()

# Fix Render's DATABASE_URL format (postgres:// → postgresql://)
db_url = os.getenv("DATABASE_URL", "")
if db_url.startswith("postgres://"):
    os.environ["DATABASE_URL"] = db_url.replace("postgres://", "postgresql://", 1)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware # Added for Flutter connection
from backend.b1_ingestion.routes import router as b1_router
from backend.auth.routes import router as auth_router # Added for Google Auth
from backend.b2_analytics.routes import router as b2_router  # Analytics Engine

# FastAPI() creates the application instance.
# title and version appear in the auto-generated docs page
# at localhost:8000/docs — this is what you show your professor.
app = FastAPI(
    title="Subscription Fatigue Optimizer API",
    version="1.0.0",
    description="DBMS Project — IIIT Allahabad"
)

# CRITICAL: CORS configuration allows your Flutter emulator to communicate with Python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],  
    allow_headers=["*"],  
)

# Auto-initialize database on startup
@app.on_event("startup")
def on_startup():
    from backend.init_db import init_database
    init_database()

# Include all module routers
app.include_router(b1_router)
app.include_router(auth_router) # Included the new auth router
app.include_router(b2_router)   # B2 Analytics Engine

# ── B3 Payment + Virtual Card routes (integrated into main server) ──
from backend.db.connection import run_query
from fastapi import HTTPException
from pydantic import BaseModel
import uuid

class CreateCardRequest(BaseModel):
    user_id: int
    sub_id: int

class SimulatePaymentRequest(BaseModel):
    card_token: str
    amount: float

@app.post("/virtualcard/create", tags=["B3 — Payments"])
def create_virtual_card(req: CreateCardRequest):
    """Create a virtual card for a subscription."""
    try:
        card_number = "VC-" + str(uuid.uuid4())[:12].upper()
        run_query(
            """INSERT INTO Virtual_Cards (user_id, sub_id, card_number, status)
               VALUES (%s, %s, %s, 'active')
               RETURNING card_id, card_number, status""",
            params=(req.user_id, req.sub_id, card_number),
            fetch=True
        )
        # Also link the card to the subscription
        card_rows = run_query(
            "SELECT card_id FROM Virtual_Cards WHERE card_number = %s",
            params=(card_number,)
        )
        if card_rows:
            run_query(
                "UPDATE Subscriptions SET virtual_card_id = %s WHERE sub_id = %s AND user_id = %s",
                params=(card_rows[0]['card_id'], req.sub_id, req.user_id),
                fetch=False
            )
        return {"success": True, "card_number": card_number, "status": "active"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/virtualcards/{user_id}", tags=["B3 — Payments"])
def get_user_cards(user_id: int):
    """Get all virtual cards for a user."""
    try:
        rows = run_query("""
            SELECT vc.card_id, vc.card_number, vc.status, vc.created_at,
                   s.sub_id, sv.service_name, s.detected_cost
            FROM Virtual_Cards vc
            LEFT JOIN Subscriptions s ON vc.sub_id = s.sub_id
            LEFT JOIN Services sv ON s.service_id = sv.service_id
            WHERE vc.user_id = %s
            ORDER BY vc.created_at DESC
        """, params=(user_id,))
        return {"user_id": user_id, "cards": rows}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/virtualcard/{card_id}/freeze", tags=["B3 — Payments"])
def freeze_card(card_id: int):
    """Freeze a virtual card (kill switch)."""
    try:
        result = run_query(
            "UPDATE Virtual_Cards SET status = 'frozen' WHERE card_id = %s RETURNING card_id",
            params=(card_id,),
            fetch=True
        )
        if not result:
            raise HTTPException(status_code=404, detail="Card not found")
        # Also update linked subscription status
        run_query(
            "UPDATE Subscriptions SET status = 'frozen' WHERE virtual_card_id = %s",
            params=(card_id,),
            fetch=False
        )
        return {"success": True, "message": "Card frozen successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/virtualcard/{card_id}/unfreeze", tags=["B3 — Payments"])
def unfreeze_card(card_id: int):
    """Unfreeze a virtual card."""
    try:
        result = run_query(
            "UPDATE Virtual_Cards SET status = 'active' WHERE card_id = %s RETURNING card_id",
            params=(card_id,),
            fetch=True
        )
        if not result:
            raise HTTPException(status_code=404, detail="Card not found")
        run_query(
            "UPDATE Subscriptions SET status = 'active' WHERE virtual_card_id = %s",
            params=(card_id,),
            fetch=False
        )
        return {"success": True, "message": "Card unfrozen successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/virtualcard/{card_id}", tags=["B3 — Payments"])
def cancel_card(card_id: int):
    """Cancel (delete) a virtual card."""
    try:
        # Unlink from subscription first
        run_query(
            "UPDATE Subscriptions SET virtual_card_id = NULL WHERE virtual_card_id = %s",
            params=(card_id,),
            fetch=False
        )
        result = run_query(
            "DELETE FROM Virtual_Cards WHERE card_id = %s RETURNING card_id",
            params=(card_id,),
            fetch=True
        )
        if not result:
            raise HTTPException(status_code=404, detail="Card not found")
        return {"success": True, "message": "Card cancelled and deleted"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/payments/simulate", tags=["B3 — Payments"])
def simulate_payment(req: SimulatePaymentRequest):
    """Simulate a payment charge on a virtual card."""
    try:
        rows = run_query(
            "SELECT status FROM Virtual_Cards WHERE card_number = %s",
            params=(req.card_token,)
        )
        if not rows:
            raise HTTPException(status_code=404, detail="Invalid card token")
        if rows[0]['status'] == 'frozen':
            raise HTTPException(status_code=403, detail="Transaction Blocked: Card is Frozen")
        return {"success": True, "message": f"Successfully charged ₹{req.amount}"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── P2P / Shared Bills routes ──

class CreateBillRequest(BaseModel):
    sub_id: int
    payer_id: int
    debtor_id: int
    amount_owed: float
    due_date: str = None

class SettleBillRequest(BaseModel):
    bill_id: int

@app.get("/p2p/balances/{user_id}", tags=["P2P — Shared Bills"])
def get_p2p_balances(user_id: int):
    """Get all pending P2P balances for a user."""
    try:
        # Money others owe this user
        owes_you = run_query("""
            SELECT sb.bill_id, sb.amount_owed, sb.status, sb.due_date,
                   u.name AS friend_name, u.email AS friend_email,
                   sv.service_name
            FROM Shared_Bills sb
            JOIN Users u ON sb.debtor_id = u.user_id
            LEFT JOIN Subscriptions s ON sb.sub_id = s.sub_id
            LEFT JOIN Services sv ON s.service_id = sv.service_id
            WHERE sb.payer_id = %s AND sb.status = 'pending'
            ORDER BY sb.created_at DESC
        """, params=(user_id,))

        # Money this user owes others
        you_owe = run_query("""
            SELECT sb.bill_id, sb.amount_owed, sb.status, sb.due_date,
                   u.name AS friend_name, u.email AS friend_email,
                   sv.service_name
            FROM Shared_Bills sb
            JOIN Users u ON sb.payer_id = u.user_id
            LEFT JOIN Subscriptions s ON sb.sub_id = s.sub_id
            LEFT JOIN Services sv ON s.service_id = sv.service_id
            WHERE sb.debtor_id = %s AND sb.status = 'pending'
            ORDER BY sb.created_at DESC
        """, params=(user_id,))

        total_owed_to_you = sum(float(r['amount_owed']) for r in owes_you) if owes_you else 0
        total_you_owe = sum(float(r['amount_owed']) for r in you_owe) if you_owe else 0

        return {
            "user_id": user_id,
            "owes_you": owes_you,
            "you_owe": you_owe,
            "total_owed_to_you": total_owed_to_you,
            "total_you_owe": total_you_owe,
            "net_balance": total_owed_to_you - total_you_owe
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/p2p/create", tags=["P2P — Shared Bills"])
def create_shared_bill(req: CreateBillRequest):
    """Create a new shared bill / P2P request."""
    try:
        run_query(
            """INSERT INTO Shared_Bills (sub_id, payer_id, debtor_id, amount_owed, due_date, status)
               VALUES (%s, %s, %s, %s, %s, 'pending')""",
            params=(req.sub_id, req.payer_id, req.debtor_id, req.amount_owed, req.due_date),
            fetch=False
        )
        return {"success": True, "message": "Shared bill created"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/p2p/settle", tags=["P2P — Shared Bills"])
def settle_bill(req: SettleBillRequest):
    """Settle a pending shared bill."""
    try:
        result = run_query(
            """UPDATE Shared_Bills SET status = 'settled', settled_at = NOW()
               WHERE bill_id = %s AND status = 'pending'
               RETURNING bill_id""",
            params=(req.bill_id,),
            fetch=True
        )
        if not result:
            raise HTTPException(status_code=404, detail="Bill not found or already settled")
        return {"success": True, "message": "Bill settled successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/p2p/history/{user_id}", tags=["P2P — Shared Bills"])
def get_p2p_history(user_id: int):
    """Get all P2P transaction history (settled + pending)."""
    try:
        rows = run_query("""
            SELECT sb.bill_id, sb.amount_owed, sb.status, sb.due_date, sb.settled_at,
                   payer.name AS payer_name, debtor.name AS debtor_name,
                   sv.service_name,
                   CASE WHEN sb.payer_id = %s THEN 'sent' ELSE 'received' END AS direction
            FROM Shared_Bills sb
            JOIN Users payer ON sb.payer_id = payer.user_id
            JOIN Users debtor ON sb.debtor_id = debtor.user_id
            LEFT JOIN Subscriptions s ON sb.sub_id = s.sub_id
            LEFT JOIN Services sv ON s.service_id = sv.service_id
            WHERE sb.payer_id = %s OR sb.debtor_id = %s
            ORDER BY sb.created_at DESC
            LIMIT 50
        """, params=(user_id, user_id, user_id))
        return {"user_id": user_id, "history": rows}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Groups routes ──

# Create groups table if it doesn't exist
try:
    run_query("""
        CREATE TABLE IF NOT EXISTS Subscription_Groups (
            group_id     SERIAL PRIMARY KEY,
            name         VARCHAR(100) NOT NULL,
            invite_code  VARCHAR(10) UNIQUE NOT NULL,
            sub_id       INT REFERENCES Subscriptions(sub_id),
            creator_id   INT NOT NULL REFERENCES Users(user_id),
            created_at   TIMESTAMP DEFAULT NOW()
        )
    """, fetch=False)
    run_query("""
        CREATE TABLE IF NOT EXISTS Group_Members (
            id         SERIAL PRIMARY KEY,
            group_id   INT NOT NULL REFERENCES Subscription_Groups(group_id) ON DELETE CASCADE,
            user_id    INT NOT NULL REFERENCES Users(user_id),
            joined_at  TIMESTAMP DEFAULT NOW(),
            UNIQUE(group_id, user_id)
        )
    """, fetch=False)
except:
    pass  # tables already exist

import random
import string

def _gen_invite_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))


@app.get("/groups/{user_id}", tags=["Groups"])
def get_user_groups(user_id: int):
    """Get groups the user belongs to."""
    try:
        rows = run_query("""
            SELECT sg.group_id, sg.name, sg.invite_code, sg.sub_id,
                   sv.service_name, sv.category, s.detected_cost,
                   (SELECT COUNT(*) FROM Group_Members gm WHERE gm.group_id = sg.group_id) AS member_count
            FROM Group_Members gm
            JOIN Subscription_Groups sg ON gm.group_id = sg.group_id
            LEFT JOIN Subscriptions s ON sg.sub_id = s.sub_id
            LEFT JOIN Services sv ON s.service_id = sv.service_id
            WHERE gm.user_id = %s
            ORDER BY sg.created_at DESC
        """, params=(user_id,))
        return {"user_id": user_id, "groups": rows}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class CreateGroupRequest(BaseModel):
    name: str
    creator_id: int
    sub_id: int

@app.post("/groups/create", tags=["Groups"])
def create_group(req: CreateGroupRequest):
    """Create a new group with an invite code."""
    try:
        invite_code = _gen_invite_code()
        run_query(
            """INSERT INTO Subscription_Groups (name, invite_code, sub_id, creator_id)
               VALUES (%s, %s, %s, %s)""",
            params=(req.name, invite_code, req.sub_id, req.creator_id),
            fetch=False
        )
        # Get the created group
        group_rows = run_query(
            "SELECT group_id FROM Subscription_Groups WHERE invite_code = %s",
            params=(invite_code,)
        )
        if group_rows:
            # Add creator as first member
            run_query(
                "INSERT INTO Group_Members (group_id, user_id) VALUES (%s, %s)",
                params=(group_rows[0]['group_id'], req.creator_id),
                fetch=False
            )
        return {"success": True, "invite_code": invite_code, "name": req.name}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class JoinGroupRequest(BaseModel):
    invite_code: str
    user_id: int

@app.post("/groups/join", tags=["Groups"])
def join_group(req: JoinGroupRequest):
    """Join a group using an invite code."""
    try:
        group_rows = run_query(
            "SELECT group_id, name FROM Subscription_Groups WHERE invite_code = %s",
            params=(req.invite_code,)
        )
        if not group_rows:
            raise HTTPException(status_code=404, detail="Invalid invite code")

        group_id = group_rows[0]['group_id']
        group_name = group_rows[0]['name']

        # Check if already a member
        existing = run_query(
            "SELECT id FROM Group_Members WHERE group_id = %s AND user_id = %s",
            params=(group_id, req.user_id)
        )
        if existing:
            return {"success": True, "message": "Already a member", "group_name": group_name}

        run_query(
            "INSERT INTO Group_Members (group_id, user_id) VALUES (%s, %s)",
            params=(group_id, req.user_id),
            fetch=False
        )
        return {"success": True, "message": f"Joined '{group_name}' successfully!", "group_name": group_name}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Subscription direct freeze/unfreeze (no card needed) ──

class SubFreezeRequest(BaseModel):
    user_id: int

@app.post("/subscription/{sub_id}/freeze", tags=["B3 — Payments"])
def freeze_subscription(sub_id: int, req: SubFreezeRequest):
    """Directly freeze a subscription in the database."""
    try:
        result = run_query(
            "UPDATE Subscriptions SET status = 'frozen' WHERE sub_id = %s AND user_id = %s RETURNING sub_id",
            params=(sub_id, req.user_id),
            fetch=True
        )
        if not result:
            raise HTTPException(status_code=404, detail="Subscription not found")
        return {"success": True, "message": "Subscription frozen"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/subscription/{sub_id}/unfreeze", tags=["B3 — Payments"])
def unfreeze_subscription(sub_id: int, req: SubFreezeRequest):
    """Directly unfreeze a subscription in the database."""
    try:
        result = run_query(
            "UPDATE Subscriptions SET status = 'active' WHERE sub_id = %s AND user_id = %s RETURNING sub_id",
            params=(sub_id, req.user_id),
            fetch=True
        )
        if not result:
            raise HTTPException(status_code=404, detail="Subscription not found")
        return {"success": True, "message": "Subscription unfrozen"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── C++ Settlement Engine Integration ──
# Uses the compiled pybind11 module for Minimum Cash Flow optimization

import sys as _sys
import os as _os
_cpp_path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "cpp_engine-P2P")
if _cpp_path not in _sys.path:
    _sys.path.insert(0, _cpp_path)

from settlement_wrapper import settle_debts_as_dicts, CPP_AVAILABLE

@app.get("/settlement/engine-status", tags=["C++ Engine"])
def settlement_engine_status():
    """Check if the C++ settlement engine is loaded."""
    return {
        "cpp_engine_loaded": CPP_AVAILABLE,
        "engine": "C++ pybind11 (O3 optimized)" if CPP_AVAILABLE else "Python fallback",
        "algorithm": "Minimum Cash Flow — Greedy"
    }


@app.get("/settlement/optimize/{group_id}", tags=["C++ Engine"])
def optimize_group_settlement(group_id: int):
    """
    Fetches group members + subscription cost, calculates each member's
    share, then runs the C++ Minimum Cash Flow algorithm to produce
    the minimum number of transactions to settle all debts.
    
    Flow:
      1. Get group details (subscription cost, creator)
      2. Get all members
      3. Calculate per-person share = total_cost / member_count
      4. Creator paid full amount → positive balance
      5. Others owe their share → negative balance
      6. Feed into C++ engine → optimal transactions
    """
    try:
        # Get group with linked subscription cost
        group_rows = run_query("""
            SELECT sg.group_id, sg.name, sg.creator_id, sg.sub_id,
                   COALESCE(s.detected_cost, 0) as total_cost,
                   u.name as creator_name
            FROM Subscription_Groups sg
            LEFT JOIN Subscriptions s ON sg.sub_id = s.sub_id
            LEFT JOIN Users u ON sg.creator_id = u.user_id
            WHERE sg.group_id = %s
        """, params=(group_id,))

        if not group_rows:
            raise HTTPException(status_code=404, detail="Group not found")

        group = group_rows[0]
        total_cost = float(group['total_cost'])
        creator_id = group['creator_id']
        creator_name = group['creator_name'] or f"User {creator_id}"

        # Get all members
        members = run_query("""
            SELECT gm.user_id, u.name
            FROM Group_Members gm
            JOIN Users u ON gm.user_id = u.user_id
            WHERE gm.group_id = %s
        """, params=(group_id,))

        # Include creator if not already in members list
        member_ids = {m['user_id'] for m in members}
        if creator_id not in member_ids:
            members.insert(0, {"user_id": creator_id, "name": creator_name})

        member_count = len(members)
        if member_count <= 1:
            return {
                "group_id": group_id,
                "group_name": group['name'],
                "total_cost": total_cost,
                "member_count": member_count,
                "per_person_share": total_cost,
                "transactions": [],
                "message": "Only one member — no settlements needed."
            }

        per_person = round(total_cost / member_count, 2)

        # Build net balances: creator is owed, others owe
        net_balances = {}
        for m in members:
            name = m['name'] or f"User {m['user_id']}"
            if m['user_id'] == creator_id:
                # Creator paid full, is owed (total - their share)
                net_balances[name] = round(total_cost - per_person, 2)
            else:
                # Others owe their share (negative balance)
                net_balances[name] = round(-per_person, 2)

        # Run C++ Minimum Cash Flow algorithm
        transactions = settle_debts_as_dicts(net_balances)

        return {
            "group_id": group_id,
            "group_name": group['name'],
            "total_cost": total_cost,
            "member_count": member_count,
            "per_person_share": per_person,
            "engine": "C++ pybind11" if CPP_AVAILABLE else "Python fallback",
            "net_balances": net_balances,
            "transactions": transactions,
            "message": f"Optimized into {len(transactions)} transaction(s) using Minimum Cash Flow algorithm."
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/")
def root():
    
    return {
        "status": "Subscription Optimizer API is running",
        "docs": "Visit /docs for interactive API documentation"
    }

@app.get("/health")
def health():
    
    """
    Health check endpoint.
    Why does this exist?
    In production, monitoring tools ping /health every 30 seconds.
    If it stops responding, alerts fire and the server restarts.
    Standard practice for any production API.
    """
    from backend.db.connection import run_query
    try:
        run_query("SELECT 1")
        db_status = "connected"
    except:
        db_status = "disconnected"

    return {
        "api": "running",
        "database": db_status
    }