#!/bin/bash
echo "Starting PostgreSQL..."
/Users/Shared/DBngin/postgresql/17.0/bin/pg_ctl -D /Users/chinmay/Documents/postgresql_data start

echo "Starting Redis..."
/Users/Shared/DBngin/redis/7.0.0/bin/redis-server --daemonize yes

# Note: If you install MySQL via DBngin, you can add it here.
# For example:
# /Users/Shared/DBngin/mysql/8.0.33/bin/mysqld --daemonize --datadir=/Users/chinmay/Documents/mysql_data

echo "All databases started!"
