#!/usr/bin/env python3
"""
Script d'initialisation pour Qdrant
Crée la collection pour stocker les embeddings des questions et des requêtes SQL
"""
import requests
import time
import sys
import os

# Configuration
QDRANT_HOST = "vector-db"
QDRANT_PORT = 6333
COLLECTION_NAME = "semantic_cache"
VECTOR_SIZE = 384  # Taille des vecteurs pour all-MiniLM-L6-v2

def wait_for_qdrant():
    """Attend que Qdrant soit prêt"""
    max_retries = 30
    retry_interval = 5  # secondes
    
    for i in range(max_retries):
        try:
            # Utiliser l'endpoint racine pour vérifier si Qdrant est prêt
            response = requests.get(f"http://{QDRANT_HOST}:{QDRANT_PORT}/")
            if response.status_code == 200:
                print("Qdrant est prêt!")
                return True
        except requests.exceptions.ConnectionError:
            pass
        
        print(f"En attente de Qdrant... ({i+1}/{max_retries})")
        time.sleep(retry_interval)
    
    print("Impossible de se connecter à Qdrant après plusieurs tentatives.")
    return False

def create_collection():
    """Crée la collection pour stocker les embeddings"""
    url = f"http://{QDRANT_HOST}:{QDRANT_PORT}/collections/{COLLECTION_NAME}"
    
    # Supprimer la collection si elle existe
    try:
        requests.delete(url)
        print(f"Collection '{COLLECTION_NAME}' supprimée si elle existait.")
    except:
        pass
    
    # Configuration de la collection pour Qdrant 1.3.0
    payload = {
        "vectors": {
            "size": VECTOR_SIZE,
            "distance": "Cosine"
        },
        "optimizers_config": {
            "default_segment_number": 2
        },
        "replication_factor": 1,
        "write_consistency_factor": 1,
        "on_disk_payload": True,
        "hnsw_config": {
            "m": 16,
            "ef_construct": 100
        }
    }
    
    # Créer la collection
    response = requests.put(url, json=payload)
    if response.status_code == 200:
        print(f"Collection '{COLLECTION_NAME}' créée avec succès!")
        
        # Créer les index pour les champs de payload
        create_payload_index("question", "text")
        create_payload_index("sql_query", "text")
        return True
    else:
        print(f"Erreur lors de la création de la collection: {response.text}")
        return False
    
def create_payload_index(field_name, field_schema):
    """Crée un index sur un champ de payload"""
    url = f"http://{QDRANT_HOST}:{QDRANT_PORT}/collections/{COLLECTION_NAME}/index"
    
    payload = {
        "field_name": field_name,
        "field_schema": field_schema
    }
    
    response = requests.put(url, json=payload)
    if response.status_code == 200:
        print(f"Index créé pour le champ '{field_name}'")
    else:
        print(f"Erreur lors de la création de l'index pour '{field_name}': {response.text}")

if __name__ == "__main__":
    print(f"Initialisation de Qdrant sur {QDRANT_HOST}:{QDRANT_PORT}")
    
    if wait_for_qdrant():
        create_collection()
    else:
        sys.exit(1)