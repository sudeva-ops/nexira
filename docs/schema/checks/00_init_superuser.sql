-- Test-only roles and passwords. Real ones come from .env (D-01).
CREATE ROLE nexira_owner LOGIN PASSWORD 'owner';
CREATE ROLE nexira_app NOLOGIN;
CREATE ROLE nexira_api LOGIN PASSWORD 'api' IN ROLE nexira_app;
CREATE DATABASE nexira OWNER nexira_owner;
\c nexira
CREATE EXTENSION postgis;
CREATE EXTENSION pgcrypto;
