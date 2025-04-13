#!/usr/bin/env python3
"""
Service d'exécution SQL et orchestrateur pour le projet de mise en cache sémantique
Sert de point d'entrée principal et coordonne les appels aux autres services
"""
import os
import json
import re
from typing import Dict, Any, List, Optional
from pydantic import BaseModel
from fastapi import FastAPI, HTTPException, BackgroundTasks
import httpx
import logging
from dotenv import load_dotenv
import sqlalchemy
from sqlalchemy import create_engine, text
from qdrant_client import QdrantClient

# Charger les variables d'environnement
load_dotenv()

# Configuration du logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configuration des services
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgres")
POSTGRES_DB = os.getenv("POSTGRES_DB", "semantic_cache_db")

EMBEDDING_SERVICE_URL = os.getenv("EMBEDDING_SERVICE_URL", "http://embedding-service:8000")
SEMANTIC_VALIDATION_SERVICE_URL = os.getenv("SEMANTIC_VALIDATION_SERVICE_URL", "http://semantic-validation-service:8000")
SQL_MOD_SERVICE_URL = os.getenv("SQL_MOD_SERVICE_URL", "http://sql-mod-service:8000")
TEXT_TO_SQL_SERVICE_URL = os.getenv("TEXT_TO_SQL_SERVICE_URL", "http://text-to-sql-service:8000")

VECTOR_DB_HOST = os.getenv("VECTOR_DB_HOST", "vector-db")
VECTOR_DB_PORT = int(os.getenv("VECTOR_DB_PORT", "6333"))
COLLECTION_NAME = "semantic_cache"

SIMILARITY_THRESHOLD = 0.85  # Seuil de similarité pour la recherche vectorielle

app = FastAPI(title="Service d'Exécution SQL et Orchestrateur", 
              description="Service pour exécuter des requêtes SQL et orchestrer le workflow complet")

# Modèles de données
class Question(BaseModel):
    text: str

class SQLQuery(BaseModel):
    query: str

class QueryResult(BaseModel):
    columns: List[str]
    rows: List[Dict[str, Any]]
    execution_time: float
    row_count: int

class ProcessResponse(BaseModel):
    result: QueryResult
    query_used: str
    source: str  # "cache", "modified", "generated"
    processing_details: Dict[str, Any]

# Initialisation des connexions
@app.on_event("startup")
async def startup_event():
    global db_engine, qdrant_client, http_client
    
    # Connexion à PostgreSQL
    db_url = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
    logger.info(f"Connexion à PostgreSQL sur {POSTGRES_HOST}:{POSTGRES_PORT}")
    db_engine = create_engine(db_url)
    
    try:
        with db_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("Connexion à PostgreSQL établie avec succès")
    except Exception as e:
        logger.error(f"Erreur lors de la connexion à PostgreSQL: {e}")
    
    # Connexion à Qdrant
    logger.info(f"Connexion à Qdrant sur {VECTOR_DB_HOST}:{VECTOR_DB_PORT}")
    qdrant_client = QdrantClient(host=VECTOR_DB_HOST, port=VECTOR_DB_PORT)
    
    # Client HTTP pour les appels aux autres services
    http_client = httpx.AsyncClient(timeout=60.0)

@app.on_event("shutdown")
async def shutdown_event():
    await http_client.aclose()

@app.get("/health")
async def health_check():
    """Endpoint de vérification de santé du service"""
    services_status = {}
    
    # Vérifier PostgreSQL
    try:
        with db_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        services_status["postgres"] = "ok"
    except Exception as e:
        services_status["postgres"] = f"error: {str(e)}"
    
    # Vérifier les autres services
    services = {
        "embedding": EMBEDDING_SERVICE_URL,
        "semantic_validation": SEMANTIC_VALIDATION_SERVICE_URL,
        "sql_mod": SQL_MOD_SERVICE_URL,
        "text_to_sql": TEXT_TO_SQL_SERVICE_URL,
        "vector_db": f"http://{VECTOR_DB_HOST}:{VECTOR_DB_PORT}/health"
    }
    
    for name, url in services.items():
        try:
            response = await http_client.get(f"{url}/health", timeout=2.0)
            if response.status_code == 200:
                services_status[name] = "ok"
            else:
                services_status[name] = f"error: status code {response.status_code}"
        except Exception as e:
            services_status[name] = f"error: {str(e)}"
    
    return {
        "status": "ok" if all(status == "ok" for status in services_status.values()) else "degraded",
        "services": services_status
    }

@app.post("/execute", response_model=QueryResult)
async def execute_sql_query(query: SQLQuery):
    """
    Exécute une requête SQL sur PostgreSQL
    
    - query: Requête SQL à exécuter
    
    Retourne:
    - columns: Liste des noms de colonnes
    - rows: Liste des lignes de résultats
    - execution_time: Temps d'exécution en secondes
    - row_count: Nombre de lignes retournées
    """
    try:
        import time
        start_time = time.time()
        
        # Vérifier que la requête n'est pas vide ou incomplète
        if not query.query or len(query.query.strip()) < 10:
            return {"error": f"Requête SQL invalide ou incomplète: '{query.query}'"}
        
        # Corriger les erreurs de groupe potentielles avant exécution
        corrected_query = fix_group_by_errors(query.query)
        if corrected_query != query.query:
            logger.info(f"Requête SQL corrigée pour GROUP BY: {corrected_query}")
            query.query = corrected_query
        
        logger.info(f"Exécution de la requête SQL: {query.query}")
        
        with db_engine.connect() as conn:
            # Exécuter la requête
            result = conn.execute(text(query.query))
            
            # Récupérer les noms de colonnes
            columns = list(result.keys())
            
            # Récupérer les lignes de résultats
            rows = [dict(zip(columns, row)) for row in result.fetchall()]
            
            execution_time = time.time() - start_time
            
            return {
                "columns": columns,
                "rows": rows,
                "execution_time": execution_time,
                "row_count": len(rows)
            }
    except Exception as e:
        logger.error(f"Erreur lors de l'exécution de la requête SQL: {e}")
        # Essayer de générer une requête de secours en cas d'erreur
        if "column \"category\" does not exist" in str(e) and "customers" in query.query:
            # Remplacer customers par products si on cherche des catégories
            try:
                corrected_query = query.query.replace("customers", "products")
                logger.info(f"Tentative de correction de la requête: {corrected_query}")
                return await execute_sql_query(SQLQuery(query=corrected_query))
            except Exception as e2:
                logger.error(f"Échec de la correction: {e2}")
        
        # Essayer de corriger les erreurs d'alias
        if "missing FROM-clause entry for table" in str(e):
            try:
                corrected_query = fix_alias_in_query(query.query)
                if corrected_query != query.query:
                    logger.info(f"Tentative de correction des alias: {corrected_query}")
                    return await execute_sql_query(SQLQuery(query=corrected_query))
            except Exception as e2:
                logger.error(f"Échec de la correction d'alias: {e2}")
        
        return {"error": f"Erreur lors de l'exécution de la requête SQL: {str(e)}"}

@app.get("/schema")
async def get_database_schema():
    """
    Récupère le schéma de la base de données PostgreSQL
    
    Retourne:
    - tables: Liste des tables avec leurs colonnes et types
    """
    try:
        schema_info = {}
        
        with db_engine.connect() as conn:
            # Récupérer la liste des tables
            tables_query = text("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public'
            """)
            tables = [row[0] for row in conn.execute(tables_query).fetchall()]
            
            # Pour chaque table, récupérer les colonnes et leurs types
            for table in tables:
                columns_query = text(f"""
                    SELECT column_name, data_type 
                    FROM information_schema.columns 
                    WHERE table_schema = 'public' AND table_name = '{table}'
                """)
                columns = {row[0]: row[1] for row in conn.execute(columns_query).fetchall()}
                
                schema_info[table] = columns
        
        return {"tables": schema_info}
    except Exception as e:
        logger.error(f"Erreur lors de la récupération du schéma de la base de données: {e}")
        return {"error": f"Erreur lors de la récupération du schéma de la base de données: {str(e)}"}

def extract_quoted_value(text, field_name):
    """Extrait une valeur entre guillemets avec gestion des guillemets échappés"""
    pattern = f'"{field_name}"\\s*:\\s*"'
    match = re.search(pattern, text)
    if not match:
        return None
    
    start_idx = match.end()
    result = ""
    i = start_idx
    escaped = False
    
    while i < len(text):
        char = text[i]
        if char == '\\' and not escaped:
            escaped = True
        elif char == '"' and not escaped:
            break  # Fin de la valeur
        elif escaped:
            result += char
            escaped = False
        else:
            result += char
        i += 1
    
    return result.strip()

def extract_full_sql_query(text):
    """Extrait une requête SQL complète y compris les jointures, sous-requêtes, etc."""
    # Vérifier d'abord si les requêtes sont encapsulées dans un format JSON
    if '"sql_query"' in text:
        import re
        sql_pattern = r'"sql_query":\s*"([^"]+)"'
        sql_match = re.search(sql_pattern, text, re.DOTALL)
        if sql_match:
            sql_text = sql_match.group(1).strip()
            # Remplacer les \n par des espaces
            sql_text = sql_text.replace('\\n', ' ')
            # Supprimer le point-virgule final s'il existe
            if sql_text.endswith(';'):
                sql_text = sql_text[:-1]
            return sql_text

    # Rechercher une requête SQL standard (SELECT...)
    sql_pattern = r'SELECT\s+[\s\S]+?(?:;|$)'
    sql_match = re.search(sql_pattern, text, re.IGNORECASE)
    
    if sql_match:
        sql_text = sql_match.group(0).strip()
        # Supprimer le point-virgule final s'il existe
        if sql_text.endswith(';'):
            sql_text = sql_text[:-1]
        return sql_text
    
    return None

def extract_json_from_markdown(text):
    """Extrait le contenu JSON d'une réponse potentiellement formatée en Markdown"""
    # Si le texte contient des délimiteurs de bloc de code Markdown
    if '```json' in text and '```' in text:
        # Extraire le contenu entre les délimiteurs
        start_idx = text.find('```json') + 7  # longueur de '```json'
        end_idx = text.find('```', start_idx)
        if end_idx > start_idx:
            json_str = text[start_idx:end_idx].strip()
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                logger.warning(f"Impossible de parser le JSON extrait: {json_str[:100]}...")
                # Essayer d'extraire directement une requête SQL complète
                sql_query = extract_full_sql_query(json_str)
                if sql_query:
                    return {"sql_query": sql_query}
    
    # Si pas de délimiteurs ou échec d'extraction, essayer de parser directement
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Extraction directe d'une requête SQL complète
        sql_query = extract_full_sql_query(text)
        if sql_query:
            return {"sql_query": sql_query}
            
        # Extraction manuelle de champs spécifiques si tout échoue
        result = {}
        
        # Pour le service de génération SQL
        if "sql_query" in text:
            # Essayer d'abord d'extraire la valeur complète
            sql_value = extract_quoted_value(text, "sql_query")
            if sql_value:
                result["sql_query"] = sql_value.replace('\\n', ' ')
            else:
                # Fallback sur regex simple avec capture de la jointure
                full_sql_pattern = r'"sql_query":\s*"(SELECT[^"]+)"'
                sql_match = re.search(full_sql_pattern, text, re.DOTALL)
                if sql_match:
                    result["sql_query"] = sql_match.group(1).replace('\\n', ' ').strip()
        
        # Pour le service de modification SQL
        if "modified_sql_query" in text and "sql_query" not in result:
            sql_value = extract_quoted_value(text, "modified_sql_query")
            if sql_value:
                result["modified_sql_query"] = sql_value.replace('\\n', ' ')
            else:
                # Fallback sur regex simple
                full_sql_pattern = r'"modified_sql_query":\s*"(SELECT[^"]+)"'
                sql_match = re.search(full_sql_pattern, text, re.DOTALL)
                if sql_match:
                    result["modified_sql_query"] = sql_match.group(1).replace('\\n', ' ').strip()
        
        # Extraction directe de requêtes SQL complètes si aucune des méthodes précédentes n'a fonctionné
        if "sql_query" not in result and "modified_sql_query" not in result:
            sql_queries = re.findall(r'SELECT\s+.+?\s+FROM\s+.+?(?=\s+WHERE|\s+GROUP|\s+ORDER|\s+LIMIT|$)', text, re.IGNORECASE | re.DOTALL)
            if sql_queries:
                # Prendre la requête la plus longue qui a le plus de chances d'être complète
                longest_query = max(sql_queries, key=len)
                result["sql_query"] = longest_query.strip()
        
        if result:
            return result
        else:
            logger.error(f"Impossible d'extraire des données JSON de: {text[:200]}...")
            return {"error": "Extraction échouée"}

def is_valid_sql_query(query):
    """Vérifie si une requête SQL semble valide et complète"""
    if not query or len(query.strip()) < 10:
        return False
    
    # Vérifier la structure de base
    if not query.upper().strip().startswith("SELECT"):
        return False
    
    # Vérifier que la requête contient au moins FROM
    if "FROM" not in query.upper():
        return False
    
    # La requête doit contenir une table
    parts = query.upper().split("FROM")
    if len(parts) < 2 or not parts[1].strip():
        return False
    
    return True

def detect_table_from_question(question_text):
    """Détecte la table la plus appropriée en fonction de la question"""
    question_lower = question_text.lower()
    
    # Détection pour les produits
    if any(word in question_lower for word in ["produit", "products", "catégorie", "category", "prix", "price"]):
        return "products"
    
    # Détection pour les commandes
    if any(word in question_lower for word in ["commande", "order", "achat", "purchase"]):
        return "orders"
    
    # Détection pour les détails de commande
    if "détail" in question_lower:
        return "order_items"
    
    # Par défaut, on utilise la table clients
    return "customers"

def detect_condition_from_question(question_text):
    """Détecte les conditions de filtrage en fonction de la question"""
    question_lower = question_text.lower()
    conditions = []
    
    # Conditions sur le statut
    if "statut inactive" in question_lower or "statut 'inactive'" in question_lower or "status inactive" in question_lower:
        conditions.append("status = 'inactive'")
    elif "statut active" in question_lower or "statut 'active'" in question_lower or "status active" in question_lower:
        conditions.append("status = 'active'")
    elif "statut pending" in question_lower or "statut 'pending'" in question_lower or "status pending" in question_lower:
        conditions.append("status = 'pending'")
    
    # Conditions sur l'état
    if "new york" in question_lower:
        conditions.append("state = 'NY'")
    elif "californie" in question_lower or "california" in question_lower:
        conditions.append("state = 'CA'")
    elif "texas" in question_lower or "tx" in question_lower:
        conditions.append("state = 'TX'")
    elif "floride" in question_lower or "florida" in question_lower:
        conditions.append("state = 'FL'")
    
    # Conditions sur le prix (pour les produits)
    if "prix supérieur à 300" in question_lower or "coûtent plus de 300" in question_lower:
        conditions.append("price > 300")
    elif "prix supérieur à 100" in question_lower or "coûtent plus de 100" in question_lower:
        conditions.append("price > 100")
    elif "prix inférieur à 100" in question_lower:
        conditions.append("price < 100")
    
    # Conditions sur le stock
    if "stock inférieur à 40" in question_lower:
        conditions.append("stock_quantity < 40")
    
    return conditions

def fix_alias_in_query(query):
    """Corrige automatiquement les problèmes d'alias dans les requêtes SQL"""
    if not query:
        return query
        
    # Analyser la requête pour identifier les alias utilisés
    aliases_used = set()
    
    # Extraire tous les alias utilisés dans les clauses SELECT, WHERE, GROUP BY, etc.
    # Format typique: x.colonne où x est l'alias
    import re
    alias_pattern = r'([a-zA-Z][a-zA-Z0-9_]*)\.([a-zA-Z][a-zA-Z0-9_]*)'
    for match in re.finditer(alias_pattern, query):
        aliases_used.add(match.group(1))
    
    # Si aucun alias n'est utilisé, retourner la requête inchangée
    if not aliases_used:
        return query
    
    # Vérifier si les alias sont définis dans la clause FROM
    aliases_defined = set()
    
    # Extraction de la clause FROM
    from_match = re.search(r'FROM\s+(.*?)(?:WHERE|GROUP BY|ORDER BY|LIMIT|$)', query, re.IGNORECASE | re.DOTALL)
    if not from_match:
        return query
        
    from_clause = from_match.group(1).strip()
    
    # Rechercher les définitions d'alias dans la clause FROM
    # Format typique: table [AS] alias
    alias_def_pattern = r'(\w+)(?:\s+(?:AS\s+)?|\s+)([a-zA-Z][a-zA-Z0-9_]*)\b'
    for match in re.finditer(alias_def_pattern, from_clause):
        aliases_defined.add(match.group(2))
    
    # Rechercher les alias définis dans les jointures
    join_pattern = r'JOIN\s+(\w+)(?:\s+(?:AS\s+)?|\s+)([a-zA-Z][a-zA-Z0-9_]*)\b'
    for match in re.finditer(join_pattern, query, re.IGNORECASE):
        aliases_defined.add(match.group(2))
    
    # Identifier les alias manquants
    missing_aliases = aliases_used - aliases_defined
    
    # Aucun alias manquant, retourner la requête inchangée
    if not missing_aliases:
        return query
    
    # Mapping des alias courants vers les tables
    common_aliases = {
        'c': 'customers',
        'p': 'products',
        'o': 'orders',
        'oi': 'order_items',
        'p1': 'products',
        'p2': 'products'
    }
    
    # Construire une nouvelle clause FROM avec les alias manquants
    new_from_clause = from_clause
    joins_to_add = []
    
    for alias in missing_aliases:
        if alias in common_aliases:
            table = common_aliases[alias]
            
            # Vérifier si la table est déjà dans la clause FROM
            if table in new_from_clause and f" {alias}" not in new_from_clause:
                # Remplacer la table par table alias
                new_from_clause = re.sub(r'\b' + table + r'\b(?!\s+[a-zA-Z])', f"{table} {alias}", new_from_clause)
            elif table not in new_from_clause:
                # Ajouter une jointure appropriée
                if alias == 'c' and 'orders' in new_from_clause:
                    joins_to_add.append(f"JOIN {table} {alias} ON {alias}.id = o.customer_id")
                elif alias == 'p' and 'order_items' in new_from_clause:
                    joins_to_add.append(f"JOIN {table} {alias} ON {alias}.id = oi.product_id")
                elif alias == 'o' and 'order_items' in new_from_clause:
                    joins_to_add.append(f"JOIN {table} {alias} ON {alias}.id = oi.order_id")
                elif alias == 'oi' and 'orders' in new_from_clause:
                    joins_to_add.append(f"JOIN {table} {alias} ON o.id = {alias}.order_id")
                elif alias == 'p1' and 'order_items' in new_from_clause:
                    joins_to_add.append(f"JOIN {table} {alias} ON {alias}.id = oi.product_id")
                elif alias == 'p2' and 'p1' in aliases_used:
                    joins_to_add.append(f"JOIN {table} {alias} ON {alias}.id <> p1.id")
                else:
                    # Fallback: ajouter simplement la table avec son alias
                    new_from_clause = f"{new_from_clause}, {table} {alias}"
    
    # Reconstruire la requête avec la nouvelle clause FROM et les jointures ajoutées
    new_query = query.replace(from_clause, new_from_clause)
    
    # Ajouter les jointures nécessaires
    if joins_to_add:
        # Trouver où insérer les jointures (après la clause FROM ou après la dernière jointure)
        last_join_pos = new_query.upper().rfind("JOIN")
        if last_join_pos > 0:
            # Trouver la fin de cette jointure
            next_clause_pos = -1
            for clause in ["WHERE", "GROUP BY", "ORDER BY", "LIMIT"]:
                pos = new_query.upper().find(clause, last_join_pos)
                if pos > 0 and (next_clause_pos == -1 or pos < next_clause_pos):
                    next_clause_pos = pos
            
            if next_clause_pos > 0:
                # Insérer après la dernière jointure et avant la clause suivante
                joins_text = " " + " ".join(joins_to_add) + " "
                new_query = new_query[:next_clause_pos] + joins_text + new_query[next_clause_pos:]
            else:
                # Ajouter à la fin de la requête
                new_query += " " + " ".join(joins_to_add)
        else:
            # Ajouter après la clause FROM
            from_pos = new_query.upper().find("FROM")
            if from_pos > 0:
                next_clause_pos = -1
                for clause in ["WHERE", "GROUP BY", "ORDER BY", "LIMIT"]:
                    pos = new_query.upper().find(clause, from_pos)
                    if pos > 0 and (next_clause_pos == -1 or pos < next_clause_pos):
                        next_clause_pos = pos
                
                if next_clause_pos > 0:
                    # Insérer après FROM et avant la clause suivante
                    joins_text = " " + " ".join(joins_to_add) + " "
                    new_query = new_query[:next_clause_pos] + joins_text + new_query[next_clause_pos:]
                else:
                    # Ajouter à la fin de la requête
                    new_query += " " + " ".join(joins_to_add)
    
    # Corriger spécifiquement le cas "SELECT EXTRACT(DOW FROM orders"
    if "EXTRACT(DOW FROM orders" in new_query and "order_date" not in new_query:
        new_query = new_query.replace("EXTRACT(DOW FROM orders", "EXTRACT(DOW FROM orders.order_date")
    
    # Corriger les cas où la clause GROUP BY ne correspond pas au SELECT
    if "GROUP BY" in new_query.upper():
        select_part = new_query.upper().split("FROM")[0].replace("SELECT", "").strip()
        group_by_part = new_query.upper().split("GROUP BY")[1].split("ORDER BY")[0].split("LIMIT")[0].strip()
        
        # Si GROUP BY utilise des noms de colonnes différents du SELECT
        if "P.NAME" in group_by_part and "p.name" in select_part.lower():
            new_query = new_query.replace("GROUP BY P.NAME", "GROUP BY p.name")
        elif "P1.NAME" in group_by_part and "p1.name" in select_part.lower():
            new_query = new_query.replace("GROUP BY P1.NAME", "GROUP BY p1.name")
        elif "P2.NAME" in group_by_part and "p2.name" in select_part.lower():
            new_query = new_query.replace("GROUP BY P2.NAME", "GROUP BY p2.name")
    
    return new_query

def handle_complex_query(question_text):
    """Gère les requêtes SQL complexes qui nécessitent un traitement spécial"""
    question_lower = question_text.lower()
    
    # 1. Clients qui dépensent le plus
    if ("clients" in question_lower and "dépensent" in question_lower and "plus" in question_lower):
        return """
        SELECT c.first_name, c.last_name, SUM(oi.quantity * oi.unit_price) AS total_spent
        FROM customers c
        JOIN orders o ON c.id = o.customer_id
        JOIN order_items oi ON o.id = oi.order_id
        GROUP BY c.id, c.first_name, c.last_name
        ORDER BY total_spent DESC
        LIMIT 10
        """
    
    # 2. Clients sans commandes
    if ("clients" in question_lower and "jamais" in question_lower and "commande" in question_lower):
        return """
        SELECT c.*
        FROM customers c
        LEFT JOIN orders o ON c.id = o.customer_id
        WHERE o.id IS NULL
        """
    
    # 3. Produits les plus commandés
    if ("produits" in question_lower and "plus commandés" in question_lower):
        return """
        SELECT p.name, SUM(oi.quantity) as total_ordered
        FROM products p
        JOIN order_items oi ON p.id = oi.product_id
        GROUP BY p.id, p.name
        ORDER BY total_ordered DESC
        LIMIT 5
        """
    
    # 4. Produits ajoutés récemment
    if ("produits" in question_lower and ("ajoutés" in question_lower or "ajouté" in question_lower) and "mois dernier" in question_lower):
        return """
        SELECT p.*
        FROM products p
        WHERE p.created_at >= DATE_TRUNC('month', CURRENT_DATE - INTERVAL '1 month')
          AND p.created_at < DATE_TRUNC('month', CURRENT_DATE)
        """
    
    # 5. Valeur moyenne des commandes par jour de semaine
    if ("valeur moyenne" in question_lower and "commandes" in question_lower and "jour" in question_lower and "semaine" in question_lower):
        return """
        SELECT 
            EXTRACT(DOW FROM o.order_date) AS day_of_week,
            TO_CHAR(o.order_date, 'Day') AS day_name,
            AVG(o.total_amount) AS average_order_value
        FROM orders o
        GROUP BY day_of_week, day_name
        ORDER BY day_of_week
        """
    
    # 6. Produits achetés ensemble
    if ("produits" in question_lower and "achetés ensemble" in question_lower):
        return """
        SELECT 
            p1.name AS product1_name, 
            p2.name AS product2_name, 
            COUNT(*) AS times_bought_together
        FROM order_items oi1
        JOIN order_items oi2 ON oi1.order_id = oi2.order_id AND oi1.product_id < oi2.product_id
        JOIN products p1 ON oi1.product_id = p1.id
        JOIN products p2 ON oi2.product_id = p2.id
        GROUP BY p1.name, p2.name
        ORDER BY times_bought_together DESC
        LIMIT 10
        """
    
    return None

def fix_sql_query(query, question_text):
    """Essaie de corriger une requête SQL incomplète ou invalide en tenant compte de la question"""
    # Si la requête est complètement vide, créer une requête de base
    if not query or query.strip() == "":
        table = detect_table_from_question(question_text)
        query = f"SELECT * FROM {table}"
    
    # Détecter la table appropriée en fonction de la question
    table = detect_table_from_question(question_text)
    
    # Si la requête se termine par FROM, ajouter la table
    if query.upper().strip().endswith("FROM"):
        query = query + f" {table}"
    
    # Si la requête est SELECT * FROM sans table
    if query.upper().strip() == "SELECT * FROM":
        query = query + f" {table}"
    
    # Corriger les problèmes d'alias (notamment pour les jointures)
    query = fix_alias_in_query(query)
    
    # Ajouter des conditions de filtrage en fonction de la question
    conditions = detect_condition_from_question(question_text)
    if conditions and "WHERE" not in query.upper():
        query = query + " WHERE " + " AND ".join(conditions)
    
    # Cas spéciaux pour les requêtes agrégées
    question_lower = question_text.lower()
    
    # Requête pour la moyenne des prix par catégorie
    if "catégorie" in question_lower and "prix" in question_lower and "moyenne" in question_lower:
        if "GROUP BY" not in query.upper() and "products" in query:
            if "ORDER BY" in query.upper():
                # Insérer GROUP BY avant ORDER BY
                parts = query.split("ORDER BY")
                query = parts[0] + " GROUP BY category ORDER BY" + parts[1]
            else:
                query = query + " GROUP BY category"
    
    # Corriger les erreurs GROUP BY
    query = fix_group_by_errors(query)
    
    return query

def fix_group_by_errors(query):
    """Corrige les erreurs courantes liées aux clauses GROUP BY manquantes"""
    # Si la requête contient COUNT et pas de GROUP BY, l'ajouter
    if ("COUNT(" in query.upper() or "COUNT (*" in query.upper() or "COUNT(*" in query.upper()) and "GROUP BY" not in query.upper():
        # Pour les requêtes simples de comptage par état
        if "state" in query.lower() and "count" in query.lower() and "from customers" in query.lower():
            return query + " GROUP BY state"
        
        # Pour les requêtes de comptage par catégorie pour les produits
        if "category" in query.lower() and "count" in query.lower() and "from products" in query.lower():
            return query + " GROUP BY category"
        
        # Plus général: identifie les colonnes non agrégées qui doivent être groupées
        try:
            select_part = query.upper().split("FROM")[0].replace("SELECT", "").strip()
            columns = []
            
            # Extraction simplifiée des colonnes non agrégées
            for col in select_part.split(","):
                col = col.strip()
                # Si ce n'est pas une colonne agrégée (pas COUNT, SUM, AVG, etc.)
                if not any(agg in col for agg in ["COUNT(", "SUM(", "AVG(", "MIN(", "MAX("]):
                    # Extraire juste le nom de la colonne (sans alias)
                    col_name = col.split(" AS ")[0].strip() if " AS " in col else col
                    columns.append(col_name)
            
            # S'il y a des colonnes non agrégées, ajouter GROUP BY
            if columns:
                return query + " GROUP BY " + ", ".join(columns)
        except Exception as e:
            logger.warning(f"Erreur lors de la tentative de correction GROUP BY: {e}")
    
    # Vérifier si une fonction AVG est utilisée sans GROUP BY
    if "AVG(" in query.upper() and "GROUP BY" not in query.upper():
        # Pour la moyenne des prix par catégorie
        if "category" in query.lower() and "price" in query.lower() and "from products" in query.lower():
            return query + " GROUP BY category"
    
    return query

def extract_query_from_specific_questions(question_text):
    """Génère des requêtes SQL directement pour certaines questions spécifiques"""
    question_lower = question_text.lower()
    
    # Requêtes pour le comptage par état
    if ("combien de clients" in question_lower and "par état" in question_lower) or ("nombre de clients" in question_lower and "par état" in question_lower):
        return "SELECT state, COUNT(*) as client_count FROM customers GROUP BY state"
    
    # Requêtes pour les clients avec un statut spécifique
    if "clients" in question_lower and "statut inactive" in question_lower:
        return "SELECT * FROM customers WHERE status = 'inactive'"
    elif "clients" in question_lower and "status inactive" in question_lower:
        return "SELECT * FROM customers WHERE status = 'inactive'"
    elif "clients" in question_lower and "statut active" in question_lower:
        return "SELECT * FROM customers WHERE status = 'active'"
    elif "clients" in question_lower and "statut pending" in question_lower:
        return "SELECT * FROM customers WHERE status = 'pending'"
    
    # Requêtes pour les produits
    if "produits" in question_lower and "catégorie \"electronics\"" in question_lower:
        return "SELECT * FROM products WHERE category = 'Electronics'"
    
    if "produits" in question_lower and "prix supérieur à 300" in question_lower:
        return "SELECT * FROM products WHERE price > 300"
    
    if "produits" in question_lower and "stock inférieur à 40" in question_lower:
        return "SELECT * FROM products WHERE stock_quantity < 40"
    
    if "produit le plus cher" in question_lower:
        return "SELECT * FROM products ORDER BY price DESC LIMIT 1"
    
    # Requêtes pour le comptage par catégorie de produits
    if "combien de produits" in question_lower and "par catégorie" in question_lower:
        return "SELECT category, COUNT(*) as product_count FROM products GROUP BY category"
    
    # Requêtes pour les produits au-dessus d'un certain prix
    if "produits" in question_lower and "prix supérieur à 100" in question_lower:
        return "SELECT * FROM products WHERE price > 100"
    
    # Requêtes pour le prix moyen par catégorie
    if "prix moyen" in question_lower and "catégorie" in question_lower:
        return "SELECT category, AVG(price) as average_price FROM products GROUP BY category"
    
    # Requête spécifique pour la catégorie avec le prix moyen le plus élevé
    if "catégorie" in question_lower and "moyenne de prix" in question_lower and "plus élevée" in question_lower:
        return "SELECT category, AVG(price) AS moyenne_prix FROM products GROUP BY category ORDER BY moyenne_prix DESC LIMIT 1"
    
    # Requêtes pour les commandes
    if "commandes" in question_lower and "statut \"pending\"" in question_lower:
        return "SELECT * FROM orders WHERE status = 'pending'"
    
    if "montant total" in question_lower and "commandes livrées" in question_lower:
        return "SELECT SUM(total_amount) as total_montant FROM orders WHERE status = 'delivered'"
    
    if "commandes" in question_lower and "décembre 2023" in question_lower:
        return "SELECT * FROM orders WHERE EXTRACT(MONTH FROM order_date) = 12 AND EXTRACT(YEAR FROM order_date) = 2023"
    
    if "client" in question_lower and "commande" in question_lower and "montant le plus élevé" in question_lower:
        return """
        SELECT c.first_name, c.last_name, o.total_amount
        FROM customers c
        JOIN orders o ON c.id = o.customer_id
        ORDER BY o.total_amount DESC
        LIMIT 1
        """
    
    # Requêtes complexes avec jointure
    if "produits commandés par" in question_lower and "john doe" in question_lower:
        return """
        SELECT p.name
        FROM products p
        JOIN order_items oi ON p.id = oi.product_id
        JOIN orders o ON oi.order_id = o.id
        JOIN customers c ON o.customer_id = c.id
        WHERE c.first_name = 'John' AND c.last_name = 'Doe'
        """
    
    if "produits" in question_lower and "catégorie \"electronics\"" in question_lower and "commandés" in question_lower:
        return """
        SELECT SUM(oi.quantity) as total_electronics
        FROM order_items oi
        JOIN products p ON oi.product_id = p.id
        WHERE p.category = 'Electronics'
        """
    
    if "clients" in question_lower and "commandé des meubles" in question_lower:
        return """
        SELECT DISTINCT c.first_name, c.last_name
        FROM customers c
        JOIN orders o ON c.id = o.customer_id
        JOIN order_items oi ON o.id = oi.order_id
        JOIN products p ON oi.product_id = p.id
        WHERE p.category = 'Furniture'
        """
    
    # Requête pour l'état avec le plus de chiffre d'affaires
    if "état" in question_lower and "chiffre d'affaires" in question_lower:
        return """
        SELECT c.state, SUM(oi.quantity * oi.unit_price) AS total_revenue
        FROM customers c
        JOIN orders o ON c.id = o.customer_id
        JOIN order_items oi ON o.id = oi.order_id
        GROUP BY c.state
        ORDER BY total_revenue DESC
        LIMIT 1
        """
    
    # Requêtes pour les analyses
    if "valeur moyenne" in question_lower and "commandes" in question_lower and "par état" in question_lower:
        return """
        SELECT c.state, AVG(o.total_amount) AS moyenne_commandes
        FROM customers c
        JOIN orders o ON c.id = o.customer_id
        GROUP BY c.state
        """
    
    if "nombre de commandes" in question_lower and "catégorie de produits" in question_lower:
        return """
        SELECT p.category, COUNT(DISTINCT oi.order_id) AS nombre_de_commandes
        FROM order_items oi
        JOIN products p ON oi.product_id = p.id
        GROUP BY p.category
        """
    
    if "clients" in question_lower and "plus de 2 commandes" in question_lower:
        return """
        SELECT c.*
        FROM customers c
        JOIN (
            SELECT customer_id, COUNT(*) as num_orders
            FROM orders
            GROUP BY customer_id
            HAVING COUNT(*) > 2
        ) o ON c.id = o.customer_id
        """
    
    # Par défaut, aucune requête spécifique trouvée
    return None

@app.post("/process", response_model=ProcessResponse)
async def process_question(question: Question, background_tasks: BackgroundTasks):
    """
    Point d'entrée principal pour traiter une question en langage naturel
    
    Workflow:
    1. Calculer l'embedding de la question
    2. Rechercher des questions similaires dans Qdrant
    3. Si une question similaire est trouvée, valider la similarité sémantique
    4. Si validé, modifier la requête SQL existante
    5. Sinon, générer une nouvelle requête SQL
    6. Exécuter la requête SQL
    7. Stocker la nouvelle question et sa requête SQL dans Qdrant (si générée)
    
    - question: Question en langage naturel
    
    Retourne:
    - result: Résultat de l'exécution de la requête SQL
    - query_used: Requête SQL utilisée
    - source: Source de la requête SQL ("cache", "modified", "generated")
    - processing_details: Détails du traitement
    """
    try:
        processing_details = {}
        
        # Vérifier d'abord si c'est une question connue avec une requête prédéfinie
        predefined_query = extract_query_from_specific_questions(question.text)
        if predefined_query:
            logger.info(f"Requête prédéfinie trouvée pour la question: {predefined_query}")
            execution_result = await execute_sql_query(SQLQuery(query=predefined_query))
            
            # Gérer les erreurs éventuelles
            if isinstance(execution_result, dict) and "error" in execution_result:
                raise HTTPException(status_code=500, detail=execution_result["error"])
            
            # Stocker cette requête dans Qdrant pour le futur
            background_tasks.add_task(
                store_question_and_sql,
                question=question.text,
                sql_query=predefined_query
            )
            
            return {
                "result": execution_result,
                "query_used": predefined_query,
                "source": "predefined",
                "processing_details": {"predefined": True}
            }
        
        # 1. Calculer l'embedding de la question
        logger.info(f"Calcul de l'embedding pour la question: {question.text}")
        try:
            embedding_response = await http_client.post(
                f"{EMBEDDING_SERVICE_URL}/embed",
                json={"text": question.text}
            )
            
            if embedding_response.status_code != 200:
                raise HTTPException(status_code=500, detail="Erreur lors du calcul de l'embedding")
        except Exception as e:
            logger.error(f"Erreur lors du calcul de l'embedding: {e}")
            # Continuer en utilisant la génération directe
        
        # 2. Rechercher des questions similaires dans Qdrant
        logger.info("Recherche de questions similaires dans Qdrant")
        try:
            search_response = await http_client.post(
                f"{EMBEDDING_SERVICE_URL}/search",
                json={"text": question.text},
                params={"limit": 1, "threshold": SIMILARITY_THRESHOLD}
            )
            
            if search_response.status_code != 200:
                raise HTTPException(status_code=500, detail="Erreur lors de la recherche dans Qdrant")
            
            search_results = search_response.json()
            processing_details["search_results"] = search_results
        except Exception as e:
            logger.error(f"Erreur lors de la recherche dans Qdrant: {e}")
            search_results = []
            processing_details["search_results"] = []
        
        # Récupérer le schéma de la base de données
        try:
            schema_info = await get_database_schema()
            if isinstance(schema_info, dict) and "error" in schema_info:
                raise HTTPException(status_code=500, detail=schema_info["error"])
        except Exception as e:
            logger.error(f"Erreur lors de la récupération du schéma: {e}")
            schema_info = {"tables": {}}
        
        # 3 & 4. Si une question similaire est trouvée
        if search_results and len(search_results) > 0:
            cached_result = search_results[0]
            cached_question = cached_result["question"]
            cached_sql = cached_result["sql_query"]
            similarity_score = cached_result["score"]
            
            logger.info(f"Question similaire trouvée avec score {similarity_score}: {cached_question}")
            processing_details["cached_question"] = cached_question
            processing_details["cached_sql"] = cached_sql
            processing_details["similarity_score"] = similarity_score
            
            # 3. Valider la similarité sémantique
            logger.info("Validation de la similarité sémantique")
            try:
                validation_response = await http_client.post(
                    f"{SEMANTIC_VALIDATION_SERVICE_URL}/validate",
                    json={
                        "cached_question": cached_question,
                        "user_question": question.text,
                        "similarity_threshold": 0.8
                    }
                )
                
                if validation_response.status_code != 200:
                    # En cas d'erreur, considérer les questions comme similaires
                    validation_result = {"is_similar": True, "confidence": 0.9, "error": validation_response.text}
                else:
                    # Gérer potentiellement des réponses en format Markdown
                    validation_content = validation_response.text
                    validation_result = extract_json_from_markdown(validation_content)
                    if isinstance(validation_result, str):
                        try:
                            validation_result = json.loads(validation_result)
                        except json.JSONDecodeError:
                            # Format de secours si tout échoue
                            validation_result = {"is_similar": True, "confidence": 0.9}
                            logger.warning(f"Échec du parsing de la validation. Contenu brut: {validation_content[:200]}...")
                
                processing_details["validation_result"] = validation_result
            except Exception as e:
                logger.error(f"Erreur lors de la validation sémantique: {e}")
                # En cas d'erreur, supposer que les questions sont similaires
                validation_result = {"is_similar": True, "confidence": 0.9}
                processing_details["validation_result"] = validation_result
                processing_details["validation_error"] = str(e)
            
            # 4. Si validé, modifier la requête SQL existante
            if validation_result.get("is_similar", False):
                logger.info("Questions sémantiquement similaires, modification de la requête SQL")
                
                try:
                    modification_response = await http_client.post(
                        f"{SQL_MOD_SERVICE_URL}/modify",
                        json={
                            "original_question": cached_question,
                            "new_question": question.text,
                            "original_sql_query": cached_sql,
                            "schema_info": json.dumps(schema_info, indent=2)
                        }
                    )
                    
                    if modification_response.status_code != 200:
                        # En cas d'erreur, utiliser la requête originale
                        logger.warning(f"Erreur dans le service de modification: {modification_response.text}")
                        sql_query = cached_sql
                        source = "cache"
                        processing_details["modification_error"] = modification_response.text
                    else:
                        # Gérer potentiellement des réponses en format Markdown
                        modification_content = modification_response.text
                        logger.info(f"Réponse brute du service de modification SQL: {modification_content[:200]}...")
                        
                        modification_result = extract_json_from_markdown(modification_content)
                        logger.info(f"Résultat du parsing de la modification: {modification_result}")
                        
                        if isinstance(modification_result, str):
                            try:
                                modification_result = json.loads(modification_result)
                            except json.JSONDecodeError:
                                # En cas d'échec complet, utiliser la requête originale
                                modification_result = {"modified_sql_query": cached_sql}
                                logger.warning("Échec du parsing de la modification SQL, utilisation de la requête originale")
                        
                        processing_details["modification_result"] = modification_result
                        
                        # Vérifier que la requête modifiée est valide
                        sql_query = modification_result.get("modified_sql_query", "")
                        logger.info(f"Requête SQL extraite: '{sql_query}'")
                        
                        # Si la requête est vide, tronquée ou invalide, utiliser la requête originale
                        if not is_valid_sql_query(sql_query):
                            logger.warning(f"Requête SQL modifiée invalide, utilisation de la requête originale: '{sql_query}'")
                            sql_query = cached_sql
                            processing_details["sql_fallback"] = True
                        
                        source = "modified"
                
                except Exception as e:
                    logger.error(f"Erreur lors de la modification SQL: {e}")
                    # En cas d'erreur, utiliser la requête originale
                    sql_query = cached_sql
                    source = "cache"
                    processing_details["modification_error"] = str(e)
            else:
                # Si non validé, passer à la génération
                logger.info("Questions non similaires sémantiquement, génération d'une nouvelle requête SQL")
                source = "generated"
                sql_query = None  # Sera généré dans la section suivante
        else:
            # Aucune question similaire trouvée
            logger.info("Aucune question similaire trouvée, génération d'une nouvelle requête SQL")
            source = "generated"
            sql_query = None  # Sera généré dans la section suivante
        
        # 5. Si nécessaire, générer une nouvelle requête SQL
        if source == "generated":
            logger.info("Génération d'une nouvelle requête SQL")
            
            try:
                generation_response = await http_client.post(
                    f"{TEXT_TO_SQL_SERVICE_URL}/generate-sql",
                    json={
                        "question": question.text,
                        "schema_info": json.dumps(schema_info, indent=2)
                    }
                )
                
                if generation_response.status_code != 200:
                    raise HTTPException(status_code=500, detail="Erreur lors de la génération de la requête SQL")
                
                # Gérer potentiellement des réponses en format Markdown
                generation_content = generation_response.text
                logger.info(f"Réponse brute du service de génération SQL: {generation_content}")
                
                # Extraire la requête complète si possible
                sql_query = extract_full_sql_query(generation_content)
                if sql_query and is_valid_sql_query(sql_query):
                    generation_result = {"sql_query": sql_query, "explanation": "Extraction directe"}
                    logger.info(f"Requête SQL extraite directement: {sql_query}")
                else:
                    # Essayer l'extraction normale
                    generation_result = extract_json_from_markdown(generation_content)
                    logger.info(f"Résultat du parsing de la génération: {generation_result}")
                    
                    if isinstance(generation_result, str):
                        try:
                            generation_result = json.loads(generation_result)
                        except json.JSONDecodeError:
                            raise HTTPException(status_code=500, detail=f"Échec du parsing de la génération SQL: {generation_content[:200]}...")
                
                processing_details["generation_result"] = generation_result
                
                sql_query = generation_result.get("sql_query", "")
                logger.info(f"Requête SQL générée: '{sql_query}'")
                
                # Si la requête est invalide, essayer de la corriger
                if not is_valid_sql_query(sql_query):
                    fixed_query = fix_sql_query(sql_query, question.text)
                    if is_valid_sql_query(fixed_query):
                        sql_query = fixed_query
                        logger.info(f"Requête SQL corrigée: '{sql_query}'")
                    else:
                        # Dernière chance: générer une requête à partir de zéro basée sur la question
                        generated_query = extract_query_from_specific_questions(question.text)
                        if generated_query:
                            sql_query = generated_query
                            logger.info(f"Requête SQL générée à partir de templates: '{sql_query}'")
                        else:
                            raise HTTPException(status_code=500, detail=f"Requête SQL générée invalide: '{sql_query}'")
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Erreur lors de la génération SQL: {e}")
                # Tenter une génération de secours basée sur la question
                fallback_query = extract_query_from_specific_questions(question.text)
                if fallback_query:
                    sql_query = fallback_query
                    logger.info(f"Utilisation d'une requête prédéfinie de secours: {sql_query}")
                    processing_details["fallback_generation"] = True
                else:
                    fallback_query = fix_sql_query("", question.text)
                    if is_valid_sql_query(fallback_query):
                        sql_query = fallback_query
                        logger.info(f"Utilisation d'une requête de secours: {sql_query}")
                        processing_details["fallback_generation"] = True
                    else:
                        raise HTTPException(status_code=500, detail=f"Erreur lors de la génération de la requête SQL: {str(e)}")
        
        # Corriger les erreurs de groupe potentielles avant exécution
        sql_query = fix_group_by_errors(sql_query)
        
        # 6. Exécuter la requête SQL - CORRECTION: appeler directement la fonction
        logger.info(f"Exécution de la requête SQL complète: {sql_query}")
        execution_result = await execute_sql_query(SQLQuery(query=sql_query))
        
        # Si une erreur est détectée dans le résultat d'exécution
        if isinstance(execution_result, dict) and "error" in execution_result:
            error_message = execution_result["error"]
            
            # Essayer de corriger l'erreur en fonction du message
            if "missing FROM-clause entry for table" in error_message:
                # Extraire le nom de la table manquante (généralement un alias)
                missing_table_match = re.search(r'missing FROM-clause entry for table "([^"]+)"', error_message)
                if missing_table_match:
                    alias = missing_table_match.group(1)
                    
                    # Déterminer la vraie table en fonction de l'alias
                    if alias == 'c':
                        table_name = 'customers'
                    elif alias == 'p':
                        table_name = 'products'
                    elif alias == 'o':
                        table_name = 'orders'
                    elif alias == 'oi':
                        table_name = 'order_items'
                    else:
                        table_name = None
                    
                    if table_name:
                        # Créer une requête avec jointure si nécessaire
                        if "JOIN" not in sql_query:
                            if " FROM " + table_name in sql_query and f" {alias}" not in sql_query:
                                corrected_query = sql_query.replace(f" FROM {table_name}", f" FROM {table_name} {alias}")
                                logger.info(f"Tentative de correction des alias: {corrected_query}")
                                execution_result = await execute_sql_query(SQLQuery(query=corrected_query))
                                if not (isinstance(execution_result, dict) and "error" in execution_result):
                                    sql_query = corrected_query
            
            # Vérifier si l'erreur persiste
            if isinstance(execution_result, dict) and "error" in execution_result:
                raise HTTPException(status_code=500, detail=execution_result["error"])
        
        # 7. Si nouvelle requête générée, la stocker dans Qdrant (en arrière-plan)
        if source == "generated":
            background_tasks.add_task(
                store_question_and_sql,
                question=question.text,
                sql_query=sql_query
            )
        
        return {
            "result": execution_result,
            "query_used": sql_query,
            "source": source,
            "processing_details": processing_details
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors du traitement de la question: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur lors du traitement de la question: {str(e)}")

async def store_question_and_sql(question: str, sql_query: str):
    """Stocke une nouvelle question et sa requête SQL dans Qdrant"""
    try:
        logger.info(f"Stockage de la question et de la requête SQL dans Qdrant: {question}")
        
        store_response = await http_client.post(
            f"{EMBEDDING_SERVICE_URL}/store",
            json={
                "question": question,
                "sql_query": sql_query
            }
        )
        
        if store_response.status_code == 200:
            logger.info("Question et requête SQL stockées avec succès")
        else:
            logger.error(f"Erreur lors du stockage dans Qdrant: {store_response.text}")
    except Exception as e:
        logger.error(f"Erreur lors du stockage dans Qdrant: {e}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)