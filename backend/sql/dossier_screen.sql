WITH
meta AS
(
    SELECT ticker, name, sector, industry, scalemarketcap, exchange, isdelisted
    FROM fundamentals.v_companies
    WHERE ticker = {ticker:String}
),
annual_periods AS
(
    SELECT * EXCEPT rn
    FROM
    (
        SELECT
            calendardate, datekey, revenue, netinc, netmargin, epsdil,
            grossmargin, roe, roa, marketcap, pe, ps, pb, ev, fcf,
            debt, cashneq, equity, ebitda,
            row_number() OVER
            (
                PARTITION BY calendardate
                ORDER BY datekey DESC
            ) AS rn
        FROM fundamentals.sf1
        WHERE ticker = {ticker:String} AND dimension = 'MRY'
    )
    WHERE rn = 1
),
latest AS
(
    SELECT *
    FROM annual_periods
    ORDER BY calendardate DESC
    LIMIT 1
),
prior AS
(
    SELECT revenue, netinc
    FROM annual_periods
    ORDER BY calendardate DESC
    LIMIT 1 OFFSET 1
),
ttm AS
(
    SELECT revenue, netinc, epsdil, fcf
    FROM fundamentals.sf1
    WHERE ticker = {ticker:String} AND dimension = 'MRT'
    ORDER BY calendardate DESC, datekey DESC
    LIMIT 1
),
growth AS
(
    SELECT
        round((a.revenue / nullIf(p.revenue, 0) - 1) * 100, 2) AS revenue_yoy_pct,
        round((a.netinc / nullIf(p.netinc, 0) - 1) * 100, 2) AS earnings_yoy_pct
    FROM latest AS a, prior AS p
),
sector_target AS
(
    SELECT pe, ps, roe, sector
    FROM fundamentals.v_latest_fundamentals
    WHERE ticker = {ticker:String} AND dimension = 'MRY'
    LIMIT 1
),
sector_pct AS
(
    SELECT
        if((SELECT pe FROM sector_target) > 0,
           round(countIf(f.pe > 0 AND f.pe <= (SELECT pe FROM sector_target)) * 100.0 /
                 nullIf(countIf(f.pe > 0), 0), 1),
           NULL) AS pe_percentile_in_sector,
        if((SELECT ps FROM sector_target) > 0,
           round(countIf(f.ps > 0 AND f.ps <= (SELECT ps FROM sector_target)) * 100.0 /
                 nullIf(countIf(f.ps > 0), 0), 1),
           NULL) AS ps_percentile_in_sector,
        round(countIf(f.roe IS NOT NULL AND f.roe <= (SELECT roe FROM sector_target)) * 100.0 /
              nullIf(countIf(f.roe IS NOT NULL), 0), 1) AS roe_percentile_in_sector
    FROM fundamentals.v_latest_fundamentals AS f
    WHERE f.dimension = 'MRY'
      AND f.sector = (SELECT sector FROM sector_target)
),
latest_holding_quarter AS
(
    SELECT max(calendardate) AS q
    FROM fundamentals.sf3
    WHERE ticker = {ticker:String} AND securitytype = 'SHR'
),
concentration AS
(
    SELECT
        round(sum(value), 0) AS total_value,
        countDistinct(investorname) AS holder_count,
        round(
            (
                SELECT sum(v)
                FROM
                (
                    SELECT value AS v
                    FROM fundamentals.sf3
                    WHERE ticker = {ticker:String}
                      AND securitytype = 'SHR'
                      AND calendardate = (SELECT q FROM latest_holding_quarter)
                    ORDER BY value DESC
                    LIMIT 5
                )
            ) * 100.0 / nullIf(sum(value), 0),
            1
        ) AS top5_concentration_pct
    FROM fundamentals.sf3
    WHERE ticker = {ticker:String}
      AND securitytype = 'SHR'
      AND calendardate = (SELECT q FROM latest_holding_quarter)
),
quarterly_periods AS
(
    SELECT * EXCEPT rn
    FROM
    (
        SELECT
            calendardate, datekey, fiscalperiod, revenue, netinc, eps, grossmargin,
            row_number() OVER
            (
                PARTITION BY calendardate
                ORDER BY datekey DESC
            ) AS rn
        FROM fundamentals.sf1
        WHERE ticker = {ticker:String} AND dimension = 'MRQ'
    )
    WHERE rn = 1
    ORDER BY calendardate DESC
    LIMIT 8
)
SELECT
    {ticker:String} AS ticker,
    (SELECT name FROM meta) AS name,
    (SELECT sector FROM meta) AS sector,
    (SELECT industry FROM meta) AS industry,
    (SELECT scalemarketcap FROM meta) AS scale_marketcap,
    (SELECT exchange FROM meta) AS exchange,
    (SELECT isdelisted FROM meta) AS is_delisted,
    (SELECT calendardate FROM latest) AS latest_annual_date,
    (SELECT revenue FROM latest) AS revenue_annual,
    (SELECT netinc FROM latest) AS net_income_annual,
    (SELECT revenue FROM ttm) AS revenue_ttm,
    (SELECT netinc FROM ttm) AS net_income_ttm,
    (SELECT epsdil FROM ttm) AS eps_diluted_ttm,
    (SELECT fcf FROM ttm) AS free_cash_flow_ttm,
    (SELECT netmargin FROM latest) AS net_margin,
    (SELECT grossmargin FROM latest) AS gross_margin,
    (SELECT roe FROM latest) AS roe,
    (SELECT marketcap FROM latest) AS market_cap,
    (SELECT pe FROM latest) AS pe,
    (SELECT ps FROM latest) AS ps,
    (SELECT pb FROM latest) AS pb,
    (SELECT ev FROM latest) AS enterprise_value,
    (SELECT debt FROM latest) AS debt,
    (SELECT cashneq FROM latest) AS cash,
    (SELECT equity FROM latest) AS equity,
    (SELECT ebitda FROM latest) AS ebitda,
    (SELECT revenue_yoy_pct FROM growth) AS revenue_yoy_pct,
    (SELECT earnings_yoy_pct FROM growth) AS earnings_yoy_pct,
    (SELECT pe_percentile_in_sector FROM sector_pct) AS pe_percentile_in_sector,
    (SELECT ps_percentile_in_sector FROM sector_pct) AS ps_percentile_in_sector,
    (SELECT roe_percentile_in_sector FROM sector_pct) AS roe_percentile_in_sector,
    (SELECT total_value FROM concentration) AS institutional_total_value,
    (SELECT holder_count FROM concentration) AS institutional_holder_count,
    (SELECT top5_concentration_pct FROM concentration) AS institutional_top5_concentration_pct,
    (SELECT groupArray((calendardate, fiscalperiod, revenue, netinc, eps, grossmargin)) FROM quarterly_periods) AS quarterly_trend
