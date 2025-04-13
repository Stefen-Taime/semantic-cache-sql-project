#!/usr/bin/env python3
"""
Service de modification SQL pour le projet de mise en cache sémantique
Utilise l'API Groq pour modifier une requête SQL existante en fonction des nouveaux paramètres
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

app = FastAPI(title="Service de Modification SQL", 
              description="Service pour modifier une requête SQL existante en fonction des nouveaux paramètres")

# Modèles de données
class SQLModificationRequest(BaseModel):
    original_question: str
    new_question: str
    original_sql_query: str
    schema_info: Optional[str] = None

class SQLModificationResponse(BaseModel):
    modified_sql_query: str
    explanation: str
    parameters_changed: Dict[str, Any]

# Initialisation du client Groq
def get_groq_client():
    if not GROQ_API_KEY:
        raise HTTPException(status_code=500, detail="GROQ_API_KEY non configurée")
    return groq.Client(api_key=GROQ_API_KEY)

@app.get("/health")
async def health_check():
    """Endpoint de vérification de santé du service"""
    return {"status": "ok", "model": MODEL_NAME}

@app.post("/modify", response_model=SQLModificationResponse)
async def modify_sql_query(
    request: SQLModificationRequest,
    groq_client: groq.Client = Depends(get_groq_client)
):
    """
    Modifie une requête SQL existante en fonction des nouveaux paramètres
    
    - original_question: Question originale qui a généré la requête SQL
    - new_question: Nouvelle question avec des paramètres différents
    - original_sql_query: Requête SQL originale à modifier
    - schema_info: (Optionnel) Informations sur le schéma de la base de données
    
    Retourne:
    - modified_sql_query: Requête SQL modifiée
    - explanation: Explication des modifications apportées
    - parameters_changed: Dictionnaire des paramètres qui ont été modifiés
    """
    try:
        # Construction du prompt pour Groq
        schema_context = f"\nInformations sur le schéma de la base de données:\n{request.schema_info}" if request.schema_info else ""
        
        prompt = f"""
        Tu es un expert en SQL PostgreSQL et en analyse sémantique. Ta tâche est de modifier une requête SQL existante 
        pour l'adapter à une nouvelle question, tout en conservant la structure générale de la requête.

        Question originale: "{request.original_question}"
        Requête SQL originale: 
        ```sql
        {request.original_sql_query}
        ```

        Nouvelle question: "{request.new_question}"{schema_context}

        INSTRUCTIONS IMPORTANTES:
        1. Analyse les différences entre les deux questions et modifie la requête SQL en conséquence.
        2. CONSERVE les alias de tables déjà définis dans la requête originale.
        3. Si tu ajoutes de nouvelles tables, TOUJOURS définir un alias pour chacune d'elles.
        4. TOUJOURS référencer les colonnes avec leurs alias de table (ex: c.name et non name).
        5. Si tu modifies les conditions, assure-toi qu'elles utilisent les mêmes alias que dans la requête originale.
        6. Vérifie que toutes les jointures sont correctement définies avec leurs conditions.
        7. Pour les requêtes avec GROUP BY, assure-toi que toutes les colonnes non agrégées du SELECT sont dans le GROUP BY.
        8. Les noms des tables principales sont: customers, products, orders, order_items.
        9. Les structures de jointure les plus courantes sont:
           - customers (c) ⟷ orders (o) via c.id = o.customer_id
           - orders (o) ⟷ order_items (oi) via o.id = oi.order_id
           - products (p) ⟷ order_items (oi) via p.id = oi.product_id

        Réponds UNIQUEMENT au format JSON suivant:
        {{
            "modified_sql_query": "La requête SQL modifiée",
            "explanation": "Explication détaillée des modifications apportées",
            "parameters_changed": {{
                "paramètre1": "ancienne valeur -> nouvelle valeur",
                "paramètre2": "ancienne valeur -> nouvelle valeur"
            }}
        }}
        """

        # Appel à l'API Groq
        logger.info(f"Envoi de la requête à Groq avec le modèle {MODEL_NAME}")
        response = groq_client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "Tu es un assistant spécialisé en SQL qui répond uniquement au format JSON."},
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
            if "modified_sql_query" not in result or "explanation" not in result or "parameters_changed" not in result:
                raise ValueError("Réponse JSON incomplète")
            
            # Vérifier que la requête SQL contient des alias correctement définis
            modified_sql = result["modified_sql_query"]
            if not _validate_sql_aliases(modified_sql):
                logger.warning("La requête SQL générée ne contient pas d'alias correctement définis")
                modified_sql = _fix_sql_aliases(modified_sql)
                result["explanation"] += "\n\nNote: La requête a été automatiquement corrigée pour utiliser des alias de tables."
            
            return SQLModificationResponse(
                modified_sql_query=modified_sql,
                explanation=result["explanation"],
                parameters_changed=result["parameters_changed"]
            )
        except json.JSONDecodeError:
            # Si le parsing JSON échoue, tentative d'extraction manuelle
            logger.warning("Échec du parsing JSON, tentative d'extraction manuelle")
            
            # Extraction manuelle basique
            import re
            
            # Tenter d'extraire la requête SQL
            sql_match = re.search(r'```sql\s*(.*?)\s*```', response_text, re.DOTALL)
            if sql_match:
                modified_sql = sql_match.group(1).strip()
            else:
                # Chercher une requête SQL sans les backticks
                sql_match = re.search(r'SELECT\s+.*?FROM\s+.*?(?:WHERE\s+.*?)?(?:GROUP BY\s+.*?)?(?:ORDER BY\s+.*?)?(?:LIMIT\s+\d+)?', response_text, re.DOTALL | re.IGNORECASE)
                if sql_match:
                    modified_sql = sql_match.group(0).strip()
                else:
                    modified_sql = request.original_sql_query  # Utiliser la requête originale en cas d'échec
            
            # S'assurer que la requête extraite manuellement contient des alias
            if not _validate_sql_aliases(modified_sql):
                modified_sql = _fix_sql_aliases(modified_sql)
            
            return SQLModificationResponse(
                modified_sql_query=modified_sql,
                explanation="Extraction manuelle: Impossible de parser la réponse JSON complète.",
                parameters_changed={"extraction_manuelle": "true"}
            )
            
    except Exception as e:
        logger.error(f"Erreur lors de l'appel à l'API Groq: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur lors de l'appel à l'API Groq: {str(e)}")

def _validate_sql_aliases(sql_query):
    """
    Vérifie si une requête SQL utilise correctement des alias pour les tables
    """
    if not sql_query:
        return False
    
    # Extraction de la clause FROM
    import re
    from_match = re.search(r'FROM\s+(.*?)(?:WHERE|GROUP BY|ORDER BY|LIMIT|;|$)', sql_query, re.IGNORECASE | re.DOTALL)
    if not from_match:
        return False
    
    from_clause = from_match.group(1).strip()
    
    # Rechercher les définitions d'alias dans la clause FROM
    # Format typique: table [AS] alias
    alias_pattern = r'(\w+)(?:\s+(?:AS\s+)?|\s+)([a-zA-Z][a-zA-Z0-9_]*)\b'
    aliases_found = re.findall(alias_pattern, from_clause, re.IGNORECASE)
    
    # Vérifier s'il y a au moins un alias défini
    return len(aliases_found) > 0

def _fix_sql_aliases(sql_query):
    """
    Ajoute des alias aux tables dans une requête SQL qui n'en a pas
    """
    if not sql_query:
        return sql_query
    
    import re
    
    # Extraction de la clause FROM
    from_match = re.search(r'FROM\s+(.*?)(?:WHERE|GROUP BY|ORDER BY|LIMIT|;|$)', sql_query, re.IGNORECASE | re.DOTALL)
    if not from_match:
        return sql_query
    
    from_clause = from_match.group(1).strip()
    new_from_clause = from_clause
    
    # Table mappings avec alias standards
    table_aliases = {
        "customers": "c",
        "products": "p",
        "orders": "o",
        "order_items": "oi"
    }
    
    # Ajouter des alias aux tables si elles n'en ont pas déjà
    for table, alias in table_aliases.items():
        # Vérifier si la table est présente sans alias
        table_pattern = r'\b' + table + r'\b(?!\s+[a-zA-Z])'
        if re.search(table_pattern, new_from_clause, re.IGNORECASE):
            new_from_clause = re.sub(table_pattern, f"{table} {alias}", new_from_clause, flags=re.IGNORECASE)
    
    # Remplacer l'ancienne clause FROM par la nouvelle
    new_sql = sql_query.replace(from_clause, new_from_clause)
    
    # Ajouter les alias aux colonnes dans SELECT, WHERE, GROUP BY, etc.
    for table, alias in table_aliases.items():
        # Rechercher les colonnes sans alias qui appartiennent à cette table
        # Par exemple: "name" ou "first_name" de la table "customers"
        if table == "customers":
            columns = ["id", "first_name", "last_name", "email", "state", "status"]
        elif table == "products":
            columns = ["id", "name", "description", "category", "price", "stock_quantity"]
        elif table == "orders":
            columns = ["id", "customer_id", "order_date", "status", "total_amount"]
        elif table == "order_items":
            columns = ["id", "order_id", "product_id", "quantity", "unit_price"]
        else:
            continue
        
        for column in columns:
            # Remplacer les occurrences de "column" qui ne sont pas déjà préfixées par un alias
            # mais seulement dans le contexte de la table appropriée
            column_pattern = r'(?<!\w\.)' + column + r'\b'
            
            # Dans la clause SELECT
            select_match = re.search(r'SELECT\s+(.*?)FROM', new_sql, re.IGNORECASE | re.DOTALL)
            if select_match:
                select_clause = select_match.group(1)
                if table in from_clause or table in new_from_clause:
                    new_select_clause = re.sub(column_pattern, f"{alias}.{column}", select_clause)
                    new_sql = new_sql.replace(select_clause, new_select_clause)
            
            # Dans la clause WHERE
            where_match = re.search(r'WHERE\s+(.*?)(?:GROUP BY|ORDER BY|LIMIT|;|$)', new_sql, re.IGNORECASE | re.DOTALL)
            if where_match:
                where_clause = where_match.group(1)
                if table in from_clause or table in new_from_clause:
                    new_where_clause = re.sub(column_pattern, f"{alias}.{column}", where_clause)
                    new_sql = new_sql.replace(where_clause, new_where_clause)
    
    return new_sql

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)