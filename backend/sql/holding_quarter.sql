SELECT calendardate
FROM fundamentals.sf3
WHERE securitytype = 'SHR'
GROUP BY calendardate
HAVING countDistinct(investorname) > 500
ORDER BY calendardate DESC
LIMIT 1
