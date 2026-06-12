SELECT 'CREATE DATABASE cmnc_classroom OWNER cmnc'
WHERE NOT EXISTS (
    SELECT FROM pg_database WHERE datname = 'cmnc_classroom'
)\gexec

SELECT 'CREATE DATABASE cmnc_inventory OWNER cmnc'
WHERE NOT EXISTS (
    SELECT FROM pg_database WHERE datname = 'cmnc_inventory'
)\gexec

SELECT 'CREATE DATABASE cmnc_auth OWNER cmnc'
WHERE NOT EXISTS (
    SELECT FROM pg_database WHERE datname = 'cmnc_auth'
)\gexec

SELECT 'CREATE DATABASE cmnc_policy_sync OWNER cmnc'
WHERE NOT EXISTS (
    SELECT FROM pg_database WHERE datname = 'cmnc_policy_sync'
)\gexec
