#!/bin/bash

# Colors if available
if [ -t 1 ]; then
  CYAN="\033[0;36m"
  GREEN="\033[0;32m"
  YELLOW="\033[0;33m"
  RED="\033[0;31m"
  RESET="\033[0m"
else
  CYAN=""
  GREEN=""
  YELLOW=""
  RED=""
  RESET=""
fi

API_URL="http://localhost:8000/process"

# Function to send a query
send_query() {
  local query="$1"
  echo -e "${YELLOW}Testing query:${RESET} ${CYAN}\"$query\"${RESET}"
  
  # Prepare JSON request by properly escaping quotes
  json_data=$(echo '{"text": "'"$query"'"}')
  
  # Send request with curl
  echo -e "${GREEN}Generated SQL query:${RESET}"
  curl -s -X POST "$API_URL" \
    -H "Content-Type: application/json" \
    -d "$json_data" | grep -o '"query_used":[^,]*' | cut -d':' -f2
  
  echo -e "${GREEN}-------------------------${RESET}"
  sleep 1  # One second pause between requests
}

# List of client queries
echo -e "${GREEN}=== Clients ===${RESET}"
send_query "Which clients are from New York state?"
send_query "How many clients do we have per state?"
send_query "Which clients have \"inactive\" status?"
send_query "Who are our most recently registered clients?"

# List of product queries
echo -e "${GREEN}=== Products ===${RESET}"
send_query "What products are in the \"Electronics\" category?"
send_query "Which products cost more than 300 dollars?"
send_query "Which products have less than 40 units in stock?"
send_query "What is the most expensive product in our catalog?"

# Orders
echo -e "${GREEN}=== Orders ===${RESET}"
send_query "Which orders are currently in \"pending\" status?"
send_query "What is the total amount of delivered orders?"
send_query "Which orders were placed in December 2023?"
send_query "Which client made the order with the highest amount?"

# Complex queries
echo -e "${GREEN}=== Complex queries ===${RESET}"
send_query "What products were ordered by client John Doe?"
send_query "How many products in the \"Electronics\" category have been ordered in total?"
send_query "Which clients ordered furniture (\"Furniture\" category)?"
send_query "Which state generated the most revenue?"

# Analyses
echo -e "${GREEN}=== Analyses ===${RESET}"
send_query "What is the average order value by state?"
send_query "What is the number of orders per product category?"
send_query "Which clients have made more than 2 orders?"
send_query "Which cat"