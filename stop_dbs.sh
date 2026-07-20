#!/bin/bash
echo "Stopping PostgreSQL..."
/Users/Shared/DBngin/postgresql/17.0/bin/pg_ctl -D /Users/chinmay/Documents/postgresql_data stop

echo "Stopping Redis..."
# A simple way to stop the daemonized redis server
redis_pid=$(lsof -t -i:6379)
if [ ! -z "$redis_pid" ]; then
  kill $redis_pid
  echo "Redis stopped."
else
  echo "Redis is not running."
fi

# Note: Add MySQL stop commands here if needed later.

echo "All databases stopped!"
