#!/bin/bash
N=${1:-40}
for i in $(seq 1 "$N"); do
  curl -s -o /dev/null http://localhost:5000/api/stations
done
echo "$N verzoeken verstuurd"

# api