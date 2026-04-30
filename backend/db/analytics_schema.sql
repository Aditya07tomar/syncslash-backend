-- ============================================================
-- Analytics Engine (B2) — Stored Procedures, Functions & Views
-- Owner: Analytics Engine Team
-- ============================================================

-- ============================================================
-- VIEW: ghost_subscriptions_view
-- Purpose: Identifies "ghost" subscriptions — services a user
--          is paying for but NOT actively using.
--
-- Logic:
--   A subscription is a "ghost" if:
--     1. It is marked 'active' in the Subscriptions table, AND
--     2. The user has NEVER used it (usage_count = 0), OR
--     3. The user hasn't used it in the last 30 days.
--
-- Why a VIEW and not a stored procedure?
--   Views are queryable like tables — B2 routes can SELECT from
--   this directly, and other team members (B1, B3) can also
--   reference it without calling a function. It's also composable:
--   you can JOIN ghost_subscriptions_view with other tables.
-- ============================================================
CREATE OR REPLACE VIEW ghost_subscriptions_view AS
SELECT
    s.sub_id,
    s.user_id,
    s.service_id,
    sv.service_name,
    sv.category,
    s.detected_cost,
    s.billing_cycle,
    s.next_renewal,
    s.status,

    -- Pull in usage metrics from User_Subscription_Mapping
    COALESCE(usm.usage_count, 0)  AS usage_count,
    usm.last_used_at,

    -- Calculate days since last use (NULL if never used)
    CASE
        WHEN usm.last_used_at IS NULL THEN NULL
        ELSE EXTRACT(DAY FROM NOW() - usm.last_used_at)::INT
    END AS days_since_last_use,

    -- Ghost classification reason
    CASE
        WHEN COALESCE(usm.usage_count, 0) = 0
            THEN 'never_used'
        WHEN usm.last_used_at < NOW() - INTERVAL '30 days'
            THEN 'inactive_30_days'
        ELSE 'active'
    END AS ghost_reason

FROM Subscriptions s
JOIN Services sv ON s.service_id = sv.service_id
LEFT JOIN User_Subscription_Mapping usm
    ON s.sub_id = usm.sub_id AND s.user_id = usm.user_id
WHERE
    s.status = 'active'
    AND (
        -- Condition 1: no mapping row at all, or usage_count is 0
        usm.mapping_id IS NULL
        OR COALESCE(usm.usage_count, 0) = 0
        -- Condition 2: last used more than 30 days ago
        OR usm.last_used_at < NOW() - INTERVAL '30 days'
    );


-- ============================================================
-- FUNCTION: GenerateFatigueScore
-- Purpose: For a given user, calculates a per-subscription
--          "fatigue score" indicating waste.
--
-- Formula:
--   FatigueScore = monthly_cost / GREATEST(usage_count, 0.1)
--
-- Interpretation:
--   - High score → paying a lot relative to usage (wasteful)
--   - Low score  → good value for money
--   - Score with usage_count = 0 → maximum fatigue (cost / 0.1)
--
-- Returns a TABLE so the caller gets one row per subscription
-- with the score, cost, usage, and a human-readable verdict.
-- ============================================================
CREATE OR REPLACE FUNCTION GenerateFatigueScore(p_user_id INT)
RETURNS TABLE (
    sub_id          INT,
    service_name    VARCHAR(100),
    category        VARCHAR(50),
    monthly_cost    NUMERIC(10,2),
    usage_count     INT,
    days_since_use  INT,
    fatigue_score   NUMERIC(10,2),
    verdict         TEXT
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        s.sub_id,
        sv.service_name,
        sv.category,
        s.detected_cost                                     AS monthly_cost,
        COALESCE(usm.usage_count, 0)                        AS usage_count,

        -- Days since last use (NULL → never used, coalesce to 9999)
        CASE
            WHEN usm.last_used_at IS NULL THEN 9999
            ELSE EXTRACT(DAY FROM NOW() - usm.last_used_at)::INT
        END                                                 AS days_since_use,

        -- The fatigue formula
        ROUND(
            s.detected_cost / GREATEST(COALESCE(usm.usage_count, 0)::NUMERIC, 0.1),
            2
        )                                                   AS fatigue_score,

        -- Human-readable verdict based on thresholds
        CASE
            WHEN COALESCE(usm.usage_count, 0) = 0
                THEN '🔴 Ghost Sub — you are paying but NEVER using this'
            WHEN s.detected_cost / GREATEST(COALESCE(usm.usage_count, 0)::NUMERIC, 0.1) > 500
                THEN '🟠 High Fatigue — consider cancelling'
            WHEN s.detected_cost / GREATEST(COALESCE(usm.usage_count, 0)::NUMERIC, 0.1) > 100
                THEN '🟡 Moderate Fatigue — watch your usage'
            ELSE '🟢 Good Value — this subscription is worth it'
        END                                                 AS verdict

    FROM Subscriptions s
    JOIN Services sv         ON s.service_id = sv.service_id
    LEFT JOIN User_Subscription_Mapping usm
        ON s.sub_id = usm.sub_id AND s.user_id = usm.user_id
    WHERE
        s.user_id = p_user_id
        AND s.status = 'active'
    ORDER BY fatigue_score DESC;
END;
$$ LANGUAGE plpgsql;


-- ============================================================
-- FUNCTION: GenerateMonthlyReport
-- Purpose: Returns a comprehensive monthly spending report for
--          a user, grouped by service category.
--
-- Includes:
--   - Total monthly spend
--   - Spend per category (Streaming, Music, etc.)
--   - Number of active vs ghost subscriptions
--   - Total potential savings (sum of ghost sub costs)
--
-- Why a function and not a view?
--   Views cannot accept parameters. We need p_user_id as input.
--   A parameterized view would be a function — which is this.
-- ============================================================
CREATE OR REPLACE FUNCTION GenerateMonthlyReport(p_user_id INT)
RETURNS TABLE (
    category            VARCHAR(50),
    service_count       BIGINT,
    total_category_cost NUMERIC(10,2),
    ghost_count         BIGINT,
    potential_savings   NUMERIC(10,2)
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        sv.category,

        -- How many active subscriptions in this category
        COUNT(s.sub_id)                                     AS service_count,

        -- Total monthly cost for this category
        COALESCE(SUM(s.detected_cost), 0)::NUMERIC(10,2)   AS total_category_cost,

        -- How many of those are ghosts (0 usage or stale)
        COUNT(CASE
            WHEN COALESCE(usm.usage_count, 0) = 0
              OR usm.last_used_at < NOW() - INTERVAL '30 days'
              OR usm.mapping_id IS NULL
            THEN 1
        END)                                                AS ghost_count,

        -- Potential savings = cost of ghost subs in this category
        COALESCE(SUM(
            CASE
                WHEN COALESCE(usm.usage_count, 0) = 0
                  OR usm.last_used_at < NOW() - INTERVAL '30 days'
                  OR usm.mapping_id IS NULL
                THEN s.detected_cost
                ELSE 0
            END
        ), 0)::NUMERIC(10,2)                                AS potential_savings

    FROM Subscriptions s
    JOIN Services sv ON s.service_id = sv.service_id
    LEFT JOIN User_Subscription_Mapping usm
        ON s.sub_id = usm.sub_id AND s.user_id = usm.user_id
    WHERE
        s.user_id = p_user_id
        AND s.status = 'active'
    GROUP BY sv.category
    ORDER BY total_category_cost DESC;
END;
$$ LANGUAGE plpgsql;


-- ============================================================
-- SEED: Create some Subscription rows for test user 1
-- so that the analytics functions have data to work with.
-- This assumes run_classification_pipeline has already run,
-- or we insert directly for demo purposes.
-- ============================================================
INSERT INTO Subscriptions (user_id, service_id, detected_cost, billing_cycle, next_renewal, status)
SELECT
    1,
    sv.service_id,
    sv.base_cost_inr,
    'monthly',
    CURRENT_DATE + INTERVAL '30 days',
    'active'
FROM Services sv
WHERE sv.service_name IN ('Netflix', 'Spotify', 'Amazon Prime', 'YouTube Premium', 'Disney+ Hotstar')
ON CONFLICT (user_id, service_id) DO NOTHING;

-- Insert usage mapping data to make the analytics interesting:
-- Netflix: heavy usage, Spotify: moderate, Amazon Prime: light,
-- YouTube Premium: zero (ghost!), Disney+ Hotstar: zero (ghost!)
INSERT INTO User_Subscription_Mapping (user_id, sub_id, usage_count, last_used_at)
SELECT
    1,
    s.sub_id,
    CASE sv.service_name
        WHEN 'Netflix'          THEN 25   -- used 25 times
        WHEN 'Spotify'          THEN 15   -- used 15 times
        WHEN 'Amazon Prime'     THEN 3    -- barely used
        WHEN 'YouTube Premium'  THEN 0    -- ghost!
        WHEN 'Disney+ Hotstar'  THEN 0    -- ghost!
    END,
    CASE sv.service_name
        WHEN 'Netflix'          THEN NOW() - INTERVAL '1 day'
        WHEN 'Spotify'          THEN NOW() - INTERVAL '3 days'
        WHEN 'Amazon Prime'     THEN NOW() - INTERVAL '45 days'  -- stale
        WHEN 'YouTube Premium'  THEN NULL                         -- never used
        WHEN 'Disney+ Hotstar'  THEN NULL                         -- never used
    END
FROM Subscriptions s
JOIN Services sv ON s.service_id = sv.service_id
WHERE s.user_id = 1
  AND sv.service_name IN ('Netflix', 'Spotify', 'Amazon Prime', 'YouTube Premium', 'Disney+ Hotstar')
ON CONFLICT DO NOTHING;