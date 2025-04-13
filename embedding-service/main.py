#!/usr/bin/env python3
"""
Service d'embeddings pour le projet de mise en cache sémantique
Utilise sentence-transformers pour calculer les embeddings des questions
et les stocker dans Qdrant (version ≥ 1.x)
"""
import os
from typing import Dict, List, Any
from pydantic import BaseModel
from fastapi import FastAPI, HTTPException
from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
from qdrant_client.http import models, exceptions
import logging

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Variables d'environnement / Configuration
VECTOR_DB_HOST = os.getenv("VECTOR_DB_HOST", "vector-db")
VECTOR_DB_PORT = int(os.getenv("VECTOR_DB_PORT", "6333"))
COLLECTION_NAME = "semantic_cache"
MODEL_NAME = "all-MiniLM-L6-v2"

app = FastAPI(
    title="Service d'Embeddings (Compat Qdrant 1.x)",
    description="Service pour calculer et stocker les embeddings des questions"
)

# ----- Schémas Pydantic -----
class Question(BaseModel):
    text: str

class QuestionWithSQL(BaseModel):
    question: str
    sql_query: str

class SearchResult(BaseModel):
    id: int
    question: str
    sql_query: str
    score: float

class EmbeddingResponse(BaseModel):
    embedding: List[float]
    dimension: int

# ----- Événement de démarrage -----
@app.on_event("startup")
async def startup_event():
    """
    Charge le modèle SentenceTransformer et se connecte à Qdrant (1.x).
    """
    global model, qdrant_client
    
    logger.info(f"Chargement du modèle '{MODEL_NAME}'...")
    model = SentenceTransformer(MODEL_NAME)
    logger.info(f"Modèle '{MODEL_NAME}' chargé avec succès.")
    
    logger.info(f"Connexion à Qdrant sur {VECTOR_DB_HOST}:{VECTOR_DB_PORT}...")
    qdrant_client = QdrantClient(host=VECTOR_DB_HOST, port=VECTOR_DB_PORT)

    # Vérifier si la collection existe déjà
    try:
        collection_info = qdrant_client.get_collection(COLLECTION_NAME)
        logger.info(f"Collection '{COLLECTION_NAME}' trouvée: {collection_info}")
    except exceptions.ResponseHandlingException as e:
        logger.warning(f"Collection '{COLLECTION_NAME}' introuvable: {e}")
        logger.info("Tentative de création de la collection...")

        try:
            # Syntaxe Qdrant 1.3.0
            qdrant_client.recreate_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=models.VectorParams(
                    size=model.get_sentence_embedding_dimension(),
                    distance=models.Distance.COSINE
                )
            )

            # Créer des index de payload pour les champs "question" et "sql_query"
            qdrant_client.create_payload_index(
                collection_name=COLLECTION_NAME,
                field_name="question",
                field_schema="text"
            )

            qdrant_client.create_payload_index(
                collection_name=COLLECTION_NAME,
                field_name="sql_query",
                field_schema="text"
            )

            logger.info(f"Collection '{COLLECTION_NAME}' créée et configurée avec succès.")
        except Exception as e2:
            logger.error(f"Erreur lors de la création de la collection: {e2}")

# ----- Endpoints -----
@app.get("/health")
async def health_check():
    """Endpoint de vérification de santé du service"""
    return {"status": "ok", "model": MODEL_NAME}

@app.post("/embed", response_model=EmbeddingResponse)
async def embed_text(question: Question):
    """
    Calcule l'embedding d'une question (sans le stocker dans Qdrant).
    Utile pour un simple test ou un usage ponctuel.
    """
    try:
        embedding = model.encode(question.text).tolist()
        return {
            "embedding": embedding,
            "dimension": len(embedding)
        }
    except Exception as e:
        logger.error(f"Erreur lors du calcul de l'embedding: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors du calcul de l'embedding: {str(e)}"
        )

@app.post("/store", response_model=Dict[str, Any])
async def store_question_and_sql(item: QuestionWithSQL):
    """
    Calcule l'embedding d'une question et stocke dans Qdrant
    avec la requête SQL associée (payload).
    """
    try:
        # Calcul de l'embedding
        embedding = model.encode(item.question).tolist()

        # Génération d'un ID (par exemple, hash de la question)
        question_id = abs(hash(item.question)) % (10 ** 10)

        # Upsert (insertion/mise à jour) dans Qdrant
        qdrant_client.upsert(
            collection_name=COLLECTION_NAME,
            points=[
                models.PointStruct(
                    id=question_id,
                    vector=embedding,  # Sans spécifier "default"
                    payload={
                        "question": item.question,
                        "sql_query": item.sql_query
                    }
                )
            ]
        )
        
        return {
            "status": "success",
            "message": "Question et requête SQL stockées avec succès",
            "id": question_id
        }
    except Exception as e:
        logger.error(f"Erreur lors du stockage dans Qdrant: {e}")
        if hasattr(e, 'response') and hasattr(e.response, 'content'):
            logger.error(f"Raw response content:\n{e.response.content}")
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors du stockage dans Qdrant: {str(e)}"
        )

@app.post("/search", response_model=List[SearchResult])
async def search_similar_questions(
    question: Question,
    limit: int = 5,
    threshold: float = 0.7
):
    """
    Recherche les questions similaires dans Qdrant avec un score >= threshold.
    Renvoie les ID, payload (question/sql_query) et le score de similarité.
    """
    try:
        # Embedding de la question
        embedding = model.encode(question.text).tolist()
        
        # Recherche vectorielle avec syntaxe Qdrant 1.3.0
        search_results = qdrant_client.search(
            collection_name=COLLECTION_NAME,
            query_vector=embedding,  # Sans spécifier "default"
            limit=limit,
            score_threshold=threshold,
            with_payload=True
        )
        
        # Mise en forme des résultats
        results = []
        for res in search_results:
            results.append(
                SearchResult(
                    id=res.id,
                    question=res.payload.get("question", ""),
                    sql_query=res.payload.get("sql_query", ""),
                    score=res.score
                )
            )
        
        return results
    except Exception as e:
        logger.error(f"Erreur lors de la recherche dans Qdrant: {e}")
        if hasattr(e, 'response') and hasattr(e.response, 'content'):
            logger.error(f"Raw response content:\n{e.response.content}")
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la recherche dans Qdrant: {str(e)}"
        )

# ----- Lancement du serveur -----
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)