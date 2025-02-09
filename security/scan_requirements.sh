#!/bin/bash

# Fail if any command exits with a non-zero status
set -e

# Check for safety and bandit
if ! command -v safety &> /dev/null; then
  echo "Safety not found. Please install it."
  exit 1
fi

if ! command -v bandit &> /dev/null; then
  echo "Bandit not found. Please install it."
  exit 1
fi

# Scan requirements.txt for vulnerabilities using safety
echo "Scanning requirements.txt with safety..."
safety check --full-report --file requirements.txt

# If safety finds vulnerabilities, exit with an error code
if ! safety check --check --file requirements.txt; then
  echo "Vulnerabilities found by safety. Please review the report."
fi

# Scan source code for vulnerabilities using bandit
echo "Scanning source code with bandit..."
bandit -r src/

echo "Security scan complete."
