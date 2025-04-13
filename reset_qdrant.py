#!/usr/bin/env python3
import requests
import json
import random

# Configuration
QDRANT_HOST = "localhost"
QDRANT_PORT = 6333
COLLECTION_NAME = "semantic_cache"
VECTOR_SIZE = 384

# Supprimer la collection existante
delete_url = f"http://{QDRANT_HOST}:{QDRANT_PORT}/collections/{COLLECTION_NAME}"
requests.delete(delete_url)
print(f"Collection '{COLLECTION_NAME}' supprimée.")

# Créer la collection avec la bonne configuration
create_url = f"http://{QDRANT_HOST}:{QDRANT_PORT}/collections/{COLLECTION_NAME}"
create_payload = {
    "vectors": {
        "size": VECTOR_SIZE,
        "distance": "Cosine"
    },
    "optimizers_config": {
        "default_segment_number": 2
    },
    "replication_factor": 1,
    "write_consistency_factor": 1,
    "on_disk_payload": True
}

create_response = requests.put(create_url, json=create_payload)
print(f"Création de collection: {create_response.status_code} - {create_response.text}")

# Créer des index pour les champs de payload
index_url = f"http://{QDRANT_HOST}:{QDRANT_PORT}/collections/{COLLECTION_NAME}/index"

for field in ["question", "sql_query"]:
    index_payload = {
        "field_name": field,
        "field_schema": "text"
    }
    index_response = requests.put(index_url, json=index_payload)
    print(f"Création d'index pour {field}: {index_response.status_code}")

# Ajouter un point de test
test_vector = [random.uniform(-1, 1) for _ in range(VECTOR_SIZE)]
point_url = f"http://{QDRANT_HOST}:{QDRANT_PORT}/collections/{COLLECTION_NAME}/points"
point_payload = {
    "points": [
        {
            "id": 1,
            "vector": test_vector,
            "payload": {
                "question": "Quels sont les clients de Californie?",
                "sql_query": "SELECT * FROM customers WHERE state = 'CA'"
            }
        }
    ]
}

point_response = requests.put(point_url, json=point_payload)
print(f"Ajout de point test: {point_response.status_code} - {point_response.text}")

# Faire une recherche de test
search_url = f"http://{QDRANT_HOST}:{QDRANT_PORT}/collections/{COLLECTION_NAME}/points/search"
search_payload = {
    "vector": test_vector,
    "limit": 1
}

search_response = requests.post(search_url, json=search_payload)
print(f"Recherche test: {search_response.status_code} - {search_response.text}")