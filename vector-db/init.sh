#!/bin/bash
# Script d'initialisation pour le conteneur Qdrant

# Attendre que Qdrant soit complètement démarré
echo "Attente du démarrage complet de Qdrant..."
sleep 10

# Exécuter le script d'initialisation Python
python3 /qdrant/init_qdrant.py

echo "Initialisation de Qdrant terminée."