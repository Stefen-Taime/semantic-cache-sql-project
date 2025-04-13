#!/usr/bin/env python3
"""
Service de validation sémantique pour le projet de mise en cache sémantique
Utilise l'API Groq pour vérifier la similarité sémantique entre deux questions
"""
import os
from typing import Dict, Any, Optional
from pydantic import BaseModel
from fastapi import FastAPI, HTTPException, Depends
import groq
import logging
from dotenv import load_dotenv

# Charger les variables d'environnement
load_dotenv()

# Configuration du logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configuration
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    logger.warning("GROQ_API_KEY non définie. Le service ne fonctionnera pas correctement.")

MODEL_NAME = "meta-llama/llama-4-scout-17b-16e-instruct"  # Modèle Groq à utiliser

app = FastAPI(title="Service de Validation Sémantique", 
              description="Service pour vérifier la similarité sémantique entre deux questions")

# Modèles de données
class ValidationRequest(BaseModel):
    cached_question: str
    user_question: str
    similarity_threshold: Optional[float] = 0.8

class ValidationResponse(BaseModel):
    is_similar: bool
    confidence: float
    explanation: str

# Initialisation du client Groq
def get_groq_client():
    if not GROQ_API_KEY:
        raise HTTPException(status_code=500, detail="GROQ_API_KEY non configurée")
    return groq.Client(api_key=GROQ_API_KEY)

@app.get("/health")
async def health_check():
    """Endpoint de vérification de santé du service"""
    return {"status": "ok", "model": MODEL_NAME}

@app.post("/validate", response_model=ValidationResponse)
async def validate_semantic_similarity(
    request: ValidationRequest,
    groq_client: groq.Client = Depends(get_groq_client)
):
    """
    Valide la similarité sémantique entre deux questions en utilisant l'API Groq
    
    - cached_question: Question stockée dans le cache
    - user_question: Question posée par l'utilisateur
    - similarity_threshold: Seuil de similarité (entre 0 et 1)
    
    Retourne:
    - is_similar: True si les questions sont sémantiquement similaires
    - confidence: Niveau de confiance (entre 0 et 1)
    - explanation: Explication de la décision
    """
    try:
        # Construction du prompt pour Groq
        prompt = f"""
        Tu es un expert en analyse sémantique. Ta tâche est d'évaluer si deux questions sont sémantiquement similaires,
        c'est-à-dire si elles demandent essentiellement la même information, même si elles sont formulées différemment.

        Question 1: "{request.cached_question}"
        Question 2: "{request.user_question}"

        Analyse en détail la similarité sémantique entre ces deux questions. Considère:
        1. L'intention principale de chaque question
        2. Les entités ou concepts clés mentionnés
        3. Le type d'information demandée
        4. Les contraintes ou conditions spécifiées

        Détermine si ces questions sont sémantiquement similaires avec un seuil de similarité de {request.similarity_threshold}.
        
        Réponds UNIQUEMENT au format JSON suivant:
        {{
            "is_similar": true/false,
            "confidence": 0.0-1.0,
            "explanation": "Ton explication détaillée"
        }}
        """

        # Appel à l'API Groq
        logger.info(f"Envoi de la requête à Groq avec le modèle {MODEL_NAME}")
        response = groq_client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "Tu es un assistant spécialisé dans l'analyse sémantique qui répond uniquement au format JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2,
            max_tokens=1000
        )

        # Extraction de la réponse
        response_text = response.choices[0].message.content
        logger.info(f"Réponse de Groq: {response_text}")
        
        # Tentative de parsing du JSON
        import json
        try:
            result = json.loads(response_text)
            # Vérification des champs requis
            if "is_similar" not in result or "confidence" not in result or "explanation" not in result:
                raise ValueError("Réponse JSON incomplète")
            
            return ValidationResponse(
                is_similar=result["is_similar"],
                confidence=result["confidence"],
                explanation=result["explanation"]
            )
        except json.JSONDecodeError:
            # Si le parsing JSON échoue, tentative d'extraction manuelle
            logger.warning("Échec du parsing JSON, tentative d'extraction manuelle")
            
            # Extraction manuelle basique
            is_similar = "true" in response_text.lower() and "false" not in response_text.lower()
            confidence = 0.7  # Valeur par défaut
            explanation = response_text
            
            return ValidationResponse(
                is_similar=is_similar,
                confidence=confidence,
                explanation="Extraction manuelle: " + explanation[:200] + "..."
            )
            
    except Exception as e:
        logger.error(f"Erreur lors de l'appel à l'API Groq: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur lors de l'appel à l'API Groq: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
