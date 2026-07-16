-- Deep-dive universe (rubric v15, gate 25): the top-N eligible companies by
-- market cap (descending), deterministic. The screening-flag promotion that
-- gate 3 allows is handled by Python at assignment time, NOT by this SQL, so
-- the SQL respects the assignment-time rule and never reads opinions.
-- Null-safe: marketcap is filtered to > 0 so the SELECT market_cap column is
-- never null.
WITH latest AS
(
    SELECT ticker, marketcap
    FROM fundamentals.v_latest_fundamentals
    WHERE dimension = 'MRY' AND marketcap > 0
),
elig AS
(
    SELECT
        t.ticker AS ticker,
        t.name AS name,
        t.sector AS sector,
        t.scalemarketcap AS scale_marketcap,
        l.marketcap AS market_cap
    FROM fundamentals.v_companies AS t
    INNER JOIN latest AS l USING (ticker)
    WHERE t.isdelisted = 'N'
      AND t.scalemarketcap IN ('4 - Mid', '5 - Large', '6 - Mega')
)
SELECT ticker, name, sector, scale_marketcap, market_cap
FROM elig
ORDER BY market_cap DESC, ticker
LIMIT {limit:UInt32}
