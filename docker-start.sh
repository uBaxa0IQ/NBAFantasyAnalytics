#!/bin/bash

echo "Starting NBA Fantasy Analytics with Docker..."
echo

if [ ! -f .env ]; then
    echo "ERROR: .env file not found!"
    echo "Please create .env file with your ESPN credentials:"
    echo "ESPN_S2=your_espn_s2_token_here"
    echo "SWID={your-swid-guid-here}"
    exit 1
fi

echo "Stopping any existing containers..."
docker-compose down 2>/dev/null

echo
echo "Building and starting containers..."
docker-compose up -d --build

echo
echo "Application is starting..."
echo "Backend: http://localhost:8000"
echo "Frontend: http://localhost:3001"
echo
echo "To view logs: docker-compose logs -f"
echo "To stop: docker-compose down"

