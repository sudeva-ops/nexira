-- NEXIRA database bootstrap (D-01). Run once as the superuser by 00-nexira-init.sh.
-- psql variables: owner_password, api_password, db_name.
--
--   nexira_owner  LOGIN, owns all objects, runs Alembic. Not a superuser.
--   nexira_app    NOLOGIN group role holding the runtime grants.
--   nexira_api    LOGIN, member of nexira_app; the only user the backend uses.

CREATE ROLE nexira_owner LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD :'owner_password';
CREATE ROLE nexira_app NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
CREATE ROLE nexira_api LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD :'api_password' IN ROLE nexira_app;

CREATE DATABASE :"db_name" OWNER nexira_owner;
REVOKE ALL ON DATABASE :"db_name" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"db_name" TO nexira_app;

\connect :"db_name"

-- Extensions need a superuser; the schema's CREATE EXTENSION IF NOT EXISTS is then a no-op.
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
-- Schema public belongs to pg_database_owner (= nexira_owner) and PUBLIC cannot
-- create in it (PostgreSQL 15+), so nexira_api can never create objects.
