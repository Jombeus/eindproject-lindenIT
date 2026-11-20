#!/bin/bash
for pw in welkom123 test123 admin123 password qwerty 123456 letmein admin; do
  curl -s -o /dev/null -w "admin / $pw -> HTTP %{http_code}\n" \
    -d "username=admin&password=$pw" http://localhost:5000/login
  sleep 0.5
done

# running random asss passwords