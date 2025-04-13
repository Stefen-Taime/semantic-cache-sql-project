#!/usr/bin/env python3
"""
Service de génération Text-to-SQL pour le projet de mise en cache sémantique
Utilise l'API Groq pour générer des requêtes SQL à partir de questions en langage naturel
"""
import os
from typing import Dict, Any, Optional, List
from pydantic import BaseModel
from fastapi import FastAPI, HTTPException, Depends
import groq
import logging
from dotenv import load_dotenv
import re
import json

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

app = FastAPI(title="Service de Génération Text-to-SQL", 
              description="Service pour générer des requêtes SQL à partir de questions en langage naturel")

# Modèles de données
class TextToSQLRequest(BaseModel):
    question: str
    schema_info: Optional[str] = None
    table_examples: Optional[Dict[str, List[Dict[str, Any]]]] = None

class TextToSQLResponse(BaseModel):
    sql_query: str
    explanation: str
    confidence: float

# Initialisation du client Groq
def get_groq_client():
    if not GROQ_API_KEY:
        raise HTTPException(status_code=500, detail="GROQ_API_KEY non configurée")
    return groq.Client(api_key=GROQ_API_KEY)

@app.get("/health")
async def health_check():
    """Endpoint de vérification de santé du service"""
    return {"status": "ok", "model": MODEL_NAME}

@app.post("/generate-sql", response_model=TextToSQLResponse)
async def generate_sql_from_text(
    request: TextToSQLRequest,
    groq_client: groq.Client = Depends(get_groq_client)
):
    """
    Génère une requête SQL à partir d'une question en langage naturel
    
    - question: Question en langage naturel
    - schema_info: (Optionnel) Informations sur le schéma de la base de données
    - table_examples: (Optionnel) Exemples de données pour chaque table
    
    Retourne:
    - sql_query: Requête SQL générée
    - explanation: Explication de la requête SQL
    - confidence: Niveau de confiance (entre 0 et 1)
    """
    try:
        # Construction du prompt pour Groq
        schema_context = f"\nInformations sur le schéma de la base de données:\n{request.schema_info}" if request.schema_info else ""
        
        # Ajouter des exemples de données si disponibles
        examples_context = ""
        if request.table_examples:
            examples_context = "\nExemples de données dans les tables:\n"
            for table_name, rows in request.table_examples.items():
                examples_context += f"\nTable {table_name}:\n"
                if rows:
                    # Afficher les en-têtes
                    headers = list(rows[0].keys())
                    examples_context += "| " + " | ".join(headers) + " |\n"
                    examples_context += "| " + " | ".join(["---" for _ in headers]) + " |\n"
                    
                    # Afficher les données (limité à 5 lignes)
                    for row in rows[:5]:
                        examples_context += "| " + " | ".join([str(row.get(h, "")) for h in headers]) + " |\n"
        
        prompt = f"""
        Tu es un expert en SQL PostgreSQL. Ta tâche est de générer une requête SQL valide à partir d'une question en langage naturel.

        Question: "{request.question}"{schema_context}{examples_context}

        INSTRUCTIONS IMPORTANTES:
        1. Génère une requête SQL qui répond précisément à cette question.
        2. TOUJOURS définir des alias pour CHAQUE table utilisée (par exemple "FROM customers c" et non "FROM customers").
        3. TOUJOURS utiliser l'alias défini pour référencer les colonnes (par exemple "c.first_name" et non "customers.first_name").
        4. Si tu utilises plusieurs fois la même table (pour des sous-requêtes ou des auto-jointures), utilise des alias différents (p1, p2, etc.).
        5. Lorsque tu joins plusieurs tables, TOUJOURS spécifier la condition de jointure.
        6. Pour les requêtes d'agrégation (COUNT, SUM, AVG), TOUJOURS inclure toutes les colonnes non agrégées dans la clause GROUP BY.
        7. Les noms des tables principales sont: customers, products, orders, order_items.
        8. Les structures de jointure les plus courantes sont:
           - customers (c) ⟷ orders (o) via c.id = o.customer_id
           - orders (o) ⟷ order_items (oi) via o.id = oi.order_id
           - products (p) ⟷ order_items (oi) via p.id = oi.product_id

        Réponds UNIQUEMENT au format JSON suivant:
        {{
            "sql_query": "La requête SQL générée",
            "explanation": "Explication détaillée de la requête SQL et de son fonctionnement",
            "confidence": 0.0-1.0
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
        try:
            # Tentative 1: Parsing direct du JSON
            try:
                result = json.loads(response_text)
                if "sql_query" not in result or "explanation" not in result:
                    raise ValueError("Réponse JSON incomplète")
                
                # Si confidence n'est pas présent, utiliser une valeur par défaut
                confidence = result.get("confidence", 0.8)
                
                # Vérifier que la requête SQL contient des alias correctement définis
                sql_query = result["sql_query"]
                if not _validate_sql_aliases(sql_query):
                    logger.warning("La requête SQL générée ne contient pas d'alias correctement définis")
                    sql_query = _fix_sql_aliases(sql_query)
                    result["explanation"] += "\n\nNote: La requête a été automatiquement corrigée pour utiliser des alias de tables."
                
                return TextToSQLResponse(
                    sql_query=sql_query,
                    explanation=result["explanation"],
                    confidence=confidence
                )
            
            except json.JSONDecodeError:
                # Tentative 2: Extraction du bloc JSON dans le texte
                json_block_match = re.search(r'```json\s*(\{.*?\})\s*```', response_text, re.DOTALL)
                if json_block_match:
                    try:
                        result = json.loads(json_block_match.group(1))
                        if "sql_query" in result and "explanation" in result:
                            confidence = result.get("confidence", 0.8)
                            sql_query = result["sql_query"]
                            
                            if not _validate_sql_aliases(sql_query):
                                sql_query = _fix_sql_aliases(sql_query)
                            
                            return TextToSQLResponse(
                                sql_query=sql_query,
                                explanation=result["explanation"],
                                confidence=confidence
                            )
                    except json.JSONDecodeError:
                        pass
                
                # Si le JSON ne peut pas être extrait, passer à l'extraction de la requête SQL
                raise ValueError("Échec de l'extraction JSON")
                
        except Exception as json_error:
            # Si toutes les tentatives de parsing JSON échouent, passer à l'extraction manuelle
            logger.warning(f"Échec du parsing JSON: {json_error}, tentative d'extraction manuelle")
            
            # Extraction manuelle de la requête SQL
            sql_query = _extract_sql_query(response_text)
            
            # Vérifier et corriger les alias dans la requête extraite
            if not _validate_sql_aliases(sql_query):
                sql_query = _fix_sql_aliases(sql_query)
            
            logger.info(f"Requête SQL extraite manuellement: {sql_query}")
            
            return TextToSQLResponse(
                sql_query=sql_query,
                explanation="Extraction manuelle: Impossible de parser la réponse JSON complète.",
                confidence=0.5
            )
            
    except Exception as e:
        logger.error(f"Erreur lors de l'appel à l'API Groq: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur lors de l'appel à l'API Groq: {str(e)}")

def _extract_sql_query(text):
    """Extrait une requête SQL complète d'un texte"""
    # Essayer d'extraire d'un contenu JSON
    try:
        if text.strip().startswith('{') and text.strip().endswith('}'):
            # On a probablement du JSON, essayons de l'analyser
            json_content = json.loads(text)
            if "sql_query" in json_content:
                return json_content["sql_query"]
    except:
        pass
    
    # Essayer d'extraire d'un bloc de code
    sql_match = re.search(r'```(?:sql)?\s*(SELECT\s+.*?)\s*```', text, re.DOTALL | re.IGNORECASE)
    if sql_match:
        sql_text = sql_match.group(1).strip()
        if sql_text.endswith(';'):
            sql_text = sql_text[:-1]
        return sql_text
    
    # Essayer d'extraire une requête SQL directement formatée sans délimiteurs
    # Capturer la requête complète avec toutes les clauses
    sql_pattern = r'(SELECT\s+.+?FROM\s+.+?(?:WHERE\s+.+?)?(?:GROUP\s+BY\s+.+?)?(?:ORDER\s+BY\s+.+?)?(?:LIMIT\s+\d+)?(?:;)?)'
    sql_match = re.search(sql_pattern, text, re.DOTALL | re.IGNORECASE)
    if sql_match:
        sql_text = sql_match.group(1).strip()
        if sql_text.endswith(';'):
            sql_text = sql_text[:-1]
        return sql_text
    
    # Chercher spécifiquement les requêtes dans un format JSON mais pas un objet JSON complet
    if '"sql_query"' in text:
        # Essayer avec une regex plus inclusive pour capturer toute la requête
        sql_pattern = r'"sql_query":\s*"(SELECT\s+.+?(?:;|"))'
        sql_match = re.search(sql_pattern, text, re.DOTALL | re.IGNORECASE)
        if sql_match:
            sql_text = sql_match.group(1).strip()
            # Supprimer les caractères d'échappement JSON
            sql_text = sql_text.replace('\\n', ' ').replace('\\t', ' ').replace('\\"', '"')
            # Supprimer le point-virgule ou guillemet final s'il existe
            if sql_text.endswith(';'):
                sql_text = sql_text[:-1]
            if sql_text.endswith('"'):
                sql_text = sql_text[:-1]
            return sql_text
    
    # Extraction plus agressive en cas d'échec des méthodes précédentes
    # Chercher simplement une requête SELECT complète
    select_pattern = r'(SELECT\s+.+?FROM\s+\w+(?:\s+\w+)?(?:\s+.+)?)'
    select_match = re.search(select_pattern, text, re.DOTALL | re.IGNORECASE)
    if select_match:
        return select_match.group(1).strip()
    
    # Si aucune requête n'est trouvée, retourner une requête par défaut
    return "SELECT * FROM customers c LIMIT 10"  # Requête par défaut avec alias

def _validate_sql_aliases(sql_query):
    """
    Vérifie si une requête SQL utilise correctement des alias pour les tables
    """
    if not sql_query:
        return False
    
    # Extraction de la clause FROM
    from_match = re.search(r'FROM\s+(.*?)(?:WHERE|GROUP BY|ORDER BY|LIMIT|;|$)', sql_query, re.IGNORECASE | re.DOTALL)
    if not from_match:
        return False
    
    from_clause = from_match.group(1).strip()
    
    # Rechercher les définitions d'alias dans la clause FROM
    # Format typique: table [AS] alias
    alias_pattern = r'(\w+)(?:\s+(?:AS\s+)?|\s+)([a-zA-Z][a-zA-Z0-9_]*)\b'
    aliases_found = re.findall(alias_pattern, from_clause, re.IGNORECASE)
    
    # Rechercher les alias définis dans les jointures
    join_pattern = r'JOIN\s+(\w+)(?:\s+(?:AS\s+)?|\s+)([a-zA-Z][a-zA-Z0-9_]*)\b'
    join_aliases = re.findall(join_pattern, sql_query, re.IGNORECASE)
    
    # Vérifier s'il y a au moins un alias défini
    return len(aliases_found) > 0 or len(join_aliases) > 0

def _fix_sql_aliases(sql_query):
    """
    Ajoute des alias aux tables dans une requête SQL qui n'en a pas
    """
    if not sql_query or len(sql_query.strip()) < 10:
        return "SELECT * FROM customers c LIMIT 10"  # Requête par défaut avec alias
    
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
    
    # Si on a une clause JOIN sans alias, ajouter les alias
    for table, alias in table_aliases.items():
        join_pattern = r'(JOIN\s+' + table + r')(?!\s+[a-zA-Z])'
        if re.search(join_pattern, new_sql, re.IGNORECASE):
            new_sql = re.sub(join_pattern, f"\\1 {alias}", new_sql, flags=re.IGNORECASE)
    
    # S'assurer que la requête a une syntaxe correcte
    if "GROUP BY" in new_sql.upper():
        # Vérifier que les colonnes du SELECT sont toutes dans le GROUP BY
        select_match = re.search(r'SELECT\s+(.*?)\s+FROM', new_sql, re.IGNORECASE | re.DOTALL)
        group_by_match = re.search(r'GROUP BY\s+(.*?)(?:ORDER BY|LIMIT|;|$)', new_sql, re.IGNORECASE | re.DOTALL)
        
        if select_match and group_by_match:
            select_cols = [col.strip() for col in select_match.group(1).split(',')]
            group_by_cols = [col.strip() for col in group_by_match.group(1).split(',')]
            
            # Identifier les colonnes non agrégées dans SELECT qui ne sont pas dans GROUP BY
            non_agg_cols = []
            for col in select_cols:
                # Ignorer les colonnes avec fonctions d'agrégation
                if not re.search(r'(COUNT|SUM|AVG|MIN|MAX|GROUP_CONCAT)\s*\(', col, re.IGNORECASE):
                    # Ignorer les alias de colonnes
                    if " AS " in col.upper():
                        col = col.split(" AS ")[0].strip()
                    if col not in group_by_cols:
                        non_agg_cols.append(col)
            
            # Si nécessaire, ajouter les colonnes manquantes au GROUP BY
            if non_agg_cols:
                new_group_by = group_by_match.group(1) + ", " + ", ".join(non_agg_cols)
                new_sql = new_sql.replace(group_by_match.group(0), f"GROUP BY {new_group_by}")
    
    return new_sql

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)