#!/usr/bin/env python3
"""
Test script for the semantic caching and Text-to-SQL generation project
This script demonstrates the complete workflow of the system by sending multiple questions
and displaying the results
"""
import requests
import json
import time
from typing import Dict, Any

# Configuration
EXECUTOR_URL = "http://localhost:8000"
EMBEDDING_URL = "http://localhost:8001"
VECTOR_DB_URL = "http://localhost:6333"

def print_separator():
    """Displays a separation line"""
    print("\n" + "="*80 + "\n")

def check_services_health():
    """Checks the health status of all services"""
    print("Checking services status...")
    try:
        response = requests.get(f"{EXECUTOR_URL}/health")
        if response.status_code == 200:
            health_data = response.json()
            print(f"Global status: {health_data['status']}")
            print("Individual services status:")
            for service, status in health_data['services'].items():
                print(f"  - {service}: {status}")
            return True
        else:
            print(f"Error when checking services status: {response.status_code}")
            return False
    except Exception as e:
        print(f"Connection error: {e}")
        return False

def get_database_schema():
    """Retrieves the database schema"""
    print("Retrieving database schema...")
    try:
        response = requests.get(f"{EXECUTOR_URL}/schema")
        if response.status_code == 200:
            schema_data = response.json()
            print("Database schema:")
            for table, columns in schema_data['tables'].items():
                print(f"  Table: {table}")
                for column, data_type in columns.items():
                    print(f"    - {column}: {data_type}")
            return schema_data
        else:
            print(f"Error while retrieving schema: {response.status_code}")
            return None
    except Exception as e:
        print(f"Connection error: {e}")
        return None

def process_question(question: str) -> Dict[str, Any]:
    """
    Processes a natural language question
    
    Args:
        question: Natural language question
        
    Returns:
        Processing result
    """
    print(f"Processing question: '{question}'")
    try:
        response = requests.post(
            f"{EXECUTOR_URL}/process",
            json={"text": question}
        )
        if response.status_code == 200:
            result = response.json()
            print(f"Response source: {result['source']}")
            print(f"SQL query used: {result['query_used']}")
            print("Results:")
            print_table(result['result']['columns'], result['result']['rows'])
            print(f"Execution time: {result['result']['execution_time']:.4f} seconds")
            print(f"Number of rows: {result['result']['row_count']}")
            return result
        else:
            print(f"Error while processing question: {response.status_code}")
            print(response.text)
            return {}
    except Exception as e:
        print(f"Connection error: {e}")
        return {}

def print_table(columns, rows):
    """Displays results in table format"""
    if not rows:
        print("No results")
        return
    
    # Calculate the width of each column
    col_widths = {col: len(col) for col in columns}
    for row in rows:
        for col in columns:
            col_widths[col] = max(col_widths[col], len(str(row.get(col, ""))))
    
    # Display header
    header = " | ".join(col.ljust(col_widths[col]) for col in columns)
    print(header)
    print("-" * len(header))
    
    # Display rows
    for row in rows:
        print(" | ".join(str(row.get(col, "")).ljust(col_widths[col]) for col in columns))

def main():
    """Main function"""
    print_separator()
    print("DEMO OF SEMANTIC CACHING AND TEXT-TO-SQL GENERATION SYSTEM")
    print_separator()
    
    # Check services status
    if not check_services_health():
        print("Not all services are available. Please verify that all containers are running.")
        return
    
    print_separator()
    
    # Retrieve database schema
    schema = get_database_schema()
    if not schema:
        print("Unable to retrieve database schema.")
        return
    
    print_separator()
    
    # List of questions to process
    questions = [
        # First question - will be generated
        "Which customers live in California?",
        
        # Similar question - should use cache with modification
        "List all customers who live in New York",
        
        # Different question - will be generated
        "What are the products in the Electronics category with a price higher than 500 dollars?",
        
        # Similar question - should use cache with modification
        "Show me all products in the Furniture category",
        
        # More complex question - will be generated
        "Which customers have placed orders with a total amount greater than 1000 dollars?",
        
        # Similar question - should use cache with modification
        "List customers who have placed orders with a total amount greater than 500 dollars"
    ]
    
    # Process each question
    results = {}
    for i, question in enumerate(questions):
        print_separator()
        print(f"QUESTION {i+1}/{len(questions)}")
        results[question] = process_question(question)
        # Wait a bit between questions to allow time for the cache to update
        if i < len(questions) - 1:
            time.sleep(2)
    
    print_separator()
    print("RESULTS SUMMARY")
    print_separator()
    
    for i, (question, result) in enumerate(results.items()):
        if result:
            print(f"Question {i+1}: {question}")
            print(f"Source: {result['source']}")
            print(f"Execution time: {result['result']['execution_time']:.4f} seconds")
            print(f"Number of rows: {result['result']['row_count']}")
            print()
    
    print_separator()
    print("END OF DEMO")
    print_separator()

if __name__ == "__main__":
    main()