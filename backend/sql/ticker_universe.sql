SELECT DISTINCT
    t.ticker,
    t.name,
    t.sector,
    t.scalemarketcap AS scale_marketcap
FROM fundamentals.tickers AS t
INNER JOIN
(
    SELECT DISTINCT ticker
    FROM fundamentals.sf1
) AS s USING (ticker)
WHERE t.isdelisted = 'N'
  AND t.scalemarketcap IN ('4 - Mid', '5 - Large', '6 - Mega')
ORDER BY t.scalemarketcap DESC, t.ticker
LIMIT {limit:UInt32}
