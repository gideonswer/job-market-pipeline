-- Handy analytics queries (PostgreSQL). Run with psql or any SQL client.

-- 1. Top 20 skills and the share of listings that ask for them
SELECT s.skill,
       COUNT(*) AS jobs,
       ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM jobs WHERE extracted_at IS NOT NULL), 1) AS pct_of_jobs
FROM job_skills s
GROUP BY s.skill
ORDER BY jobs DESC
LIMIT 20;

-- 2. Median salary (lakhs/year) by role and seniority, only where salary is stated
SELECT role_category,
       seniority,
       COUNT(*) AS jobs_with_salary,
       PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY (salary_min_lpa + salary_max_lpa) / 2) AS median_lpa
FROM jobs
WHERE salary_min_lpa IS NOT NULL
GROUP BY role_category, seniority
HAVING COUNT(*) >= 3
ORDER BY role_category, median_lpa;

-- 3. Weekly demand for one skill (change 'RAG' to anything)
SELECT DATE_TRUNC('week', j.posted_at) AS week, COUNT(*) AS jobs
FROM jobs j
JOIN job_skills s ON s.job_id = j.id
WHERE s.skill = 'RAG'
GROUP BY week
ORDER BY week;

-- 4. Skills that most often appear together with 'LLMs'
SELECT b.skill, COUNT(*) AS together
FROM job_skills a
JOIN job_skills b ON a.job_id = b.job_id AND a.skill <> b.skill
WHERE a.skill = 'LLMs'
GROUP BY b.skill
ORDER BY together DESC
LIMIT 10;

-- 5. Pipeline health: last 10 runs
SELECT id, started_at, finished_at - started_at AS duration, scraped, inserted, extracted, failed, status, notes
FROM pipeline_runs
ORDER BY id DESC
LIMIT 10;
